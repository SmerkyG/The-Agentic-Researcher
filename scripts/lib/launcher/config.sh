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
    AR_USER_ID
    AR_PROJECT_RECORDS_BRANCH
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
    AR_PROJECT_RECORDS_BRANCH="${AR_PROJECT_RECORDS_BRANCH:-agentic/project-records}"
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
PREPARE_CLIENT=false
REFRESH_CAPABILITIES=false
MODEL_SPECIFIED=false
DEBUG_LAUNCH=false
WORKSPACE_DIR=""
WORKSPACE_INPUT_DIR=""
AT_WORKSPACE_DIR_ARG=""
AT_BRANCH_ARG=""
TOP_LEVEL_RUN_ROOT=""
TOP_LEVEL_ARGS=()
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

normalize_top_level_command() {
    local command="" root="" index
    local -a args=("$@")

    if (( ${#args[@]} >= 1 )) && [[ "${args[0]}" == "-C" ]]; then
        if (( ${#args[@]} < 3 )); then
            echo "Error: -C requires an AT repository path and a command." >&2
            exit 2
        fi
        root="${args[1]}"
        command="${args[2]}"
        case "$command" in
            init|clone|checkout|branch)
                exec "$SCRIPT_DIR/scripts/bin/agentic-workspace" -C "$root" "$command" "${args[@]:3}"
                ;;
            run)
                TOP_LEVEL_RUN_ROOT="$root"
                TOP_LEVEL_ARGS=("${args[@]:3}")
                return
                ;;
            *)
                echo "Error: Unknown Agentic Team command: $command" >&2
                show_help >&2
                exit 2
                ;;
        esac
    fi

    # Permit known launcher options before `run` while keeping the subcommand
    # explicit. Option values are skipped so `--model run` is not mistaken for
    # the subcommand.
    index=0
    while (( index < ${#args[@]} )); do
        case "${args[$index]}" in
            run)
                TOP_LEVEL_ARGS=("${args[@]:0:$index}" "${args[@]:$((index + 1))}")
                return
                ;;
            --sandbox|--cli|--capability|--main-agent|--model|--context)
                index=$((index + 2))
                ;;
            --resume|-r)
                if (( index + 1 < ${#args[@]} )) && [[ "${args[$((index + 1))]}" != "run" && "${args[$((index + 1))]}" != -* ]]; then
                    index=$((index + 2))
                else
                    index=$((index + 1))
                fi
                ;;
            --test|--render-only|--prepare-client|--refresh-capabilities|--debug-launch|--yolo|--continue|-c)
                index=$((index + 1))
                ;;
            *)
                break
                ;;
        esac
    done

    command="${args[0]:-}"
    case "$command" in
        init|clone|checkout|branch)
            exec "$SCRIPT_DIR/scripts/bin/agentic-workspace" "$command" "${args[@]:1}"
            ;;
        run)
            TOP_LEVEL_ARGS=("${args[@]:1}")
            ;;
        --setup|--clean|--uninstall|--help|-h)
            TOP_LEVEL_ARGS=("${args[@]}")
            ;;
        "")
            echo "Error: agentic-team requires a command." >&2
            show_help >&2
            exit 2
            ;;
        *)
            echo "Error: Expected an Agentic Team command, not '$command'." >&2
            echo "Use 'agentic-team run ...' to launch an agent." >&2
            show_help >&2
            exit 2
            ;;
    esac
}

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
            --prepare-client)
                PREPARE_CLIENT=true
                AR_SANDBOX_OVERRIDE=none
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
                echo "Error: --work-branch is not a run option; select the paired branch in 'agentic-team run BRANCH'."
                exit 1
                ;;
            --worktree-path|--from|--project-dir|--branch|--state)
                echo "Error: $1 is not a run option. Use 'agentic-team checkout' to create a paired branch checkout."
                exit 1
                ;;
            --agent-branch)
                echo "Error: --agent-branch has been removed. Select the paired branch in 'agentic-team run BRANCH'."
                exit 1
                ;;
            --agent-topic)
                echo "Error: --agent-topic has been removed. Select the paired branch in 'agentic-team run BRANCH'."
                exit 1
                ;;
            --allow-shared-branch)
                echo "Error: --allow-shared-branch has been removed. Create a separate paired branch instead."
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
    if [[ "$PREPARE_CLIENT" == "true" && "$RENDER_ONLY" == "true" ]]; then
        echo "Error: --prepare-client and --render-only are separate modes"
        exit 1
    fi
    if [[ "$PREPARE_CLIENT" == "true" && "$TEST_MODE" == "true" ]]; then
        echo "Error: --prepare-client cannot be combined with --test"
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
  agentic-team init AT_DIR
  agentic-team clone UPSTREAM_URL AT_DIR
  agentic-team [-C AT_DIR] checkout BRANCH
  agentic-team [-C AT_DIR] checkout -b NEW_BRANCH [START_POINT]
  agentic-team [-C AT_DIR] branch
  agentic-team [-C AT_DIR] run [BRANCH] [OPTIONS] [CLI_OPTIONS...]

Options:
  --setup             Run the interactive setup wizard
  --clean             Remove launcher-managed local state
  --uninstall         Remove the installed launcher and optional local state
  --sandbox NAME      Sandbox for this invocation ($sandbox_options)
  --test              Quick validation of sandbox environment
  --render-only       Materialize instruction, skill, and agent files, then exit
  --prepare-client    Prepare an external client context and launcher, then exit
  --refresh-capabilities
                      With --render-only, run capability refresh hooks before rendering
  --capability NAME   Enable a capability from capabilities/ (repeatable)
  --main-agent NAME   Override top-level main agent for this invocation
  --debug-launch      Print extra launcher details and enable CLI startup logs where supported
  --cli CLI           Select CLI ($cli_options)
  --yolo              Auto-approve tool call permissions where supported
  --resume [ID]       Resume a session (interactive picker, or specify ID)
  --continue, -c      Continue the most recent conversation
  --model MODEL       Override default model
  BRANCH              Existing paired AT branch to run
  CLI_OPTIONS         Additional options passed to the selected CLI

Examples:
  agentic-team init ~/my-project-at
  agentic-team clone https://github.com/example/project.git ~/my-project-at
  agentic-team -C ~/my-project-at checkout main
  agentic-team -C ~/my-project-at checkout -b agent/benchmarks main
  agentic-team -C ~/my-project-at branch
  agentic-team -C ~/my-project-at run agent/benchmarks --main-agent ml-engineer
  agentic-team -C ~/my-project-at run agent/benchmarks --sandbox none --yolo
  agentic-team --setup                      # Setup wizard
  agentic-team --clean                      # Interactive cleanup of local state
  agentic-team --uninstall                  # Remove installed launcher
  agentic-team --clean --yes --include-config
  agentic-team -C ~/my-project-at run main --test
  agentic-team -C ~/my-project-at run main --render-only --cli codex
  agentic-team -C ~/my-project-at run main --prepare-client --cli codex
  agentic-team run --main-agent general  # when invoked inside branches/BRANCH/code

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
