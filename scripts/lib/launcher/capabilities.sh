# Sourced by agentic-team. Capability package orchestration.

enabled_capability_names() {
    local raw="${AR_CAPABILITIES:-agentic-notes,experiment-log}"
    local capability

    raw="${raw//,/ }"
    for capability in $raw; do
        [[ -n "$capability" ]] || continue
        [[ "$capability" == "none" ]] && continue
        if [[ "$capability" =~ ^[A-Za-z0-9._-]+$ ]]; then
            printf '%s\n' "$capability"
        else
            echo "Warning: Ignoring invalid capability name: $capability" >&2
        fi
    done
}

capability_enabled() {
    local needle="$1"
    local capability

    for capability in $(enabled_capability_names); do
        [[ "$capability" == "$needle" ]] && return 0
    done
    return 1
}

capability_root() {
    local capability_name="$1"
    local root

    for root in \
        "$WORKSPACE_DIR/.agentic-team/capabilities/$capability_name" \
        "$STATE_ROOT/repos/org-agentic-notes/capabilities/$capability_name" \
        "$SCRIPT_DIR/capabilities/$capability_name"
    do
        [[ -d "$root" ]] || continue
        printf '%s\n' "$root"
        return 0
    done

    return 1
}

available_capability_names() {
    local capabilities_dir capability_dir

    for capabilities_dir in \
        "$WORKSPACE_DIR/.agentic-team/capabilities" \
        "$STATE_ROOT/repos/org-agentic-notes/capabilities" \
        "$SCRIPT_DIR/capabilities"
    do
        [[ -d "$capabilities_dir" ]] || continue
        for capability_dir in "$capabilities_dir"/*; do
            [[ -d "$capability_dir" ]] || continue
            basename "$capability_dir"
        done
    done | sort -u
}

capability_required_names() {
    local capability_dir="$1"
    local manifest="$capability_dir/capability.toml"

    [[ -f "$manifest" ]] || return 0
    awk '
        /^[[:space:]]*requires[[:space:]]*=/ {
            value=$0
            sub(/^[^=]*=/, "", value)
            gsub(/[\[\],]/, " ", value)
            gsub(/["\047]/, "", value)
            count=split(value, names, /[[:space:]]+/)
            for (i=1; i<=count; i++) {
                if (names[i] != "") print names[i]
            }
        }
    ' "$manifest"
}

capability_name_for_source() {
    local source_path="$1"
    local capability_name root

    for capability_name in $(available_capability_names); do
        root="$(capability_root "$capability_name")" || continue
        case "$source_path" in
            "$root"/agents/*|"$root"/skills/*)
                printf '%s\n' "$capability_name"
                return 0
                ;;
        esac
    done
    return 1
}

capability_hook_path() {
    local capability_name="$1"
    local hook_name="$2"
    local root

    if ! root="$(capability_root "$capability_name")"; then
        return 1
    fi
    if [[ -x "$root/hooks/$hook_name" ]]; then
        printf '%s\n' "$root/hooks/$hook_name"
        return 0
    fi
    return 1
}

capability_bin_host_paths() {
    local capability_name root bin_dir

    for capability_name in $(enabled_capability_names); do
        if root="$(capability_root "$capability_name")"; then
            bin_dir="$root/bin"
            [[ -d "$bin_dir" ]] && printf '%s\n' "$bin_dir"
        fi
    done
}

capability_runtime_root() {
    local capability_name="$1"
    local host_root="$2"

    if [[ "$host_root" == "$SCRIPT_DIR/capabilities/$capability_name" ]]; then
        printf '%s/capabilities/%s\n' "$(ar_install_env_path)" "$capability_name"
    elif [[ "$host_root" == "$WORKSPACE_DIR/.agentic-team/capabilities/$capability_name" ]]; then
        workspace_runtime_path ".agentic-team/capabilities/$capability_name"
    else
        printf '%s\n' "$host_root"
    fi
}

capability_bin_runtime_paths() {
    local capability_name root runtime_root bin_dir

    for capability_name in $(enabled_capability_names); do
        if root="$(capability_root "$capability_name")"; then
            runtime_root="$(capability_runtime_root "$capability_name" "$root")"
            bin_dir="$runtime_root/bin"
            [[ -d "$root/bin" ]] && printf '%s\n' "$bin_dir"
        fi
    done
}

capability_package_host_paths() {
    local capability_name root

    for capability_name in $(enabled_capability_names); do
        root="$(capability_root "$capability_name")" || continue
        [[ -d "$root/package" ]] && printf '%s\n' "$root/package"
    done
}

capability_package_runtime_paths() {
    local capability_name root runtime_root

    for capability_name in $(enabled_capability_names); do
        root="$(capability_root "$capability_name")" || continue
        [[ -d "$root/package" ]] || continue
        runtime_root="$(capability_runtime_root "$capability_name" "$root")"
        printf '%s/package\n' "$runtime_root"
    done
}

join_colon_paths() {
    local path joined=""

    while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        joined="${joined:+$joined:}$path"
    done
    printf '%s\n' "$joined"
}

capability_workflow_host_path() {
    capability_package_host_paths | join_colon_paths
}

capability_workflow_runtime_path() {
    capability_package_runtime_paths | join_colon_paths
}

capability_hook_call() {
    local capability_name="$1"
    local hook_name="$2"
    shift
    shift
    local hook_exe

    if ! hook_exe="$(capability_hook_path "$capability_name" "$hook_name")"; then
        return 0
    fi
    AT_PROJECT_DIR="${CAPABILITY_HOOK_PROJECT_DIR:-$WORKSPACE_DIR}" \
    AT_BRANCH="${CAPABILITY_HOOK_BRANCH:-${WORKSPACE_GIT_BRANCH:-}}" \
    AT_SESSION_ID="${CAPABILITY_HOOK_SESSION_ID:-${AR_SESSION_ID:-}}" \
    AT_AGENT_TYPE="${CAPABILITY_HOOK_AGENT_TYPE:-${AR_MAIN_AGENT:-research-coordinator}}" \
    AT_WORK_BRANCH="${CAPABILITY_HOOK_WORK_BRANCH:-${AR_WORK_BRANCH:-}}" \
    AT_CLI="${CAPABILITY_HOOK_CLI:-$AR_CLI}" \
    AT_OUTPUT_DIR="${CAPABILITY_HOOK_OUTPUT_DIR:-}" \
    AT_HEARTBEAT_DIR="${CAPABILITY_HOOK_HEARTBEAT_DIR:-}" \
    AT_REFRESH_INTERVAL_SECONDS="${CAPABILITY_HOOK_INTERVAL_SECONDS:-}" \
    AT_STALE_SECONDS="${CAPABILITY_HOOK_STALE_SECONDS:-}" \
        "$hook_exe" "$@"
}

project_agent_root_for_cli() {
    cli_call_required project_agent_root
}

capability_render_command() {
    export_capability_env

    "$SCRIPT_DIR/scripts/lib/launcher/capability_render.py" \
        --project-dir "$WORKSPACE_DIR" \
        --agent-type "${AR_MAIN_AGENT:-research-coordinator}" \
        --work-branch "${AR_WORK_BRANCH:-}" \
        --cli "$AR_CLI" \
        "$@"
}

CAPABILITY_RENDER_DIR=""
CAPABILITY_RENDER_INSTRUCTION_PATH=""
CAPABILITY_RENDER_SOURCE_PATHS=()
CAPABILITY_RENDER_SOURCE_OUTPUTS=()
CAPABILITY_SECTION_DIR=""

cached_capability_source_path() {
    local source_path="$1"
    local index

    for ((index=0; index<${#CAPABILITY_RENDER_SOURCE_PATHS[@]}; index++)); do
        if [[ "${CAPABILITY_RENDER_SOURCE_PATHS[$index]}" == "$source_path" ]]; then
            printf '%s\n' "${CAPABILITY_RENDER_SOURCE_OUTPUTS[$index]}"
            return 0
        fi
    done
    return 1
}

render_source_with_capability() {
    local renderer="$1"
    local source_path="$2"
    local rendered_path

    if rendered_path="$(cached_capability_source_path "$source_path")"; then
        cat "$rendered_path"
        return 0
    fi
    echo "Error: Capability render bundle omitted $renderer source: $source_path" >&2
    return 1
}

prepare_capability_render_bundle() {
    local temp_root capability_name capability_dir source_path renderer source_kind
    local output_relative output_path agent_name index=0
    local -a render_args

    temp_root="$RUNTIME_ROOT/tmp"
    mkdir -p "$temp_root"
    CAPABILITY_RENDER_DIR="$(mktemp -d "$temp_root/capability-render.XXXXXX")" || return 1
    CAPABILITY_RENDER_INSTRUCTION_PATH="$CAPABILITY_RENDER_DIR/instructions.md"
    CAPABILITY_RENDER_SOURCE_PATHS=()
    CAPABILITY_RENDER_SOURCE_OUTPUTS=()
    CAPABILITY_SECTION_DIR="$CAPABILITY_RENDER_DIR/agent-sections"

    render_args=(bundle --output-dir "$CAPABILITY_RENDER_DIR")
    for capability_name in $(enabled_capability_names); do
        capability_dir="$(capability_root "$capability_name")" || continue
        for source_path in "$capability_dir"/agents/*.md "$capability_dir"/skills/*/SKILL.md; do
            [[ -f "$source_path" ]] || continue
            renderer="$(frontmatter_value "$source_path" "renderer")"
            [[ -n "$renderer" ]] || continue
            source_kind="agent"
            [[ "$(basename "$source_path")" == "SKILL.md" ]] && source_kind="skill"
            output_relative="sources/$index.md"
            output_path="$CAPABILITY_RENDER_DIR/$output_relative"
            CAPABILITY_RENDER_SOURCE_PATHS+=("$source_path")
            CAPABILITY_RENDER_SOURCE_OUTPUTS+=("$output_path")
            render_args+=(--source "$renderer" "$source_kind" "$source_path" "$output_relative")
            index=$((index + 1))
        done
    done

    ACTIVE_PROJECT_AGENT_NAMES=()
    for capability_name in $(enabled_capability_names); do
        capability_dir="$(capability_root "$capability_name")" || continue
        collect_active_project_agent_names "$capability_dir/agents"
    done
    if capability_enabled agentic-notes; then
        for agent_name in "${ACTIVE_PROJECT_AGENT_NAMES[@]}"; do
            render_args+=(
                --agent-section agentic-notes "$agent_name" "agent-sections/$agent_name.md"
            )
        done
    fi

    if ! capability_render_command "${render_args[@]}"; then
        cleanup_capability_render_bundle
        return 1
    fi
}

cleanup_capability_render_bundle() {
    if [[ -n "$CAPABILITY_RENDER_DIR" ]]; then
        rm -rf "$CAPABILITY_RENDER_DIR"
    fi
    CAPABILITY_RENDER_DIR=""
    CAPABILITY_RENDER_INSTRUCTION_PATH=""
    CAPABILITY_RENDER_SOURCE_PATHS=()
    CAPABILITY_RENDER_SOURCE_OUTPUTS=()
    CAPABILITY_SECTION_DIR=""
}

render_agentic_notes_for_agent_type() {
    local render_agent_type="$1"
    local rendered_path

    capability_enabled agentic-notes || return 0

    if [[ -n "$CAPABILITY_SECTION_DIR" ]]; then
        rendered_path="$CAPABILITY_SECTION_DIR/$render_agent_type.md"
        if [[ -f "$rendered_path" ]]; then
            cat "$rendered_path"
        fi
    fi
}

valid_agent_name() {
    [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

render_markdown_agent_file() {
    local source_path="$1"
    local target_path="$2"
    local agent_name="$3"
    local temp_path="${target_path}.tmp"
    local body_path="${target_path}.body.tmp"

    if ! render_expanded_agent_body "$source_path" > "$body_path"; then
        rm -f "$body_path"
        return 1
    fi

    awk -v agent_name="$agent_name" '
        BEGIN { inserted=0; in_frontmatter=0 }
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && $0 ~ /^[[:space:]]*(kind|codex_reasoning_effort|model_reasoning_effort|renderer|workflow_interface|workflow_module|workflow_entry|workflow_receiver):[[:space:]]*/ { next }
        in_frontmatter && $0 == "---" {
            print
            print ""
            print "<!-- Generated by agentic-team. Edit the source agent definition to change this agent. -->"
            inserted=1
            exit
        }
        END {
            if (inserted == 0) {
                print "<!-- Generated by agentic-team. Edit the source agent definition to change this agent. -->"
            }
        }
    ' "$source_path" > "$temp_path"
    cat "$body_path" >> "$temp_path"
    {
        printf '\n'
        render_agentic_notes_for_agent_type "$agent_name"
    } >> "$temp_path"

    rm -f "$body_path"
    mv "$temp_path" "$target_path"
}

render_agent_for_cli() {
    cli_call_required render_agent "$@"
}

ACTIVE_PROJECT_AGENT_NAMES=()

add_active_project_agent_name() {
    local agent_name="$1"
    ACTIVE_PROJECT_AGENT_NAMES+=("$agent_name")
}

collect_active_project_agent_names() {
    local source_dir="$1"
    local source_path agent_name kind

    [[ -d "$source_dir" ]] || return 0
    for source_path in "$source_dir"/*.md; do
        [[ -f "$source_path" ]] || continue
        agent_name="$(agent_name_for_source "$source_path")"
        [[ -n "$agent_name" ]] || continue
        valid_agent_name "$agent_name" || continue
        kind="$(agent_kind_for_source "$source_path")"
        [[ "$kind" == "subagent" ]] || continue
        add_active_project_agent_name "$agent_name"
    done
}

is_active_project_agent_name() {
    local needle="$1"
    local agent_name

    for agent_name in "${ACTIVE_PROJECT_AGENT_NAMES[@]}"; do
        [[ "$agent_name" == "$needle" ]] && return 0
    done
    return 1
}

cleanup_inactive_managed_agents() {
    local agent_root="$1"
    local managed_marker="$2"
    local target_path target_file agent_name

    [[ -d "$agent_root" ]] || return 0
    for target_path in "$agent_root"/*; do
        [[ -f "$target_path" ]] || continue
        grep -q "$managed_marker" "$target_path" || continue
        target_file="$(basename "$target_path")"
        case "$target_file" in
            *.toml)
                agent_name="${target_file%.toml}"
                ;;
            *.md)
                agent_name="${target_file%.md}"
                ;;
            *)
                continue
                ;;
        esac
        if ! is_active_project_agent_name "$agent_name"; then
            rm -f "$target_path"
        fi
    done
}

render_agent_source_dir() {
    local agent_root="$1"
    local source_dir="$2"
    local source_label="$3"
    local kind_filter="$4"
    local managed_marker="Generated by agentic-team"
    local source_path agent_name kind description codex_reasoning_effort target_path

    [[ -d "$source_dir" ]] || return 0

    for source_path in "$source_dir"/*.md; do
        [[ -f "$source_path" ]] || continue
        agent_name="$(agent_name_for_source "$source_path")"
        kind="$(agent_kind_for_source "$source_path")"
        if [[ "$kind" != "$kind_filter" ]]; then
            continue
        fi
        description="$(frontmatter_value "$source_path" "description")"
        codex_reasoning_effort="$(frontmatter_value "$source_path" "codex_reasoning_effort")"
        if [[ -z "$codex_reasoning_effort" ]]; then
            codex_reasoning_effort="$(frontmatter_value "$source_path" "model_reasoning_effort")"
        fi
        [[ -n "$description" ]] || description="$agent_name agent."

        if ! valid_agent_name "$agent_name"; then
            echo "Warning: Skipping $source_label agent with invalid name: $agent_name"
            continue
        fi

        target_path="$(cli_call_required agent_target_path "$agent_root" "$agent_name")"
        [[ -n "$target_path" ]] || continue

        if [[ -f "$target_path" ]] && ! grep -q "$managed_marker" "$target_path"; then
            echo "Warning: Skipping $source_label agent at $target_path (not managed by agentic-team)"
            continue
        fi

        render_agent_for_cli "$source_path" "$target_path" "$agent_name" "$description" "$codex_reasoning_effort"
    done
}

setup_project_agents() {
    local agent_root capability_name capability_dir
    local render_status=0
    agent_root="$(project_agent_root_for_cli)"
    [[ -n "$agent_root" ]] || return 0

    mkdir -p "$agent_root"

    ACTIVE_PROJECT_AGENT_NAMES=()
    for capability_name in $(enabled_capability_names); do
        capability_dir="$(capability_root "$capability_name")" || continue
        collect_active_project_agent_names "$capability_dir/agents"
    done
    cleanup_inactive_managed_agents "$agent_root" "Generated by agentic-team"
    for capability_name in $(enabled_capability_names); do
        capability_dir="$(capability_root "$capability_name")" || continue
        if ! render_agent_source_dir "$agent_root" "$capability_dir/agents" "$capability_name" "subagent"; then
            render_status=1
        fi
    done

    return "$render_status"
}

render_skill_instruction_file() {
    local instruction_source="$1"

    [[ -f "$instruction_source" ]] || return 0

    cat "$instruction_source"
}

render_skill_instruction_parts() {
    local source_path skill_name capability_dir

    for skill_name in $(enabled_capability_names); do
        capability_dir="$(capability_root "$skill_name")" || continue
        source_path="$capability_dir/INSTRUCTIONS.md"
        render_skill_instruction_file "$source_path"
        printf '\n'
    done
}

export_capability_env() {
    if [[ -n "${AR_WORK_BRANCH_ID:-}" ]]; then
        AR_SESSION_ID="${AR_SESSION_ID:-$AR_WORK_BRANCH_ID-$$-$(date +%s)}"
    fi

    export_ar_capability_env
}

setup_agentic_notes_capability_once() {
    capability_enabled agentic-notes || return 0
    [[ "$AGENTIC_NOTES_CAPABILITY_SETUP" == "true" ]] && return 0

    export_capability_env
    if ! capability_hook_call agentic-notes setup; then
        echo "Error: Capability 'agentic-notes' setup failed."
        exit 1
    fi
    AGENTIC_NOTES_CAPABILITY_SETUP=true
}

setup_capabilities() {
    local capability_name

    export_capability_env

    for capability_name in $(enabled_capability_names); do
        if [[ "$capability_name" == "agentic-notes" && "$AGENTIC_NOTES_CAPABILITY_SETUP" == "true" ]]; then
            continue
        fi
        if ! capability_hook_call "$capability_name" setup; then
            echo "Error: Capability '$capability_name' setup failed."
            exit 1
        fi
    done
}

refresh_capabilities() {
    local capability_name

    export_capability_env

    for capability_name in $(enabled_capability_names); do
        if ! capability_hook_call "$capability_name" post-compaction; then
            echo "Error: Capability '$capability_name' refresh failed."
            exit 1
        fi
    done
}

cleanup_capabilities() {
    local capability_name

    export_ar_capability_env

    for capability_name in $(enabled_capability_names); do
        capability_hook_call "$capability_name" cleanup >/dev/null || true
    done
}

launcher_cleanup() {
    local status=$?
    trap - EXIT
    cleanup_capability_render_bundle || true
    if [[ "$CAPABILITY_CLEANUP_ENABLED" == "true" ]]; then
        run_capability_launcher_hooks cleanup || true
    fi
    cleanup_capabilities || true
    cleanup_branch_guard || true
    return "$status"
}

setup_capability_refresh_loops() {
    [[ "$TEST_MODE" == "true" ]] && return 0
    [[ "$RENDER_ONLY" == "true" ]] && return 0

    case "${AR_NOTES_AUTO_REFRESH:-true}" in
        0|false|False|FALSE|no|No|NO|off|Off|OFF)
            return 0
            ;;
    esac

    case "${AR_NOTES_REFRESH_MODE:-periodic}" in
        periodic|background)
            ;;
        *)
            return 0
            ;;
    esac

    local interval heartbeat_period heartbeat_dir heartbeat_file refresh_log launcher_pid stale_seconds
    interval="${AR_NOTES_REFRESH_INTERVAL_SECONDS:-120}"
    if ! [[ "$interval" =~ ^[0-9]+$ ]] || [[ "$interval" -lt 1 ]]; then
        interval=120
    fi
    heartbeat_period=$((interval / 4))
    if [[ "$heartbeat_period" -lt 1 ]]; then
        heartbeat_period=1
    elif [[ "$heartbeat_period" -gt 30 ]]; then
        heartbeat_period=30
    fi
    stale_seconds=$((interval * 2))
    if [[ "$stale_seconds" -lt $((heartbeat_period * 3)) ]]; then
        stale_seconds=$((heartbeat_period * 3))
    fi

    heartbeat_dir="$RUNTIME_ROOT/refresh-heartbeats"
    heartbeat_file="$heartbeat_dir/$$.heartbeat"
    refresh_log="$RUNTIME_ROOT/logs/agentic-notes-refresh.log"
    launcher_pid="$$"
    mkdir -p "$heartbeat_dir" "$(dirname "$refresh_log")"
    touch "$heartbeat_file"

    (
        while kill -0 "$launcher_pid" 2>/dev/null; do
            touch "$heartbeat_file"
            sleep "$heartbeat_period"
        done
        rm -f "$heartbeat_file"
    ) >/dev/null 2>&1 &

    local capability_name
    for capability_name in $(enabled_capability_names); do
        CAPABILITY_HOOK_HEARTBEAT_DIR="$heartbeat_dir" \
        CAPABILITY_HOOK_INTERVAL_SECONDS="$interval" \
        CAPABILITY_HOOK_STALE_SECONDS="$stale_seconds" \
            capability_hook_call "$capability_name" refresh-loop >>"$refresh_log" 2>&1 &
    done
}

render_capability_instruction_parts() {
    export_ar_capability_env

    if [[ -z "$CAPABILITY_RENDER_INSTRUCTION_PATH" || ! -f "$CAPABILITY_RENDER_INSTRUCTION_PATH" ]]; then
        echo "Error: Capability render bundle did not produce instructions.md" >&2
        return 1
    fi
    cat "$CAPABILITY_RENDER_INSTRUCTION_PATH"
}
