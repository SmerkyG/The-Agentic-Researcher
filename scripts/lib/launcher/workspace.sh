# Sourced by agentic-team. Repository-v2 discovery, validation, and branch guards.

validate_workspace() {
    local original_workspace resolved_workspace
    [[ -n "$WORKSPACE_DIR" ]] || WORKSPACE_DIR="$(pwd)"
    original_workspace="$WORKSPACE_DIR"
    WORKSPACE_INPUT_DIR="$original_workspace"
    export WORKSPACE_INPUT_DIR
    if ! resolved_workspace="$(resolve_realpath "$WORKSPACE_DIR")"; then
        echo "Error: Cannot resolve path: $original_workspace" >&2
        exit 1
    fi
    WORKSPACE_DIR="$resolved_workspace"
    [[ -d "$WORKSPACE_DIR" ]] || { echo "Error: Directory does not exist: $WORKSPACE_DIR" >&2; exit 1; }

    case "$WORKSPACE_DIR" in
        /|/etc/*|/etc|/root/*|/root|/sys/*|/sys|/proc/*|/proc|/dev/*|/dev|/boot/*|/boot)
            echo "Error: Cannot sandbox system directories: $WORKSPACE_DIR" >&2
            exit 1
            ;;
        /home/*/.ssh/*|/home/*/.ssh|/Users/*/.ssh/*|/Users/*/.ssh)
            echo "Error: Cannot sandbox SSH directories: $WORKSPACE_DIR" >&2
            exit 1
            ;;
        /home/*/.gnupg/*|/home/*/.gnupg|/Users/*/.gnupg/*|/Users/*/.gnupg)
            echo "Error: Cannot sandbox GPG directories: $WORKSPACE_DIR" >&2
            exit 1
            ;;
        /home/*/.aws/*|/home/*/.aws|/home/*/.kube/*|/home/*/.kube|/home/*/.config/gcloud/*|/home/*/.config/gcloud|/Users/*/.aws/*|/Users/*/.aws|/Users/*/.kube/*|/Users/*/.kube|/Users/*/.config/gcloud/*|/Users/*/.config/gcloud)
            echo "Error: Cannot sandbox cloud credential directories: $WORKSPACE_DIR" >&2
            exit 1
            ;;
    esac
}

validate_cli_workspace() {
    cli_call validate_workspace
}

slugify_workspace_name() {
    local text="$1" slug
    slug="$(printf '%s' "$text" | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
    slug="${slug:0:72}"
    printf '%s\n' "${slug%-}"
}

expand_path() {
    case "$1" in
        "~") printf '%s\n' "$HOME" ;;
        "~/"*) printf '%s/%s\n' "$HOME" "${1#~/}" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

path_is_at_repository_root() {
    [[ -f "$1/.agentic-team.json" && -d "$1/repo.git" ]]
}

find_at_repository_root() {
    local path
    path="$(expand_path "$1")"
    path="$(resolve_realpath "$path" 2>/dev/null || true)"
    [[ -n "$path" ]] || return 1
    [[ -f "$path" ]] && path="$(dirname "$path")"
    while [[ "$path" != "/" ]]; do
        if path_is_at_repository_root "$path"; then
            printf '%s\n' "$path"
            return 0
        fi
        path="$(dirname "$path")"
    done
    return 1
}

at_code_path_for_branch() {
    printf '%s/branches/%s/code\n' "$1" "$2"
}

at_records_path_for_branch() {
    printf '%s/branches/%s/records\n' "$1" "$2"
}

list_materialized_at_branches() {
    local root="$1" line branch
    git -C "$root/repo.git" worktree list --porcelain 2>/dev/null \
        | while IFS= read -r line; do
            [[ "$line" == "branch refs/heads/"* ]] || continue
            branch="${line#branch refs/heads/}"
            [[ "$branch" == "agentic/project-records" || "$branch" == agentic/branch-records/* ]] && continue
            printf '%s\n' "$branch"
        done | LC_ALL=C sort -u
}

show_materialized_at_branches() {
    local root="$1" branches branch
    branches="$(list_materialized_at_branches "$root")"
    if [[ -z "$branches" ]]; then
        echo "No paired branches have been checked out in $root." >&2
        return
    fi
    echo "Available Agentic Team branches:" >&2
    while IFS= read -r branch; do
        [[ -n "$branch" ]] && printf '  %s\n' "$branch" >&2
    done <<< "$branches"
}

resolve_launch_positionals() {
    local count first root branch input resolved_input
    count="${#POSITIONAL_ARGS[@]}"
    root="$TOP_LEVEL_RUN_ROOT"

    if [[ -n "$root" ]]; then
        if ! root="$(find_at_repository_root "$root")"; then
            echo "Error: Not an Agentic Team repository: $TOP_LEVEL_RUN_ROOT" >&2
            exit 1
        fi
        if (( count > 0 )); then
            branch="${POSITIONAL_ARGS[0]}"
            (( count > 1 )) && CLI_ARGS+=("${POSITIONAL_ARGS[@]:1}")
        fi
    elif (( count > 0 )); then
        first="$(expand_path "${POSITIONAL_ARGS[0]}")"
        if [[ -d "$first" ]] && root="$(find_at_repository_root "$first" 2>/dev/null)"; then
            resolved_input="$(resolve_realpath "$first")"
            if path_is_at_repository_root "$resolved_input"; then
                (( count > 1 )) && branch="${POSITIONAL_ARGS[1]}"
                (( count > 2 )) && CLI_ARGS+=("${POSITIONAL_ARGS[@]:2}")
            else
                input="$resolved_input"
                (( count > 1 )) && CLI_ARGS+=("${POSITIONAL_ARGS[@]:1}")
            fi
        else
            if ! root="$(find_at_repository_root "$(pwd)" 2>/dev/null)"; then
                echo "Error: Run from an Agentic Team repository or pass '-C AT_DIR'." >&2
                exit 1
            fi
            branch="${POSITIONAL_ARGS[0]}"
            (( count > 1 )) && CLI_ARGS+=("${POSITIONAL_ARGS[@]:1}")
        fi
    else
        if ! root="$(find_at_repository_root "$(pwd)" 2>/dev/null)"; then
            echo "Error: Run from an Agentic Team repository or pass '-C AT_DIR'." >&2
            exit 1
        fi
        input="$(resolve_realpath "$(pwd)")"
    fi

    if [[ -n "$input" ]] && ! path_is_at_repository_root "$input"; then
        WORKSPACE_DIR="$input"
        branch="$(git -C "$WORKSPACE_DIR" branch --show-current 2>/dev/null || true)"
    fi
    if [[ -z "$branch" ]]; then
        show_materialized_at_branches "$root"
        echo "Run with: agentic-team -C $root run BRANCH [OPTIONS]" >&2
        exit 1
    fi
    if ! git -C "$root/repo.git" check-ref-format --branch "$branch" >/dev/null 2>&1; then
        echo "Error: Invalid branch name: $branch" >&2
        exit 1
    fi
    WORKSPACE_DIR="${WORKSPACE_DIR:-$(at_code_path_for_branch "$root" "$branch")}"
    if [[ ! -d "$WORKSPACE_DIR" ]]; then
        echo "Error: Branch '$branch' has no paired checkout at $WORKSPACE_DIR" >&2
        echo "Create it with: agentic-team -C $root checkout $branch" >&2
        exit 1
    fi
    AT_WORKSPACE_DIR_ARG="$root"
    AT_BRANCH_ARG="$branch"
    AR_WORKSPACE_ROOT="$root"
    export AR_WORKSPACE_ROOT
}

resolve_named_at_work() {
    AR_WORKSPACE_ROOT="$AT_WORKSPACE_DIR_ARG"
    export AR_WORKSPACE_ROOT
}

derive_workspace_name() {
    AR_WORKSPACE_NAME="$(slugify_workspace_name "$(basename "$AR_WORKSPACE_ROOT")")"
    AR_WORKSPACE_NAME="${AR_WORKSPACE_NAME:-project}"
    export AR_WORKSPACE_NAME
}

current_workspace_git_branch() {
    git -C "$WORKSPACE_DIR" branch --show-current 2>/dev/null || true
}

workspace_is_git_worktree() {
    [[ "$(git -C "$WORKSPACE_DIR" rev-parse --is-inside-work-tree 2>/dev/null || true)" == "true" ]]
}

agentic_workspace_root() {
    printf '%s\n' "$AR_WORKSPACE_ROOT"
}

set_agentic_workspace_root() {
    export AR_WORKSPACE_ROOT
}

agentic_runtime_root() {
    if [[ -n "${AR_RUNTIME_ROOT:-}" ]]; then
        resolve_realpath "$AR_RUNTIME_ROOT" 2>/dev/null || printf '%s\n' "$AR_RUNTIME_ROOT"
    else
        printf '%s/.runtime\n' "$AR_WORKSPACE_ROOT"
    fi
}

set_agentic_runtime_root() {
    AR_RUNTIME_ROOT="$(agentic_runtime_root)"
    RUNTIME_ROOT="$AR_RUNTIME_ROOT"
    export AR_RUNTIME_ROOT RUNTIME_ROOT
}

agentic_artifacts_dir() {
    if [[ -n "${AR_ARTIFACTS_DIR:-}" ]]; then
        resolve_realpath "$AR_ARTIFACTS_DIR" 2>/dev/null || printf '%s\n' "$AR_ARTIFACTS_DIR"
    else
        printf '%s/artifacts/project\n' "$AR_WORKSPACE_ROOT"
    fi
}

set_agentic_artifacts_dir() {
    AR_ARTIFACTS_DIR="$(agentic_artifacts_dir)"
    export AR_ARTIFACTS_DIR
}

project_records_dir_path() {
    printf '%s/project-records\n' "$AR_WORKSPACE_ROOT"
}

branch_records_dir_path_for_branch() {
    at_records_path_for_branch "$AR_WORKSPACE_ROOT" "$1"
}

work_branch_id() {
    local branch="$1" slug digest
    slug="$(slugify_workspace_name "$branch")"
    slug="${slug:-branch}"
    if [[ "$slug" == "$branch" ]]; then
        printf '%s\n' "$slug"
        return
    fi
    digest="$(printf '%s' "$branch" | git hash-object --stdin | cut -c1-10)"
    printf '%s-%s\n' "$slug" "$digest"
}

git_commit_identity_configured() {
    git -C "$WORKSPACE_DIR" var GIT_AUTHOR_IDENT >/dev/null 2>&1 \
        && git -C "$WORKSPACE_DIR" var GIT_COMMITTER_IDENT >/dev/null 2>&1
}

setup_workspace_git_identity() {
    local name email
    workspace_is_git_worktree || return 0
    git_commit_identity_configured && return 0
    name="${AR_GIT_NAME:-${AR_NOTES_GIT_NAME:-}}"
    email="${AR_GIT_EMAIL:-${AR_NOTES_GIT_EMAIL:-}}"
    [[ -n "$name" && -n "$email" ]] || return 0
    git -C "$WORKSPACE_DIR" config user.name "$name"
    git -C "$WORKSPACE_DIR" config user.email "$email"
}

set_work_branch_vars() {
    local branch="$1"
    WORKSPACE_GIT_BRANCH="$branch"
    AR_WORK_BRANCH="$branch"
    AR_WORK_BRANCH_ID="$(work_branch_id "$branch")"
    AR_WORK_BRANCH_PREFIX="$branch"
    AR_PROJECT_RECORDS_DIR="$(project_records_dir_path)"
    AR_BRANCH_RECORDS_DIR="$(branch_records_dir_path_for_branch "$branch")"
    export WORKSPACE_GIT_BRANCH AR_WORK_BRANCH AR_WORK_BRANCH_ID AR_WORK_BRANCH_PREFIX
    export AR_PROJECT_RECORDS_DIR AR_BRANCH_RECORDS_DIR
}

branch_guard_dir_for() {
    printf '%s/branch-guards/%s\n' "$RUNTIME_ROOT" "$(work_branch_id "$1")"
}

file_mtime_epoch() {
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || printf '0\n'
}

branch_guard_is_fresh() {
    local now mtime stale_seconds
    stale_seconds="${AR_BRANCH_GUARD_STALE_SECONDS:-300}"
    now="$(date +%s)"
    mtime="$(file_mtime_epoch "$1")"
    [[ "$mtime" =~ ^[0-9]+$ ]] && (( now - mtime <= stale_seconds ))
}

branch_guard_first_active_file() {
    local guard_dir guard
    guard_dir="$(branch_guard_dir_for "$1")"
    [[ -d "$guard_dir" ]] || return 1
    for guard in "$guard_dir"/*.guard; do
        [[ -f "$guard" && "$guard" != "${BRANCH_GUARD_FILE:-}" ]] || continue
        if branch_guard_is_fresh "$guard"; then
            printf '%s\n' "$guard"
            return 0
        fi
    done
    return 1
}

branch_guard_summary() {
    [[ -f "$1" ]] || return 0
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
    ' "$1"
}

require_main_agent_selection() {
    if [[ -z "${AR_MAIN_AGENT:-}" ]]; then
        echo "Error: No main agent selected." >&2
        echo "Run 'agentic-team --setup AR_MAIN_AGENT=NAME' or pass '--main-agent NAME'." >&2
        exit 1
    fi
}

resolve_main_agent_metadata() {
    local kind legacy_ownership
    valid_agent_name "$AR_MAIN_AGENT" || { echo "Error: Invalid AR_MAIN_AGENT: $AR_MAIN_AGENT" >&2; exit 1; }
    if ! MAIN_AGENT_SOURCE_PATH="$(find_agent_source_by_name "$AR_MAIN_AGENT")"; then
        echo "Error: Main agent definition not found: $AR_MAIN_AGENT" >&2
        exit 1
    fi
    MAIN_AGENT_CAPABILITY="$(capability_name_for_source "$MAIN_AGENT_SOURCE_PATH" || true)"
    kind="$(agent_kind_for_source "$MAIN_AGENT_SOURCE_PATH")"
    [[ "$kind" == "main" ]] || { echo "Error: AR_MAIN_AGENT '$AR_MAIN_AGENT' resolves to kind '$kind'." >&2; exit 1; }
    legacy_ownership="$(frontmatter_value "$MAIN_AGENT_SOURCE_PATH" branch_ownership)"
    [[ -z "$legacy_ownership" ]] || { echo "Error: Main agent '$AR_MAIN_AGENT' uses removed branch_ownership metadata." >&2; exit 1; }
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
    local heartbeat_seconds launcher_pid
    [[ "$TEST_MODE" == "true" || "$RENDER_ONLY" == "true" ]] && return 0
    ensure_branch_session_id
    BRANCH_GUARD_FILE="$(branch_guard_dir_for "$AR_WORK_BRANCH")/$AR_SESSION_ID.guard"
    BRANCH_GUARD_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    write_branch_guard_file
    heartbeat_seconds="${AR_BRANCH_GUARD_HEARTBEAT_SECONDS:-30}"
    [[ "$heartbeat_seconds" =~ ^[0-9]+$ && "$heartbeat_seconds" -ge 1 ]] || heartbeat_seconds=30
    launcher_pid="$$"
    ( while kill -0 "$launcher_pid" 2>/dev/null; do write_branch_guard_file; sleep "$heartbeat_seconds"; done ) >/dev/null 2>&1 &
    BRANCH_GUARD_HEARTBEAT_PID="$!"
}

cleanup_branch_guard() {
    if [[ -n "${BRANCH_GUARD_HEARTBEAT_PID:-}" ]]; then
        kill "$BRANCH_GUARD_HEARTBEAT_PID" >/dev/null 2>&1 || true
        wait "$BRANCH_GUARD_HEARTBEAT_PID" >/dev/null 2>&1 || true
        BRANCH_GUARD_HEARTBEAT_PID=""
    fi
    [[ -z "${BRANCH_GUARD_FILE:-}" ]] || rm -f "$BRANCH_GUARD_FILE"
    BRANCH_GUARD_FILE=""
}

prepare_work_branch() {
    local branch active_guard
    workspace_is_git_worktree || { echo "Error: Paired code checkout is not a Git worktree: $WORKSPACE_DIR" >&2; exit 1; }
    branch="$(current_workspace_git_branch)"
    if [[ -z "$branch" || "$branch" != "$AT_BRANCH_ARG" ]]; then
        echo "Error: Expected branch '$AT_BRANCH_ARG' at $WORKSPACE_DIR, found '${branch:-detached HEAD}'." >&2
        exit 1
    fi
    if [[ "$(resolve_realpath "$WORKSPACE_DIR")" != "$(resolve_realpath "$(at_code_path_for_branch "$AR_WORKSPACE_ROOT" "$branch")")" ]]; then
        echo "Error: Agentic Team only runs from its managed checkout for '$branch'." >&2
        exit 1
    fi
    set_work_branch_vars "$branch"
    [[ "$TEST_MODE" == "true" || "$RENDER_ONLY" == "true" ]] && return 0
    if active_guard="$(branch_guard_first_active_file "$branch")"; then
        echo "Error: Branch '$branch' already has an active local agent session." >&2
        branch_guard_summary "$active_guard"
        exit 1
    fi
    register_branch_guard
}
