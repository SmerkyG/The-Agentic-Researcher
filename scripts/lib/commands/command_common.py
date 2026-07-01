"""Shared mechanics for built-in Agentic Team command executables."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml


COMMAND_LIB_DIR = Path(__file__).resolve().parent


class CommandError(RuntimeError):
    pass


def state_root() -> Path:
    return Path(os.environ.get("AR_STATE_ROOT", "~/.cache/agentic-team")).expanduser()


def load_request() -> dict[str, Any]:
    text = sys.stdin.read()
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise CommandError("request YAML must be a mapping")
    if "kind" in data:
        raise CommandError("omit request kind; select the command by running it directly")
    return data


def internal_request(request: dict[str, Any], kind: str) -> dict[str, Any]:
    data = dict(request)
    data["kind"] = kind
    return data


def request_text(request: dict[str, Any]) -> str:
    return yaml.safe_dump(request, sort_keys=False, allow_unicode=False)


def run_command(
    command: list[str],
    *,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CommandError(f"{' '.join(command)} failed: {detail}")
    return result


def run_json(command: list[str]) -> dict[str, Any]:
    result = run_command(command)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError(f"{' '.join(command)} returned non-JSON output: {result.stdout.strip()}") from exc
    if not isinstance(data, dict):
        raise CommandError(f"{' '.join(command)} returned non-object JSON")
    return data


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, sort_keys=True))


def bool_from(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def project_dir_from(request: dict[str, Any]) -> str:
    return str(request.get("project_dir") or os.environ.get("AR_PROJECT_DIR") or ".")


def work_branch_from(request: dict[str, Any]) -> str | None:
    value = (
        request.get("work_branch")
        or os.environ.get("AR_WORK_BRANCH")
    )
    return str(value) if value else None


def main(func: Any) -> int:
    try:
        func()
    except CommandError as exc:
        command_name = os.environ.get("AR_COMMAND_NAME") or Path(sys.argv[0]).name or "command"
        print(f"{command_name}: {exc}", file=sys.stderr)
        return 1
    return 0
