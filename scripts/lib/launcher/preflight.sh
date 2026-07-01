# Sourced by agentic-team. Sandbox, container, and capability preflight helpers.

validate_api_key() {
    cli_call validate_auth
}
validate_sandbox() {
    if ! is_registered_sandbox "$AR_SANDBOX"; then
        echo "Error: Unsupported sandbox: $AR_SANDBOX"
        echo "Supported sandboxes: $(registered_sandbox_display_list)"
        exit 1
    fi
}

container_image_exists() {
    sandbox_call_required image_exists
}

auto_build_enabled() {
    case "${AR_AUTO_BUILD:-true}" in
        0|false|False|FALSE|no|No|NO|off|Off|OFF)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

build_container_image() {
    sandbox_call_required build_image
}

ensure_container_image() {
    if [[ "$AR_SANDBOX" == "none" ]]; then
        return 0
    fi

    if container_image_exists; then
        return 0
    fi

    if ! auto_build_enabled; then
        echo "Error: Container image for $AR_SANDBOX was not found."
        echo ""
        echo "Build it with:"
        echo "  $SCRIPT_DIR/container/build.sh --runtime $AR_SANDBOX"
        echo ""
        echo "Or use none mode:"
        echo "  agentic-team --sandbox none ..."
        exit 1
    fi

    echo "Container image for $AR_SANDBOX was not found."
    echo "Building it now. This may take several minutes."
    echo ""
    build_container_image
}

validate_container() {
    sandbox_call_required validate
}

append_enabled_capability() {
    local capability_name="$1"
    local existing

    [[ -n "$capability_name" && "$capability_name" != "none" ]] || return 0

    for existing in "${SELECTED_CAPABILITIES[@]}"; do
        if [[ "$existing" == "$capability_name" ]]; then
            return 0
        fi
    done

    SELECTED_CAPABILITIES+=("$capability_name")
}

capability_selected() {
    local needle="$1"
    local existing

    for existing in "${SELECTED_CAPABILITIES[@]}"; do
        [[ "$existing" == "$needle" ]] && return 0
    done
    return 1
}

append_capabilities_from_list() {
    local capability_list="$1"
    local normalized capability_name

    normalized="${capability_list//,/ }"
    for capability_name in $normalized; do
        append_enabled_capability "$capability_name"
    done
}

append_main_agent_required_capabilities() {
    local capability_name

    [[ -n "${MAIN_AGENT_SOURCE_PATH:-}" ]] || return 0
    while IFS= read -r capability_name; do
        append_enabled_capability "$capability_name"
    done < <(frontmatter_list_values "$MAIN_AGENT_SOURCE_PATH" "required_capabilities")
}

selected_capabilities_csv() {
    local IFS=,
    printf '%s' "${SELECTED_CAPABILITIES[*]}"
}

resolve_capabilities() {
    SELECTED_CAPABILITIES=()
    JOB_BACKEND="none"
    append_capabilities_from_list "${AR_CAPABILITIES:-agentic-notes,experiment-log}"
    append_main_agent_required_capabilities
    AR_CAPABILITIES="$(selected_capabilities_csv)"
    AR_CAPABILITIES="${AR_CAPABILITIES:-none}"
    export AR_CAPABILITIES

    if capability_selected "cluster-run"; then
        JOB_BACKEND="cluster-run"
    fi

    if capability_selected "remote-run"; then
        if [[ "${JOB_BACKEND:-none}" != "none" ]]; then
            echo "Error: Select only one managed job backend capability."
            exit 1
        fi
        JOB_BACKEND="remote-run"
    fi
}

validate_capabilities() {
    local capability_name capability_dir

    for capability_name in "${SELECTED_CAPABILITIES[@]}"; do
        if [[ ! "$capability_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
            echo "Error: Invalid capability name: $capability_name"
            echo "Capability names may contain only letters, numbers, dots, underscores, and hyphens."
            exit 1
        fi
        if ! capability_dir="$(capability_root "$capability_name")"; then
            echo "Error: Capability not found: $capability_name"
            echo "Expected org or built-in directory named: capabilities/$capability_name"
            exit 1
        fi
        if [[ ! -d "$capability_dir/skills" && ! -f "$capability_dir/INSTRUCTIONS.md" && ! -d "$capability_dir/bin" && ! -d "$capability_dir/lib" && ! -d "$capability_dir/hooks" && ! -d "$capability_dir/launcher" ]]; then
            echo "Error: Capability $capability_name has no recognized content"
            exit 1
        fi
    done
}

capability_launcher_hook_path() {
    local capability_name="$1"
    local hook_name="$2"
    local root

    if ! root="$(capability_root "$capability_name")"; then
        return 1
    fi
    printf '%s\n' "$root/launcher/$hook_name.sh"
}

run_capability_launcher_hooks() {
    local hook_name="$1"
    local require_hook="${2:-false}"
    local capability_name hook_path ran_hook=false

    for capability_name in "${SELECTED_CAPABILITIES[@]}"; do
        hook_path="$(capability_launcher_hook_path "$capability_name" "$hook_name")"
        [[ -f "$hook_path" ]] || continue
        # Capability launcher hooks are trusted local scripts and are sourced
        # so they can add binds/env vars or retain cleanup state.
        source "$hook_path"
        ran_hook=true
    done

    if [[ "$ran_hook" == "true" || "$require_hook" != "true" ]]; then
        return 0
    fi
    return 1
}
