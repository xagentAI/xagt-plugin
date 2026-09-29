from __future__ import annotations

import json
import re
from pathlib import Path

from eth_utils import keccak

from services.action_policy_repository import ActionPolicyRepository
from services.action_service.schemas import ActionApproval, AgentActionIntent
from services.policy_service.schemas import PolicyDecision
from shared.config import AppConfig


SENSITIVE_KEYS = {
    "signature",
    "raw_signature",
    "raw_transaction",
    "signed_message",
    "signed_payload",
    "signed_transaction",
}
EVM_SIGNATURE_PATTERN = re.compile(r"^0x[0-9a-fA-F]{130}$")
LEGACY_CHAIN_ALIASES = {
    "base": "eip155:8453",
    "polygon": "eip155:137",
}


def _proof_hash(value: str) -> str:
    try:
        material = bytes.fromhex(value.removeprefix("0x"))
    except ValueError:
        material = value.encode("utf-8")
    return "0x" + keccak(material).hex()


def _sanitize(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, nested in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in SENSITIVE_KEYS:
                if isinstance(nested, str) and nested:
                    sanitized[f"{key}_proof_hash"] = _proof_hash(nested)
                continue
            sanitized[key] = _sanitize(nested)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and EVM_SIGNATURE_PATTERN.fullmatch(value):
        return _proof_hash(value)
    return value


def _normalize_legacy_policy(record: dict) -> dict:
    normalized = _sanitize(record)
    chain = normalized.get("chain")
    if isinstance(chain, str):
        normalized["chain"] = LEGACY_CHAIN_ALIASES.get(
            chain.strip().lower(), chain
        )
    return normalized


def _latest_records(path: Path, id_field: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid legacy JSON in {path} at line {line_number}"
            ) from exc
        if not isinstance(record, dict) or not record.get(id_field):
            raise RuntimeError(
                f"legacy record in {path} at line {line_number} has no {id_field}"
            )
        records[str(record[id_field])] = record
    return records


def _persist_or_compare(
    *,
    record_id: str,
    payload: dict,
    existing: dict | None,
    create,
    record_type: str,
) -> bool:
    if existing is None:
        create(payload)
        return True
    if existing != payload:
        raise RuntimeError(
            f"legacy {record_type} {record_id} conflicts with authoritative database"
        )
    return False


def import_legacy_action_policy_state(
    config: AppConfig | None = None,
) -> dict[str, int]:
    config = config or AppConfig.from_env()
    repository = ActionPolicyRepository(config.funding_database_url)
    action_path = Path(config.action_intent_file)
    approval_path = Path(config.action_approval_file)
    policy_path = Path(config.policy_decision_file)

    action_records = _latest_records(action_path, "action_id")
    approval_records = _latest_records(approval_path, "approval_id")
    policy_records = _latest_records(policy_path, "policy_decision_id")
    imported = {"actions": 0, "approvals": 0, "policies": 0}

    for action_id, raw in action_records.items():
        payload = AgentActionIntent.model_validate(_sanitize(raw)).to_dict()
        imported["actions"] += int(
            _persist_or_compare(
                record_id=action_id,
                payload=payload,
                existing=repository.action_intent(action_id),
                create=repository.create_action_intent,
                record_type="action",
            )
        )

    for approval_id, raw in approval_records.items():
        raw_signature = raw.get("signature")
        sanitized = _sanitize(raw)
        if isinstance(raw_signature, str) and raw_signature:
            sanitized["proof_hash"] = _proof_hash(raw_signature)
        payload = ActionApproval.model_validate(sanitized).to_dict()
        imported["approvals"] += int(
            _persist_or_compare(
                record_id=approval_id,
                payload=payload,
                existing=repository.action_approval(approval_id),
                create=repository.create_action_approval,
                record_type="approval",
            )
        )

    for policy_id, raw in policy_records.items():
        payload = PolicyDecision.model_validate(
            _normalize_legacy_policy(raw)
        ).to_dict()
        imported["policies"] += int(
            _persist_or_compare(
                record_id=policy_id,
                payload=payload,
                existing=repository.policy_decision(policy_id),
                create=repository.create_policy_decision,
                record_type="policy decision",
            )
        )

    for path in (action_path, approval_path, policy_path):
        path.unlink(missing_ok=True)
    return imported


def main() -> None:
    print(json.dumps(import_legacy_action_policy_state(), sort_keys=True))


if __name__ == "__main__":
    main()
