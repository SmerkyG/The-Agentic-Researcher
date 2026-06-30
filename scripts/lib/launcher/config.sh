# Sourced by agentic-researcher. Argument parsing, config loading, defaults, and launcher globals.

capture_env_overrides() {
    local var override_var unset_marker="__AR_UNSET__"
    local override_vars=(
        AR_SANDBOX
        AR_CLI_TOOL
        AR_DEFAULT_MODEL
        AR_STATE_ROOT
        AR_EXTRA_BIND_DIRS
        AR_EXTRA_ENV
        AR_DOCKER_GPUS
        AR_OPTIONAL_SKILLS
        AR_ORG_NOTES_REPO
        AR_MAIN_AGENT
        AR_INSTRUCTION_PROVIDERS
        AR_AGENT_BRANCH
        AR_AGENT_TOPIC
        AR_BRANCH_OWNERSHIP
        AR_USER_ID
        AR_PROJECT_ID
        AR_AGENTIC_STATE_BRANCH
        AR_NOTES_AUTO_REFRESH
        AR_NOTES_REFRESH_MODE
        AR_NOTES_REFRESH_INTERVAL_SECONDS
        AR_PROFILE_STARTUP
        AR_AUTO_BUILD
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
    )

    for var in "${override_vars[@]}"; do
        override_var="${var}_ENV_OVERRIDE"
        if [[ -n "${!var+x}" ]]; then
            printf -v "$override_var" '%s' "${!var}"
        else
            printf -v "$override_var" '%s' "$unset_marker"
        fi
    done
}

config_file_path() {
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/agentic-researcher/config.sh"
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
    local override_vars=(
        AR_SANDBOX
        AR_CLI_TOOL
        AR_DEFAULT_MODEL
        AR_STATE_ROOT
        AR_EXTRA_BIND_DIRS
        AR_EXTRA_ENV
        AR_DOCKER_GPUS
        AR_OPTIONAL_SKILLS
        AR_ORG_NOTES_REPO
        AR_MAIN_AGENT
        AR_INSTRUCTION_PROVIDERS
        AR_AGENT_BRANCH
        AR_AGENT_TOPIC
        AR_BRANCH_OWNERSHIP
        AR_USER_ID
        AR_PROJECT_ID
        AR_AGENTIC_STATE_BRANCH
        AR_NOTES_AUTO_REFRESH
        AR_NOTES_REFRESH_MODE
        AR_NOTES_REFRESH_INTERVAL_SECONDS
        AR_PROFILE_STARTUP
        AR_AUTO_BUILD
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
    )

    for var in "${override_vars[@]}"; do
        override_var="${var}_ENV_OVERRIDE"
        if [[ "${!override_var:-__AR_UNSET__}" != "__AR_UNSET__" ]]; then
            printf -v "$var" '%s' "${!override_var}"
        fi
    done

    if [[ -n "${AR_SANDBOX_OVERRIDE:-}" ]]; then
        AR_SANDBOX="$AR_SANDBOX_OVERRIDE"
    fi
    if [[ -n "${AR_OPTIONAL_SKILLS_OVERRIDE:-}" ]]; then
        if [[ -n "${AR_OPTIONAL_SKILLS:-}" ]]; then
            AR_OPTIONAL_SKILLS="$AR_OPTIONAL_SKILLS,$AR_OPTIONAL_SKILLS_OVERRIDE"
        else
            AR_OPTIONAL_SKILLS="$AR_OPTIONAL_SKILLS_OVERRIDE"
        fi
    fi
    if [[ -n "${AR_PROJECT_ID_OVERRIDE:-}" ]]; then
        AR_PROJECT_ID="$AR_PROJECT_ID_OVERRIDE"
    fi
    if [[ -n "${AR_MAIN_AGENT_OVERRIDE:-}" ]]; then
        AR_MAIN_AGENT="$AR_MAIN_AGENT_OVERRIDE"
    fi
    if [[ -n "${AR_AGENT_BRANCH_OVERRIDE:-}" ]]; then
        AR_AGENT_BRANCH="$AR_AGENT_BRANCH_OVERRIDE"
    fi
    if [[ -n "${AR_CLI_TOOL_OVERRIDE:-}" ]]; then
        AR_CLI_TOOL="$AR_CLI_TOOL_OVERRIDE"
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
    AR_CLI_TOOL="${AR_CLI_TOOL:-claude}"
    AR_STATE_ROOT="${AR_STATE_ROOT:-$HOME/.cache/agentic-researcher}"
    AR_EXTRA_BIND_DIRS="${AR_EXTRA_BIND_DIRS:-}"
    AR_EXTRA_ENV="${AR_EXTRA_ENV:-}"
    AR_DOCKER_GPUS="${AR_DOCKER_GPUS:-auto}"
    AR_OPTIONAL_SKILLS="${AR_OPTIONAL_SKILLS:-}"
    AR_ORG_NOTES_REPO="${AR_ORG_NOTES_REPO:-}"
    AR_MAIN_AGENT="${AR_MAIN_AGENT:-research-coordinator}"
    AR_INSTRUCTION_PROVIDERS="${AR_INSTRUCTION_PROVIDERS:-agentic-notes,experiment-log}"
    AR_AGENT_BRANCH="${AR_AGENT_BRANCH:-}"
    AR_AGENT_TOPIC="${AR_AGENT_TOPIC:-}"
    AR_BRANCH_OWNERSHIP="${AR_BRANCH_OWNERSHIP:-}"
    AR_USER_ID="${AR_USER_ID:-$USER}"
    AR_PROJECT_ID="${AR_PROJECT_ID:-}"
    AR_AGENTIC_STATE_BRANCH="${AR_AGENTIC_STATE_BRANCH:-agentic/state}"
    AR_NOTES_AUTO_REFRESH="${AR_NOTES_AUTO_REFRESH:-true}"
    AR_NOTES_REFRESH_MODE="${AR_NOTES_REFRESH_MODE:-periodic}"
    AR_NOTES_REFRESH_INTERVAL_SECONDS="${AR_NOTES_REFRESH_INTERVAL_SECONDS:-120}"
    AR_PROFILE_STARTUP="${AR_PROFILE_STARTUP:-false}"
    AR_AUTO_BUILD="${AR_AUTO_BUILD:-true}"
    cli_call_required apply_defaults
}
YOLO_MODE=false
TEST_MODE=false
RENDER_ONLY=false
MODEL_SPECIFIED=false
DEBUG_LAUNCH=false
ALLOW_SHARED_BRANCH=false
WORKSPACE_DIR=""
TOOL_ARGS=()
SELECTED_OPTIONAL_SKILLS=()
OPTIONAL_SKILL_BINDS=()
OPTIONAL_SKILL_ENV=()
OPTIONAL_CLEANUP_ENABLED=false
INSTRUCTION_FILE_REGENERATED=false
BRANCH_GUARD_FILE=""
BRANCH_GUARD_HEARTBEAT_PID=""
BRANCH_GUARD_OVERRIDE=false
MAIN_AGENT_SOURCE_PATH=""
AGENTIC_NOTES_PROVIDER_SETUP=false

append_optional_skill_override() {
    local skill_name="$1"
    if [[ -n "${AR_OPTIONAL_SKILLS_OVERRIDE:-}" ]]; then
        AR_OPTIONAL_SKILLS_OVERRIDE="$AR_OPTIONAL_SKILLS_OVERRIDE,$skill_name"
    else
        AR_OPTIONAL_SKILLS_OVERRIDE="$skill_name"
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
            --tool)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --tool requires a value ($cli_options)"
                    exit 1
                fi
                AR_CLI_TOOL_OVERRIDE="$2"
                shift 2
                ;;
            --gpu-backend)
                echo "Error: --gpu-backend has been removed. Use --optional-skill cluster-run or another backend skill."
                exit 1
                ;;
            --optional-skill)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --optional-skill requires a value"
                    exit 1
                fi
                append_optional_skill_override "$2"
                shift 2
                ;;
            --project-id)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --project-id requires a value"
                    exit 1
                fi
                AR_PROJECT_ID_OVERRIDE="$2"
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
            --agent-branch)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --agent-branch requires a value"
                    exit 1
                fi
                AR_AGENT_BRANCH_OVERRIDE="$2"
                shift 2
                ;;
            --agent-topic)
                echo "Error: --agent-topic has been removed. Use --agent-branch with the Git branch name."
                exit 1
                ;;
            --allow-shared-branch)
                ALLOW_SHARED_BRANCH=true
                shift
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
                        TOOL_ARGS+=("--resume")
                        shift
                    else
                        TOOL_ARGS+=("--resume" "$2")
                        shift 2
                    fi
                else
                    TOOL_ARGS+=("--resume")
                    shift
                fi
                ;;
            --continue|-c)
                TOOL_ARGS+=("--continue")
                shift
                ;;
            --model)
                MODEL_SPECIFIED=true
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --model requires a value"
                    exit 1
                fi
                TOOL_ARGS+=("$1" "$2")
                shift 2
                ;;
            --context)
                if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                    echo "Error: --context requires a value"
                    exit 1
                fi
                TOOL_ARGS+=("$1" "$2")
                shift 2
                ;;
            -*)
                TOOL_ARGS+=("$1")
                shift
                ;;
            *)
                if [[ -z "$WORKSPACE_DIR" ]]; then
                    WORKSPACE_DIR="$1"
                else
                    TOOL_ARGS+=("$1")
                fi
                shift
                ;;
        esac
    done
}

show_help() {
    local sandbox_options cli_options
    sandbox_options="$(registered_sandbox_option_list)"
    cli_options="$(registered_cli_option_list)"

    cat << EOF
agentic-researcher: Launch an AI coding agent for autonomous research.

Usage:
  agentic-researcher [OPTIONS] [DIRECTORY] [TOOL_OPTIONS...]

Options:
  --setup             Run the interactive setup wizard
  --clean             Remove launcher-managed local state
  --uninstall         Remove the installed launcher and optional local state
  --sandbox NAME      Sandbox for this invocation ($sandbox_options)
  --test              Quick validation of sandbox environment
  --render-only       Materialize instruction, skill, and agent files, then exit
  --optional-skill NAME
                      Install an optional skill from optional-skills/ (repeatable)
  --project-id ID     Override inferred project id for notes and experiment state
  --main-agent NAME   Override top-level main agent for this invocation
  --agent-branch NAME Create/switch to this Git branch before launch
  --allow-shared-branch
                      Continue on a branch that appears to have another active local writer
  --debug-launch      Print extra launcher details and enable tool startup logs where supported
  --tool TOOL         Select CLI tool ($cli_options)
  --yolo              Auto-approve tool permissions where supported
  --resume [ID]       Resume a session (interactive picker, or specify ID)
  --continue, -c      Continue the most recent conversation
  --model MODEL       Override default model
  DIRECTORY           Project directory to work in (default: current directory)
  TOOL_OPTIONS        Additional options passed to the CLI tool

Examples:
  agentic-researcher --sandbox none
  agentic-researcher --optional-skill cluster-run
  agentic-researcher --sandbox apptainer --optional-skill remote-run
  agentic-researcher --sandbox apptainer --optional-skill remote-run --test
  agentic-researcher
  agentic-researcher --main-agent research-paper-author
  agentic-researcher --setup                      # Setup wizard
  agentic-researcher --clean                      # Interactive cleanup of local state
  agentic-researcher --uninstall                  # Remove installed launcher
  agentic-researcher --clean --yes --include-config
  agentic-researcher --test
  agentic-researcher --render-only --tool codex
  agentic-researcher --tool opencode --debug-launch
  agentic-researcher                              # Current directory; unoccupied agent/* branches start directly
  agentic-researcher ~/my-project
  agentic-researcher --yolo
  agentic-researcher --tool gemini
  agentic-researcher --tool codex ~/project
  agentic-researcher --yolo --model opus
  agentic-researcher --agent-branch agent/kernel-search

What's Sandboxed:
  The agent can write your project directory and AR_STATE_ROOT.
  The AR install is mounted read-only at /opt/agentic-researcher.
  Cannot access the rest of your home directory, except selected auth/config mounts.
  Even with --yolo, the agent stays sandboxed.

Security:
  --yolo auto-approves tool calls but maintains filesystem isolation.
  --sandbox none disables Agentic Researcher filesystem isolation.
  OpenCode/Gemini/Codex have no built-in permission system.
  Review changes before committing to git.
EOF
}
