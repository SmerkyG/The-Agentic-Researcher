# Sourced by agentic-team. Project/worktree validation and branch ownership guard logic.

validate_workspace() {
    # Default to current directory
    if [[ -z "$WORKSPACE_DIR" ]]; then
        WORKSPACE_DIR="$(pwd)"
    fi

    # Resolve symlinks in a macOS/Linux portable way.
    local original_workspace resolved_workspace
    original_workspace="$WORKSPACE_DIR"
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

slugify_project_id() {
    local text="$1" slug
    slug="$(printf '%s' "$text" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
    slug="${slug:0:72}"
    slug="${slug%-}"
    printf '%s\n' "${slug:-project}"
}

project_remote_name() {
    local value="$1" repo
    value="${value%%#*}"
    value="${value%/}"

    if [[ "$value" =~ ^[A-Za-z][A-Za-z0-9+.-]*://[^/]+/(.+)$ ]]; then
        value="${BASH_REMATCH[1]}"
    elif [[ "$value" == file://* ]]; then
        value="${value#file://}"
    elif [[ "$value" =~ ^([^@/:]+@)?([^/:]+):(.+)$ ]]; then
        value="${BASH_REMATCH[3]}"
    fi

    value="${value%/}"
    value="${value%.git}"
    repo="${value##*/}"
    printf '%s\n' "${repo:-project}"
}

infer_project_id_from_remote() {
    local remote repo_name
    remote="$(git -C "$WORKSPACE_DIR" remote get-url origin 2>/dev/null || true)"
    [[ -n "$remote" ]] || return 1
    repo_name="$(project_remote_name "$remote")"
    slugify_project_id "$repo_name"
}

validate_project_id() {
    local inferred
    if [[ -n "${AR_PROJECT_ID:-}" ]]; then
        AR_PROJECT_ID="$(slugify_project_id "$AR_PROJECT_ID")"
        export AR_PROJECT_ID
        return
    fi

    if inferred="$(infer_project_id_from_remote)" && [[ -n "$inferred" ]]; then
        AR_PROJECT_ID="$inferred"
        export AR_PROJECT_ID
        return
    fi

    echo "Error: Agentic Team could not infer a project id because this project has no git remote."
    echo ""
    echo "Add a git remote or provide an explicit id:"
    echo "  agentic-team --project-id my-project-2026 $WORKSPACE_DIR"
    echo ""
    echo "Use the same id for all worktrees and agents that should share notes and experiment logs."
    exit 1
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
    slugify_project_id "$1"
}

git_branch_exists() {
    git -C "$WORKSPACE_DIR" show-ref --verify --quiet "refs/heads/$1"
}

valid_git_branch_name() {
    git -C "$WORKSPACE_DIR" check-ref-format --branch "$1" >/dev/null 2>&1
}

branch_guard_dir_for() {
    local branch="$1"
    printf '%s/branch-guards/%s/%s\n' "$STATE_ROOT" "$AR_PROJECT_ID" "$(slugify_project_id "$branch")"
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
    base="work/$(slugify_project_id "${AR_USER_ID:-${USER:-agent}}")"
    candidate="$base"
    n=2
    while git_branch_exists "$candidate" || branch_guard_is_occupied "$candidate"; do
        candidate="$base-$n"
        n=$((n + 1))
    done
    printf '%s\n' "$candidate"
}

default_worktree_path() {
    local branch="$1" parent base slug candidate n
    parent="$(dirname "$WORKSPACE_DIR")"
    base="$(basename "$WORKSPACE_DIR")"
    slug="$(slugify_project_id "$branch")"
    candidate="$parent/$base-$slug"
    n=2
    while [[ -e "$candidate" ]]; do
        candidate="$parent/$base-$slug-$n"
        n=$((n + 1))
    done
    printf '%s\n' "$candidate"
}

launch_is_interactive() {
    [[ -t 0 && -t 1 ]]
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
    AR_WORK_BRANCH_PREFIX="$owner_branch"
    export WORKSPACE_GIT_BRANCH AR_WORK_BRANCH AR_WORK_BRANCH_ID AR_WORK_BRANCH_PREFIX
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
    if git_branch_exists "$target_branch"; then
        git -C "$WORKSPACE_DIR" worktree add "$target_dir" "$target_branch"
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
    echo "Ownership:       $AR_BRANCH_OWNERSHIP"
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

    echo "Exclusive main agent '$AR_MAIN_AGENT' should normally use its own work branch."
    print_branch_decision_context "$branch" "$occupied" "$dirty" "$base_ref" "$active_guard"

    if [[ "$occupied" == "yes" ]]; then
        echo "Choose how to continue:"
        echo "  1. Create a new worktree with a new work branch from $base_ref (recommended)"
        echo "  2. Use the current branch anyway and allow shared-branch work"
        echo "  3. Cancel"
        max_choice=3
        default_choice=1
    elif [[ "$dirty" == "yes" ]]; then
        echo "Choose how to continue:"
        echo "  1. Create a work branch in this worktree, carrying current changes (recommended)"
        echo "  2. Create a new clean worktree with a work branch from $base_ref"
        echo "  3. Use the current branch anyway"
        echo "  4. Cancel"
        max_choice=4
        default_choice=1
    else
        echo "Choose how to continue:"
        echo "  1. Create a work branch in this worktree: $candidate (recommended)"
        echo "  2. Create a new worktree with a work branch from $base_ref"
        echo "  3. Use the current branch anyway"
        echo "  4. Cancel"
        max_choice=4
        default_choice=1
    fi

    choice="$(prompt_menu_choice "$max_choice" "$default_choice")"
    case "$choice" in
        1)
            target_branch="$(prompt_work_branch_name "$candidate")"
            if [[ "$occupied" == "yes" ]]; then
                target_path="$(prompt_worktree_path "$(default_worktree_path "$target_branch")")"
                create_worktree "$target_branch" "$base_ref" "$target_path" || exit 1
            else
                switch_to_work_branch "$target_branch" "HEAD" || exit 1
            fi
            return 0
            ;;
        2)
            if [[ "$occupied" == "yes" ]]; then
                BRANCH_GUARD_OVERRIDE=true
                return 0
            fi
            target_branch="$(prompt_work_branch_name "$candidate")"
            target_path="$(prompt_worktree_path "$(default_worktree_path "$target_branch")")"
            create_worktree "$target_branch" "$base_ref" "$target_path" || exit 1
            return 0
            ;;
        3)
            if [[ "$occupied" == "yes" ]]; then
                echo "Launch cancelled."
                exit 1
            fi
            BRANCH_GUARD_OVERRIDE=true
            return 0
            ;;
        *)
            echo "Launch cancelled."
            exit 1
            ;;
    esac
}

resolve_main_agent_metadata() {
    local main_agent="${AR_MAIN_AGENT:-research-coordinator}" kind ownership

    if ! valid_agent_name "$main_agent"; then
        echo "Error: Invalid AR_MAIN_AGENT: $main_agent"
        exit 1
    fi

    if ! MAIN_AGENT_SOURCE_PATH="$(find_agent_source_by_name "$main_agent")"; then
        echo "Error: Main agent definition not found: $main_agent"
        echo "Add agents/$main_agent.md with frontmatter 'kind: main' to Agentic Team or the org repo."
        exit 1
    fi

    kind="$(agent_kind_for_source "$MAIN_AGENT_SOURCE_PATH")"
    if [[ "$kind" != "main" ]]; then
        echo "Error: AR_MAIN_AGENT '$main_agent' resolves to kind '$kind', not kind 'main'."
        exit 1
    fi

    ownership="$(frontmatter_value "$MAIN_AGENT_SOURCE_PATH" "branch_ownership")"
    ownership="${ownership:-exclusive}"
    case "$ownership" in
        exclusive|shared|readonly)
            ;;
        *)
            echo "Error: Main agent '$main_agent' has invalid branch_ownership '$ownership'."
            echo "Allowed values: exclusive, shared, readonly"
            exit 1
            ;;
    esac
    AR_BRANCH_OWNERSHIP="$ownership"
    export AR_BRANCH_OWNERSHIP
}

ensure_branch_session_id() {
    AR_SESSION_ID="${AR_SESSION_ID:-$AR_PROJECT_ID-${AR_WORK_BRANCH_ID:-branch}-$$-$(date +%s)}"
    export AR_SESSION_ID
}

write_branch_guard_file() {
    local now
    [[ -n "${BRANCH_GUARD_FILE:-}" ]] || return 0
    now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    mkdir -p "$(dirname "$BRANCH_GUARD_FILE")"
    {
        printf 'project_id=%s\n' "$AR_PROJECT_ID"
        printf 'branch=%s\n' "$AR_WORK_BRANCH"
        printf 'current_branch=%s\n' "$WORKSPACE_GIT_BRANCH"
        printf 'branch_ownership=%s\n' "$AR_BRANCH_OWNERSHIP"
        printf 'override=%s\n' "$BRANCH_GUARD_OVERRIDE"
        printf 'session_id=%s\n' "$AR_SESSION_ID"
        printf 'main_agent=%s\n' "${AR_MAIN_AGENT:-research-coordinator}"
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
    [[ "$AR_BRANCH_OWNERSHIP" == "exclusive" ]] || return 0
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
    local branch owner_branch active_guard candidate base_ref target_path occupied dirty

    [[ "$TEST_MODE" == "true" ]] && return 0

    if ! workspace_is_git_worktree; then
        [[ "$RENDER_ONLY" == "true" || "$AR_BRANCH_OWNERSHIP" == "readonly" ]] && return 0
        echo "Error: Agentic Team branch ownership requires launching from a Git worktree."
        echo ""
        echo "Create or enter a project Git checkout, then relaunch."
        exit 1
    fi

    branch="$(current_workspace_git_branch)"
    if [[ -z "$branch" ]]; then
        [[ "$RENDER_ONLY" == "true" || "$AR_BRANCH_OWNERSHIP" == "readonly" ]] && return 0
        echo "Error: Agentic Team branch ownership requires a named Git branch, but this worktree is detached."
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

    case "$AR_BRANCH_OWNERSHIP" in
        readonly|shared)
            return 0
            ;;
    esac

    if ! protected_work_branch "$branch" && ! branch_guard_is_occupied "$AR_WORK_BRANCH"; then
        register_branch_guard
        return 0
    fi

    if [[ "$ALLOW_SHARED_BRANCH" == "true" ]]; then
        BRANCH_GUARD_OVERRIDE=true
        register_branch_guard
        return 0
    fi

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

    if ! launch_is_interactive; then
        echo "Error: Exclusive main agent '$AR_MAIN_AGENT' is not on an unoccupied work branch."
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
        target_path="$(default_worktree_path "$candidate")"
        echo ""
        if [[ "$occupied" == "yes" ]]; then
            echo "Create a new worktree with an unused work branch:"
            echo "  git worktree add -b $candidate $target_path $base_ref"
            echo "  agentic-team $target_path"
        else
            echo "Create or switch to an unused work branch first:"
            echo "  git switch -c $candidate"
            echo "  agentic-team $WORKSPACE_DIR"
        fi
        if [[ "$dirty" == "yes" && "$occupied" == "yes" ]]; then
            echo ""
            echo "Note: uncommitted changes in the current worktree stay where they are."
        fi
        echo ""
        echo "Or choose an explicit branch before launch:"
        echo "  agentic-team --work-branch $candidate $WORKSPACE_DIR"
        echo ""
        echo "Or continue intentionally with shared-branch work:"
        echo "  agentic-team --allow-shared-branch $WORKSPACE_DIR"
        exit 1
    fi

    prepare_work_branch_interactive "$branch" "$AR_WORK_BRANCH" "$occupied" "$dirty" "$active_guard"
    branch="$(current_workspace_git_branch)"
    owner_branch="$(work_branch_from_branch "$branch")"
    set_work_branch_vars "$owner_branch" "$branch"

    if [[ "$BRANCH_GUARD_OVERRIDE" == "true" ]]; then
        register_branch_guard
        return 0
    fi

    if branch_guard_is_occupied "$AR_WORK_BRANCH"; then
        echo "Error: Branch '$AR_WORK_BRANCH' appears to have another active local agent session."
        branch_guard_summary "$(branch_guard_first_active_file "$AR_WORK_BRANCH")"
        exit 1
    fi

    register_branch_guard
    return 0
}
