# Sourced by agentic-researcher. Instruction, module, skill, and managed agent rendering.

setup_storage() {
    STATE_ROOT="${AR_STATE_ROOT:-$HOME/.cache/agentic-researcher}"

    UV_CACHE_DIR="${UV_CACHE_DIR:-$STATE_ROOT/uv/cache}"
    UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$STATE_ROOT/uv/python}"
    UV_TOOL_DIR="${UV_TOOL_DIR:-$STATE_ROOT/uv/tools}"
    export UV_CACHE_DIR UV_PYTHON_INSTALL_DIR UV_TOOL_DIR

    if [[ "$AR_SANDBOX" == "none" ]]; then
        mkdir -p "$STATE_ROOT"
        CACHE_BASE="$STATE_ROOT"
        HF_HOME="${HF_HOME:-$CACHE_BASE/hf_home}"
        TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-$CACHE_BASE/triton_cache}"
        WANDB_DIR="${WANDB_DIR:-$CACHE_BASE/wandb}"
        return
    fi

    # Sandbox-specific config directory (isolated from host)
    AR_CONFIG_STORE="$STATE_ROOT/agentic-researcher-config"

    mkdir -p "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" "$UV_TOOL_DIR" \
             "$AR_CONFIG_STORE"

    # Apptainer cache
    if [[ "$AR_SANDBOX" == "apptainer" ]]; then
        export APPTAINER_CACHEDIR="$STATE_ROOT/apptainer_cache"
        mkdir -p -m 700 "$APPTAINER_CACHEDIR"

        CONTAINER_TMP="$STATE_ROOT/apptainer_cache/container-tmp"
        mkdir -p -m 700 "$CONTAINER_TMP"
    fi

    CACHE_BASE="$STATE_ROOT"
    HF_HOME="$CACHE_BASE/hf_home"
    TRITON_CACHE_DIR="$CACHE_BASE/triton_cache"
    WANDB_DIR="$CACHE_BASE/wandb"
    mkdir -p "$HF_HOME" "$TRITON_CACHE_DIR" "$WANDB_DIR"

    cli_call_all setup_storage
}
render_module_block() {
    local module_name="$1"
    local module_path="$SCRIPT_DIR/modules/$module_name.md"

    if [[ ! -f "$module_path" ]]; then
        echo "Warning: Module not found: $module_name" >&2
        return 0
    fi

    cat "$module_path"
    printf '\n'
}

expand_modules_from_stdin() {
    local line module_name
    local module_regex='^<!--[[:space:]]*AR_MODULE:[[:space:]]*([A-Za-z0-9._-]+)[[:space:]]*-->$'

    while IFS= read -r line; do
        if [[ "$line" =~ $module_regex ]]; then
            module_name="${BASH_REMATCH[1]}"
            render_module_block "$module_name"
        else
            printf '%s\n' "$line"
        fi
    done
}

render_instruction_template() {
    local output_path="$1"

    if [[ "$AR_SANDBOX" == "docker" || "$AR_SANDBOX" == "podman" ]]; then
        awk '
            /<!-- DOCKER-OMIT-START -->/ { skip=1; next }
            /<!-- DOCKER-OMIT-END -->/   { skip=0; next }
            !skip { print }
        ' "$SCRIPT_DIR/INSTRUCTIONS.md" | expand_modules_from_stdin > "$output_path"
    else
        expand_modules_from_stdin < "$SCRIPT_DIR/INSTRUCTIONS.md" > "$output_path"
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

agent_name_exists_in_source_dir() {
    local agent_name="$1"
    local source_dir="$2"
    local source_path candidate_name

    [[ -d "$source_dir" ]] || return 1
    for source_path in "$source_dir"/*.md; do
        [[ -f "$source_path" ]] || continue
        candidate_name="$(agent_name_for_source "$source_path")"
        [[ "$candidate_name" == "$agent_name" ]] && return 0
    done
    return 1
}

find_agent_source_by_name() {
    local agent_name="$1"
    local source_dir source_path candidate_name
    local source_dirs=()

    if [[ -n "${AR_ORG_NOTES_REPO:-}" && -d "$STATE_ROOT/repos/org-agentic-notes/agents" ]]; then
        source_dirs+=("$STATE_ROOT/repos/org-agentic-notes/agents")
    fi
    source_dirs+=("$SCRIPT_DIR/agents")

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

setup_main_agent_instruction_block() {
    local instruction_path="$WORKSPACE_DIR/$INSTRUCTION_TARGET"
    local main_agent="${AR_MAIN_AGENT:-research-coordinator}"
    local source_path kind temp_path

    [[ -f "$instruction_path" ]] || return 0

    if ! valid_agent_name "$main_agent"; then
        echo "Error: Invalid AR_MAIN_AGENT: $main_agent"
        exit 1
    fi

    if [[ -n "${MAIN_AGENT_SOURCE_PATH:-}" ]]; then
        source_path="$MAIN_AGENT_SOURCE_PATH"
    elif ! source_path="$(find_agent_source_by_name "$main_agent")"; then
        echo "Error: Main agent definition not found: $main_agent"
        echo "Add agents/$main_agent.md with frontmatter 'kind: main' to AR or the org notes repo."
        exit 1
    fi

    kind="$(agent_kind_for_source "$source_path")"
    if [[ "$kind" != "main" ]]; then
        echo "Error: AR_MAIN_AGENT '$main_agent' resolves to kind '$kind', not kind 'main'."
        exit 1
    fi

    temp_path="${instruction_path}.tmp"
    cp "$instruction_path" "$temp_path"
    {
        printf '\n'
        strip_frontmatter "$source_path" | expand_modules_from_stdin
    } >> "$temp_path"
    mv "$temp_path" "$instruction_path"
}

setup_branch_instruction_block() {
    local instruction_path="$WORKSPACE_DIR/$INSTRUCTION_TARGET"
    local temp_path

    [[ -f "$instruction_path" ]] || return 0
    [[ -n "${AR_AGENT_BRANCH:-}" ]] || return 0

    temp_path="${instruction_path}.tmp"
    cp "$instruction_path" "$temp_path"

    {
        printf '\n'
        printf '## Agent Branch\n\n'
        printf 'Active branch: `%s`.\n\n' "$WORKSPACE_GIT_BRANCH"
        printf 'Branch ownership mode: `%s`.\n\n' "${AR_BRANCH_OWNERSHIP:-exclusive}"
        case "${AR_BRANCH_OWNERSHIP:-exclusive}" in
            readonly)
                printf 'This invocation is read-only. Do not modify project files, stage changes, commit, or push. If sandbox support is available, the launcher may enforce read-only access; otherwise treat this as an instruction-level constraint.\n\n'
                ;;
            shared)
                printf 'This invocation may share the branch with other agents or humans. Use ordinary Git collaboration: inspect status before editing, pull/rebase/merge when appropriate, and resolve conflicts explicitly.\n\n'
                ;;
            *)
                if [[ "${BRANCH_GUARD_OVERRIDE:-false}" == "true" ]]; then
                    printf 'This invocation was explicitly allowed to use a branch that is not an unoccupied `agent/*` branch. Another local agent may also be writing here, so use normal Git conflict checks and do not assume exclusive ownership.\n\n'
                else
                    printf 'This invocation is expected to be the only mutating top-level agent for this branch on this AR installation. The launcher uses a local soft branch guard to catch accidental duplicate writers; Git remains the source of truth for conflicts.\n\n'
                fi
                printf 'Work on `%s` or child branches such as `%s/exp/<experiment-name>`. Do not commit to `main` or `master` unless the user explicitly asks.\n\n' "$AR_AGENT_BRANCH" "$AR_AGENT_BRANCH"
                ;;
        esac
    } >> "$temp_path"

    mv "$temp_path" "$instruction_path"
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
    local output_path="$1"
    local agent_root="$2"
    local source_dir="$3"
    local override_dir="${4:-}"
    local source_path agent_name kind description target_path contract_path

    [[ -d "$source_dir" ]] || return 0

    for source_path in "$source_dir"/*.md; do
        [[ -f "$source_path" ]] || continue
        agent_name="$(agent_name_for_source "$source_path")"
        if [[ -n "$override_dir" ]] && agent_name_exists_in_source_dir "$agent_name" "$override_dir"; then
            continue
        fi
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
        } >> "$output_path"
        SUBAGENT_CATALOG_EMITTED=true
    done
}

setup_subagent_catalog_instruction_block() {
    local instruction_path="$WORKSPACE_DIR/$INSTRUCTION_TARGET"
    local temp_path agent_root org_agent_dir=""

    [[ -f "$instruction_path" ]] || return 0

    temp_path="${instruction_path}.tmp"
    cp "$instruction_path" "$temp_path"

    agent_root="$(project_agent_root_for_tool)"
    if [[ -n "${AR_ORG_NOTES_REPO:-}" ]]; then
        org_agent_dir="$STATE_ROOT/repos/org-agentic-notes/agents"
    fi

    {
        printf '\n'
        printf '## Available Subagents\n\n'
        printf 'Subagents are delegated tools. Use this catalog to decide when a subagent exists, but do not infer the full input shape from memory. Before launching a subagent, read its rendered definition file and use that file'\''s `## Subagent Contract` section for the typed request template. Each subagent has exactly one request template; if a workflow needs a different request shape, use a different subagent.\n\n'
    } >> "$temp_path"

    SUBAGENT_CATALOG_EMITTED=false
    if [[ -n "$agent_root" ]]; then
        append_subagent_catalog_source_dir "$temp_path" "$agent_root" "$SCRIPT_DIR/agents" "$org_agent_dir"
        if [[ -n "${AR_ORG_NOTES_REPO:-}" ]]; then
            append_subagent_catalog_source_dir "$temp_path" "$agent_root" "$org_agent_dir" ""
        fi
    fi
    if [[ "$SUBAGENT_CATALOG_EMITTED" != "true" ]]; then
        printf '(none)\n' >> "$temp_path"
    fi
    mv "$temp_path" "$instruction_path"
}

setup_instruction_file() {
    local target
    target="$(cli_call_required instruction_target)"

    INSTRUCTION_FILE_REGENERATED=false

    if [[ -f "$SCRIPT_DIR/INSTRUCTIONS.md" ]]; then
        render_instruction_template "$WORKSPACE_DIR/$target"
        INSTRUCTION_FILE_REGENERATED=true
    fi

    INSTRUCTION_TARGET="$target"
}

normalize_markdown_file() {
    local target_path="$1"
    [[ -f "$target_path" ]] || return 0
    resolve_python_cmd || return 0
    "${AR_PYTHON_CMD[@]}" - "$target_path" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
blank_run = 0
in_fence = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("```"):
        in_fence = not in_fence
        out.append(line.rstrip())
        blank_run = 0
        continue
    if in_fence:
        out.append(line.rstrip())
        continue
    if stripped == "":
        blank_run += 1
        if blank_run <= 1:
            out.append("")
        continue
    blank_run = 0
    out.append(line.rstrip())

while out and out[-1] == "":
    out.pop()

path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
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

project_skill_roots_for_tool() {
    cli_call_required project_skill_root
}

is_active_project_skill() {
    local needle="$1"
    local source_path skill_name

    for source_path in "$SCRIPT_DIR"/skills/*/SKILL.md; do
        [[ -f "$source_path" ]] || continue
        skill_name="$(basename "$(dirname "$source_path")")"
        [[ "$skill_name" == "$needle" ]] && return 0
    done

    for skill_name in "${SELECTED_OPTIONAL_SKILLS[@]}"; do
        [[ -f "$SCRIPT_DIR/optional-skills/$skill_name/SKILL.md" ]] || continue
        [[ "$skill_name" == "$needle" ]] && return 0
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
    local managed_marker="Generated by agentic-researcher"
    local skill_root source_path skill_name skill_dir target_path

    while IFS= read -r skill_root; do
        [[ -n "$skill_root" ]] || continue
        mkdir -p "$skill_root"
        cleanup_inactive_managed_skills "$skill_root" "$managed_marker"

        for source_path in "$SCRIPT_DIR"/skills/*/SKILL.md; do
            [[ -f "$source_path" ]] || continue
            skill_name="$(basename "$(dirname "$source_path")")"
            skill_dir="$skill_root/$skill_name"
            target_path="$skill_dir/SKILL.md"

            if [[ -f "$target_path" ]] && ! grep -q "$managed_marker" "$target_path"; then
                echo "Warning: Skipping existing skill at $target_path (not managed by agentic-researcher)"
                continue
            fi

            mkdir -p "$skill_dir"
            render_managed_skill_file "$source_path" "$target_path"
        done

        for skill_name in "${SELECTED_OPTIONAL_SKILLS[@]}"; do
            source_path="$SCRIPT_DIR/optional-skills/$skill_name/SKILL.md"
            [[ -f "$source_path" ]] || continue
            skill_dir="$skill_root/$skill_name"
            target_path="$skill_dir/SKILL.md"

            if [[ -f "$target_path" ]] && ! grep -q "$managed_marker" "$target_path"; then
                echo "Warning: Skipping existing optional skill at $target_path (not managed by agentic-researcher)"
                continue
            fi

            mkdir -p "$skill_dir"
            render_managed_skill_file "$source_path" "$target_path"
        done
    done < <(project_skill_roots_for_tool)
}

render_managed_skill_file() {
    local source_path="$1"
    local target_path="$2"
    local temp_path="${target_path}.tmp"

    awk '
        BEGIN { inserted=0; in_frontmatter=0 }
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && $0 == "---" {
            print
            print ""
            print "<!-- Generated by agentic-researcher. Edit the source skill to change this file. -->"
            inserted=1
            in_frontmatter=0
            next
        }
        { print }
        END {
            if (inserted == 0) {
                print "<!-- Generated by agentic-researcher. Edit the source skill to change this file. -->"
            }
        }
    ' "$source_path" > "$temp_path"

    mv "$temp_path" "$target_path"
}

