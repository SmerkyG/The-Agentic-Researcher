#!/bin/bash

register_cli_adapter claude 10

cli_claude_apply_defaults() {
    AR_AUTH_MODE="${AR_AUTH_MODE:-oauth}"
    AR_API_PROVIDER="${AR_API_PROVIDER:-anthropic}"
    AR_API_KEY_ENV="${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
    AR_DEFAULT_MODEL="${AR_DEFAULT_MODEL:-sonnet}"
}

cli_claude_setup_storage() {
    CLAUDE_JSON="$AR_CONFIG_STORE/claude.json"

    mkdir -p \
        "$AR_CONFIG_STORE/.cache" \
        "$AR_CONFIG_STORE/.local/bin" \
        "$AR_CONFIG_STORE/.local/state" \
        "$AR_CONFIG_STORE/.ssh"

    # Pre-create placeholder files for nested file binds. On Docker/Podman the
    # launcher bind-mounts $AR_CONFIG_STORE over $AR_SANDBOX_HOME; nested bind
    # targets inside that dir must already exist on the host.
    touch "$AR_CONFIG_STORE/.gitconfig" "$AR_CONFIG_STORE/.claude.json"

    if [[ ! -f "$CLAUDE_JSON" ]]; then
        echo '{"hasCompletedOnboarding": true}' > "$CLAUDE_JSON"
    fi
}

cli_claude_validate_auth() {
    # Tool-managed auth and OAuth are handled inside Claude itself.
    if [[ "${AR_AUTH_MODE:-tool}" == "tool" || "${AR_AUTH_MODE:-tool}" == "oauth" ]]; then
        return
    fi
    local key_var="${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
    if [[ -z "${!key_var:-}" ]]; then
        echo "Error: $key_var environment variable is not set."
        echo ""
        echo "Either set your API key:"
        echo "  export $key_var='your-api-key-here'"
        echo ""
        echo "Or switch to OAuth login:"
        echo "  agentic-researcher --setup  (select 'oauth' for authentication)"
        exit 1
    fi
}

cli_claude_validate_workspace() {
    local resolved_home
    if [[ -n "${HOME:-}" ]] && resolved_home="$(resolve_realpath "$HOME" 2>/dev/null)"; then
        case "$WORKSPACE_DIR" in
            "$resolved_home/.claude"|"$resolved_home/.claude"/*)
                echo "Error: Cannot sandbox Claude config directories: $WORKSPACE_DIR"
                exit 1
                ;;
        esac
    fi

    case "$WORKSPACE_DIR" in
        /home/*/.claude/*|/home/*/.claude|/Users/*/.claude/*|/Users/*/.claude)
            echo "Error: Cannot sandbox Claude config directories: $WORKSPACE_DIR"
            exit 1
            ;;
    esac
}

cli_claude_instruction_target() {
    printf '%s\n' "CLAUDE.md"
}

cli_claude_project_skill_root() {
    printf '%s\n' "$WORKSPACE_DIR/.claude/skills"
}

cli_claude_project_agent_root() {
    printf '%s\n' "$WORKSPACE_DIR/.claude/agents"
}

cli_claude_agent_target_path() {
    printf '%s/%s.md\n' "$1" "$2"
}

cli_claude_render_agent() {
    render_markdown_agent_file "$@"
}

cli_claude_setup_compaction_hooks() {
    local script_path="$WORKSPACE_DIR/.claude/hooks/agentic-researcher-compaction.py"
    render_compaction_context_hook_script "$script_path" || return 0

    local script_runtime instruction_runtime notes_cli_runtime project_runtime agent_type_runtime tool_runtime python_runtime command patch_json
    script_runtime="$(workspace_runtime_path ".claude/hooks/agentic-researcher-compaction.py")"
    instruction_runtime="$(workspace_runtime_path "$INSTRUCTION_TARGET")"
    notes_cli_runtime="$(ar_notes_cli_env_path)"
    project_runtime="$(workspace_root_runtime_path)"
    agent_type_runtime="${AR_MAIN_AGENT:-research-coordinator}"
    tool_runtime="$AR_CLI_TOOL"
    python_runtime="$(python_runtime_command_string)"
    command="$python_runtime $(shell_quote "$script_runtime") $(shell_quote "$instruction_runtime") $(shell_quote "$notes_cli_runtime") $(shell_quote "$project_runtime") $(shell_quote "$agent_type_runtime") $(shell_quote "$tool_runtime")"
    patch_json=$(cat <<EOF
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": $(json_string "$command"),
            "timeout": 120
          }
        ]
      }
    ]
  }
}
EOF
)
    if ! merge_managed_hook_json "$WORKSPACE_DIR/.claude/settings.local.json" "agentic-researcher-compaction" "$patch_json"; then
        echo "Warning: Could not update Claude compaction hook settings."
    fi
}

cli_claude_translate_tool_args() {
    if [[ "$MODEL_SPECIFIED" == "false" && -n "${AR_DEFAULT_MODEL:-}" ]]; then
        TOOL_ARGS+=("--model" "$AR_DEFAULT_MODEL")
    fi
    if [[ "$YOLO_MODE" == "true" ]]; then
        TOOL_ARGS+=("--dangerously-skip-permissions")
    fi
}

cli_claude_add_env_args() {
    append_env_arg_from_host "ANTHROPIC_API_KEY"
    if [[ "${AR_AUTH_MODE:-}" == "api-key" ]]; then
        append_env_arg_from_host_as "ANTHROPIC_API_KEY" "${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
    fi
    if [[ -n "${AR_CUSTOM_ANTHROPIC_ENDPOINT:-}" && "${AR_AUTH_MODE:-}" == "api-key" ]]; then
        ENV_ARGS+=(--env "ANTHROPIC_BASE_URL=$AR_CUSTOM_ANTHROPIC_ENDPOINT")
    fi
}

cli_claude_add_apptainer_binds() {
    BIND_ARGS+=(
        --bind "$AR_CONFIG_STORE:$AR_SANDBOX_HOME/.claude"
        --bind "$CLAUDE_JSON:$AR_SANDBOX_HOME/.claude.json"
        "${RESEARCH_BINDS[@]}"
    )
}

cli_claude_add_oci_args() {
    OCI_ARGS+=(
        -v "$AR_CONFIG_STORE:$AR_SANDBOX_HOME/.claude"
        -v "$CLAUDE_JSON:$AR_SANDBOX_HOME/.claude.json"
    )
    append_oci_env_from_host "ANTHROPIC_API_KEY"
    if [[ "${AR_AUTH_MODE:-}" == "api-key" ]]; then
        append_oci_env_from_host_as "ANTHROPIC_API_KEY" "${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
    fi
    if [[ -n "${AR_CUSTOM_ANTHROPIC_ENDPOINT:-}" && "${AR_AUTH_MODE:-}" == "api-key" ]]; then
        OCI_ARGS+=(-e "ANTHROPIC_BASE_URL=$AR_CUSTOM_ANTHROPIC_ENDPOINT")
    fi
}

cli_claude_setup_native_environment() {
    if [[ "${AR_AUTH_MODE:-}" == "api-key" ]]; then
        export_env_from_host_as "ANTHROPIC_API_KEY" "${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
    fi
    if [[ -n "${AR_CUSTOM_ANTHROPIC_ENDPOINT:-}" && "${AR_AUTH_MODE:-}" == "api-key" ]]; then
        export ANTHROPIC_BASE_URL="$AR_CUSTOM_ANTHROPIC_ENDPOINT"
    fi
}

cli_claude_native_command() {
    printf '%s\n' "claude"
}

cli_claude_display_name() {
    printf '%s\n' "Claude Code"
}
