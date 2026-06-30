# Sourced by agentic-researcher. CLI/sandbox registries and adapter dispatch helpers.

join_values() {
    local sep="$1"
    shift
    local first=true value
    for value in "$@"; do
        if [[ "$first" == "true" ]]; then
            first=false
        else
            printf '%s' "$sep"
        fi
        printf '%s' "$value"
    done
}

register_cli_adapter() {
    local name="$1"
    local order="${2:-100}"
    REGISTERED_CLIS+=("$order:$name")
}

registered_cli_names() {
    local entry
    printf '%s\n' "${REGISTERED_CLIS[@]}" | sort -t: -k1,1n | while IFS= read -r entry; do
        [[ -n "$entry" ]] || continue
        printf '%s\n' "${entry#*:}"
    done
}

registered_cli_option_list() {
    join_values "|" $(registered_cli_names)
}

registered_cli_display_list() {
    join_values ", " $(registered_cli_names)
}

is_registered_cli() {
    local needle="$1"
    local name
    for name in $(registered_cli_names); do
        [[ "$name" == "$needle" ]] && return 0
    done
    return 1
}

# CLI adapters own tool-specific paths, rendering, hooks, arg translation, and
# auth/sandbox wiring. Keep new CLI support in scripts/lib/cli/<tool>.sh.
load_cli_adapters() {
    local adapter
    for adapter in "$SCRIPT_DIR"/scripts/lib/cli/*.sh; do
        [[ -f "$adapter" ]] || continue
        source "$adapter"
    done
}

cli_adapter_name() {
    printf '%s\n' "${AR_CLI_TOOL//-/_}"
}

cli_adapter_function() {
    local method="$1"
    printf 'cli_%s_%s\n' "$(cli_adapter_name)" "$method"
}

cli_call() {
    local method="$1"
    shift
    local fn
    fn="$(cli_adapter_function "$method")"
    if declare -F "$fn" >/dev/null 2>&1; then
        "$fn" "$@"
    fi
}

cli_call_for() {
    local cli_name="$1"
    local method="$2"
    shift 2
    local fn
    fn="cli_${cli_name//-/_}_${method}"
    if declare -F "$fn" >/dev/null 2>&1; then
        "$fn" "$@"
    fi
}

cli_call_all() {
    local method="$1"
    shift
    local cli_name
    for cli_name in $(registered_cli_names); do
        cli_call_for "$cli_name" "$method" "$@"
    done
}

cli_call_required() {
    local method="$1"
    shift
    local fn
    fn="$(cli_adapter_function "$method")"
    if ! is_registered_cli "$AR_CLI_TOOL"; then
        echo "Error: Unsupported CLI tool: $AR_CLI_TOOL"
        echo "Supported tools: $(registered_cli_display_list)"
        exit 1
    fi
    if ! declare -F "$fn" >/dev/null 2>&1; then
        echo "Error: Unsupported CLI tool: $AR_CLI_TOOL"
        echo "Supported tools: $(registered_cli_display_list)"
        exit 1
    fi
    "$fn" "$@"
}

register_sandbox_adapter() {
    local name="$1"
    local order="${2:-100}"
    REGISTERED_SANDBOXES+=("$order:$name")
}

registered_sandbox_names() {
    local entry
    printf '%s\n' "${REGISTERED_SANDBOXES[@]}" | sort -t: -k1,1n | while IFS= read -r entry; do
        [[ -n "$entry" ]] || continue
        printf '%s\n' "${entry#*:}"
    done
}

registered_sandbox_option_list() {
    join_values "|" $(registered_sandbox_names)
}

registered_sandbox_display_list() {
    join_values ", " $(registered_sandbox_names)
}

is_registered_sandbox() {
    local needle="$1"
    local name
    for name in $(registered_sandbox_names); do
        [[ "$name" == "$needle" ]] && return 0
    done
    return 1
}

# Sandbox adapters own container/native image checks, host validation, and
# launch mechanics. Keep new sandbox support in scripts/lib/sandbox/<name>.sh.
load_sandbox_adapters() {
    local adapter
    for adapter in "$SCRIPT_DIR"/scripts/lib/sandbox/*.sh; do
        [[ -f "$adapter" ]] || continue
        source "$adapter"
    done
}

sandbox_adapter_name() {
    printf '%s\n' "${AR_SANDBOX//-/_}"
}

sandbox_adapter_function() {
    local method="$1"
    printf 'sandbox_%s_%s\n' "$(sandbox_adapter_name)" "$method"
}

sandbox_call() {
    local method="$1"
    shift
    local fn
    fn="$(sandbox_adapter_function "$method")"
    if declare -F "$fn" >/dev/null 2>&1; then
        "$fn" "$@"
    fi
}

sandbox_call_required() {
    local method="$1"
    shift
    local fn
    fn="$(sandbox_adapter_function "$method")"
    if ! is_registered_sandbox "$AR_SANDBOX"; then
        echo "Error: Unsupported sandbox: $AR_SANDBOX"
        echo "Supported sandboxes: $(registered_sandbox_display_list)"
        exit 1
    fi
    if ! declare -F "$fn" >/dev/null 2>&1; then
        echo "Error: Unsupported sandbox: $AR_SANDBOX"
        echo "Supported sandboxes: $(registered_sandbox_display_list)"
        exit 1
    fi
    "$fn" "$@"
}

append_env_arg_from_host() {
    local env_name="$1"
    [[ -n "$env_name" && -n "${!env_name:-}" ]] || return 0
    ENV_ARGS+=(--env "${env_name}=${!env_name}")
}

append_env_arg_from_host_as() {
    local target_name="$1"
    local source_name="$2"
    [[ -n "$target_name" && -n "$source_name" && -n "${!source_name:-}" ]] || return 0
    if [[ -z "${!target_name:-}" ]]; then
        ENV_ARGS+=(--env "${target_name}=${!source_name}")
    fi
}

append_oci_env_from_host() {
    local env_name="$1"
    [[ -n "$env_name" && -n "${!env_name:-}" ]] || return 0
    OCI_ARGS+=(-e "${env_name}=${!env_name}")
}

append_oci_env_from_host_as() {
    local target_name="$1"
    local source_name="$2"
    [[ -n "$target_name" && -n "$source_name" && -n "${!source_name:-}" ]] || return 0
    if [[ -z "${!target_name:-}" ]]; then
        OCI_ARGS+=(-e "${target_name}=${!source_name}")
    fi
}

export_env_from_host_as() {
    local target_name="$1"
    local source_name="$2"
    [[ -n "$target_name" && -n "$source_name" && -n "${!source_name:-}" ]] || return 0
    if [[ -z "${!target_name:-}" ]]; then
        export "$target_name=${!source_name}"
    fi
}

