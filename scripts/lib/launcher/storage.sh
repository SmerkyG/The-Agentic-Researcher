# Sourced by agentic-team. Shared and sandbox-specific storage setup.

STORAGE_NAMES=()
STORAGE_HOST_DIRS=()
STORAGE_SANDBOX_DIRS=()

storage_dir_index() {
    local name="$1" index

    for ((index=0; index<${#STORAGE_NAMES[@]}; index++)); do
        if [[ "${STORAGE_NAMES[$index]}" == "$name" ]]; then
            printf '%s\n' "$index"
            return 0
        fi
    done
    return 1
}

register_storage_dir() {
    local name="$1" host_dir="$2" sandbox_dir="${3:-}" index

    if [[ ! "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        echo "Error: Invalid storage environment variable name: $name" >&2
        return 1
    fi
    if [[ -z "$host_dir" || "$host_dir" != /* ]]; then
        echo "Error: Storage directory for $name must be an absolute host path: $host_dir" >&2
        return 1
    fi

    if index="$(storage_dir_index "$name")"; then
        STORAGE_HOST_DIRS[$index]="$host_dir"
        if [[ -n "$sandbox_dir" ]]; then
            STORAGE_SANDBOX_DIRS[$index]="$sandbox_dir"
        fi
    else
        STORAGE_NAMES+=("$name")
        STORAGE_HOST_DIRS+=("$host_dir")
        STORAGE_SANDBOX_DIRS+=("${sandbox_dir:-/agent-storage/$name}")
        index=$((${#STORAGE_NAMES[@]} - 1))
    fi

    mkdir -p "$host_dir"
    printf -v "$name" '%s' "$host_dir"
    export "$name"
}

register_configured_storage_dirs() {
    local mapping name host_dir

    for mapping in "${AR_STORAGE_DIRS[@]}"; do
        if [[ "$mapping" != *=* ]]; then
            echo "Error: AR_STORAGE_DIRS entry must be ENV_NAME=/absolute/host/path: $mapping" >&2
            return 1
        fi
        name="${mapping%%=*}"
        host_dir="${mapping#*=}"
        register_storage_dir "$name" "$host_dir" || return 1
    done
}

append_storage_bind_args() {
    local array_name="$1" flag="$2" index
    local -n target_array="$array_name"

    for ((index=0; index<${#STORAGE_NAMES[@]}; index++)); do
        target_array+=("$flag" "${STORAGE_HOST_DIRS[$index]}:${STORAGE_SANDBOX_DIRS[$index]}")
    done
}

append_storage_env_args() {
    local array_name="$1" flag="$2" index
    local -n target_array="$array_name"

    for ((index=0; index<${#STORAGE_NAMES[@]}; index++)); do
        target_array+=("$flag" "${STORAGE_NAMES[$index]}=${STORAGE_SANDBOX_DIRS[$index]}")
    done
}

write_storage_array_assignments() {
    local array_name index

    for array_name in STORAGE_NAMES STORAGE_HOST_DIRS STORAGE_SANDBOX_DIRS; do
        local -n values="$array_name"
        printf '%s=(\n' "$array_name"
        for ((index=0; index<${#values[@]}; index++)); do
            printf '    %s\n' "$(shell_quote "${values[$index]}")"
        done
        printf ')\n'
    done
}

setup_storage() {
    STATE_ROOT="${AR_STATE_ROOT:-$HOME/.cache/agentic-team}"
    RUNTIME_ROOT="${AR_RUNTIME_ROOT:-${AR_WORKSPACE_ROOT:-}/.runtime}"
    AR_RUNTIME_ROOT="$RUNTIME_ROOT"
    export AR_RUNTIME_ROOT RUNTIME_ROOT

    if [[ -n "${AR_WORKSPACE_ROOT:-}" ]]; then
        mkdir -p "$AR_WORKSPACE_ROOT"
    fi
    if [[ -n "${RUNTIME_ROOT:-}" ]]; then
        mkdir -p "$RUNTIME_ROOT"
    fi
    if [[ -n "${AR_ARTIFACTS_DIR:-}" ]]; then
        mkdir -p "$AR_ARTIFACTS_DIR"
    fi

    STORAGE_NAMES=()
    STORAGE_HOST_DIRS=()
    STORAGE_SANDBOX_DIRS=()

    if [[ "$AR_SANDBOX" == "none" ]]; then
        mkdir -p "$STATE_ROOT"
        [[ -n "${UV_CACHE_DIR:-}" ]] && register_storage_dir UV_CACHE_DIR "$UV_CACHE_DIR" /uv-cache
        [[ -n "${UV_PYTHON_INSTALL_DIR:-}" ]] && register_storage_dir UV_PYTHON_INSTALL_DIR "$UV_PYTHON_INSTALL_DIR" /uv-python
        [[ -n "${UV_TOOL_DIR:-}" ]] && register_storage_dir UV_TOOL_DIR "$UV_TOOL_DIR" /uv-tools
        [[ -n "${HF_HOME:-}" ]] && register_storage_dir HF_HOME "$HF_HOME"
        [[ -n "${TRITON_CACHE_DIR:-}" ]] && register_storage_dir TRITON_CACHE_DIR "$TRITON_CACHE_DIR"
        [[ -n "${WANDB_DIR:-}" ]] && register_storage_dir WANDB_DIR "$WANDB_DIR"
        register_configured_storage_dirs
        return
    fi

    register_storage_dir UV_CACHE_DIR "${UV_CACHE_DIR:-$STATE_ROOT/uv/cache}" /uv-cache
    register_storage_dir UV_PYTHON_INSTALL_DIR "${UV_PYTHON_INSTALL_DIR:-$STATE_ROOT/uv/python}" /uv-python
    register_storage_dir UV_TOOL_DIR "${UV_TOOL_DIR:-$STATE_ROOT/uv/tools}" /uv-tools
    register_storage_dir HF_HOME "${HF_HOME:-$STATE_ROOT/hf_home}"
    register_storage_dir TRITON_CACHE_DIR "${TRITON_CACHE_DIR:-$STATE_ROOT/triton_cache}"
    register_storage_dir WANDB_DIR "${WANDB_DIR:-$STATE_ROOT/wandb}"
    register_configured_storage_dirs

    AR_CONFIG_STORE="$STATE_ROOT/agentic-team-config"
    mkdir -p "$AR_CONFIG_STORE"

    sandbox_call setup_storage

    cli_call_all setup_storage
}
