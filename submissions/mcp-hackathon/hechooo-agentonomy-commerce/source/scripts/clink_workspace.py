from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REQUIRED_ACTIONS = ("start", "stop", "status", "test")


@dataclass(frozen=True)
class AppConfig:
    name: str
    path: Path
    commands: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Workspace:
    schema_version: int
    apps: tuple[AppConfig, ...]


@dataclass(frozen=True)
class ExecutionPlan:
    app: str
    action: str
    cwd: Path
    command: tuple[str, ...]


def load_workspace(path: Path) -> Workspace:
    with path.open("rb") as manifest:
        raw = tomllib.load(manifest)

    apps = tuple(
        AppConfig(
            name=item["name"],
            path=Path(item["path"]),
            commands={
                action: tuple(command)
                for action, command in item["commands"].items()
            },
        )
        for item in raw["apps"]
    )
    return Workspace(schema_version=raw["schema_version"], apps=apps)


def validate_workspace(workspace: Workspace, root: Path) -> list[str]:
    errors: list[str] = []
    if workspace.schema_version != 1:
        errors.append(
            f"unsupported workspace schema_version: {workspace.schema_version}"
        )

    names = [app.name for app in workspace.apps]
    duplicate_names = sorted(
        name for name in set(names) if names.count(name) > 1
    )
    for name in duplicate_names:
        errors.append(f"duplicate app name: {name}")

    for app in workspace.apps:
        app_root = root / app.path
        if not app_root.is_dir():
            errors.append(f"{app.name}: missing app directory {app.path}")
            continue

        for action in REQUIRED_ACTIONS:
            command = app.commands.get(action)
            if not command:
                errors.append(f"{app.name}: missing command for {action}")
                continue

            entrypoint = _relative_entrypoint(command)
            if entrypoint and not (app_root / entrypoint).is_file():
                errors.append(
                    f"{app.name}: missing {action} entrypoint "
                    f"{app.path / entrypoint}"
                )

    return errors


def _relative_entrypoint(command: tuple[str, ...]) -> Path | None:
    if len(command) < 2:
        return None
    executable = Path(command[0]).name
    candidate = command[1]
    if executable in {"bash", "sh"}:
        return Path(candidate)
    if executable.startswith("python") and not candidate.startswith("-"):
        return Path(candidate)
    return None


def plan_execution(
    workspace: Workspace,
    root: Path,
    app_name: str,
    action: str,
) -> ExecutionPlan:
    app = next((item for item in workspace.apps if item.name == app_name), None)
    if app is None:
        raise ValueError(f"unknown app: {app_name}")
    command = app.commands.get(action)
    if command is None:
        raise ValueError(f"unknown action for {app_name}: {action}")
    return ExecutionPlan(
        app=app.name,
        action=action,
        cwd=root / app.path,
        command=command,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clink monorepo workspace")
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    subparsers.add_parser("list", help="List imported applications")
    subparsers.add_parser("doctor", help="Validate workspace structure")
    execute = subparsers.add_parser("exec", help="Run an application action")
    execute.add_argument("app")
    execute.add_argument("action")
    execute.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    workspace = load_workspace(root / "clink.workspace.toml")

    if args.command_name == "list":
        print(
            json.dumps(
                [
                    {"name": app.name, "path": app.path.as_posix()}
                    for app in workspace.apps
                ],
                ensure_ascii=False,
            )
        )
        return 0

    if args.command_name == "doctor":
        errors = validate_workspace(workspace, root)
        print(
            json.dumps(
                {"status": "ok" if not errors else "error", "errors": errors},
                ensure_ascii=False,
            )
        )
        return 0 if not errors else 1

    try:
        plan = plan_execution(
            workspace,
            root,
            args.app,
            args.action,
        )
    except ValueError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2

    if args.dry_run:
        print(
            json.dumps(
                {
                    "app": plan.app,
                    "action": plan.action,
                    "cwd": plan.cwd.relative_to(root).as_posix(),
                    "command": list(plan.command),
                },
                sort_keys=True,
            )
        )
        return 0

    completed = subprocess.run(plan.command, cwd=plan.cwd, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
