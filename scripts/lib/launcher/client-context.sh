# Sourced by agentic-team. External per-work client context and launch preparation.

client_context_registry_path() {
    printf '%s/agentic-team/client-contexts.json\n' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

client_runtime_command() {
    printf '%s/agentic-team-client\n' "$(ar_core_bin_env_path)"
}

client_asset_path() {
    printf '%s/%s\n' "$AR_CLIENT_DIR" "$1"
}

setup_client_context() {
    local env_file workflow_mcp="" agentic_notes="" capabilities name entry saved_ifs

    AR_CLIENT_ROOT="$AR_WORKSPACE_ROOT/$AR_WORK_NAME/client"
    AR_CLIENT_DIR="$AR_CLIENT_ROOT/$AR_CLI"
    AR_CLIENT_CONTEXT="$AR_CLIENT_DIR/context.json"
    AR_CLIENT_CONTEXT_REGISTRY="$(client_context_registry_path)"
    export AR_CLIENT_ROOT AR_CLIENT_DIR AR_CLIENT_CONTEXT AR_CLIENT_CONTEXT_REGISTRY
    mkdir -p "$AR_CLIENT_DIR" "$(dirname "$AR_CLIENT_CONTEXT_REGISTRY")"

    env_file="$(mktemp "$AR_RUNTIME_ROOT/client-context-env.XXXXXX")"
    ar_runtime_env_pairs > "$env_file"
    cli_call client_context_env_pairs >> "$env_file"
    for name in "${STORAGE_NAMES[@]}"; do
        [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        printf '%s=%s\n' "$name" "${!name:-}" >> "$env_file"
    done
    if [[ -n "${AR_EXTRA_ENV:-}" ]]; then
        saved_ifs="$IFS"
        IFS='|'
        for entry in $AR_EXTRA_ENV; do
            [[ "$entry" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
            printf '%s\n' "$entry" >> "$env_file"
        done
        IFS="$saved_ifs"
    fi
    if capability_enabled imperative-workflows; then
        workflow_mcp="$(imperative_workflows_mcp_runtime_command || true)"
    fi
    if capability_enabled agentic-notes; then
        agentic_notes="$(agentic_notes_runtime_command || true)"
    fi
    capabilities="$(join_values , "${SELECTED_CAPABILITIES[@]}")"
    local register_status=0
    python3 "$SCRIPT_DIR/scripts/bin/agentic-team-client" register \
        --manifest "$AR_CLIENT_CONTEXT" \
        --registry "$AR_CLIENT_CONTEXT_REGISTRY" \
        --env-file "$env_file" \
        --client "$AR_CLI" \
        --project-dir "$WORKSPACE_DIR" \
        --instruction-path "$(workspace_runtime_path "$INSTRUCTION_TARGET")" \
        --main-agent "$AR_MAIN_AGENT" \
        --work-branch "${AR_WORK_BRANCH:-}" \
        --work-name "${AR_WORK_NAME:-}" \
        --capabilities "$capabilities" \
        --workflow-mcp "$workflow_mcp" \
        --capability-refresh "$(ar_core_bin_env_path)/capability-refresh" \
        --agentic-notes "$agentic_notes" || register_status=$?
    rm -f "$env_file"
    return "$register_status"
}

write_prepared_client_launcher() {
    local launch_path="$AR_CLIENT_DIR/launch" command
    local -a launch_command

    command="$(native_cli_command)"
    launch_command=(
        "$(client_runtime_command)"
        exec
        --client "$AR_CLI"
        --manifest "$AR_CLIENT_CONTEXT"
        --
        "$command"
        "${CLI_ARGS[@]}"
    )
    {
        printf '#!/bin/bash\nset -e\nexec'
        printf ' %q' "${launch_command[@]}"
        printf '\n'
    } > "$launch_path"
    chmod +x "$launch_path"
    printf '%s\n' "$launch_path"
}
