#!/bin/bash
#
# entrypoint.sh: Docker entrypoint for Agentic Researcher container.
# Equivalent to Apptainer %runscript.
#

set -euo pipefail
CONTAINER_HOME="${AR_SANDBOX_HOME:-${HOME:-/agent-home}}"
export AR_SANDBOX_HOME="$CONTAINER_HOME"

is_valid_linux_name() {
    [[ "$1" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]
}

prepare_home_layout_for_user() {
    local host_uid="$1"
    local host_gid="$2"
    local writable_dirs=(
        "$CONTAINER_HOME"
        "$CONTAINER_HOME/.config"
        "$CONTAINER_HOME/.cache"
        "$CONTAINER_HOME/.local"
        "$CONTAINER_HOME/.local/bin"
        "$CONTAINER_HOME/.local/share"
        "$CONTAINER_HOME/.local/state"
        "$CONTAINER_HOME/.claude"
        "$CONTAINER_HOME/.gemini"
        "$CONTAINER_HOME/.gemini/skills"
        "$CONTAINER_HOME/.gemini/agents"
        "$CONTAINER_HOME/.gemini/history"
        "$CONTAINER_HOME/.gemini/tmp"
        "$CONTAINER_HOME/.gemini/tmp/bin"
        "$CONTAINER_HOME/.codex"
        "$CONTAINER_HOME/.pi"
        "$CONTAINER_HOME/.pi/agent"
        "$CONTAINER_HOME/.opencode"
        "$CONTAINER_HOME/.opencode/bin"
    )

    mkdir -p "${writable_dirs[@]}"
    chown "$host_uid:$host_gid" "${writable_dirs[@]}"
}

setup_container_user() {
    if [[ "$(id -u)" -ne 0 || "${AR_USER_READY:-0}" == "1" ]]; then
        return
    fi

    local host_uid="${HOST_UID:-1000}"
    local host_gid="${HOST_GID:-1000}"
    local requested_user="${HOST_USER:-agent}"
    local requested_group="${HOST_GROUP:-$requested_user}"
    local container_user="$requested_user"
    local container_group="$requested_group"

    if ! is_valid_linux_name "$requested_group"; then
        container_group="hostgrp-${host_gid}"
    fi
    if ! is_valid_linux_name "$requested_user"; then
        container_user="hostuser-${host_uid}"
    fi

    if getent group "$host_gid" >/dev/null 2>&1; then
        container_group="$(getent group "$host_gid" | cut -d: -f1)"
    elif is_valid_linux_name "$requested_group" && getent group "$requested_group" >/dev/null 2>&1; then
        container_group="hostgrp-${host_gid}"
        groupadd -g "$host_gid" "$container_group"
    else
        groupadd -g "$host_gid" "$container_group"
    fi

    if getent passwd "$host_uid" >/dev/null 2>&1; then
        container_user="$(getent passwd "$host_uid" | cut -d: -f1)"
    elif is_valid_linux_name "$requested_user" && getent passwd "$requested_user" >/dev/null 2>&1; then
        container_user="hostuser-${host_uid}"
        useradd -l -u "$host_uid" -g "$host_gid" -d "$CONTAINER_HOME" -M -N -s /bin/bash "$container_user"
    else
        useradd -l -u "$host_uid" -g "$host_gid" -d "$CONTAINER_HOME" -M -N -s /bin/bash "$container_user"
    fi

    # Docker may auto-create bind-mount parents under the synthetic home as root.
    # Pre-create and chown the writable home layout before dropping privileges.
    prepare_home_layout_for_user "$host_uid" "$host_gid"

    export HOME="$CONTAINER_HOME"
    export USER="$container_user"
    export LOGNAME="$container_user"
    export AR_USER_READY=1

    exec gosu "$host_uid:$host_gid" "$0" "$@"
}

setup_container_user "$@"

setup_home_layout() {
    mkdir -p \
        "$HOME/.config" \
        "$HOME/.cache" \
        "$HOME/.local/bin" \
        "$HOME/.local/share" \
        "$HOME/.local/state" \
        "$HOME/.claude" \
        "$HOME/.config/opencode" \
        "$HOME/.local/share/opencode" \
        "$HOME/.gemini/skills" \
        "$HOME/.gemini/agents" \
        "$HOME/.gemini/history" \
        "$HOME/.gemini/tmp/bin" \
        "$HOME/.gemini" \
        "$HOME/.codex" \
        "$HOME/.pi/agent" \
        "$HOME/.opencode/bin" 2>/dev/null

    if [[ ! -f "$HOME/.gemini/projects.json" ]]; then
        printf '{\n  "projects": {}\n}\n' > "$HOME/.gemini/projects.json" 2>/dev/null || true
    fi
    if [[ ! -f "$HOME/.gemini/settings.json" ]]; then
        printf '{}\n' > "$HOME/.gemini/settings.json" 2>/dev/null || true
    fi

    export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
    export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
}

link_tool_binary() {
    local tool_name="$1"
    local target_path="$2"
    local tool_bin

    tool_bin="$(command -v "$tool_name" 2>/dev/null || true)"
    if [[ -n "$tool_bin" ]]; then
        ln -sf "$tool_bin" "$target_path" 2>/dev/null
    fi
}

setup_home_layout

# Create symlinks so tools find binaries at native install paths
link_tool_binary claude "$HOME/.local/bin/claude"
link_tool_binary opencode "$HOME/.opencode/bin/opencode"
link_tool_binary gemini "$HOME/.local/bin/gemini"
link_tool_binary codex "$HOME/.local/bin/codex"
link_tool_binary pi "$HOME/.local/bin/pi"

# Multi-tool dispatch: check SANDBOX_TOOL env var
case "${SANDBOX_TOOL:-claude}" in
    claude)   exec claude "$@" ;;
    opencode) exec opencode "$@" ;;
    gemini)   exec gemini "$@" ;;
    codex)    exec codex "$@" ;;
    pi)       exec pi "$@" ;;
    *)        echo "Unknown tool: $SANDBOX_TOOL"; exit 1 ;;
esac
