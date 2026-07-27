# Sourced by agentic-team. Project/worktree validation and branch guard logic.

validate_workspace() {
    # Default to current directory
    if [[ -z "$WORKSPACE_DIR" ]]; then
        WORKSPACE_DIR="$(pwd)"
    fi

    # Resolve symlinks in a macOS/Linux portable way.
    local original_workspace resolved_workspace
    original_workspace="$WORKSPACE_DIR"
    WORKSPACE_INPUT_DIR="$original_workspace"
    export WORKSPACE_INPUT_DIR
    if ! resolved_workspace="$(resolve_realpath "$WORKSPACE_DIR")"; then
        echo "Error: Cannot resolve path: $original_workspace"
        exit 1
    fi
    WORKSPACE_DIR="$resolved_workspace"

    if [[ ! -d "$WORKSPACE_DIR" ]]; then
        echo "Error: Directory does not exist: $WORKSPACE_DIR"
        exit 1
    fi

    # SECURITY: Prevent sandboxing of sensitive system directories
    case "$WORKSPACE_DIR" in
        /|/etc/*|/etc|/root/*|/root|/sys/*|/sys|/proc/*|/proc|/dev/*|/dev|/boot/*|/boot)
            echo "Error: Cannot sandbox system directories: $WORKSPACE_DIR"
            exit 1
            ;;
        /home/*/.ssh/*|/home/*/.ssh|/Users/*/.ssh/*|/Users/*/.ssh)
            echo "Error: Cannot sandbox SSH directories: $WORKSPACE_DIR"
            exit 1
            ;;
        /home/*/.gnupg/*|/home/*/.gnupg|/Users/*/.gnupg/*|/Users/*/.gnupg)
            echo "Error: Cannot sandbox GPG directories: $WORKSPACE_DIR"
            exit 1
            ;;
        /home/*/.aws/*|/home/*/.aws|/home/*/.kube/*|/home/*/.kube|/home/*/.config/gcloud/*|/home/*/.config/gcloud|/Users/*/.aws/*|/Users/*/.aws|/Users/*/.kube/*|/Users/*/.kube|/Users/*/.config/gcloud/*|/Users/*/.config/gcloud)
            echo "Error: Cannot sandbox cloud credential directories: $WORKSPACE_DIR"
            exit 1
            ;;
    esac
}

validate_cli_workspace() {
    cli_call validate_workspace
}

slugify_workspace_name() {
    local text="$1" slug
    slug="$(printf '%s' "$text" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
    slug="${slug:0:72}"
    slug="${slug%-}"
    printf '%s\n' "${slug:-project}"
}

path_looks_like_at_workspace() {
    local path="$1" base
    base="$(basename "$path")"
    [[ "$base" == *-at ]] && return 0
    [[ -e "$path/project" || -e "$path/project-state" ]] && return 0
    return 1
}

workspace_input_is_at_code_path() {
    local path="${WORKSPACE_INPUT_DIR:-$WORKSPACE_DIR}"
    [[ "$(basename "$path")" == "code" && "$(basename "$(dirname "$(dirname "$path")")")" == *-at ]]
}

resolve_launch_positionals() {
    local count first
    count="${#POSITIONAL_ARGS[@]}"

    if [[ -n "$WORKTREE_PATH_ARG" ]]; then
        WORKSPACE_DIR="$WORKTREE_PATH_ARG"
        if (( count > 0 )); then
            CLI_ARGS+=("${POSITIONAL_ARGS[@]}")
        fi
        return
    fi

    if (( count == 0 )); then
        return
    fi

    first="${POSITIONAL_ARGS[0]}"
    if (( count >= 2 )) && { path_looks_like_at_workspace "$first" || [[ -n "$AT_PROJECT_DIR_ARG" || -n "$AT_FROM_REF" ]]; }; then
        AT_WORKSPACE_DIR_ARG="$first"
        AT_WORK_NAME_ARG="${POSITIONAL_ARGS[1]}"
        if (( count > 2 )); then
            CLI_ARGS+=("${POSITIONAL_ARGS[@]:2}")
        fi
        return
    fi

    if (( count == 1 )) && { path_looks_like_at_workspace "$first" || [[ -n "$AT_PROJECT_DIR_ARG" ]]; }; then
        AT_WORKSPACE_DIR_ARG="$first"
        return
    fi

    WORKSPACE_DIR="$first"
    if (( count > 1 )); then
        CLI_ARGS+=("${POSITIONAL_ARGS[@]:1}")
    fi
}

fallback_workspace_name_from_path() {
    local path="$WORKSPACE_DIR" at_root project_link resolved_project base

    if [[ "$(basename "$path")" == "code" && "$(basename "$(dirname "$(dirname "$path")")")" == *-at ]]; then
        at_root="$(dirname "$(dirname "$path")")"
        project_link="$at_root/project"
        if [[ -e "$project_link" || -L "$project_link" ]]; then
            if resolved_project="$(resolve_realpath "$project_link" 2>/dev/null)"; then
                slugify_workspace_name "$(basename "$resolved_project")"
                return
            fi
        fi
        base="$(basename "$at_root")"
        slugify_workspace_name "${base%-at}"
        return
    fi

    slugify_workspace_name "$(basename "$path")"
}

derive_workspace_name() {
    AR_WORKSPACE_NAME="$(fallback_workspace_name_from_path)"
    export AR_WORKSPACE_NAME
}

current_workspace_git_branch() {
    git -C "$WORKSPACE_DIR" branch --show-current 2>/dev/null || true
}

workspace_is_git_worktree() {
    [[ "$(git -C "$WORKSPACE_DIR" rev-parse --is-inside-work-tree 2>/dev/null || true)" == "true" ]]
}

protected_work_branch() {
    case "$1" in
        main|master|trunk|dev|develop|release|release/*)
            return 0
            ;;
    esac
    return 1
}

work_branch_from_branch() {
    local branch="$1"
    if [[ "$branch" == */exp/* ]]; then
        printf '%s\n' "${branch%%/exp/*}"
    else
        printf '%s\n' "$branch"
    fi
}

work_branch_id() {
    slugify_workspace_name "$1"
}

work_name_from_branch() {
    local branch="$1" leaf
    leaf="${branch##*/}"
    slugify_workspace_name "${leaf:-$branch}"
}

agentic_workspace_root() {
    local input_dir="${WORKSPACE_INPUT_DIR:-$WORKSPACE_DIR}" root_dir resolved_input parent

    if [[ -n "${AR_WORKSPACE_ROOT:-}" ]]; then
        resolve_realpath "$AR_WORKSPACE_ROOT" 2>/dev/null || printf '%s\n' "$AR_WORKSPACE_ROOT"
        return
    fi

    if [[ "$(basename "$input_dir")" == "code" && "$(basename "$(dirname "$(dirname "$input_dir")")")" == *-at ]]; then
        root_dir="$(dirname "$(dirname "$input_dir")")"
        resolve_realpath "$root_dir" 2>/dev/null || printf '%s\n' "$root_dir"
        return
    fi

    if resolved_input="$(resolve_realpath "$input_dir" 2>/dev/null)"; then
        input_dir="$resolved_input"
    fi

    if [[ "$(basename "$input_dir")" == "code" && "$(basename "$(dirname "$(dirname "$input_dir")")")" == *-at ]]; then
        dirname "$(dirname "$input_dir")"
        return
    fi

    parent="$(dirname "$WORKSPACE_DIR")"
    printf '%s/%s-at\n' "$parent" "$AR_WORKSPACE_NAME"
}

set_agentic_workspace_root() {
    AR_WORKSPACE_ROOT="$(agentic_workspace_root)"
    export AR_WORKSPACE_ROOT
}

agentic_runtime_root() {
    if [[ -n "${AR_RUNTIME_ROOT:-}" ]]; then
        resolve_realpath "$AR_RUNTIME_ROOT" 2>/dev/null || printf '%s\n' "$AR_RUNTIME_ROOT"
        return
    fi
    printf '%s/.runtime\n' "$AR_WORKSPACE_ROOT"
}

set_agentic_runtime_root() {
    AR_RUNTIME_ROOT="$(agentic_runtime_root)"
    RUNTIME_ROOT="$AR_RUNTIME_ROOT"
    export AR_RUNTIME_ROOT RUNTIME_ROOT
}

agentic_artifacts_dir() {
    if [[ -n "${AR_ARTIFACTS_DIR:-}" ]]; then
        resolve_realpath "$AR_ARTIFACTS_DIR" 2>/dev/null || printf '%s\n' "$AR_ARTIFACTS_DIR"
        return
    fi
    printf '%s/artifacts/project\n' "$AR_WORKSPACE_ROOT"
}

set_agentic_artifacts_dir() {
    AR_ARTIFACTS_DIR="$(agentic_artifacts_dir)"
    export AR_ARTIFACTS_DIR
}

project_state_dir_path() {
    printf '%s/project-state\n' "$AR_WORKSPACE_ROOT"
}

work_dir_path_for_branch() {
    local branch="$1" work_name
    work_name="$(work_name_from_branch "$branch")"
    printf '%s/%s\n' "$AR_WORKSPACE_ROOT" "$work_name"
}

code_worktree_path_for_branch() {
    local branch="$1"
    printf '%s/code\n' "$(work_dir_path_for_branch "$branch")"
}

work_state_dir_path_for_branch() {
    local branch="$1"
    printf '%s/state\n' "$(work_dir_path_for_branch "$branch")"
}

git_branch_exists() {
    git -C "$WORKSPACE_DIR" show-ref --verify --quiet "refs/heads/$1"
}

valid_git_branch_name() {
    git -C "$WORKSPACE_DIR" check-ref-format --branch "$1" >/dev/null 2>&1
}

branch_guard_dir_for() {
    local branch="$1"
    printf '%s/branch-guards/%s\n' "$RUNTIME_ROOT" "$(slugify_workspace_name "$branch")"
}

file_mtime_epoch() {
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || printf '0\n'
}

branch_guard_is_fresh() {
    local path="$1" now mtime stale_seconds
    stale_seconds="${AR_BRANCH_GUARD_STALE_SECONDS:-300}"
    now="$(date +%s)"
    mtime="$(file_mtime_epoch "$path")"
    [[ "$mtime" =~ ^[0-9]+$ ]] || return 1
    (( now - mtime <= stale_seconds ))
}

branch_guard_first_active_file() {
    local branch="$1" guard_dir guard
    guard_dir="$(branch_guard_dir_for "$branch")"
    [[ -d "$guard_dir" ]] || return 1
    for guard in "$guard_dir"/*.guard; do
        [[ -f "$guard" ]] || continue
        [[ "$guard" == "${BRANCH_GUARD_FILE:-}" ]] && continue
        if branch_guard_is_fresh "$guard"; then
            printf '%s\n' "$guard"
            return 0
        fi
    done
    return 1
}

branch_guard_is_occupied() {
    branch_guard_first_active_file "$1" >/dev/null
}

branch_guard_summary() {
    local guard="$1"
    [[ -f "$guard" ]] || return 0
    awk -F= '
        $1 == "session_id" { session=$2 }
        $1 == "main_agent" { main_agent=$2 }
        $1 == "pid" { pid=$2 }
        $1 == "host" { host=$2 }
        $1 == "workspace" { workspace=$2 }
        $1 == "started_at" { started_at=$2 }
        END {
            if (session) printf "Session: %s\n", session
            if (main_agent) printf "Main agent: %s\n", main_agent
            if (pid || host) printf "Process: %s on %s\n", pid, host
            if (workspace) printf "Workspace: %s\n", workspace
            if (started_at) printf "Started: %s\n", started_at
        }
    ' "$guard"
}

git_ref_exists() {
    git -C "$WORKSPACE_DIR" rev-parse --verify --quiet "$1^{commit}" >/dev/null 2>&1
}

workspace_has_uncommitted_changes() {
    [[ -n "$(git -C "$WORKSPACE_DIR" status --porcelain 2>/dev/null || true)" ]]
}

git_commit_identity_configured() {
    git -C "$WORKSPACE_DIR" var GIT_AUTHOR_IDENT >/dev/null 2>&1 \
        && git -C "$WORKSPACE_DIR" var GIT_COMMITTER_IDENT >/dev/null 2>&1
}

configured_at_git_name() {
    printf '%s\n' "${AR_GIT_NAME:-${AR_NOTES_GIT_NAME:-}}"
}

configured_at_git_email() {
    printf '%s\n' "${AR_GIT_EMAIL:-${AR_NOTES_GIT_EMAIL:-}}"
}

setup_workspace_git_identity() {
    local name email

    workspace_is_git_worktree || return 0
    git_commit_identity_configured && return 0

    name="$(configured_at_git_name)"
    email="$(configured_at_git_email)"
    [[ -n "$name" && -n "$email" ]] || return 0

    git -C "$WORKSPACE_DIR" config user.name "$name"
    git -C "$WORKSPACE_DIR" config user.email "$email"
}

branch_config_get() {
    local branch="$1" key="$2"
    git -C "$WORKSPACE_DIR" config --get "branch.$branch.$key" 2>/dev/null || true
}

record_work_branch_base() {
    local branch="$1" base_ref="$2" base_commit
    [[ -n "$branch" && -n "$base_ref" ]] || return 0
    git -C "$WORKSPACE_DIR" config "branch.$branch.agentic-base" "$base_ref" || true
    if base_commit="$(git -C "$WORKSPACE_DIR" rev-parse "$base_ref^{commit}" 2>/dev/null)"; then
        git -C "$WORKSPACE_DIR" config "branch.$branch.agentic-base-commit" "$base_commit" || true
    fi
}

infer_work_branch_base_ref() {
    local owner_branch="$1" current_branch="$2" value candidate upstream

    value="$(branch_config_get "$owner_branch" "agentic-base")"
    if [[ -n "$value" ]] && git_ref_exists "$value"; then
        printf '%s\n' "$value"
        return 0
    fi

    if [[ -n "$current_branch" ]] && [[ "$current_branch" != "$owner_branch" ]]; then
        printf '%s\n' "$current_branch"
        return 0
    fi

    upstream="$(git -C "$WORKSPACE_DIR" rev-parse --abbrev-ref "$owner_branch@{upstream}" 2>/dev/null || true)"
    if [[ -n "$upstream" ]] && git_ref_exists "$upstream"; then
        printf '%s\n' "$upstream"
        return 0
    fi

    candidate="$(git -C "$WORKSPACE_DIR" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    if [[ -n "$candidate" ]] && git_ref_exists "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
    fi

    for candidate in origin/main origin/master main master dev; do
        if git_ref_exists "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    printf 'HEAD\n'
}

unused_work_branch_candidate() {
    local base candidate n
    base="work/$(slugify_workspace_name "${AR_USER_ID:-${USER:-agent}}")"
    candidate="$base"
    n=2
    while git_branch_exists "$candidate" || branch_guard_is_occupied "$candidate"; do
        candidate="$base-$n"
        n=$((n + 1))
    done
    printf '%s\n' "$candidate"
}

default_worktree_path() {
    local branch="$1" candidate n
    set_agentic_workspace_root
    candidate="$(code_worktree_path_for_branch "$branch")"
    n=2
    while [[ -e "$candidate" ]]; do
        candidate="$(work_dir_path_for_branch "$branch")-$n/code"
        n=$((n + 1))
    done
    printf '%s\n' "$candidate"
}

launch_is_interactive() {
    [[ -t 0 && -t 1 ]]
}

expand_path() {
    local path="$1"
    case "$path" in
        "~")
            printf '%s\n' "$HOME"
            ;;
        "~/"*)
            printf '%s/%s\n' "$HOME" "${path#~/}"
            ;;
        *)
            printf '%s\n' "$path"
            ;;
    esac
}

default_project_for_at_root() {
    local at_root="$1" base parent project_name
    base="$(basename "$at_root")"
    parent="$(dirname "$at_root")"
    if [[ "$base" == *-at ]]; then
        project_name="${base%-at}"
        printf '%s/%s\n' "$parent" "$project_name"
    else
        printf '%s\n' "$parent/project"
    fi
}

prompt_at_workspace_root() {
    local default_root="$1" answer
    read -r -p "AT workspace directory [$default_root]: " answer
    printf '%s\n' "${answer:-$default_root}"
}

prompt_at_work_name() {
    local default_name="$1" answer
    read -r -p "AT work name [$default_name]: " answer
    printf '%s\n' "${answer:-$default_name}"
}

list_at_work_names() {
    local at_root="$1" code_dir

    for code_dir in "$at_root"/*/code; do
        [[ -d "$code_dir" || -L "$code_dir" ]] || continue
        basename "$(dirname "$code_dir")"
    done | LC_ALL=C sort
}

show_at_work_names() {
    local work_names="$1" work_name

    [[ -n "$work_names" ]] || return 0
    echo "Existing AT work entries:" >&2
    while IFS= read -r work_name; do
        [[ -n "$work_name" ]] || continue
        printf '  %s\n' "$work_name" >&2
    done <<< "$work_names"
}

prompt_at_project_dir() {
    local default_project="$1" answer
    read -r -p "Project checkout [$default_project]: " answer
    printf '%s\n' "${answer:-$default_project}"
}

prompt_at_source_ref() {
    local default_ref="$1" answer
    read -r -p "Create work from branch/ref or AT work [$default_ref]: " answer
    printf '%s\n' "${answer:-$default_ref}"
}

relative_path_between() {
    local relative_path

    if command -v realpath >/dev/null 2>&1 \
        && relative_path="$(realpath --relative-to="$2" "$1" 2>/dev/null)"; then
        printf '%s\n' "$relative_path"
        return 0
    fi

    python3 - "$1" "$2" <<'PY'
import os
import sys

target, start = sys.argv[1], sys.argv[2]
print(os.path.relpath(os.path.realpath(target), os.path.realpath(start)))
PY
}

ensure_at_project_symlink() {
    local project_dir="$1" link target
    [[ -n "${AR_WORKSPACE_ROOT:-}" ]] || return 0
    mkdir -p "$AR_WORKSPACE_ROOT"
    link="$AR_WORKSPACE_ROOT/project"
    if [[ -e "$link" || -L "$link" ]]; then
        return 0
    fi
    target="$(relative_path_between "$project_dir" "$AR_WORKSPACE_ROOT")"
    ln -s "$target" "$link"
}

current_branch_for_dir() {
    git -C "$1" branch --show-current 2>/dev/null || true
}

resolve_named_at_work() {
    local at_root work_name work_dir code_dir project_dir default_project source_ref default_ref
    local existing_work_names default_work_name
    local -a ensure_args

    [[ -n "$AT_WORKSPACE_DIR_ARG" ]] || return 0

    at_root="$(expand_path "$AT_WORKSPACE_DIR_ARG")"
    if ! at_root="$(resolve_realpath "$at_root" 2>/dev/null)"; then
        mkdir -p "$at_root"
        at_root="$(resolve_realpath "$at_root")"
    fi
    AR_WORKSPACE_ROOT="$at_root"
    export AR_WORKSPACE_ROOT

    work_name="$AT_WORK_NAME_ARG"
    if [[ -z "$work_name" ]]; then
        existing_work_names="$(list_at_work_names "$at_root")"
        show_at_work_names "$existing_work_names"
        if ! launch_is_interactive; then
            echo "Error: AT workspace launch requires a work name."
            echo "Example: agentic-team $at_root research-main"
            exit 1
        fi
        default_work_name="$(printf '%s\n' "$existing_work_names" | sed -n '1p')"
        default_work_name="${default_work_name:-research-main}"
        work_name="$(prompt_at_work_name "$default_work_name")"
    fi
    work_name="$(slugify_workspace_name "$work_name")"
    work_dir="$at_root/$work_name"
    code_dir="$work_dir/code"

    if [[ -e "$code_dir" || -L "$code_dir" ]]; then
        WORKSPACE_DIR="$code_dir"
        return 0
    fi

    project_dir="$AT_PROJECT_DIR_ARG"
    if [[ -z "$project_dir" && ( -e "$at_root/project" || -L "$at_root/project" ) ]]; then
        project_dir="$at_root/project"
    fi
    if [[ -z "$project_dir" ]]; then
        if ! launch_is_interactive; then
            echo "Error: $code_dir does not exist and no project checkout is linked."
            echo "Create it with:"
            echo "  agentic-team $at_root $work_name --from BRANCH --project-dir PROJECT_DIR"
            exit 1
        fi
        default_project="$(default_project_for_at_root "$at_root")"
        project_dir="$(prompt_at_project_dir "$default_project")"
    fi

    source_ref="$AT_FROM_REF"
    if [[ -z "$source_ref" ]]; then
        if ! launch_is_interactive; then
            echo "Error: $code_dir does not exist; pass --from REF_OR_WORK to create it."
            exit 1
        fi
        default_ref="$(current_branch_for_dir "$project_dir")"
        default_ref="${default_ref:-HEAD}"
        source_ref="$(prompt_at_source_ref "$default_ref")"
    fi

    ensure_args=(
        "$SCRIPT_DIR/scripts/bin/agentic-workspace"
        ensure-work
        "$work_name"
        --workspace-root "$at_root"
        --from "$source_ref"
        --project-dir "$project_dir"
        --state "$AT_STATE_MODE"
        --capabilities "$AR_CAPABILITIES"
    )
    if [[ -n "$AT_NEW_BRANCH_ARG" ]]; then
        ensure_args+=(--branch "$AT_NEW_BRANCH_ARG")
    fi
    "${ensure_args[@]}"

    WORKSPACE_DIR="$code_dir"
}

prompt_menu_choice() {
    local max="$1" default="$2" answer
    while true; do
        read -r -p "Choice [$default]: " answer
        answer="${answer:-$default}"
        if [[ "$answer" =~ ^[0-9]+$ ]] && (( answer >= 1 && answer <= max )); then
            printf '%s\n' "$answer"
            return 0
        fi
        echo "Enter a number from 1 to $max."
    done
}

prompt_work_branch_name() {
    local default_branch="$1" branch
    read -r -p "Work branch name [$default_branch]: " branch
    branch="${branch:-$default_branch}"
    printf '%s\n' "$branch"
}

prompt_worktree_path() {
    local default_path="$1" path
    read -r -p "Worktree path [$default_path]: " path
    printf '%s\n' "${path:-$default_path}"
}

set_work_branch_vars() {
    local owner_branch="$1" current_branch="$2"
    WORKSPACE_GIT_BRANCH="$current_branch"
    AR_WORK_BRANCH="$owner_branch"
    AR_WORK_BRANCH_ID="$(work_branch_id "$owner_branch")"
    AR_WORK_NAME="$(work_name_from_branch "$owner_branch")"
    AR_WORK_BRANCH_PREFIX="$owner_branch"
    set_agentic_workspace_root
    AR_PROJECT_STATE_DIR="$(project_state_dir_path)"
    AR_WORK_STATE_DIR="$(work_state_dir_path_for_branch "$owner_branch")"
    export WORKSPACE_GIT_BRANCH AR_WORK_BRANCH AR_WORK_BRANCH_ID AR_WORK_NAME AR_WORK_BRANCH_PREFIX
    export AR_PROJECT_STATE_DIR AR_WORK_STATE_DIR
}

switch_to_work_branch() {
    local target="$1" base_ref="${2:-HEAD}" existed=false
    if ! valid_git_branch_name "$target"; then
        echo "Error: Invalid Git branch name: $target"
        return 1
    fi
    if branch_guard_is_occupied "$target"; then
        echo "Error: Branch '$target' appears to have another active local agent session."
        branch_guard_summary "$(branch_guard_first_active_file "$target")"
        return 1
    fi
    if git_branch_exists "$target"; then
        existed=true
        git -C "$WORKSPACE_DIR" switch "$target"
    else
        git -C "$WORKSPACE_DIR" switch -c "$target" "$base_ref"
    fi
    if [[ "$existed" != "true" ]]; then
        record_work_branch_base "$target" "$base_ref"
    fi
}

create_worktree() {
    local target_branch="$1" base_ref="$2" target_dir="$3" base_commit
    if ! valid_git_branch_name "$target_branch"; then
        echo "Error: Invalid Git branch name: $target_branch"
        return 1
    fi
    if branch_guard_is_occupied "$target_branch"; then
        echo "Error: Branch '$target_branch' appears to have another active local agent session."
        branch_guard_summary "$(branch_guard_first_active_file "$target_branch")"
        return 1
    fi
    if [[ -e "$target_dir" ]]; then
        echo "Error: Worktree path already exists: $target_dir"
        return 1
    fi
    mkdir -p "$(dirname "$target_dir")"
    if git_branch_exists "$target_branch"; then
        if [[ "$(current_workspace_git_branch)" == "$target_branch" ]]; then
            ln -s "$WORKSPACE_DIR" "$target_dir"
            echo "Using existing checkout via symlink: $target_dir -> $WORKSPACE_DIR"
        else
            git -C "$WORKSPACE_DIR" worktree add "$target_dir" "$target_branch"
        fi
    else
        git -C "$WORKSPACE_DIR" worktree add -b "$target_branch" "$target_dir" "$base_ref"
        git -C "$target_dir" config "branch.$target_branch.agentic-base" "$base_ref" || true
        if base_commit="$(git -C "$target_dir" rev-parse "$base_ref^{commit}" 2>/dev/null)"; then
            git -C "$target_dir" config "branch.$target_branch.agentic-base-commit" "$base_commit" || true
        fi
    fi
    WORKSPACE_DIR="$(resolve_realpath "$target_dir")"
}

print_branch_decision_context() {
    local branch="$1" occupied="$2" dirty="$3" base_ref="$4" active_guard="${5:-}"
    echo "Branch:          $branch"
    echo "Another agent:   $occupied"
    echo "Uncommitted:     $dirty"
    echo "Base for branch: $base_ref"
    if [[ -n "$active_guard" ]]; then
        echo ""
        echo "Active local agent:"
        branch_guard_summary "$active_guard"
    fi
    echo ""
}

prepare_work_branch_interactive() {
    local branch="$1" owner_branch="$2" occupied="$3" dirty="$4" active_guard="$5"
    local base_ref candidate choice target_branch target_path max_choice default_choice

    base_ref="$(infer_work_branch_base_ref "$owner_branch" "$branch")"
    candidate="$(unused_work_branch_candidate)"

    echo "Agentic Team main agents require their own work branch."
    print_branch_decision_context "$branch" "$occupied" "$dirty" "$base_ref" "$active_guard"

    if [[ "$occupied" == "yes" ]]; then
        echo "Choose how to continue:"
        echo "  1. Create a new worktree with a new work branch from $base_ref (recommended)"
        echo "  2. Cancel"
        max_choice=2
        default_choice=1
    elif [[ "$dirty" == "yes" ]]; then
        echo "Choose how to continue:"
        echo "  1. Create a new clean AT worktree with a work branch from $base_ref (recommended)"
        echo "  2. Create a work branch in this worktree, carrying current changes"
        echo "  3. Cancel"
        max_choice=3
        default_choice=1
    else
        echo "Choose how to continue:"
        echo "  1. Create a new AT worktree with a work branch from $base_ref (recommended)"
        echo "  2. Create a work branch in this worktree: $candidate"
        echo "  3. Cancel"
        max_choice=3
        default_choice=1
    fi

    choice="$(prompt_menu_choice "$max_choice" "$default_choice")"
    case "$choice" in
        1)
            AR_WORKSPACE_ROOT="$(prompt_at_workspace_root "$(agentic_workspace_root)")"
            export AR_WORKSPACE_ROOT
            ensure_at_project_symlink "$WORKSPACE_DIR"
            base_ref="$(prompt_at_source_ref "$base_ref")"
            target_branch="$(prompt_work_branch_name "$candidate")"
            target_path="$(code_worktree_path_for_branch "$target_branch")"
            create_worktree "$target_branch" "$base_ref" "$target_path" || exit 1
            return 0
            ;;
        2)
            if [[ "$occupied" == "yes" ]]; then
                echo "Launch cancelled."
                exit 1
            fi
            target_branch="$(prompt_work_branch_name "$candidate")"
            switch_to_work_branch "$target_branch" "HEAD" || exit 1
            return 0
            ;;
        3)
            echo "Launch cancelled."
            exit 1
            ;;
    esac
}

prepare_at_work_entry_interactive() {
    local branch="$1" owner_branch="$2" occupied="$3" dirty="$4" active_guard="$5"
    local base_ref candidate target_branch target_path

    base_ref="$(infer_work_branch_base_ref "$owner_branch" "$branch")"
    candidate="$(unused_work_branch_candidate)"

    echo "Agentic Team should run in an AT work entry."
    print_branch_decision_context "$branch" "$occupied" "$dirty" "$base_ref" "$active_guard"

    AR_WORKSPACE_ROOT="$(prompt_at_workspace_root "$(agentic_workspace_root)")"
    export AR_WORKSPACE_ROOT
    ensure_at_project_symlink "$WORKSPACE_DIR"
    base_ref="$(prompt_at_source_ref "$base_ref")"
    target_branch="$(prompt_work_branch_name "$candidate")"
    target_path="$(code_worktree_path_for_branch "$target_branch")"
    create_worktree "$target_branch" "$base_ref" "$target_path" || exit 1
}

require_main_agent_selection() {
    if [[ -z "${AR_MAIN_AGENT:-}" ]]; then
        echo "Error: No main agent selected."
        echo "Run 'agentic-team --setup AR_MAIN_AGENT=NAME' or pass '--main-agent NAME'."
        exit 1
    fi
}

resolve_main_agent_metadata() {
    local main_agent="$AR_MAIN_AGENT" kind legacy_ownership

    if ! valid_agent_name "$main_agent"; then
        echo "Error: Invalid AR_MAIN_AGENT: $main_agent"
        exit 1
    fi

    if ! MAIN_AGENT_SOURCE_PATH="$(find_agent_source_by_name "$main_agent")"; then
        echo "Error: Main agent definition not found: $main_agent"
        echo "Add an agents/$main_agent.md definition with 'kind: main' inside a project, org, or built-in capability."
        exit 1
    fi
    MAIN_AGENT_CAPABILITY="$(capability_name_for_source "$MAIN_AGENT_SOURCE_PATH" || true)"

    kind="$(agent_kind_for_source "$MAIN_AGENT_SOURCE_PATH")"
    if [[ "$kind" != "main" ]]; then
        echo "Error: AR_MAIN_AGENT '$main_agent' resolves to kind '$kind', not kind 'main'."
        exit 1
    fi

    legacy_ownership="$(frontmatter_value "$MAIN_AGENT_SOURCE_PATH" "branch_ownership")"
    if [[ -n "$legacy_ownership" ]]; then
        echo "Error: Main agent '$main_agent' uses branch_ownership, which has been removed."
        echo "All main agents require their own branches. Remove branch_ownership from the agent definition."
        exit 1
    fi
}

ensure_branch_session_id() {
    AR_SESSION_ID="${AR_SESSION_ID:-${AR_WORK_BRANCH_ID:-branch}-$$-$(date +%s)}"
    export AR_SESSION_ID
}

write_branch_guard_file() {
    local now
    [[ -n "${BRANCH_GUARD_FILE:-}" ]] || return 0
    now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    mkdir -p "$(dirname "$BRANCH_GUARD_FILE")"
    {
        printf 'branch=%s\n' "$AR_WORK_BRANCH"
        printf 'current_branch=%s\n' "$WORKSPACE_GIT_BRANCH"
        printf 'session_id=%s\n' "$AR_SESSION_ID"
        printf 'main_agent=%s\n' "$AR_MAIN_AGENT"
        printf 'user_id=%s\n' "${AR_USER_ID:-${USER:-user}}"
        printf 'host=%s\n' "$(hostname 2>/dev/null || printf unknown)"
        printf 'pid=%s\n' "$$"
        printf 'workspace=%s\n' "$WORKSPACE_DIR"
        printf 'started_at=%s\n' "${BRANCH_GUARD_STARTED_AT:-$now}"
        printf 'heartbeat_at=%s\n' "$now"
    } > "$BRANCH_GUARD_FILE.tmp"
    mv "$BRANCH_GUARD_FILE.tmp" "$BRANCH_GUARD_FILE"
}

register_branch_guard() {
    local guard_dir heartbeat_seconds launcher_pid
    [[ "$TEST_MODE" == "true" || "$RENDER_ONLY" == "true" ]] && return 0
    ensure_branch_session_id
    guard_dir="$(branch_guard_dir_for "$AR_WORK_BRANCH")"
    BRANCH_GUARD_FILE="$guard_dir/$AR_SESSION_ID.guard"
    BRANCH_GUARD_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    write_branch_guard_file

    heartbeat_seconds="${AR_BRANCH_GUARD_HEARTBEAT_SECONDS:-30}"
    if ! [[ "$heartbeat_seconds" =~ ^[0-9]+$ ]] || [[ "$heartbeat_seconds" -lt 1 ]]; then
        heartbeat_seconds=30
    fi
    launcher_pid="$$"
    (
        while kill -0 "$launcher_pid" 2>/dev/null; do
            write_branch_guard_file
            sleep "$heartbeat_seconds"
        done
    ) >/dev/null 2>&1 &
    BRANCH_GUARD_HEARTBEAT_PID="$!"
}

cleanup_branch_guard() {
    if [[ -n "${BRANCH_GUARD_HEARTBEAT_PID:-}" ]]; then
        kill "$BRANCH_GUARD_HEARTBEAT_PID" >/dev/null 2>&1 || true
        wait "$BRANCH_GUARD_HEARTBEAT_PID" >/dev/null 2>&1 || true
        BRANCH_GUARD_HEARTBEAT_PID=""
    fi
    if [[ -n "${BRANCH_GUARD_FILE:-}" ]]; then
        rm -f "$BRANCH_GUARD_FILE"
        BRANCH_GUARD_FILE=""
    fi
}

prepare_work_branch() {
    local branch owner_branch active_guard candidate base_ref occupied dirty

    [[ "$TEST_MODE" == "true" ]] && return 0

    if ! workspace_is_git_worktree; then
        [[ "$RENDER_ONLY" == "true" ]] && return 0
        echo "Error: Agentic Team main agents require launching from a Git worktree."
        echo ""
        echo "Create or enter a project Git checkout, then relaunch."
        exit 1
    fi

    branch="$(current_workspace_git_branch)"
    if [[ -z "$branch" ]]; then
        [[ "$RENDER_ONLY" == "true" ]] && return 0
        echo "Error: Agentic Team main agents require a named Git branch, but this worktree is detached."
        exit 1
    fi

    if [[ -n "${AR_WORK_BRANCH:-}" ]]; then
        if [[ "$RENDER_ONLY" != "true" && "$branch" != "$AR_WORK_BRANCH" ]]; then
            switch_to_work_branch "$AR_WORK_BRANCH" || exit 1
            branch="$(current_workspace_git_branch)"
        elif [[ "$RENDER_ONLY" == "true" ]]; then
            branch="$AR_WORK_BRANCH"
        fi
    fi

    owner_branch="$(work_branch_from_branch "$branch")"
    set_work_branch_vars "$owner_branch" "$branch"

    [[ "$RENDER_ONLY" == "true" ]] && return 0

    active_guard=""
    if active_guard="$(branch_guard_first_active_file "$AR_WORK_BRANCH")"; then
        occupied="yes"
    else
        occupied="no"
    fi
    if workspace_has_uncommitted_changes; then
        dirty="yes"
    else
        dirty="no"
    fi

    if [[ -z "$WORKTREE_PATH_ARG" ]] && ! workspace_input_is_at_code_path; then
        candidate="$(unused_work_branch_candidate)"
        base_ref="$(infer_work_branch_base_ref "$AR_WORK_BRANCH" "$branch")"
        if ! launch_is_interactive; then
            echo "Error: Agentic Team must launch from an AT work entry."
            echo "Current branch: $branch"
            echo "Another active agent: $occupied"
            echo "Uncommitted changes: $dirty"
            if [[ -n "$active_guard" ]]; then
                echo ""
                echo "Another active local agent appears to be using branch '$AR_WORK_BRANCH':"
                branch_guard_summary "$active_guard"
            fi
            echo ""
            echo "Create or launch an AT work entry:"
            echo "  agentic-team $(agentic_workspace_root) $(work_name_from_branch "$candidate") --from $base_ref --project-dir $WORKSPACE_DIR --branch $candidate"
            if [[ "$dirty" == "yes" ]]; then
                echo ""
                echo "Note: uncommitted changes in the current checkout stay where they are."
            fi
            echo ""
            echo "Or launch an existing code worktree explicitly:"
            echo "  agentic-team --worktree-path PATH"
            exit 1
        fi

        prepare_at_work_entry_interactive "$branch" "$AR_WORK_BRANCH" "$occupied" "$dirty" "$active_guard"
        branch="$(current_workspace_git_branch)"
        owner_branch="$(work_branch_from_branch "$branch")"
        set_work_branch_vars "$owner_branch" "$branch"
        if branch_guard_is_occupied "$AR_WORK_BRANCH"; then
            echo "Error: Branch '$AR_WORK_BRANCH' appears to have another active local agent session."
            branch_guard_summary "$(branch_guard_first_active_file "$AR_WORK_BRANCH")"
            exit 1
        fi
        register_branch_guard
        return 0
    fi

    if ! protected_work_branch "$branch" && ! branch_guard_is_occupied "$AR_WORK_BRANCH"; then
        register_branch_guard
        return 0
    fi

    if ! launch_is_interactive; then
        echo "Error: Main agent '$AR_MAIN_AGENT' cannot use this AT work entry as-is."
        echo "Current branch: $branch"
        echo "Another active agent: $occupied"
        echo "Uncommitted changes: $dirty"
        if [[ -n "$active_guard" ]]; then
            echo ""
            echo "Another active local agent appears to be using branch '$AR_WORK_BRANCH':"
            branch_guard_summary "$active_guard"
        fi
        candidate="$(unused_work_branch_candidate)"
        base_ref="$(infer_work_branch_base_ref "$AR_WORK_BRANCH" "$branch")"
        echo ""
        if [[ "$occupied" == "yes" ]]; then
            echo "Create a new AT work entry with an unused work branch:"
            echo "  agentic-team $(agentic_workspace_root) $(work_name_from_branch "$candidate") --from $base_ref --project-dir $WORKSPACE_DIR --branch $candidate"
        else
            echo "Create a new AT work entry for the branch:"
            echo "  agentic-team $(agentic_workspace_root) $(work_name_from_branch "$candidate") --from $base_ref --project-dir $WORKSPACE_DIR --branch $candidate"
        fi
        if [[ "$dirty" == "yes" && "$occupied" == "yes" ]]; then
            echo ""
            echo "Note: uncommitted changes in the current worktree stay where they are."
        fi
        exit 1
    fi

    prepare_work_branch_interactive "$branch" "$AR_WORK_BRANCH" "$occupied" "$dirty" "$active_guard"
    branch="$(current_workspace_git_branch)"
    owner_branch="$(work_branch_from_branch "$branch")"
    set_work_branch_vars "$owner_branch" "$branch"

    if branch_guard_is_occupied "$AR_WORK_BRANCH"; then
        echo "Error: Branch '$AR_WORK_BRANCH' appears to have another active local agent session."
        branch_guard_summary "$(branch_guard_first_active_file "$AR_WORK_BRANCH")"
        exit 1
    fi

    register_branch_guard
    return 0
}
