"""Resolve Agentic Team client sessions without storing runtime config in Git worktrees."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any


SCHEMA_VERSION = 1


def default_registry_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "agentic-team" / "client-contexts.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or "=" not in raw_line:
            continue
        name, value = raw_line.split("=", 1)
        if name.isidentifier():
            values[name] = value
    return values


def register_context(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    project_dir = Path(args.project_dir).expanduser().absolute()
    real_project_dir = project_dir.resolve()
    environment = parse_env_file(Path(args.env_file))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "client": args.client,
        "project_dir": str(project_dir),
        "real_project_dir": str(real_project_dir),
        "instruction_path": args.instruction_path,
        "main_agent": args.main_agent,
        "work_branch": args.work_branch,
        "work_name": args.work_name,
        "capabilities": [item for item in args.capabilities.split(",") if item],
        "environment": environment,
        "commands": {
            "workflow_mcp": args.workflow_mcp or "",
            "capability_refresh": args.capability_refresh,
            "agentic_notes": args.agentic_notes or "",
        },
    }
    _write_json_atomic(manifest_path, manifest)

    registry_path = Path(args.registry).expanduser()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = registry_path.with_suffix(f"{registry_path.suffix}.lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        registry = _read_json(
            registry_path,
            {"schema_version": SCHEMA_VERSION, "entries": []},
        )
        if not isinstance(registry, dict):
            registry = {"schema_version": SCHEMA_VERSION, "entries": []}
        entries = registry.get("entries")
        if not isinstance(entries, list):
            entries = []
        keys = {str(project_dir), str(real_project_dir)}
        retained = [
            item
            for item in entries
            if not (
                isinstance(item, dict)
                and item.get("client") == args.client
                and item.get("project_dir") in keys
            )
        ]
        for key in sorted(keys):
            retained.append(
                {
                    "client": args.client,
                    "project_dir": key,
                    "manifest": str(manifest_path),
                }
            )
        registry["schema_version"] = SCHEMA_VERSION
        registry["entries"] = retained
        _write_json_atomic(registry_path, registry)
    return 0


def _candidate_cwd(payload: dict[str, Any] | None = None) -> Path:
    payload = payload or {}
    for key in ("cwd", "project_dir", "workspace", "working_directory"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return Path(value).expanduser().resolve()
    return Path.cwd().resolve()


def resolve_manifest(
    *,
    client: str | None = None,
    cwd: Path | None = None,
    explicit: str | None = None,
    registry_path: str | None = None,
) -> Path:
    explicit = explicit or os.environ.get("AR_CLIENT_CONTEXT")
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path.resolve()

    registry = Path(
        registry_path
        or os.environ.get("AR_CLIENT_CONTEXT_REGISTRY", "")
        or default_registry_path()
    )
    data = _read_json(registry, {})
    entries = data.get("entries", []) if isinstance(data, dict) else []
    current = (cwd or Path.cwd()).expanduser().resolve()
    matches: list[tuple[int, Path]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        if client and item.get("client") != client:
            continue
        project_text = item.get("project_dir")
        manifest_text = item.get("manifest")
        if not isinstance(project_text, str) or not isinstance(manifest_text, str):
            continue
        project = Path(project_text).expanduser().resolve()
        try:
            current.relative_to(project)
        except ValueError:
            continue
        manifest = Path(manifest_text).expanduser()
        if manifest.is_file():
            matches.append((len(project.parts), manifest.resolve()))
    if not matches:
        raise RuntimeError(
            f"no Agentic Team client context matched {current}"
            + (f" for {client}" if client else "")
        )
    return max(matches, key=lambda item: item[0])[1]


def load_manifest(path: Path) -> dict[str, Any]:
    value = _read_json(path, None)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"invalid Agentic Team client context: {path}")
    return value


def apply_environment(manifest: dict[str, Any]) -> None:
    environment = manifest.get("environment", {})
    if not isinstance(environment, dict):
        return
    for name, value in environment.items():
        if isinstance(name, str) and name.isidentifier() and isinstance(value, str):
            os.environ[name] = value


def exec_with_context(args: argparse.Namespace) -> int:
    manifest_path = resolve_manifest(
        client=args.client,
        cwd=Path(args.cwd).resolve() if args.cwd else None,
        explicit=args.manifest,
        registry_path=args.registry,
    )
    manifest = load_manifest(manifest_path)
    apply_environment(manifest)
    os.environ["AR_CLIENT_CONTEXT"] = str(manifest_path)
    os.chdir(manifest["project_dir"])
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise RuntimeError("exec requires a command")
    os.execvp(command[0], command)
    return 127


def exec_workflow_mcp(args: argparse.Namespace) -> int:
    manifest_path = resolve_manifest(
        client=args.client,
        cwd=Path(args.cwd).resolve() if args.cwd else None,
        explicit=args.manifest,
        registry_path=args.registry,
    )
    manifest = load_manifest(manifest_path)
    apply_environment(manifest)
    os.environ["AR_CLIENT_CONTEXT"] = str(manifest_path)
    command = manifest.get("commands", {}).get("workflow_mcp", "")
    if not isinstance(command, str) or not command:
        raise RuntimeError("imperative workflows are not enabled for this AT context")
    os.execv(command, [command])
    return 127


def _read_hook_payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _run(command: list[str], timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output


def _refresh_message(manifest: dict[str, Any]) -> str:
    commands = manifest.get("commands", {})
    command = commands.get("capability_refresh", "") if isinstance(commands, dict) else ""
    refresh = [
        command,
        "--instruction-path",
        manifest["instruction_path"],
        "--project-dir",
        manifest.get("environment", {}).get("AR_PROJECT_DIR", manifest["project_dir"]),
        "--agent-type",
        manifest["main_agent"],
        "--cli",
        manifest["client"],
    ]
    refreshed, status = _run(refresh, 60) if command else (False, "not configured")
    sentence = (
        "Agentic Team refreshed configured capabilities and rematerialized the rendered instruction file."
        if refreshed
        else f"Agentic Team tried to refresh configured capabilities, but refresh failed: {status}"
    )
    return (
        "You have just experienced context compaction. Treat this moment as the new "
        "`since the last compaction` boundary for Agentic Notes. "
        f"{sentence} Before continuing, read `{manifest['instruction_path']}`, then continue "
        "with whatever task was in progress before compaction. Do not restart from scratch."
    )


def _steering_message(manifest: dict[str, Any]) -> str:
    commands = manifest.get("commands", {})
    executable = commands.get("agentic_notes", "") if isinstance(commands, dict) else ""
    if not executable:
        return ""
    ok, output = _run(
        [
            executable,
            "steering-message",
            "--project-dir",
            manifest.get("environment", {}).get("AR_PROJECT_DIR", manifest["project_dir"]),
            "--agent-type",
            manifest["main_agent"],
        ],
        10,
    )
    return output if ok else ""


def run_hook(args: argparse.Namespace) -> int:
    payload = _read_hook_payload()
    try:
        manifest_path = resolve_manifest(
            client=args.client,
            cwd=_candidate_cwd(payload),
            explicit=args.manifest,
            registry_path=args.registry,
        )
        manifest = load_manifest(manifest_path)
        apply_environment(manifest)
    except RuntimeError:
        print("{}")
        return 0

    if args.mode in {"claude-compact", "codex-post-compact"}:
        message = _refresh_message(manifest)
        if args.mode == "codex-post-compact":
            print(json.dumps({"systemMessage": message}))
        else:
            event_name = payload.get("hook_event_name") or "SessionStart"
            print(
                json.dumps(
                    {
                        "systemMessage": "Agentic Team refreshed post-compaction instructions.",
                        "hookSpecificOutput": {
                            "hookEventName": event_name,
                            "additionalContext": message,
                        },
                    }
                )
            )
        return 0

    if args.mode == "codex-post-tool":
        message = _steering_message(manifest)
        if not message:
            print("{}")
        else:
            print(
                json.dumps(
                    {
                        "suppressOutput": True,
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": message,
                        },
                    }
                )
            )
        return 0

    marker = manifest_path.parent / ".compaction-pending.json"
    if args.mode == "gemini-mark":
        _write_json_atomic(marker, {"time": time.time()})
        print(
            json.dumps(
                {
                    "systemMessage": "Agentic Team will refresh instructions on the next model call.",
                    "suppressOutput": True,
                }
            )
        )
        return 0

    if args.mode in {"gemini-inject", "gemini-steering"}:
        if args.mode == "gemini-inject":
            if not marker.exists():
                print("{}")
                return 0
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
            message = _refresh_message(manifest)
        else:
            message = _steering_message(manifest)
            if not message:
                print("{}")
                return 0

        llm_request = payload.get("llm_request")
        if not isinstance(llm_request, dict):
            print("{}")
            return 0
        messages = llm_request.get("messages")
        if not isinstance(messages, list):
            messages = []
        updated_request = dict(llm_request)
        updated_request["messages"] = messages + [{"role": "system", "content": message}]
        print(
            json.dumps(
                {
                    "suppressOutput": True,
                    "hookSpecificOutput": {
                        "hookEventName": "BeforeModel",
                        "llm_request": updated_request,
                    },
                }
            )
        )
        return 0

    raise RuntimeError(f"unsupported hook mode: {args.mode}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-team-client")
    sub = parser.add_subparsers(dest="command_name", required=True)

    register = sub.add_parser("register")
    register.add_argument("--manifest", required=True)
    register.add_argument("--registry", required=True)
    register.add_argument("--env-file", required=True)
    register.add_argument("--client", required=True)
    register.add_argument("--project-dir", required=True)
    register.add_argument("--instruction-path", required=True)
    register.add_argument("--main-agent", required=True)
    register.add_argument("--work-branch", default="")
    register.add_argument("--work-name", default="")
    register.add_argument("--capabilities", default="")
    register.add_argument("--workflow-mcp", default="")
    register.add_argument("--capability-refresh", required=True)
    register.add_argument("--agentic-notes", default="")
    register.set_defaults(func=register_context)

    execute = sub.add_parser("exec")
    execute.add_argument("--client")
    execute.add_argument("--manifest")
    execute.add_argument("--registry")
    execute.add_argument("--cwd")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    execute.set_defaults(func=exec_with_context)

    mcp = sub.add_parser("exec-workflow-mcp")
    mcp.add_argument("--client", required=True)
    mcp.add_argument("--manifest")
    mcp.add_argument("--registry")
    mcp.add_argument("--cwd")
    mcp.set_defaults(func=exec_workflow_mcp)

    hook = sub.add_parser("hook")
    hook.add_argument("mode")
    hook.add_argument("--client", required=True)
    hook.add_argument("--manifest")
    hook.add_argument("--registry")
    hook.set_defaults(func=run_hook)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except RuntimeError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
