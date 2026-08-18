# Sourced by agentic-team. Instruction, module, skill, and managed agent rendering.
render_instruction_module_block() {
    local capability_name="$1"
    local module_name="$2"
    local capability_dir module_path

    if ! capability_dir="$(capability_root "$capability_name")"; then
        echo "Warning: Instruction module capability not found: $capability_name" >&2
        return 0
    fi

    module_path="$capability_dir/instruction-modules/$module_name.md"
    if [[ ! -f "$module_path" ]]; then
        echo "Warning: Instruction module not found: $capability_name/$module_name" >&2
        return 0
    fi

    cat "$module_path"
    printf '\n'
}

render_agent_source_body() {
    local source_path="$1"
    local renderer source_kind

    renderer="$(frontmatter_value "$source_path" "renderer")"
    if [[ -n "$renderer" ]]; then
        if ! capability_enabled "$renderer"; then
            echo "Error: Source renderer capability is not enabled: $renderer" >&2
            return 1
        fi
        source_kind="agent"
        [[ "$(basename "$source_path")" == "SKILL.md" ]] && source_kind="skill"
        render_source_with_capability "$renderer" "$source_path" "$source_kind"
    else
        strip_frontmatter "$source_path"
    fi
}

render_expanded_agent_body() {
    local source_path="$1"
    local temp_root="${RUNTIME_ROOT:-${TMPDIR:-/tmp}}"
    local body_path

    mkdir -p "$temp_root"
    body_path="$(mktemp "$temp_root/workflow-body.XXXXXX")"
    if ! render_agent_source_body "$source_path" > "$body_path"; then
        rm -f "$body_path"
        return 1
    fi
    expand_instruction_modules_from_stdin < "$body_path"
    rm -f "$body_path"
}

expand_instruction_modules_from_stdin() {
    local line capability_name module_name
    local module_regex='^<!--[[:space:]]*AT_INSTRUCTION_MODULE:[[:space:]]*([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)[[:space:]]*-->$'

    while IFS= read -r line; do
        if [[ "$line" =~ $module_regex ]]; then
            capability_name="${BASH_REMATCH[1]}"
            module_name="${BASH_REMATCH[2]}"
            render_instruction_module_block "$capability_name" "$module_name"
        else
            printf '%s\n' "$line"
        fi
    done
}

render_instruction_template_part() {
    if [[ "$AR_SANDBOX" == "docker" || "$AR_SANDBOX" == "podman" ]]; then
        awk '
            /<!-- DOCKER-OMIT-START -->/ { skip=1; next }
            /<!-- DOCKER-OMIT-END -->/   { skip=0; next }
            !skip { print }
        ' "$SCRIPT_DIR/INSTRUCTIONS.md" | expand_instruction_modules_from_stdin
    else
        expand_instruction_modules_from_stdin < "$SCRIPT_DIR/INSTRUCTIONS.md"
    fi
}

agent_name_for_source() {
    local source_path="$1"
    local file_stem agent_name

    file_stem="$(basename "$source_path" .md)"
    agent_name="$(frontmatter_value "$source_path" "name")"
    printf '%s\n' "${agent_name:-$file_stem}"
}

agent_kind_for_source() {
    local source_path="$1"
    local kind

    kind="$(frontmatter_value "$source_path" "kind")"
    printf '%s\n' "$kind"
}

find_agent_source_by_name() {
    local agent_name="$1"
    local source_dir source_path candidate_name capability_name capability_dir
    local source_dirs=()

    for capability_name in $(available_capability_names); do
        capability_dir="$(capability_root "$capability_name")" || continue
        source_dirs+=("$capability_dir/agents")
    done

    for source_dir in "${source_dirs[@]}"; do
        [[ -d "$source_dir" ]] || continue
        for source_path in "$source_dir"/*.md; do
            [[ -f "$source_path" ]] || continue
            candidate_name="$(agent_name_for_source "$source_path")"
            if [[ "$candidate_name" == "$agent_name" ]]; then
                printf '%s\n' "$source_path"
                return 0
            fi
        done
    done
    return 1
}

render_main_agent_instruction_part() {
    local main_agent="$AR_MAIN_AGENT"
    local source_path kind

    if ! valid_agent_name "$main_agent"; then
        echo "Error: Invalid AR_MAIN_AGENT: $main_agent"
        exit 1
    fi

    if [[ -n "${MAIN_AGENT_SOURCE_PATH:-}" ]]; then
        source_path="$MAIN_AGENT_SOURCE_PATH"
    elif ! source_path="$(find_agent_source_by_name "$main_agent")"; then
        echo "Error: Main agent definition not found: $main_agent"
        echo "Add an agents/$main_agent.md definition with 'kind: main' inside a project, org, or built-in capability."
        exit 1
    fi

    kind="$(agent_kind_for_source "$source_path")"
    if [[ "$kind" != "main" ]]; then
        echo "Error: AR_MAIN_AGENT '$main_agent' resolves to kind '$kind', not kind 'main'."
        exit 1
    fi

    render_expanded_agent_body "$source_path"
}

workspace_display_path_for_target() {
    local target_path="$1"
    local relative_path

    case "$target_path" in
        "$WORKSPACE_DIR"/*)
            relative_path="${target_path#"$WORKSPACE_DIR"/}"
            workspace_runtime_path "$relative_path"
            ;;
        *)
            printf '%s\n' "$target_path"
            ;;
    esac
}

SUBAGENT_CATALOG_EMITTED=false

append_subagent_catalog_source_dir() {
    local agent_root="$1"
    local source_dir="$2"
    local source_path agent_name kind description target_path contract_path

    [[ -d "$source_dir" ]] || return 0

    for source_path in "$source_dir"/*.md; do
        [[ -f "$source_path" ]] || continue
        agent_name="$(agent_name_for_source "$source_path")"
        [[ -n "$agent_name" ]] || continue
        valid_agent_name "$agent_name" || continue
        kind="$(agent_kind_for_source "$source_path")"
        [[ "$kind" == "subagent" ]] || continue

        description="$(frontmatter_value "$source_path" "description")"
        [[ -n "$description" ]] || description="$agent_name agent."
        target_path="$(cli_call_required agent_target_path "$agent_root" "$agent_name")"
        contract_path="$(workspace_display_path_for_target "$target_path")"

        {
            printf -- '- `%s`: %s' "$agent_name" "$description"
            printf ' Contract: `%s`.\n' "$contract_path"
        }
        SUBAGENT_CATALOG_EMITTED=true
    done
}

render_subagent_catalog_instruction_part() {
    local agent_root capability_name capability_dir

    agent_root="$(project_agent_root_for_cli)"

    printf '## Available Subagents\n\n'
    printf 'Subagents are delegated tools. Standing user request: when these instructions say to launch, use, or route work through a named subagent, treat that as an explicit user request for Codex subagent delegation. You must try to spawn the named subagent and must not replace it with a direct helper command merely because such a command exists. If the subagent spawn fails, try to spawn it one more time. If the second spawn attempt fails or subagent delegation is unavailable or policy-blocked, stop that handoff and alert the user instead of silently falling back to a direct helper. Use this catalog to decide when a subagent exists, but do not infer the full input shape from memory. Before launching a subagent, read the rendered definition file at the `Contract:` path printed on that subagent'\''s catalog line. Follow its `## Subagent Contract` request template or its embedded `## Imperative Workflow` entry class. For a `SubagentWorkflow`, start a separate subagent that follows the contract named by `agent_name`, pass its typed constructor fields as the request, and preserve inherited history when supported. Include the exact rendered `Contract:` path in the spawned child request. If Codex cannot combine a native custom agent type with a full-history fork, use the history fork and explicitly direct that child to read and follow that exact contract file instead of dropping either the history or the contract. The child must not search the filesystem or installation for another contract. For `self.fire_and_forget(...)`, discard the spawned child handle and immediately continue the parent workflow; do not call `wait_agent`, `list_agents`, `send_message`, or `followup_task` for that child, and do not make the parent response depend on child output or completion. On Codex, these definitions are project-scoped custom agents under `.codex/agents/`, not `.agents`. Do not search `.agents` for subagent definitions; `.agents/skills` is a skill discovery directory on some CLIs, not the subagent catalog.\n\n'

    SUBAGENT_CATALOG_EMITTED=false
    if [[ -n "$agent_root" ]]; then
        for capability_name in $(enabled_capability_names); do
            capability_dir="$(capability_root "$capability_name")" || continue
            append_subagent_catalog_source_dir "$agent_root" "$capability_dir/agents"
        done
    fi
    if [[ "$SUBAGENT_CATALOG_EMITTED" != "true" ]]; then
        printf '(none)\n'
    fi
}

render_agentic_records_instruction_part() {
    [[ -n "${AR_WORK_BRANCH:-}" ]] || return 0

    printf '## Agentic Records\n\n'
    printf 'Agentic Records stores shared agent memory and capability-owned records in visible Git-backed records worktrees under `$AR_WORKSPACE_ROOT`.\n\n'
    printf '| Scope | Storage |\n'
    printf '| --- | --- |\n'
    printf '| Organization | Org repo configured by `AR_ORG_NOTES_REPO`, when present |\n'
    printf '| Project | Project repo orphan branch `%s` |\n' "${AR_PROJECT_RECORDS_BRANCH:-agentic/project-records}"
    printf '| Branch | Project repo orphan branch `agentic/branch-records/%s` |\n\n' "$AR_WORK_BRANCH"
    printf 'Local records worktrees for this invocation:\n\n'
    printf '```bash\n'
    printf 'PROJECT_RECORDS_DIR="${AR_PROJECT_RECORDS_DIR:?}"\n'
    printf 'BRANCH_RECORDS_DIR="${AR_BRANCH_RECORDS_DIR:?}"\n'
    printf '```\n\n'
    printf 'Capabilities own the files they place in those worktrees. For example, Agentic Notes owns `agent-notes/`, Experiment Log owns `experiment-log/`, and research workflows may keep `condensed_report.md`, numbered report files (`report_page1.md` oldest and the highest number current), `TODO.md`, and report-ready `images/` at the branch records root.\n'
}

setup_instruction_target() {
    local target
    target="$(cli_call_required instruction_target)"

    INSTRUCTION_FILE_REGENERATED=false
    INSTRUCTION_TARGET="$target"
}

remove_unprepared_client_guards() {
    local name path first_line
    for name in AGENTS.md CLAUDE.md GEMINI.md; do
        path="$WORKSPACE_DIR/$name"
        [[ -f "$path" ]] || continue
        IFS= read -r first_line < "$path" || true
        if [[ "$first_line" == "# Unprepared Agentic Team Checkout" ]]; then
            rm -f "$path"
        fi
    done
}

setup_generated_file_excludes() {
    workspace_is_git_worktree || return 0

    local exclude_path marker_start marker_end temp_path
    exclude_path="$(git -C "$WORKSPACE_DIR" rev-parse --git-path info/exclude 2>/dev/null)" || return 0
    [[ "$exclude_path" = /* ]] || exclude_path="$WORKSPACE_DIR/$exclude_path"
    mkdir -p "$(dirname "$exclude_path")"

    marker_start="# BEGIN agentic-team generated files"
    marker_end="# END agentic-team generated files"
    temp_path="${exclude_path}.agentic-team.tmp"

    if [[ -f "$exclude_path" ]]; then
        awk -v start="$marker_start" -v end="$marker_end" '
            $0 == start { skip=1; next }
            $0 == end { skip=0; next }
            !skip { print }
        ' "$exclude_path" > "$temp_path"
    else
        : > "$temp_path"
    fi

    cat >> "$temp_path" <<'EOF'
# BEGIN agentic-team generated files
/AGENTS.md
/CLAUDE.md
/GEMINI.md
/.agents/skills/
/.claude/skills/
/.claude/agents/
/.claude/hooks/
/.claude/settings.local.json
/.codex/agents/
/.codex/hooks/
/.codex/hooks.json
/.gemini/skills/
/.gemini/agents/
/.gemini/hooks/
/.gemini/settings.json
/.opencode/skills/
/.opencode/agents/
/.opencode/plugins/
/.pi/extensions/
# END agentic-team generated files
EOF

    mv "$temp_path" "$exclude_path"
}

render_instruction_document() {
    [[ -n "${INSTRUCTION_TARGET:-}" ]] || setup_instruction_target
    remove_unprepared_client_guards

    local instruction_path="$WORKSPACE_DIR/$INSTRUCTION_TARGET"
    local temp_path="${instruction_path}.tmp"

    {
        if [[ -f "$SCRIPT_DIR/INSTRUCTIONS.md" ]]; then
            render_instruction_template_part
        fi
        printf '\n'
        render_main_agent_instruction_part
        printf '\n'
        render_skill_instruction_parts
        printf '\n'
        render_subagent_catalog_instruction_part
        printf '\n'
        render_agentic_records_instruction_part
        printf '\n'
        render_capability_instruction_parts
    } > "$temp_path"

    mv "$temp_path" "$instruction_path"
    INSTRUCTION_FILE_REGENERATED=true
}

normalize_markdown_file() {
    local target_path="$1"
    local temp_path
    [[ -f "$target_path" ]] || return 0
    temp_path="${target_path}.normalize.tmp"
    awk '
        {
            sub(/[[:space:]]+$/, "")
            stripped=$0
            sub(/^[[:space:]]+/, "", stripped)
            if (stripped ~ /^```/) {
                in_fence = !in_fence
                lines[++count] = $0
                blank_run = 0
                next
            }
            if (in_fence) {
                lines[++count] = $0
                next
            }
            if (stripped == "") {
                blank_run++
                if (blank_run <= 1) lines[++count] = ""
                next
            }
            blank_run = 0
            lines[++count] = $0
        }
        END {
            while (count > 0 && lines[count] == "") count--
            for (line_number=1; line_number<=count; line_number++) print lines[line_number]
        }
    ' "$target_path" > "$temp_path"
    mv "$temp_path" "$target_path"
}
strip_frontmatter() {
    local source_path="$1"

    awk '
        NR == 1 && $0 == "---" { in_frontmatter=1; next }
        in_frontmatter && $0 == "---" { in_frontmatter=0; next }
        !in_frontmatter { print }
    ' "$source_path"
}

frontmatter_value() {
    local source_path="$1"
    local key="$2"

    awk -v key="$key" '
        NR == 1 && $0 == "---" { in_frontmatter=1; next }
        in_frontmatter && $0 == "---" { exit }
        in_frontmatter {
            pattern = "^[[:space:]]*" key ":[[:space:]]*"
            if ($0 ~ pattern) {
                sub(pattern, "")
                sub(/^"/, "")
                sub(/"$/, "")
                print
                exit
            }
        }
    ' "$source_path"
}

frontmatter_list_values() {
    local source_path="$1"
    local key="$2"

    awk -v key="$key" '
        function clean(value) {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            gsub(/^["\047]|["\047]$/, "", value)
            return value
        }
        function emit_values(value,    n, i, parts) {
            gsub(/^\[/, "", value)
            gsub(/\]$/, "", value)
            gsub(/,/, " ", value)
            n = split(value, parts, /[[:space:]]+/)
            for (i = 1; i <= n; i++) {
                parts[i] = clean(parts[i])
                if (parts[i] != "") {
                    print parts[i]
                }
            }
        }
        NR == 1 && $0 == "---" { in_frontmatter=1; next }
        in_frontmatter && $0 == "---" { exit }
        in_frontmatter {
            key_pattern = "^[[:space:]]*" key ":[[:space:]]*"
            if (collecting) {
                if ($0 ~ /^[[:space:]]*-[[:space:]]*/) {
                    value = $0
                    sub(/^[[:space:]]*-[[:space:]]*/, "", value)
                    value = clean(value)
                    if (value != "") {
                        print value
                    }
                    next
                }
                if ($0 ~ /^[[:space:]]*$/ || $0 ~ /^[[:space:]]*#/) {
                    next
                }
                collecting=0
            }
            if ($0 ~ key_pattern) {
                value = $0
                sub(key_pattern, "", value)
                value = clean(value)
                if (value == "") {
                    collecting=1
                } else {
                    emit_values(value)
                    exit
                }
            }
        }
    ' "$source_path"
}

project_skill_roots_for_cli() {
    cli_call_required project_skill_root
}

is_active_project_skill() {
    local needle="$1"
    local capability_name capability_dir source_path skill_name

    for capability_name in $(enabled_capability_names); do
        capability_dir="$(capability_root "$capability_name")" || continue
        for source_path in "$capability_dir"/skills/*/SKILL.md; do
            [[ -f "$source_path" ]] || continue
            skill_name="$(basename "$(dirname "$source_path")")"
            [[ "$skill_name" == "$needle" ]] && return 0
        done
    done

    return 1
}

cleanup_inactive_managed_skills() {
    local skill_root="$1"
    local managed_marker="$2"
    local existing_dir skill_file skill_name

    for existing_dir in "$skill_root"/*; do
        [[ -d "$existing_dir" ]] || continue
        skill_file="$existing_dir/SKILL.md"
        [[ -f "$skill_file" ]] || continue
        grep -q "$managed_marker" "$skill_file" || continue
        skill_name="$(basename "$existing_dir")"
        if ! is_active_project_skill "$skill_name"; then
            rm -rf "$existing_dir"
        fi
    done
}

setup_project_skills() {
    local managed_marker="Generated by agentic-team"
    local skill_root source_path skill_name skill_dir target_path capability_name capability_dir

    while IFS= read -r skill_root; do
        [[ -n "$skill_root" ]] || continue
        mkdir -p "$skill_root"
        cleanup_inactive_managed_skills "$skill_root" "$managed_marker"

        for capability_name in $(enabled_capability_names); do
            capability_dir="$(capability_root "$capability_name")" || continue
            for source_path in "$capability_dir"/skills/*/SKILL.md; do
                [[ -f "$source_path" ]] || continue
                skill_name="$(basename "$(dirname "$source_path")")"
                skill_dir="$skill_root/$skill_name"
                target_path="$skill_dir/SKILL.md"

                if [[ -f "$target_path" ]] && ! grep -q "$managed_marker" "$target_path"; then
                    echo "Warning: Skipping existing capability skill at $target_path (not managed by agentic-team)"
                    continue
                fi

                mkdir -p "$skill_dir"
                render_managed_skill_file "$source_path" "$target_path"
            done
        done
    done < <(project_skill_roots_for_cli)
}

render_managed_skill_file() {
    local source_path="$1"
    local target_path="$2"
    local temp_path="${target_path}.tmp"
    local body_path="${target_path}.body.tmp"

    if ! render_expanded_agent_body "$source_path" > "$body_path"; then
        rm -f "$temp_path" "$body_path"
        return 1
    fi

    awk '
        BEGIN { inserted=0; in_frontmatter=0 }
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && $0 ~ /^[[:space:]]*(renderer|workflow_interface|workflow_module|workflow_entry|workflow_receiver):[[:space:]]*/ { next }
        in_frontmatter && $0 == "---" {
            print
            print ""
            print "<!-- Generated by agentic-team. Edit the source skill to change this file. -->"
            inserted=1
            exit
        }
        in_frontmatter { print; next }
        END {
            if (inserted == 0) {
                print "<!-- Generated by agentic-team. Edit the source skill to change this file. -->"
            }
        }
    ' "$source_path" > "$temp_path"

    printf '\n' >> "$temp_path"
    cat "$body_path" >> "$temp_path"

    mv "$temp_path" "$target_path"
    rm -f "$body_path"
}
