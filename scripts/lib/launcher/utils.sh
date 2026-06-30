# Sourced by agentic-researcher. Formatting, profiling, Python resolution, and path helpers.

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
    printf 'AR profile: %-34s %d.%03ds\n' \
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
    printf 'AR profile: %-34s %d.%03ds\n' \
        "$label" \
        $((elapsed_us / 1000000)) \
        $(((elapsed_us % 1000000) / 1000)) >&2
}

AR_PYTHON_CMD=()

resolve_python_cmd() {
    if [[ ${#AR_PYTHON_CMD[@]} -gt 0 ]]; then
        return 0
    fi

    local configured="${AR_PYTHON:-}"
    if [[ -n "$configured" ]]; then
        # AR_PYTHON may be a command plus fixed args, e.g. "uv run --no-project python".
        read -r -a AR_PYTHON_CMD <<< "$configured"
        if "${AR_PYTHON_CMD[@]}" -c 'import json, pathlib, sys' >/dev/null 2>&1; then
            return 0
        fi
        AR_PYTHON_CMD=()
    fi

    local candidate candidate_path
    for candidate in python3 python; do
        candidate_path="$(command -v "$candidate" 2>/dev/null || true)"
        if [[ -n "$candidate_path" ]] && \
            "$candidate_path" -c 'import json, pathlib, sys' >/dev/null 2>&1; then
            AR_PYTHON_CMD=("$candidate_path")
            return 0
        fi
    done

    if command -v uv >/dev/null 2>&1; then
        local uv_cmd
        uv_cmd="$(command -v uv)"
        local uv_python
        uv_python="$("$uv_cmd" python find 3.12 2>/dev/null || "$uv_cmd" python find 2>/dev/null || true)"
        if [[ -n "$uv_python" ]] && "$uv_python" -c 'import json, pathlib, sys' >/dev/null 2>&1; then
            AR_PYTHON_CMD=("$uv_python")
            return 0
        fi
        if "$uv_cmd" run --no-project python -c 'import json, pathlib, sys' >/dev/null 2>&1; then
            AR_PYTHON_CMD=("$uv_cmd" run --no-project python)
            return 0
        fi
    fi

    echo "Error: Could not find a usable Python interpreter. Set AR_PYTHON to a runnable Python command." >&2
    return 1
}

python_command_string() {
    resolve_python_cmd || return 1
    local part first=true
    for part in "${AR_PYTHON_CMD[@]}"; do
        if [[ "$first" == "true" ]]; then
            first=false
        else
            printf ' '
        fi
        shell_quote "$part"
    done
}

python_command_json_array() {
    resolve_python_cmd || return 1
    local part first=true
    printf '['
    for part in "${AR_PYTHON_CMD[@]}"; do
        if [[ "$first" == "true" ]]; then
            first=false
        else
            printf ', '
        fi
        json_string "$part"
    done
    printf ']'
}

python_runtime_command_string() {
    if [[ "$AR_SANDBOX" == "none" ]]; then
        python_command_string
    else
        printf '%s\n' "python3"
    fi
}

python_runtime_command_json_array() {
    if [[ "$AR_SANDBOX" == "none" ]]; then
        python_command_json_array
    else
        printf '%s\n' '["python3"]'
    fi
}

json_string() {
    resolve_python_cmd || return 1
    "${AR_PYTHON_CMD[@]}" -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
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

ar_notes_cli_env_path() {
    printf '%s/scripts/tools/ar-notes\n' "$(ar_install_env_path)"
}

ar_tool_cli_env_path() {
    printf '%s/scripts/ar-tool\n' "$(ar_install_env_path)"
}

provider_refresh_cli_env_path() {
    printf '%s/scripts/provider-refresh\n' "$(ar_install_env_path)"
}

ar_notes_cli_host_path() {
    printf '%s/scripts/tools/ar-notes\n' "$SCRIPT_DIR"
}

ar_tool_cli_host_path() {
    printf '%s/scripts/ar-tool\n' "$SCRIPT_DIR"
}

