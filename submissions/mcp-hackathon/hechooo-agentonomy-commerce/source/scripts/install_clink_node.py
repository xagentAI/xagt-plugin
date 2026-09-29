from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallPlan:
    profile: str
    venv: Path
    clink_home: Path
    commands: tuple[tuple[str, ...], ...]

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "venv": str(self.venv),
            "clink_home": str(self.clink_home),
            "commands": [list(command) for command in self.commands],
        }


def build_plan(
    *,
    root: Path,
    python: str,
    venv: Path,
    clink_home: Path,
    profile: str,
) -> InstallPlan:
    venv_python = venv / "bin" / "python"
    commands: list[tuple[str, ...]] = [
        (python, "-m", "venv", str(venv)),
        (
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
        ),
        (
            str(venv_python),
            "-m",
            "pip",
            "install",
            "-e",
            str(root / "apps/node"),
        ),
    ]
    if not (clink_home / "config.toml").exists():
        commands.append(
            (
                str(venv_python),
                "-m",
                "clink_node",
                "init",
                "--profile",
                profile,
            )
        )
    return InstallPlan(
        profile=profile,
        venv=venv,
        clink_home=clink_home,
        commands=tuple(commands),
    )


def main(arguments: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Install the unified Clink Node runtime."
    )
    parser.add_argument(
        "--profile",
        choices=("personal", "server"),
        default="personal",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=root / ".venv-node",
    )
    parser.add_argument(
        "--clink-home",
        type=Path,
        default=Path.home() / ".clink",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(arguments)

    plan = build_plan(
        root=root,
        python=options.python,
        venv=options.venv.expanduser().resolve(),
        clink_home=options.clink_home.expanduser().resolve(),
        profile=options.profile,
    )
    if options.dry_run:
        print(json.dumps(plan.as_dict(), sort_keys=True))
        return 0

    environment = dict(os.environ)
    environment["CLINK_HOME"] = str(plan.clink_home)
    for command in plan.commands:
        subprocess.run(command, cwd=root, env=environment, check=True)
    print(
        f"Clink Node installed profile={plan.profile} "
        f"home={plan.clink_home}"
    )
    print(
        f"Start with: {plan.venv / 'bin' / 'python'} "
        "-m clink_node start --detach"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
