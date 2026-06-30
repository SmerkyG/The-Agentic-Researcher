"""Shared mechanics for built-in Agentic Researcher tool executables."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parents[1]


class ToolError(RuntimeError):
    pass


def state_root() -> Path:
    return Path(os.environ.get("AR_STATE_ROOT", "~/.cache/agentic-researcher")).expanduser()


def helper_path(env_name: str, helper_name: str) -> Path:
    return Path(os.environ.get(env_name) or (SCRIPT_DIR / helper_name)).expanduser()


def ar_notes() -> Path:
    return helper_path("AR_NOTES_CLI", "ar-notes")


def load_request() -> dict[str, Any]:
    text = sys.stdin.read()
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ToolError("request YAML must be a mapping")
    if "kind" in data:
        raise ToolError("omit request kind; select the tool with `ar-tool run TOOL`")
    return data


def write_temp_request(request: dict[str, Any]) -> Path:
    root = state_root() / "tmp" / "ar-tool"
    root.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".yaml",
        prefix="request-",
        dir=root,
        delete=False,
    )
    with handle:
        yaml.safe_dump(request, handle, sort_keys=False, allow_unicode=False)
    return Path(handle.name)


def internal_request(request: dict[str, Any], kind: str) -> dict[str, Any]:
    data = dict(request)
    data["kind"] = kind
    return data


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ToolError(f"{' '.join(command)} failed: {detail}")
    return result


def run_json(command: list[str]) -> dict[str, Any]:
    result = run_command(command)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{' '.join(command)} returned non-JSON output: {result.stdout.strip()}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"{' '.join(command)} returned non-object JSON")
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


def topic_from(request: dict[str, Any]) -> str | None:
    value = request.get("topic") or os.environ.get("AR_AGENT_TOPIC")
    return str(value) if value else None


def main(func: Any) -> int:
    try:
        func()
    except ToolError as exc:
        print(f"{os.environ.get('AR_TOOL_NAME', 'ar-tool')}: {exc}", file=sys.stderr)
        return 1
    return 0
