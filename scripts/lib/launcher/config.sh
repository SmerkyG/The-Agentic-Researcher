# Sourced by agentic-team. Argument parsing, config loading, defaults, and launcher globals.

LAUNCHER_ENV_OVERRIDE_VARS=(
    AR_SANDBOX
    AR_CLI
    AR_DEFAULT_MODEL
    AR_STATE_ROOT
    AR_WORKSPACE_ROOT
    AR_RUNTIME_ROOT
    AR_ARTIFACTS_DIR
    AR_EXTRA_BIND_DIRS
    AR_EXTRA_ENV
    AR_DOCKER_GPUS
    AR_CAPABILITIES
    AR_ORG_NOTES_REPO
    AR_MAIN_AGENT
    AR_WORK_BRANCH
    AR_USER_ID
    AR_PROJECT_STATE_BRANCH
    AR_NOTES_AUTO_REFRESH
    AR_NOTES_REFRESH_MODE
    AR_NOTES_REFRESH_INTERVAL_SECONDS
    AR_PROFILE_STARTUP
    AR_AUTO_BUILD
    AR_GIT_NAME
    AR_GIT_EMAIL
    AR_RESOLVER_GIT_NAME
    AR_RESOLVER_GIT_EMAIL
    AR_NOTES_GIT_NAME
    AR_NOTES_GIT_EMAIL
    AR_AUTH_MODE
    AR_API_PROVIDER
    AR_API_KEY_ENV
    AR_CUSTOM_ENDPOINT
    AR_CUSTOM_ANTHROPIC_ENDPOINT
    AR_HTTPS_PROXY
    AR_HTTP_PROXY
    APPTAINER_CACHEDIR
    APPTAINER_TMPDIR
)

# Additional writable storage directories configured as ENV_NAME=/host/path.
# Bash arrays are intentionally config-file-only. Ambient cache variables are
# still used as built-in host-path overrides when no array entry replaces them.
AR_STORAGE_DIRS=()

capture_env_overrides() {
    local var override_var unset_marker="__AR_UNSET__"

    for var in "${LAUNCHER_ENV_OVERRIDE_VARS[@]}"; do
        override_var="${var}_ENV_OVERRIDE"
        if [[ -n "${!var+x}" ]]; then
            printf -v "$override_var" '%s' "${!var}"
        else
            printf -v "$override_var" '%s' "$unset_marker"
        fi
    done
}

config_file_path() {
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team/config.sh"
}

load_config() {
    local cfg
    cfg="$(config_file_path)"
    if [[ -f "$cfg" ]]; then
        source "$cfg"
    fi
}

# Environment variables override config file values
apply_env_overrides() {
    local var override_var

    for var in "${LAUNCHER_ENV_OVERRIDE_VARS[@]}"; do
        override_var="${var}_ENV_OVERRIDE"
        if [[ "${!override_var:-__AR_UNSET__}" != "__AR_UNSET__" ]]; then
            printf -v "$var" '%s' "${!override_var}"
        fi
    done

    if [[ -n "${AR_SANDBOX_OVERRIDE:-}" ]]; then
        AR_SANDBOX="$AR_SANDBOX_OVERRIDE"
    fi
    if [[ -n "${AR_CAPABILITIES_OVERRIDE:-}" ]]; then
        AR_CAPABILITIES="${AR_CAPABILITIES:-agentic-notes,experiment-log}"
        [[ "$AR_CAPABILITIES" == "none" ]] && AR_CAPABILITIES=""
        if [[ -n "$AR_CAPABILITIES" ]]; then
            AR_CAPABILITIES="$AR_CAPABILITIES,$AR_CAPABILITIES_OVERRIDE"
        else
            AR_CAPABILITIES="$AR_CAPABILITIES_OVERRIDE"
        fi
    fi
    if [[ -n "${AR_MAIN_AGENT_OVERRIDE:-}" ]]; then
        AR_MAIN_AGENT="$AR_MAIN_AGENT_OVERRIDE"
    fi
    if [[ -n "${AR_WORK_BRANCH_OVERRIDE:-}" ]]; then
        AR_WORK_BRANCH="$AR_WORK_BRANCH_OVERRIDE"
    fi
    if [[ -n "${AR_CLI_OVERRIDE:-}" ]]; then
        AR_CLI="$AR_CLI_OVERRIDE"
    fi
    if [[ -n "${AR_DEFAULT_MODEL_OVERRIDE:-}" ]]; then
        AR_DEFAULT_MODEL="$AR_DEFAULT_MODEL_OVERRIDE"
    fi
}

detect_default_sandbox() {
    if command -v docker >/dev/null 2>&1; then
        printf '%s\n' "docker"
    elif command -v podman >/dev/null 2>&1; then
        printf '%s\n' "podman"
    else
        printf '%s\n' "docker"
    fi
}

apply_defaults() {
    if [[ -z "${AR_SANDBOX:-}" ]]; then
        AR_SANDBOX="$(detect_default_sandbox)"
        if [[ "$AR_SANDBOX" == "podman" ]] && ! command -v docker >/dev/null 2>&1; then
            echo "Docker not found, falling back to Podman."
        fi
    fi
    AR_CLI="${AR_CLI:-claude}"
    AR_STATE_ROOT="${AR_STATE_ROOT:-$HOME/.cache/agentic-team}"
    AR_WORKSPACE_ROOT="${AR_WORKSPACE_ROOT:-}"
    AR_RUNTIME_ROOT="${AR_RUNTIME_ROOT:-}"
    AR_ARTIFACTS_DIR="${AR_ARTIFACTS_DIR:-}"
    AR_EXTRA_BIND_DIRS="${AR_EXTRA_BIND_DIRS:-}"
    AR_EXTRA_ENV="${AR_EXTRA_ENV:-}"
    AR_DOCKER_GPUS="${AR_DOCKER_GPUS:-auto}"
    AR_CAPABILITIES="${AR_CAPABILITIES:-agentic-notes,experiment-log}"
    AR_ORG_NOTES_REPO="${AR_ORG_NOTES_REPO:-}"
    AR_MAIN_AGENT="${AR_MAIN_AGENT:-}"
    AR_WORK_BRANCH="${AR_WORK_BRANCH:-}"
    AR_USER_ID="${AR_USER_ID:-$USER}"
    AR_PROJECT_STATE_BRANCH="${AR_PROJECT_STATE_BRANCH:-agentic/project-state}"
    AR_NOTES_AUTO_REFRESH="${AR_NOTES_AUTO_REFRESH:-true}"
    AR_NOTES_REFRESH_MODE="${AR_NOTES_REFRESH_MODE:-periodic}"
    AR_NOTES_REFRESH_INTERVAL_SECONDS="${AR_NOTES_REFRESH_INTERVAL_SECONDS:-120}"
    AR_PROFILE_STARTUP="${AR_PROFILE_STARTUP:-false}"
    AR_AUTO_BUILD="${AR_AUTO_BUILD:-true}"
    AR_GIT_NAME="${AR_GIT_NAME:-}"
    AR_GIT_EMAIL="${AR_GIT_EMAIL:-}"
    cli_call_required apply_defaults
}
YOLO_MODE=false
TEST_MODE=false
RENDER_ONLY=false
REFRESH_CAPABILITIES=false
MODEL_SPECIFIED=false
DEBUG_LAUNCH=false
WORKSPACE_DIR=""
WORKSPACE_INPUT_DIR=""
WORKTREE_PATH_ARG=""
AT_WORKSPACE_DIR_ARG=""
AT_WORK_NAME_ARG=""
AT_FROM_REF=""
AT_PROJECT_DIR_ARG=""
AT_NEW_BRANCH_ARG=""
AT_STATE_MODE="auto"
CLI_ARGS=()
POSITIONAL_ARGS=()
SELECTED_CAPABILITIES=()
CAPABILITY_BINDS=()
CAPABILITY_ENV=()
CAPABILITY_CLEANUP_ENABLED=false
INSTRUCTION_FILE_REGENERATED=false
BRANCH_GUARD_FILE=""
BRANCH_GUARD_HEARTBEAT_PID=""
MAIN_AGENT_SOURCE_PATH=""
MAIN_AGENT_CAPABILITY=""
AGENTIC_NOTES_CAPABILITY_SETUP=false

append_capability_override() {
    local capability_name="$1"
    if [[ -n "${AR_CAPABILITIES_OVERRIDE:-}" ]]; then
        AR_CAPABILITIES_OVERRIDE="$AR_CAPABILITIES_OVERRIDE,$capability_name"
    else
        AR_CAPABILITIES_OVERRIDE="$capability_name"
    fi
}

parse_arguments() {
    local sandbox_options cli_options
    sandbox_options="$(registered_sandbox_option_list)"
    cli_options="$(registered_cli_option_list)"

    if [[ $# -eq 0 ]]; then
        echo "Error: agentic-team requires a project/workspace argument or an explicit mode." >&2
        show_help >&2
        exit 2
    fi

    while [[ $# -gt 0 ]]; do
        case $1 in
            --setup)
                shift
                exec "$SCRIPT_DIR/scripts/first-setup.sh" "$@"
                ;;
            --clean)
                shift
                exec "$SCRIPT_DIR/scripts/cleanup.sh" "$@"
                ;;
            --uninstall)
                shift
                exec "$SCRIPT_DIR/scripts/uninstall.sh" "$@"
                ;;
            --test)
                TEST_MODE=true
                shift
                ;;
            --render-only)
                RENDER_ONLY=true
                shift
                ;;
            --refresh-capabilities)
                REFRESH_CAPABILITIES=true
                shift
                ;;
            --debug-launch)
                DEBUG_LAUNCH=true
                shift
                ;;
            --sandbox)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --sandbox requires a value ($sandbox_options)"
                    exit 1
                fi
                AR_SANDBOX_OVERRIDE="$2"
                shift 2
                ;;
            --cli)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --cli requires a value ($cli_options)"
                    exit 1
                fi
                AR_CLI_OVERRIDE="$2"
                shift 2
                ;;
            --tool)
                echo "Error: --tool has been removed. Use --cli to select the agent CLI."
                exit 1
                ;;
            --gpu-backend)
                echo "Error: --gpu-backend has been removed. Use --capability cluster-run or another backend capability."
                exit 1
                ;;
            --capability)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --capability requires a value"
                    exit 1
                fi
                append_capability_override "$2"
                shift 2
                ;;
            --main-agent)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --main-agent requires a value"
                    exit 1
                fi
                AR_MAIN_AGENT_OVERRIDE="$2"
                shift 2
                ;;
            --work-branch)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --work-branch requires a value"
                    exit 1
                fi
                AR_WORK_BRANCH_OVERRIDE="$2"
                shift 2
                ;;
            --worktree-path)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --worktree-path requires a value"
                    exit 1
                fi
                WORKTREE_PATH_ARG="$2"
                shift 2
                ;;
            --from)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --from requires a value"
                    exit 1
                fi
                AT_FROM_REF="$2"
                shift 2
                ;;
            --project-dir)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --project-dir requires a value"
                    exit 1
                fi
                AT_PROJECT_DIR_ARG="$2"
                shift 2
                ;;
            --branch)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --branch requires a value"
                    exit 1
                fi
                AT_NEW_BRANCH_ARG="$2"
                shift 2
                ;;
            --state)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --state requires a value (auto or clean)"
                    exit 1
                fi
                case "$2" in
                    auto|clean)
                        AT_STATE_MODE="$2"
                        ;;
                    *)
                        echo "Error: --state must be auto or clean"
                        exit 1
                        ;;
                esac
                shift 2
                ;;
            --agent-branch)
                echo "Error: --agent-branch has been removed. Use --work-branch with the Git branch name."
                exit 1
                ;;
            --agent-topic)
                echo "Error: --agent-topic has been removed. Use --work-branch with the Git branch name."
                exit 1
                ;;
            --allow-shared-branch)
                echo "Error: --allow-shared-branch has been removed. Launch a separate AT work entry instead."
                exit 1
                ;;
            --yolo)
                YOLO_MODE=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            --resume|-r)
                if [[ -n "${2:-}" && ! "$2" =~ ^- ]]; then
                    if [[ -z "$WORKSPACE_DIR" && -d "$2" ]]; then
                        CLI_ARGS+=("--resume")
                        shift
                    else
                        CLI_ARGS+=("--resume" "$2")
                        shift 2
                    fi
                else
                    CLI_ARGS+=("--resume")
                    shift
                fi
                ;;
            --continue|-c)
                CLI_ARGS+=("--continue")
                shift
                ;;
            --model)
                MODEL_SPECIFIED=true
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --model requires a value"
                    exit 1
                fi
                CLI_ARGS+=("$1" "$2")
                shift 2
                ;;
            --context)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --context requires a value"
                    exit 1
                fi
                CLI_ARGS+=("$1" "$2")
                shift 2
                ;;
            -*)
                CLI_ARGS+=("$1")
                shift
                ;;
            *)
                POSITIONAL_ARGS+=("$1")
                shift
                ;;
        esac
    done

    resolve_launch_positionals

    if [[ "$REFRESH_CAPABILITIES" == "true" && "$RENDER_ONLY" != "true" ]]; then
        echo "Error: --refresh-capabilities requires --render-only"
        exit 1
    fi
}

show_help() {
    local sandbox_options cli_options
    sandbox_options="$(registered_sandbox_option_list)"
    cli_options="$(registered_cli_option_list)"

    cat << EOF
agentic-team: Launch an AI coding agent for structured team workflows.

Usage:
  agentic-team [OPTIONS] [PROJECT_DIR] [CLI_OPTIONS...]
  agentic-team [OPTIONS] AT_DIR WORK_NAME [CLI_OPTIONS...]

Options:
  --setup             Run the interactive setup wizard
  --clean             Remove launcher-managed local state
  --uninstall         Remove the installed launcher and optional local state
  --sandbox NAME      Sandbox for this invocation ($sandbox_options)
  --test              Quick validation of sandbox environment
  --render-only       Materialize instruction, skill, and agent files, then exit
  --refresh-capabilities
                      With --render-only, run capability refresh hooks before rendering
  --capability NAME   Enable a capability from capabilities/ (repeatable)
  --project-dir DIR   Existing normal project checkout for creating/repairing an AT workspace
  --main-agent NAME   Override top-level main agent for this invocation
  --work-branch NAME  Create/switch to this Git branch before launch
  --worktree-path DIR Launch an explicit Git worktree path instead of AT_DIR WORK_NAME
  --from REF_OR_WORK  Create missing AT work from a Git ref or existing AT work name
  --branch NAME       New Git branch when creating missing AT work
  --state MODE        Context inheritance for created AT work: auto or clean
  --debug-launch      Print extra launcher details and enable CLI startup logs where supported
  --cli CLI           Select CLI ($cli_options)
  --yolo              Auto-approve tool call permissions where supported
  --resume [ID]       Resume a session (interactive picker, or specify ID)
  --continue, -c      Continue the most recent conversation
  --model MODEL       Override default model
  PROJECT_DIR         Normal project checkout for first-run setup
  AT_DIR WORK_NAME    Launch or create the named AT work entry at AT_DIR/WORK_NAME/code
  CLI_OPTIONS         Additional options passed to the selected CLI

Examples:
  agentic-team --sandbox none
  agentic-team --capability cluster-run
  agentic-team --sandbox apptainer --capability remote-run
  agentic-team --sandbox apptainer --capability remote-run --test
  agentic-team --main-agent research-paper-author
  agentic-team --setup                      # Setup wizard
  agentic-team --clean                      # Interactive cleanup of local state
  agentic-team --uninstall                  # Remove installed launcher
  agentic-team --clean --yes --include-config
  agentic-team --test
  agentic-team --render-only --cli codex
  agentic-team --render-only --refresh-capabilities --cli codex
  agentic-team --cli opencode --debug-launch
  agentic-team ~/my-project
  agentic-team ~/my-project-at research-main
  agentic-team ~/my-project-at research-main --from main --project-dir ~/my-project
  agentic-team ~/my-project-at kdtree-bounds --from research-main
  agentic-team ~/my-project-at kdtree-bounds --from research-main --state clean
  agentic-team --worktree-path ~/my-project-at/research-main/code
  agentic-team --yolo
  agentic-team --cli gemini
  agentic-team --cli codex --worktree-path ~/my-project-at/research-main/code
  agentic-team --yolo --model opus
  agentic-team --work-branch feature/kernel-search

What's Sandboxed:
  The agent can write your project directory, AR_ARTIFACTS_DIR, AR_WORKSPACE_ROOT, AR_RUNTIME_ROOT, and AR_STATE_ROOT.
  The Agentic Team install is mounted read-only at /opt/agentic-team.
  Cannot access the rest of your home directory, except selected auth/config mounts.
  Even with --yolo, the agent stays sandboxed.

Security:
  --yolo auto-approves tool calls but maintains filesystem isolation.
  --sandbox none disables Agentic Team filesystem isolation.
  OpenCode/Gemini/Codex have no built-in permission system.
  Review changes before committing to git.
EOF
}
