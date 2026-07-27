# Sourced by agentic-team. Formatting, profiling, environment, and path helpers.

toml_escape() {
    sed 's/\\/\\\\/g; s/"/\\"/g'
}

shell_quote() {
    printf "'"
    printf "%s" "$1" | sed "s/'/'\\\\''/g"
    printf "'"
}

env_truthy() {
    case "${1:-}" in
        1|true|True|TRUE|yes|Yes|YES|on|On|ON)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

profile_now_us() {
    local now sec frac
    if [[ -n "${EPOCHREALTIME:-}" ]]; then
        now="$EPOCHREALTIME"
        sec="${now%.*}"
        frac="${now#*.}000000"
        printf '%s\n' $((10#$sec * 1000000 + 10#${frac:0:6}))
        return
    fi
    printf '%s\n' "$(($(date +%s%N) / 1000))"
}

profile_step() {
    local label="$1"
    shift

    if ! env_truthy "${AR_PROFILE_STARTUP:-false}"; then
        "$@"
        return
    fi

    local start_us end_us elapsed_us
    start_us="$(profile_now_us)"
    "$@"
    end_us="$(profile_now_us)"
    elapsed_us=$((end_us - start_us))
    printf 'Agentic Team profile: %-34s %d.%03ds\n' \
        "$label" \
        $((elapsed_us / 1000000)) \
        $(((elapsed_us % 1000000) / 1000)) >&2
}

profile_elapsed() {
    local label="$1"
    local start_us="$2"

    if ! env_truthy "${AR_PROFILE_STARTUP:-false}"; then
        return 0
    fi

    local end_us elapsed_us
    end_us="$(profile_now_us)"
    elapsed_us=$((end_us - start_us))
    printf 'Agentic Team profile: %-34s %d.%03ds\n' \
        "$label" \
        $((elapsed_us / 1000000)) \
        $(((elapsed_us % 1000000) / 1000)) >&2
}

python_runtime_command_string() {
    printf '%s\n' "python3"
}

python_runtime_command_json_array() {
    printf '%s\n' '["python3"]'
}

json_string() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\b'/\\b}"
    value="${value//$'\f'/\\f}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    printf '"%s"' "$value"
}

workspace_runtime_path() {
    local relative_path="${1#./}"

    if [[ "$AR_SANDBOX" == "none" ]]; then
        printf '%s/%s\n' "$WORKSPACE_DIR" "$relative_path"
    else
        printf '/workspace/%s\n' "$relative_path"
    fi
}

workspace_root_runtime_path() {
    if [[ "$AR_SANDBOX" == "none" ]]; then
        printf '%s\n' "$WORKSPACE_DIR"
    else
        printf '%s\n' "/workspace"
    fi
}

ar_install_env_path() {
    if [[ "$AR_SANDBOX" == "none" ]]; then
        printf '%s\n' "$SCRIPT_DIR"
    else
        printf '%s\n' "$AR_INSTALL_CONTAINER_DIR"
    fi
}

ar_core_bin_env_path() {
    printf '%s/scripts/bin\n' "$(ar_install_env_path)"
}

ar_core_bin_host_path() {
    printf '%s/scripts/bin\n' "$SCRIPT_DIR"
}

ar_core_command_lib_env_path() {
    printf '%s/scripts/lib/commands\n' "$(ar_install_env_path)"
}

ar_core_command_lib_host_path() {
    printf '%s/scripts/lib/commands\n' "$SCRIPT_DIR"
}

ar_core_package_env_path() {
    printf '%s/scripts/package\n' "$(ar_install_env_path)"
}

ar_core_package_host_path() {
    printf '%s/scripts/package\n' "$SCRIPT_DIR"
}

join_path_entries() {
    local path_prefix="" entry
    while IFS= read -r entry; do
        [[ -n "$entry" ]] || continue
        if [[ -z "$path_prefix" ]]; then
            path_prefix="$entry"
        else
            path_prefix="$path_prefix:$entry"
        fi
    done
    printf '%s\n' "$path_prefix"
}

ar_runtime_path_prefix() {
    {
        capability_bin_runtime_paths
        ar_core_bin_env_path
    } | join_path_entries
}

ar_capability_path_prefix() {
    {
        capability_bin_host_paths
        ar_core_bin_host_path
    } | join_path_entries
}

path_env_pair() {
    local path_prefix="$1"

    if [[ -n "$path_prefix" ]]; then
        printf 'PATH=%s:%s\n' "$path_prefix" "${PATH:-}"
    fi
}

pythonpath_env_pair() {
    local pythonpath_prefix="$1"

    if [[ -n "$pythonpath_prefix" ]]; then
        printf 'PYTHONPATH=%s:%s\n' "$pythonpath_prefix" "${PYTHONPATH:-}"
    fi
}

ar_core_env_pairs() {
    local install_dir="$1"

    printf 'AR_SANDBOX=%s\n' "$AR_SANDBOX"
    printf 'AR_SANDBOX_HOME=%s\n' "$AR_SANDBOX_HOME"
    printf 'AR_INSTALL_DIR=%s\n' "$install_dir"
    printf 'AR_JOB_BACKEND=%s\n' "${JOB_BACKEND:-none}"
    printf 'AR_CLI=%s\n' "$AR_CLI"
    printf 'AR_STATE_ROOT=%s\n' "$STATE_ROOT"
    printf 'AR_WORKSPACE_ROOT=%s\n' "${AR_WORKSPACE_ROOT:-}"
    printf 'AR_RUNTIME_ROOT=%s\n' "${AR_RUNTIME_ROOT:-}"
    printf 'AR_ARTIFACTS_DIR=%s\n' "${AR_ARTIFACTS_DIR:-}"
}

ar_agent_context_env_pairs() {
    printf 'AR_PROJECT_DIR=%s\n' "$(workspace_root_runtime_path)"
    printf 'AR_MAIN_AGENT=%s\n' "$AR_MAIN_AGENT"
    printf 'AR_WORK_BRANCH=%s\n' "${AR_WORK_BRANCH:-}"
    printf 'AR_WORK_BRANCH_ID=%s\n' "${AR_WORK_BRANCH_ID:-}"
    printf 'AR_WORK_NAME=%s\n' "${AR_WORK_NAME:-}"
    printf 'AR_WORK_BRANCH_PREFIX=%s\n' "${AR_WORK_BRANCH_PREFIX:-}"
    printf 'AR_SESSION_ID=%s\n' "${AR_SESSION_ID:-}"
    printf 'AR_USER_ID=%s\n' "${AR_USER_ID:-$USER}"
    printf 'AR_PROJECT_STATE_DIR=%s\n' "${AR_PROJECT_STATE_DIR:-}"
    printf 'AR_WORK_STATE_DIR=%s\n' "${AR_WORK_STATE_DIR:-}"
    printf 'AR_CLIENT_ROOT=%s\n' "${AR_CLIENT_ROOT:-}"
    printf 'AR_CLIENT_DIR=%s\n' "${AR_CLIENT_DIR:-}"
    printf 'AR_CLIENT_CONTEXT=%s\n' "${AR_CLIENT_CONTEXT:-}"
    printf 'AR_CLIENT_CONTEXT_REGISTRY=%s\n' "${AR_CLIENT_CONTEXT_REGISTRY:-}"
}

ar_capability_config_env_pairs() {
    printf 'AR_ORG_NOTES_REPO=%s\n' "${AR_ORG_NOTES_REPO:-}"
    printf 'AR_CAPABILITIES=%s\n' "${AR_CAPABILITIES:-agentic-notes,experiment-log}"
    printf 'AR_PROJECT_STATE_BRANCH=%s\n' "${AR_PROJECT_STATE_BRANCH:-agentic/project-state}"
    printf 'AR_NOTES_AUTO_REFRESH=%s\n' "${AR_NOTES_AUTO_REFRESH:-true}"
    printf 'AR_NOTES_REFRESH_MODE=%s\n' "${AR_NOTES_REFRESH_MODE:-periodic}"
    printf 'AR_NOTES_REFRESH_INTERVAL_SECONDS=%s\n' "${AR_NOTES_REFRESH_INTERVAL_SECONDS:-120}"
    printf 'AR_GIT_NAME=%s\n' "${AR_GIT_NAME:-}"
    printf 'AR_GIT_EMAIL=%s\n' "${AR_GIT_EMAIL:-}"
    printf 'AR_RESOLVER_GIT_NAME=%s\n' "${AR_RESOLVER_GIT_NAME:-}"
    printf 'AR_RESOLVER_GIT_EMAIL=%s\n' "${AR_RESOLVER_GIT_EMAIL:-}"
    printf 'AR_NOTES_GIT_NAME=%s\n' "${AR_NOTES_GIT_NAME:-}"
    printf 'AR_NOTES_GIT_EMAIL=%s\n' "${AR_NOTES_GIT_EMAIL:-}"
}

ar_capability_execution_env_pairs() {
    printf 'TEST_MODE=%s\n' "$TEST_MODE"
    printf 'RENDER_ONLY=%s\n' "$RENDER_ONLY"
}

ar_agent_command_env_pairs() {
    local install_dir="$1"
    local path_prefix="$2"
    local command_lib_path core_package_path tool_path

    path_env_pair "$path_prefix"
    if [[ "$install_dir" == "$SCRIPT_DIR" ]]; then
        command_lib_path="$(ar_core_command_lib_host_path)"
        core_package_path="$(ar_core_package_host_path)"
        tool_path="$(capability_package_host_path)"
    else
        command_lib_path="$(ar_core_command_lib_env_path)"
        core_package_path="$(ar_core_package_env_path)"
        tool_path="$(capability_package_runtime_path)"
    fi
    pythonpath_env_pair "$core_package_path:$command_lib_path${tool_path:+:$tool_path}"
    printf 'AR_TOOL_PATH=%s\n' "$tool_path"
    printf 'AR_WORKFLOW_PATH=%s\n' "$tool_path"
    ar_core_env_pairs "$install_dir"
    ar_agent_context_env_pairs
    ar_capability_config_env_pairs
}

ar_runtime_env_pairs() {
    ar_agent_command_env_pairs \
        "$(ar_install_env_path)" \
        "$(ar_runtime_path_prefix)"
}

ar_capability_env_pairs() {
    ar_agent_command_env_pairs \
        "$SCRIPT_DIR" \
        "$(ar_capability_path_prefix)"
    ar_capability_execution_env_pairs
}

export_env_pairs() {
    local pair
    while IFS= read -r pair; do
        [[ -n "$pair" ]] && export "$pair"
    done
}

export_ar_runtime_env() {
    export_env_pairs < <(ar_runtime_env_pairs)
}

export_ar_capability_env() {
    export_env_pairs < <(ar_capability_env_pairs)
}

append_ar_runtime_env_args() {
    local array_name="$1"
    local flag="$2"
    local -n target_array="$array_name"
    local pair

    while IFS= read -r pair; do
        [[ -n "$pair" ]] && target_array+=("$flag" "$pair")
    done < <(ar_runtime_env_pairs)
}

write_ar_runtime_env_array_assignment() {
    local array_name="$1"
    local pair

    printf '%s=(\n' "$array_name"
    while IFS= read -r pair; do
        printf '    %s\n' "$(shell_quote "$pair")"
    done < <(ar_runtime_env_pairs)
    printf ')\n'
}
