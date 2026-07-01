# Sourced by agentic-team. Component registries and adapter dispatch helpers.

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

register_component_adapter() {
    local kind="$1"
    local name="$2"
    local order="${3:-100}"
    REGISTERED_COMPONENTS+=("$kind:$order:$name")
}

registered_component_names() {
    local kind="$1"
    local entry entry_kind order name

    for entry in "${REGISTERED_COMPONENTS[@]}"; do
        [[ -n "$entry" ]] || continue
        IFS=: read -r entry_kind order name <<< "$entry"
        [[ "$entry_kind" == "$kind" ]] || continue
        printf '%s:%s\n' "$order" "$name"
    done | sort -t: -k1,1n | while IFS= read -r entry; do
        [[ -n "$entry" ]] || continue
        printf '%s\n' "${entry#*:}"
    done
}

registered_component_option_list() {
    join_values "|" $(registered_component_names "$1")
}

registered_component_display_list() {
    join_values ", " $(registered_component_names "$1")
}

is_registered_component() {
    local kind="$1"
    local needle="$2"
    local name

    for name in $(registered_component_names "$kind"); do
        [[ "$name" == "$needle" ]] && return 0
    done
    return 1
}

load_component_adapters() {
    local kind="$1"
    local adapter

    for adapter in "$SCRIPT_DIR"/scripts/lib/"$kind"/*.sh; do
        [[ -f "$adapter" ]] || continue
        source "$adapter"
    done
}

adapter_name() {
    printf '%s\n' "${1//-/_}"
}

adapter_function() {
    local prefix="$1"
    local name="$2"
    local method="$3"
    printf '%s_%s_%s\n' "$prefix" "$(adapter_name "$name")" "$method"
}

adapter_call() {
    local prefix="$1"
    local selected="$2"
    local method="$3"
    shift 3
    local fn

    fn="$(adapter_function "$prefix" "$selected" "$method")"
    if declare -F "$fn" >/dev/null 2>&1; then
        "$fn" "$@"
    fi
}

adapter_call_required() {
    local kind="$1"
    local prefix="$2"
    local selected="$3"
    local unsupported_label="$4"
    local supported_label="$5"
    local method="$6"
    shift 6
    local fn

    fn="$(adapter_function "$prefix" "$selected" "$method")"
    if ! is_registered_component "$kind" "$selected"; then
        echo "Error: Unsupported $unsupported_label: $selected"
        echo "Supported $supported_label: $(registered_component_display_list "$kind")"
        exit 1
    fi
    if ! declare -F "$fn" >/dev/null 2>&1; then
        echo "Error: Unsupported $unsupported_label: $selected"
        echo "Supported $supported_label: $(registered_component_display_list "$kind")"
        exit 1
    fi
    "$fn" "$@"
}

register_cli_adapter() {
    register_component_adapter cli "$1" "${2:-100}"
}

registered_cli_names() {
    registered_component_names cli
}

registered_cli_option_list() {
    registered_component_option_list cli
}

registered_cli_display_list() {
    registered_component_display_list cli
}

is_registered_cli() {
    is_registered_component cli "$1"
}

# CLI adapters own CLI-specific paths, rendering, hooks, arg translation, and
# auth/sandbox wiring. Keep new CLI support in scripts/lib/cli/<name>.sh.
load_cli_adapters() {
    load_component_adapters cli
}

cli_adapter_name() {
    adapter_name "$AR_CLI"
}

cli_adapter_function() {
    adapter_function cli "$AR_CLI" "$1"
}

cli_call() {
    local method="$1"
    shift
    adapter_call cli "$AR_CLI" "$method" "$@"
}

cli_call_for() {
    local cli_name="$1"
    local method="$2"
    shift 2
    adapter_call cli "$cli_name" "$method" "$@"
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
    adapter_call_required cli cli "$AR_CLI" "CLI" "CLIs" "$method" "$@"
}

register_sandbox_adapter() {
    register_component_adapter sandbox "$1" "${2:-100}"
}

registered_sandbox_names() {
    registered_component_names sandbox
}

registered_sandbox_option_list() {
    registered_component_option_list sandbox
}

registered_sandbox_display_list() {
    registered_component_display_list sandbox
}

is_registered_sandbox() {
    is_registered_component sandbox "$1"
}

# Sandbox adapters own container/native image checks, host validation, and
# launch mechanics. Keep new sandbox support in scripts/lib/sandbox/<name>.sh.
load_sandbox_adapters() {
    load_component_adapters sandbox
}

sandbox_adapter_name() {
    adapter_name "$AR_SANDBOX"
}

sandbox_adapter_function() {
    adapter_function sandbox "$AR_SANDBOX" "$1"
}

sandbox_call() {
    local method="$1"
    shift
    adapter_call sandbox "$AR_SANDBOX" "$method" "$@"
}

sandbox_call_required() {
    local method="$1"
    shift
    adapter_call_required sandbox sandbox "$AR_SANDBOX" "sandbox" "sandboxes" "$method" "$@"
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
