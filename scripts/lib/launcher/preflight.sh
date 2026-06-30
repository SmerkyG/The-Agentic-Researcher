# Sourced by agentic-researcher. Sandbox, container, and optional-skill preflight helpers.

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
        echo "  agentic-researcher --sandbox none ..."
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

append_selected_optional_skill() {
    local skill_name="$1"
    local existing

    [[ -n "$skill_name" && "$skill_name" != "none" ]] || return 0

    for existing in "${SELECTED_OPTIONAL_SKILLS[@]}"; do
        if [[ "$existing" == "$skill_name" ]]; then
            return 0
        fi
    done

    SELECTED_OPTIONAL_SKILLS+=("$skill_name")
}

optional_skill_selected() {
    local needle="$1"
    local existing

    for existing in "${SELECTED_OPTIONAL_SKILLS[@]}"; do
        [[ "$existing" == "$needle" ]] && return 0
    done
    return 1
}

append_optional_skills_from_list() {
    local skill_list="$1"
    local normalized skill_name

    normalized="${skill_list//,/ }"
    for skill_name in $normalized; do
        append_selected_optional_skill "$skill_name"
    done
}

resolve_optional_skills() {
    SELECTED_OPTIONAL_SKILLS=()
    JOB_BACKEND="none"
    append_optional_skills_from_list "${AR_OPTIONAL_SKILLS:-}"

    if optional_skill_selected "cluster-run"; then
        JOB_BACKEND="cluster-run"
    fi

    if optional_skill_selected "remote-run"; then
        if [[ "${JOB_BACKEND:-none}" != "none" ]]; then
            echo "Error: Select only one managed job backend optional skill."
            exit 1
        fi
        JOB_BACKEND="remote-run"
    fi
}

validate_optional_skills() {
    local skill_name skill_dir

    for skill_name in "${SELECTED_OPTIONAL_SKILLS[@]}"; do
        if [[ ! "$skill_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
            echo "Error: Invalid optional skill name: $skill_name"
            echo "Optional skill names may contain only letters, numbers, dots, underscores, and hyphens."
            exit 1
        fi
        skill_dir="$SCRIPT_DIR/optional-skills/$skill_name"
        if [[ ! -d "$skill_dir" ]]; then
            echo "Error: Optional skill not found: $skill_name"
            echo "Expected directory: $skill_dir"
            exit 1
        fi
        if [[ ! -f "$skill_dir/SKILL.md" && ! -f "$skill_dir/INSTRUCTIONS.md" ]]; then
            echo "Error: Optional skill $skill_name has neither SKILL.md nor INSTRUCTIONS.md"
            exit 1
        fi
    done
}

optional_skill_hook_path() {
    local skill_name="$1"
    local hook_name="$2"

    printf '%s\n' "$SCRIPT_DIR/optional-skills/$skill_name/launcher/$hook_name.sh"
}

run_optional_skill_hooks() {
    local hook_name="$1"
    local require_hook="${2:-false}"
    local skill_name hook_path ran_hook=false

    for skill_name in "${SELECTED_OPTIONAL_SKILLS[@]}"; do
        hook_path="$(optional_skill_hook_path "$skill_name" "$hook_name")"
        [[ -f "$hook_path" ]] || continue
        # Optional skill launcher hooks are trusted local scripts and are sourced
        # so they can add binds/env vars or retain cleanup state.
        source "$hook_path"
        ran_hook=true
    done

    if [[ "$ran_hook" == "true" || "$require_hook" != "true" ]]; then
        return 0
    fi
    return 1
}

