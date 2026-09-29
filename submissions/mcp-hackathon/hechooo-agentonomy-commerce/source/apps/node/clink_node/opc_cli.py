from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import anyio

from .opc_client import OpcClient, OpcClientError, OpcClientStateStore
from .opc_onboarding import open_wallet_browser
from .opc_setup import (
    DEFAULT_OPC_ORIGIN,
    choose_agent,
    default_device_label,
    setup_opc,
)


def configure_opc_parser(commands) -> None:
    opc = commands.add_parser("opc", help="Connect this installation to shared Agentonomy.")
    actions = opc.add_subparsers(dest="opc_command", required=True)

    connect = actions.add_parser("connect", help="Create or resume an OPC pairing.")
    connect.add_argument("--server")
    connect.add_argument("--label")
    connect.add_argument("--state", type=Path)
    connect.add_argument("--allow-loopback-http", action="store_true", help=argparse.SUPPRESS)
    connect.add_argument("--no-open", action="store_true", help="Do not open the wallet page.")
    connect.add_argument("--json", action="store_true", help="Print one pairing/status JSON object and exit.")
    connect.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="Wait for authoritative consent status for up to 600 seconds (0 is nonblocking).",
    )
    connect.set_defaults(handler=_connect)

    setup = actions.add_parser("setup", help="Prepare OPC state and an optional Agent handoff.")
    setup.add_argument("--agent", choices=("codex", "generic"))
    setup.add_argument("--state", type=Path)
    setup.add_argument("--config", type=Path)
    setup.add_argument("--server")
    setup.add_argument("--label")
    setup.add_argument("--allow-loopback-http", action="store_true", help=argparse.SUPPRESS)
    setup.set_defaults(handler=_setup)

    account = actions.add_parser(
        "account",
        help="Open account management for an active OPC installation.",
    )
    account.add_argument("--state", type=Path)
    account.add_argument(
        "--no-open",
        action="store_true",
        help="Print the sensitive management link for this local headless flow.",
    )
    account.add_argument(
        "--json",
        action="store_true",
        help="Print sanitized status JSON; JSON mode never opens a browser or prints the link.",
    )
    account.set_defaults(handler=_account)

    for name, handler in (("status", _status), ("revoke", _revoke), ("mcp", _mcp)):
        command = actions.add_parser(name)
        command.add_argument("--state", type=Path)
        command.set_defaults(handler=handler)


def _state_path(namespace: argparse.Namespace) -> Path:
    if namespace.state is not None:
        return namespace.state
    root = Path(os.environ.get("CLINK_HOME", Path.home() / ".clink"))
    return root / "opc" / "client.json"


def _state_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _client(namespace: argparse.Namespace, *, initialize: bool = False) -> OpcClient:
    path = _state_path(namespace)
    kwargs: dict[str, object] = {
        "allow_loopback_http": getattr(namespace, "allow_loopback_http", False),
    }
    server = getattr(namespace, "server", None)
    label = getattr(namespace, "label", None)
    if server is not None:
        kwargs["origin"] = server
    if label is not None:
        kwargs["label"] = label
    if initialize and not _state_exists(path):
        kwargs.setdefault("origin", DEFAULT_OPC_ORIGIN)
        kwargs.setdefault("label", default_device_label())
    return OpcClient(OpcClientStateStore(path), **kwargs)


def _load(namespace: argparse.Namespace) -> OpcClient:
    return _client(namespace)


def _authoritative_status(client: OpcClient) -> dict[str, object]:
    try:
        return client.status()
    except OpcClientError as error:
        if error.status_code == 404:
            return {"installation_id": client.state.installation_id, "status": "unpaired"}
        raise


def _wait_for_consent(
    client: OpcClient,
    *,
    expires_at: int,
    wait_seconds: int,
) -> dict[str, object] | None:
    started = time.monotonic()
    deadline = started + min(wait_seconds, 600)
    while time.monotonic() < deadline:
        status = _authoritative_status(client)
        if status.get("status") in {"active", "revoked"}:
            return status
        now = time.monotonic()
        remaining = min(deadline - now, max(0, expires_at - int(time.time())))
        if remaining <= 0:
            break
        time.sleep(min(5.0, remaining))
    return None


def _connect(namespace: argparse.Namespace) -> int:
    if namespace.wait_seconds < 0 or namespace.wait_seconds > 600:
        raise ValueError("wait-seconds must be between 0 and 600")
    with _client(namespace, initialize=True) as client:
        status = _authoritative_status(client)
        if status.get("status") in {"active", "revoked"}:
            if namespace.json:
                print(json.dumps(status, sort_keys=True))
            elif status.get("status") == "active":
                print(
                    "This OPC device is already active; no new pairing was created. "
                    "Query get_clink_account_readiness before business use."
                )
            else:
                print(
                    "This OPC device is revoked; no new pairing was created. "
                    "Use an explicit new state path for a new installation."
                )
            return 0
        if status.get("status") == "unavailable":
            raise OpcClientError("OPC service status is unavailable")

        pairing = client.connect()
        if namespace.json:
            # Preserve the former one-shot machine contract exactly: one JSON
            # object, no browser, instructions, or status polling.
            print(json.dumps(pairing, sort_keys=True))
            return 0

        verification_uri = pairing["verification_uri"]
        browser_opened = False
        if not namespace.no_open:
            browser_opened = open_wallet_browser(verification_uri)
        if browser_opened:
            print(
                "Opened the expiring Agentonomy wallet-consent page. Review the "
                "device, wallet, limits and expiry, then approve only the requested "
                "signatures in your wallet. Opening the page does not sign or grant authority."
            )
        else:
            print(
                f"Open this expiring wallet-consent link on the intended operator device:\n"
                f"{verification_uri}\n"
                "Do not paste this link into chat, logs or support tickets. Review "
                "the device, wallet, limits and expiry before approving requested wallet steps."
            )
        if namespace.wait_seconds == 0:
            return 0
        result = _wait_for_consent(
            client,
            expires_at=pairing["expires_at"],
            wait_seconds=namespace.wait_seconds,
        )
        if result is None:
            print("Consent was not confirmed before the bounded wait expired; rerun connect to check status.")
        elif result.get("status") == "active":
            print(
                "Authoritative device status is active. Query get_clink_account_readiness "
                "before any business use."
            )
        else:
            print("Authoritative device status is revoked; do not reconnect this installation.")
    return 0


def _account_instructions(
    *,
    browser_opened: bool,
    json_mode: bool = False,
    no_open: bool = False,
) -> str:
    if json_mode:
        return (
            "JSON mode did not open a browser and never includes the sensitive "
            "account-management link. Rerun without --json to open the page, or "
            "run local clink opc account --no-open to display it. Opening the page "
            "does not authorize payments; review any wallet consent manually and "
            "query get_clink_account_readiness before business use."
        )
    if browser_opened:
        return (
            "Opened the account-management page. Opening it does not sign or grant "
            "authority; review any wallet consent manually, then query "
            "get_clink_account_readiness before business use."
        )
    if no_open:
        return (
            "This sensitive link is shown only for the local headless command; do "
            "not share it. Opening the page does not authorize payments; review any "
            "wallet consent manually and query get_clink_account_readiness before "
            "business use."
        )
    return (
        "The browser could not open the account-management page and the sensitive "
        "link was not printed. Run local clink opc account --no-open to display it. "
        "Opening the page does not authorize payments; review any wallet consent "
        "manually and query get_clink_account_readiness before business use."
    )


def _account(namespace: argparse.Namespace) -> int:
    json_mode = bool(getattr(namespace, "json", False))
    no_open = bool(getattr(namespace, "no_open", False))
    with _load(namespace) as client:
        link = client.open_account_link()
        if not isinstance(link, dict):
            raise OpcClientError("OPC account link response is invalid")
        status = link.get("status")
        expires_at = link.get("expires_at")
        verification_uri = link.get("verification_uri")
        if (
            status != "active"
            or type(expires_at) is not int
            or type(verification_uri) is not str
            or not verification_uri
        ):
            raise OpcClientError("OPC account link response is invalid")

        browser_opened = False
        # JSON is a machine-readable, side-effect-free mode. A combined
        # --json --no-open invocation remains valid and equally sanitized.
        if not json_mode and not no_open:
            try:
                opened = open_wallet_browser(verification_uri)
                browser_opened = type(opened) is bool and opened
            except Exception:
                browser_opened = False

        instructions = _account_instructions(
            browser_opened=browser_opened,
            json_mode=json_mode,
            no_open=no_open,
        )
        result = {
            "status": status,
            "browser_opened": browser_opened,
            "expiry": expires_at,
            "instructions": instructions,
        }
        if json_mode:
            print(json.dumps(result, sort_keys=True))
        elif no_open:
            print(
                f"Account management status: {status}\n"
                f"Browser opened: {str(browser_opened).lower()}\n"
                f"Expiry: {expires_at}\n"
                f"Open this local-only account-management link on the intended operator device:\n"
                f"{verification_uri}\n"
                f"{instructions}"
            )
        else:
            print(
                f"Account management status: {status}\n"
                f"Browser opened: {str(browser_opened).lower()}\n"
                f"Expiry: {expires_at}\n"
                f"{instructions}"
            )
    return 0


def _status(namespace: argparse.Namespace) -> int:
    with _load(namespace) as client:
        print(json.dumps(client.status(), sort_keys=True))
    return 0


def _revoke(namespace: argparse.Namespace) -> int:
    with _load(namespace) as client:
        print(json.dumps(client.revoke(), sort_keys=True))
    return 0


def _mcp(namespace: argparse.Namespace) -> int:
    with _client(namespace, initialize=True) as client:
        anyio.run(client.serve_stdio)
    return 0


def _setup(namespace: argparse.Namespace) -> int:
    agent = namespace.agent
    if agent is None:
        # Keep the generic machine-readable recipe as the only stdout value;
        # the interactive selection prompt is guidance, not part of the JSON.
        agent = choose_agent(output=lambda message: print(message, file=sys.stderr))
        if agent is None:
            print("OPC setup canceled; no state or host configuration was changed.")
            return 0
    return setup_opc(
        agent=agent,
        state_path=namespace.state or _state_path(namespace),
        config_path=namespace.config,
        server=namespace.server,
        label=namespace.label,
        allow_loopback_http=namespace.allow_loopback_http,
    )
