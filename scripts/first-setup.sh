#!/bin/bash
#
# first-setup.sh: Interactive setup wizard for Agentic Team.
#
# Generates ${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team/config.sh
#
# Usage:
#   agentic-team --setup                          # Full interactive wizard
#   agentic-team --setup KEY=VALUE [KEY=VALUE...]  # Set individual values
#   agentic-team --setup auth                      # Toggle oauth / api-key
#
# Examples:
#   agentic-team --setup AR_CLI=gemini
#   agentic-team --setup AR_EXTRA_BIND_DIRS="/data/models, /shared/datasets"
#   agentic-team --setup auth                      # Switch between subscription and custom endpoint
#

set -e

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team"
CONFIG_FILE="$CONFIG_DIR/config.sh"

# ── Quick auth toggle mode ────────────────────────────────────────
if [[ $# -eq 1 && "$1" == "auth" ]]; then
    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "Error: No config file found. Run 'agentic-team --setup' first."
        exit 1
    fi
    source "$CONFIG_FILE"
    echo "─── Authentication Mode ───"
    echo "  Current: $AR_AUTH_MODE"
    if [[ -n "${AR_CUSTOM_ANTHROPIC_ENDPOINT:-}" ]]; then
        echo "  Endpoint: $AR_CUSTOM_ANTHROPIC_ENDPOINT (used in api-key mode only)"
    fi
    echo ""
    echo "  1) oauth    — Claude subscription (interactive login)"
    echo "  2) api-key  — Custom API key + endpoint"
    echo ""
    read -rp "Select [current]: " auth_choice
    case "$auth_choice" in
        1) new_mode="oauth" ;;
        2) new_mode="api-key" ;;
        *) echo "No change."; exit 0 ;;
    esac
    if [[ "$new_mode" == "$AR_AUTH_MODE" ]]; then
        echo "Already set to $new_mode. No change."
        exit 0
    fi
    # If switching to api-key, prompt for endpoint + key env var if not already set
    if [[ "$new_mode" == "api-key" ]]; then
        if [[ -z "${AR_CUSTOM_ANTHROPIC_ENDPOINT:-}" ]]; then
            read -rp "Anthropic-compatible endpoint URL: " new_endpoint
            if [[ -n "$new_endpoint" ]]; then
                sed -i "s|^AR_CUSTOM_ANTHROPIC_ENDPOINT=.*|AR_CUSTOM_ANTHROPIC_ENDPOINT=\"${new_endpoint}\"|" "$CONFIG_FILE"
                echo "  Updated: AR_CUSTOM_ANTHROPIC_ENDPOINT=\"$new_endpoint\""
            fi
        fi
        cur_key_env="${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
        read -rp "API key env var [$cur_key_env]: " new_key_env
        new_key_env="${new_key_env:-$cur_key_env}"
        if [[ "$new_key_env" != "$cur_key_env" ]]; then
            sed -i "s|^AR_API_KEY_ENV=.*|AR_API_KEY_ENV=\"${new_key_env}\"|" "$CONFIG_FILE"
            echo "  Updated: AR_API_KEY_ENV=\"$new_key_env\""
        fi
    fi
    sed -i "s|^AR_AUTH_MODE=.*|AR_AUTH_MODE=\"${new_mode}\"|" "$CONFIG_FILE"
    echo ""
    echo "Switched to: $new_mode"
    if [[ "$new_mode" == "oauth" ]]; then
        echo "  Claude will prompt for interactive login on next launch."
    else
        echo "  Endpoint: $(grep '^AR_CUSTOM_ANTHROPIC_ENDPOINT=' "$CONFIG_FILE" | cut -d'"' -f2)"
        echo "  Make sure \$${new_key_env:-$cur_key_env} is set before launching."
    fi
    exit 0
fi

# ── Individual key=value mode ──────────────────────────────────────
if [[ $# -gt 0 && "$1" == *=* ]]; then
    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "Error: No config file found. Run 'agentic-team --setup' first (without arguments)."
        exit 1
    fi
    for arg in "$@"; do
        key="${arg%%=*}"
        val="${arg#*=}"
        # Normalize AR_EXTRA_BIND_DIRS separators
        if [[ "$key" == "AR_EXTRA_BIND_DIRS" ]]; then
            val=$(echo "$val" | tr ',' ':' | sed 's/ *: */:/g; s/^://; s/:$//')
        fi
        if grep -q "^${key}=" "$CONFIG_FILE"; then
            sed -i "s|^${key}=.*|${key}=\"${val}\"|" "$CONFIG_FILE"
            echo "Updated: $key=\"$val\""
        else
            echo "${key}=\"${val}\"" >> "$CONFIG_FILE"
            echo "Added: $key=\"$val\""
        fi
    done
    exit 0
fi

# ── Full interactive wizard ────────────────────────────────────────

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          Agentic Team - Setup Wizard                    ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

if [[ -f "$CONFIG_FILE" ]]; then
    echo "Existing configuration found: $CONFIG_FILE"
    echo ""
    echo "Tip: To change individual settings without re-running the full wizard:"
    echo "  agentic-team --setup KEY=VALUE"
    echo "  e.g., agentic-team --setup AR_CLI=gemini"
    echo ""
    read -rp "Re-run full wizard? [y/N] " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "Setup cancelled."
        exit 0
    fi
    echo ""
fi

# ── 1. Sandbox ────────────────────────────────────────────────────────
echo "─── Sandbox ───"
echo "  1) docker     (local workstations / cloud)"
echo "  2) podman     (local workstations / rootless containers)"
echo "  3) apptainer  (Linux environments)"
echo "  4) none       (host CLI, no container sandbox)"
echo ""
read -rp "Select [1]: " sandbox_choice
case "${sandbox_choice:-1}" in
    1) AR_SANDBOX=docker ;;
    2) AR_SANDBOX=podman ;;
    3) AR_SANDBOX=apptainer ;;
    4) AR_SANDBOX=none ;;
    *) echo "Invalid choice, defaulting to docker"; AR_SANDBOX=docker ;;
esac
echo "  → $AR_SANDBOX"
echo ""

# ── 2. CLI Tool ───────────────────────────────────────────────────────────
echo "─── CLI Tool ───"
echo "  1) claude    (Claude Code — default)"
echo "  2) opencode  (OpenCode — open-source, any LLM)"
echo "  3) gemini    (Gemini CLI — Google)"
echo "  4) codex     (Codex CLI — OpenAI)"
echo "  5) pi        (pi — any model backend)"
echo ""
read -rp "Select [1]: " cli__choice
case "${cli__choice:-1}" in
    1)
        AR_CLI=claude
        AR_DEFAULT_MODEL_DEFAULT=sonnet
        AR_AUTH_MODE=oauth
        AR_API_PROVIDER=anthropic
        AR_API_KEY_ENV=ANTHROPIC_API_KEY
        ;;
    2)
        AR_CLI=opencode
        AR_DEFAULT_MODEL_DEFAULT=""
        AR_AUTH_MODE=cli-tool
        AR_API_PROVIDER=""
        AR_API_KEY_ENV=""
        ;;
    3)
        AR_CLI=gemini
        AR_DEFAULT_MODEL_DEFAULT=""
        AR_AUTH_MODE=cli-tool
        AR_API_PROVIDER=""
        AR_API_KEY_ENV=""
        ;;
    4)
        AR_CLI=codex
        AR_DEFAULT_MODEL_DEFAULT=""
        AR_AUTH_MODE=cli-tool
        AR_API_PROVIDER=""
        AR_API_KEY_ENV=""
        ;;
    5)
        AR_CLI=pi
        AR_DEFAULT_MODEL_DEFAULT=""
        AR_AUTH_MODE=cli-tool
        AR_API_PROVIDER=""
        AR_API_KEY_ENV=""
        ;;
    *)
        echo "Invalid choice, defaulting to claude"
        AR_CLI=claude
        AR_DEFAULT_MODEL_DEFAULT=sonnet
        AR_AUTH_MODE=oauth
        AR_API_PROVIDER=anthropic
        AR_API_KEY_ENV=ANTHROPIC_API_KEY
        ;;
esac
echo "  → $AR_CLI"
echo ""

# Default model
if [[ -n "$AR_DEFAULT_MODEL_DEFAULT" ]]; then
    read -rp "Default model [$AR_DEFAULT_MODEL_DEFAULT]: " AR_DEFAULT_MODEL
    AR_DEFAULT_MODEL="${AR_DEFAULT_MODEL:-$AR_DEFAULT_MODEL_DEFAULT}"
else
    read -rp "Default model (leave empty for CLI default): " AR_DEFAULT_MODEL
fi
if [[ -n "$AR_DEFAULT_MODEL" ]]; then
    echo "  → $AR_DEFAULT_MODEL"
fi
echo ""

# ── 3. Network Proxy ────────────────────────────────────────────────
echo "─── Network Proxy (leave empty if not needed) ───"
read -rp "HTTPS proxy (e.g., http://proxy:3128): " AR_HTTPS_PROXY
AR_HTTP_PROXY="$AR_HTTPS_PROXY"  # Default: same as HTTPS
if [[ -n "$AR_HTTPS_PROXY" ]]; then
    read -rp "HTTP proxy [$AR_HTTPS_PROXY]: " AR_HTTP_PROXY
    AR_HTTP_PROXY="${AR_HTTP_PROXY:-$AR_HTTPS_PROXY}"
fi
echo ""

# ── 4. Local State ──────────────────────────────────────────────────
echo "─── Local State ───"
STATE_ROOT_DEFAULT="$HOME/.cache/agentic-team"
read -rp "State/cache directory [$STATE_ROOT_DEFAULT]: " AR_STATE_ROOT
AR_STATE_ROOT="${AR_STATE_ROOT:-$STATE_ROOT_DEFAULT}"
echo "  → $AR_STATE_ROOT"
echo ""

# ── 5. Extra sandbox directories ───────────────────────────────────
echo "─── Extra Sandbox Directories ───"
if [[ "$AR_SANDBOX" == "none" ]]; then
    echo "  No-sandbox mode has no Agentic Team filesystem isolation."
    echo "  Extra bind directories are not used."
    AR_EXTRA_BIND_DIRS=""
else
    echo "  By default, only your project directory is accessible inside the sandbox."
    echo "  You can allow additional directories (e.g., datasets, shared storage)."
    echo "  Separate paths with commas, colons, or spaces."
    echo ""
    read -rp "Extra directories (e.g., /data/models, /shared/datasets): " AR_EXTRA_BIND_DIRS_RAW
    # Normalize: accept commas, colons, or spaces as separators -> colon-separated
    AR_EXTRA_BIND_DIRS=$(echo "$AR_EXTRA_BIND_DIRS_RAW" | tr ',' ':' | tr ' ' ':' | sed 's/::/:/g; s/^://; s/:$//')
    if [[ -n "$AR_EXTRA_BIND_DIRS" ]]; then
        echo "  → $AR_EXTRA_BIND_DIRS"
    fi
fi
echo ""

# ── 6. Org repo ──────────────────────────────────────────────────────
echo "─── Org Repo ───"
echo "  Optional shared Git repo for organization-wide notes, agent-type notes, and"
echo "  org-provided agents and capabilities. Leave empty to use only project-local state."
echo ""
read -rp "Org repo Git URL or local path [none]: " AR_ORG_NOTES_REPO
if [[ -n "$AR_ORG_NOTES_REPO" ]]; then
    echo "  → $AR_ORG_NOTES_REPO"
else
    echo "  → none"
fi
echo ""

# ── 7. Git identity ──────────────────────────────────────────────────
echo "─── Git Identity ───"
echo "  Used for Agentic Team-created commits when a project repo does not"
echo "  already have Git user.name/user.email configured."
echo ""
AR_GIT_NAME_DEFAULT="$(git config --global --get user.name 2>/dev/null || true)"
AR_GIT_NAME_DEFAULT="${AR_GIT_NAME_DEFAULT:-${USER:-Agentic Team}}"
AR_GIT_EMAIL_DEFAULT="$(git config --global --get user.email 2>/dev/null || true)"
AR_GIT_EMAIL_DEFAULT="${AR_GIT_EMAIL_DEFAULT:-${USER:-agentic-team}@example.invalid}"
read -rp "Git commit name [$AR_GIT_NAME_DEFAULT]: " AR_GIT_NAME
AR_GIT_NAME="${AR_GIT_NAME:-$AR_GIT_NAME_DEFAULT}"
read -rp "Git commit email [$AR_GIT_EMAIL_DEFAULT]: " AR_GIT_EMAIL
AR_GIT_EMAIL="${AR_GIT_EMAIL:-$AR_GIT_EMAIL_DEFAULT}"
echo "  → $AR_GIT_NAME <$AR_GIT_EMAIL>"
echo ""

# ── 8. Main agent ────────────────────────────────────────────────────
echo "─── Main Agent ───"
echo "  Top-level agent definition to render into the workspace instruction file."
echo "  Keep the default unless your Agentic Team install or org repo provides another"
echo "  agents/*.md definition with kind: main."
echo ""
AR_MAIN_AGENT_DEFAULT="research-coordinator"
read -rp "Main agent [$AR_MAIN_AGENT_DEFAULT]: " AR_MAIN_AGENT
AR_MAIN_AGENT="${AR_MAIN_AGENT:-$AR_MAIN_AGENT_DEFAULT}"
if [[ ! "$AR_MAIN_AGENT" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid main agent name, defaulting to $AR_MAIN_AGENT_DEFAULT"
    AR_MAIN_AGENT="$AR_MAIN_AGENT_DEFAULT"
fi
echo "  → $AR_MAIN_AGENT"
echo ""

# ── Write config (all values quoted for safety) ────────────────────
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" << EOF
# Agentic Team configuration
# Generated by: agentic-team --setup ($(date +%Y-%m-%d))

# Sandbox: apptainer | docker | podman | none
AR_SANDBOX="$AR_SANDBOX"

# Authentication: oauth | cli-tool | api-key
AR_AUTH_MODE="$AR_AUTH_MODE"

# Optional API provider metadata
AR_API_PROVIDER="$AR_API_PROVIDER"

# Optional env var name for launcher-managed API key validation
AR_API_KEY_ENV="$AR_API_KEY_ENV"

# Custom endpoints
AR_CUSTOM_ENDPOINT="$AR_CUSTOM_ENDPOINT"
AR_CUSTOM_ANTHROPIC_ENDPOINT="$AR_CUSTOM_ANTHROPIC_ENDPOINT"

# CLI: claude | opencode | gemini | codex | pi
AR_CLI="$AR_CLI"

# Default model
AR_DEFAULT_MODEL="$AR_DEFAULT_MODEL"

# Network proxy
AR_HTTPS_PROXY="$AR_HTTPS_PROXY"
AR_HTTP_PROXY="$AR_HTTP_PROXY"

# Base directory for local state, caches, and container temp data
AR_STATE_ROOT="$AR_STATE_ROOT"

# Optional visible AT workspace root. Blank means sibling <repo-name>-at.
AR_WORKSPACE_ROOT=""

# Extra directories to bind into the sandbox (colon-separated)
AR_EXTRA_BIND_DIRS="$AR_EXTRA_BIND_DIRS"

# Agentic Notes and main-agent configuration.
AR_ORG_NOTES_REPO="$AR_ORG_NOTES_REPO"
AR_MAIN_AGENT="$AR_MAIN_AGENT"
AR_USER_ID="\$USER"
AR_PROJECT_STATE_BRANCH="agentic/project-state"
AR_NOTES_AUTO_REFRESH="true"
# Git identity for Agentic Team-created commits when a repo lacks identity.
AR_GIT_NAME="$AR_GIT_NAME"
AR_GIT_EMAIL="$AR_GIT_EMAIL"
# Optional override for Agentic State commits. Blank means use AR_GIT_*.
AR_NOTES_GIT_NAME=""
AR_NOTES_GIT_EMAIL=""
AR_AUTO_BUILD="true"

# Enabled capabilities from capabilities/ (comma-separated)
AR_CAPABILITIES="agentic-notes,experiment-log"
EOF

echo "════════════════════════════════════════════════════════════════"
echo "Configuration saved to: $CONFIG_FILE"
echo ""
echo "Tip: Change individual settings later with:"
echo "  agentic-team --setup KEY=VALUE"
echo ""
echo "Next steps:"
if [[ "$AR_SANDBOX" == "none" ]]; then
    echo "  1. Make sure '$AR_CLI' is installed on PATH"
    echo "  2. Launch from your project Git checkout: agentic-team ~/your-project"
    echo "     If you are on main/master, Agentic Team can prompt to create a work branch."
elif [[ "$AR_CLI" == "claude" ]]; then
    echo "  1. Launch from your project Git checkout: agentic-team ~/your-project  (will prompt for OAuth login)"
    echo "     If you are on main/master, Agentic Team can prompt to create a work branch."
    echo "     The container image builds automatically on first launch."
else
    echo "  1. Launch from your project Git checkout: agentic-team ~/your-project"
    echo "     If you are on main/master, Agentic Team can prompt to create a work branch."
    echo "     The container image builds automatically on first launch."
    echo "  2. If needed, export the selected CLI's standard API key env var before launch"
fi
echo "════════════════════════════════════════════════════════════════"
