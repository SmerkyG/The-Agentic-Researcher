# Sourced by agentic-team. Compaction hook rendering and CLI argument translation.

MANAGED_HOOK_TARGETS=()
MANAGED_HOOK_MARKERS=()
MANAGED_HOOK_PATCHES=()

merge_managed_hook_json() {
    local target_path="$1"
    local marker="$2"
    local patch_json="$3"

    MANAGED_HOOK_TARGETS+=("$target_path")
    MANAGED_HOOK_MARKERS+=("$marker")
    MANAGED_HOOK_PATCHES+=("$patch_json")
}

flush_managed_hook_json() {
    [[ ${#MANAGED_HOOK_TARGETS[@]} -gt 0 ]] || return 0

    local temp_root patch_dir index
    local -a python_args
    temp_root="${RUNTIME_ROOT:-${TMPDIR:-/tmp}}"
    mkdir -p "$temp_root"
    patch_dir="$(mktemp -d "$temp_root/hook-patches.XXXXXX")" || return 1
    python_args=()

    for ((index=0; index<${#MANAGED_HOOK_TARGETS[@]}; index++)); do
        printf '%s\n' "${MANAGED_HOOK_PATCHES[$index]}" > "$patch_dir/$index.json"
        python_args+=(
            "${MANAGED_HOOK_TARGETS[$index]}"
            "${MANAGED_HOOK_MARKERS[$index]}"
            "$patch_dir/$index.json"
        )
    done

    if ! python3 - "${python_args[@]}" <<'PY'
import json
import sys
from pathlib import Path

def is_managed_group(group, marker):
    if not isinstance(group, dict):
        return False
    for hook in group.get("hooks", []):
        if not isinstance(hook, dict):
            continue
        fields = [
            hook.get("command", ""),
            hook.get("name", ""),
            hook.get("statusMessage", ""),
            hook.get("description", ""),
        ]
        if any(marker in str(field) for field in fields):
            return True
    return False

documents = {}
for offset in range(1, len(sys.argv), 3):
    target = Path(sys.argv[offset])
    marker = sys.argv[offset + 1]
    patch_path = Path(sys.argv[offset + 2])
    patch = json.loads(patch_path.read_text(encoding="utf-8"))

    if target not in documents:
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"{target}: invalid JSON ({exc})", file=sys.stderr)
                sys.exit(1)
        else:
            data = {}
        if not isinstance(data, dict):
            print(f"{target}: top-level JSON value must be an object", file=sys.stderr)
            sys.exit(1)
        documents[target] = data

    data = documents[target]
    data_hooks = data.setdefault("hooks", {})
    if not isinstance(data_hooks, dict):
        print(f"{target}: hooks must be an object", file=sys.stderr)
        sys.exit(1)

    for event_name, groups in patch.get("hooks", {}).items():
        if not isinstance(groups, list):
            print(f"patch hooks.{event_name}: value must be an array", file=sys.stderr)
            sys.exit(1)
        existing = data_hooks.get(event_name, [])
        if not isinstance(existing, list):
            existing = []
        data_hooks[event_name] = [
            group for group in existing
            if not is_managed_group(group, marker)
        ] + groups

    patch_servers = patch.get("mcpServers", {})
    if patch_servers:
        if not isinstance(patch_servers, dict):
            print("patch mcpServers must be an object", file=sys.stderr)
            sys.exit(1)
        data_servers = data.setdefault("mcpServers", {})
        if not isinstance(data_servers, dict):
            print(f"{target}: mcpServers must be an object", file=sys.stderr)
            sys.exit(1)
        for server_name, server in patch_servers.items():
            if server is None:
                data_servers.pop(server_name, None)
            elif isinstance(server, dict):
                data_servers[server_name] = server
            else:
                print(
                    f"patch mcpServers.{server_name}: value must be an object or null",
                    file=sys.stderr,
                )
                sys.exit(1)

    patch_mcp = patch.get("mcp", {})
    if patch_mcp:
        if not isinstance(patch_mcp, dict):
            print("patch mcp must be an object", file=sys.stderr)
            sys.exit(1)
        data_mcp = data.setdefault("mcp", {})
        if not isinstance(data_mcp, dict):
            print(f"{target}: mcp must be an object", file=sys.stderr)
            sys.exit(1)
        for server_name, server in patch_mcp.items():
            if server is None:
                data_mcp.pop(server_name, None)
            elif isinstance(server, dict):
                data_mcp[server_name] = server
            else:
                print(
                    f"patch mcp.{server_name}: value must be an object or null",
                    file=sys.stderr,
                )
                sys.exit(1)

for target, data in documents.items():
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
    then
        rm -rf "$patch_dir"
        return 1
    fi

    rm -rf "$patch_dir"
    MANAGED_HOOK_TARGETS=()
    MANAGED_HOOK_MARKERS=()
    MANAGED_HOOK_PATCHES=()
}

render_compaction_context_hook_script() {
    local target_path="$1"
    local managed_marker="Generated by agentic-team"

    if [[ -f "$target_path" ]] && ! grep -q "$managed_marker" "$target_path"; then
        echo "Warning: Skipping existing compaction hook script at $target_path (not managed by agentic-team)"
        return 1
    fi

    mkdir -p "$(dirname "$target_path")"
    cat > "$target_path" <<'PY'
#!/usr/bin/env python3
# Generated by agentic-team. Edit the launcher to change this file.
import json
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    except Exception as exc:
        return False, f"{command[0]} did not run: {exc}"
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return True, output
    return False, output or f"{command[0]} exited with status {result.returncode}."


def run_refresh(capability_refresh_cli: str, instruction_path: str, project_dir: str, agent_type: str, cli: str) -> tuple[bool, str]:
    if not capability_refresh_cli:
        return False, "capability-refresh was not configured."
    command = [
        capability_refresh_cli,
        "--instruction-path",
        instruction_path,
        "--project-dir",
        project_dir,
        "--agent-type",
        agent_type,
        "--cli",
        cli,
    ]
    return run_command(command)


def read_hook_input() -> dict:
    try:
        value = json.load(sys.stdin)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def refresh_message(instruction_path: str, capability_refresh_cli: str, project_dir: str, agent_type: str, cli: str) -> str:
    refreshed, refresh_status = run_refresh(capability_refresh_cli, instruction_path, project_dir, agent_type, cli)
    refresh_sentence = (
        "Agentic Team just refreshed configured capabilities and rematerialized the rendered instruction file."
        if refreshed
        else f"Agentic Team tried to refresh configured capabilities, but refresh failed: {refresh_status}"
    )
    return (
        "You have just experienced context compaction. Treat this moment as "
        "the new `since the last compaction` boundary for Agentic Notes. "
        f"{refresh_sentence} Before continuing, read "
        f"`{instruction_path}`, the instruction file rendered for this "
        "specific Agentic Team invocation, then continue with whatever "
        "task was in progress before compaction. Do not restart from scratch."
    )


def marker_path() -> Path:
    return Path(__file__).with_name(".agentic-team-compaction.pending")


def inject_pending() -> None:
    read_hook_input()
    marker = marker_path()
    try:
        marker.unlink()
    except FileNotFoundError:
        pass

    print("{}")


def parse_args() -> tuple[str, str, str, str, str, str]:
    modes = {"session-start", "post-compact", "inject-pending"}
    if len(sys.argv) > 1 and sys.argv[1] in modes:
        mode = sys.argv[1]
        offset = 2
    else:
        mode = "session-start"
        offset = 1

    instruction_path = sys.argv[offset] if len(sys.argv) > offset else "AGENTS.md"
    capability_refresh_cli = sys.argv[offset + 1] if len(sys.argv) > offset + 1 else ""
    project_dir = sys.argv[offset + 2] if len(sys.argv) > offset + 2 else "."
    agent_type = sys.argv[offset + 3] if len(sys.argv) > offset + 3 else "research-coordinator"
    cli = sys.argv[offset + 4] if len(sys.argv) > offset + 4 else "codex"
    return mode, instruction_path, capability_refresh_cli, project_dir, agent_type, cli


def main() -> None:
    mode, instruction_path, capability_refresh_cli, project_dir, agent_type, cli = parse_args()
    if mode == "inject-pending":
        inject_pending()
        return

    hook_input = read_hook_input()
    event_name = hook_input.get("hook_event_name") or "SessionStart"
    if mode == "session-start" and event_name != "SessionStart":
        print("{}")
        return

    message = refresh_message(instruction_path, capability_refresh_cli, project_dir, agent_type, cli)
    if mode == "post-compact":
        print(json.dumps({
            "systemMessage": message,
        }))
        return

    print(json.dumps({
        "systemMessage": "Agentic Team refreshed post-compaction instructions.",
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": message,
        },
    }))


if __name__ == "__main__":
    main()
PY
    chmod +x "$target_path"
}

setup_compaction_hooks() {
    [[ -n "${INSTRUCTION_TARGET:-}" ]] || return 0

    PI_AGENTIC_COMPACTION_EXTENSION=""
    cli_call setup_compaction_hooks
}

render_steering_context_hook_script() {
    local target_path="$1"
    local managed_marker="Generated by agentic-team"

    if [[ -f "$target_path" ]] && ! grep -q "$managed_marker" "$target_path"; then
        echo "Warning: Skipping existing steering hook script at $target_path (not managed by agentic-team)"
        return 1
    fi

    mkdir -p "$(dirname "$target_path")"
    cat > "$target_path" <<'PY'
#!/usr/bin/env python3
# Generated by agentic-team. Edit the launcher to change this file.
import json
import subprocess
import sys


def read_hook_input() -> dict:
    try:
        value = json.load(sys.stdin)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def run_steering(agentic_notes_cli: str, project_dir: str, agent_type: str) -> str:
    if not agentic_notes_cli:
        return ""
    command = [
        agentic_notes_cli,
        "steering-message",
        "--project-dir",
        project_dir,
        "--agent-type",
        agent_type,
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10)
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def codex_post_tool(agentic_notes_cli: str, project_dir: str, agent_type: str) -> None:
    read_hook_input()
    message = run_steering(agentic_notes_cli, project_dir, agent_type)
    if not message:
        print("{}")
        return
    print(json.dumps({
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        },
    }))


def gemini_before_model(agentic_notes_cli: str, project_dir: str, agent_type: str) -> None:
    hook_input = read_hook_input()
    message = run_steering(agentic_notes_cli, project_dir, agent_type)
    if not message:
        print("{}")
        return

    llm_request = hook_input.get("llm_request")
    if not isinstance(llm_request, dict):
        print("{}")
        return
    messages = llm_request.get("messages")
    if not isinstance(messages, list):
        messages = []
    updated_request = dict(llm_request)
    updated_request["messages"] = messages + [{
        "role": "system",
        "content": message,
    }]
    print(json.dumps({
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "BeforeModel",
            "llm_request": updated_request,
        },
    }))


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "codex-post-tool"
    agentic_notes_cli = sys.argv[2] if len(sys.argv) > 2 else "agentic-notes"
    project_dir = sys.argv[3] if len(sys.argv) > 3 else "."
    agent_type = sys.argv[4] if len(sys.argv) > 4 else "research-coordinator"

    if mode == "gemini-before-model":
        gemini_before_model(agentic_notes_cli, project_dir, agent_type)
    else:
        codex_post_tool(agentic_notes_cli, project_dir, agent_type)


if __name__ == "__main__":
    main()
PY
    chmod +x "$target_path"
}

agentic_notes_runtime_command() {
    local notes_root notes_runtime

    if ! notes_root="$(capability_root agentic-notes)"; then
        return 1
    fi
    notes_runtime="$(capability_runtime_root agentic-notes "$notes_root")"
    printf '%s/bin/agentic-notes\n' "$notes_runtime"
}

setup_steering_hooks() {
    [[ -n "${INSTRUCTION_TARGET:-}" ]] || return 0
    capability_enabled agentic-notes || return 0

    cli_call setup_steering_hooks
}

setup_tool_transport() {
    cli_call setup_tool_transport
}

translate_cli_args() {
    cli_call translate_cli_args
}
