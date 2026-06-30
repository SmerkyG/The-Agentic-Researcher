# Sourced by agentic-researcher. Runtime bind, environment, debug, and launch command helpers.

setup_auth_binds() {
    SSH_BIND=()
    GIT_SSH_COMMAND="ssh"

    if [[ -d "$HOME/.ssh" ]]; then
        SSH_BIND=(--bind "$HOME/.ssh:$AR_SANDBOX_HOME/.ssh:ro")

        # Parse proxy for SSH tunneling
        local proxy_url="${AR_HTTPS_PROXY:-${HTTPS_PROXY:-${https_proxy:-}}}"
        local proxy_host proxy_port
        proxy_host=$(echo "$proxy_url" | sed 's|^https\?://||; s|:.*||')
        proxy_port=$(echo "$proxy_url" | sed 's|^https\?://[^:]*:||; s|/.*||')

        if [[ -n "$proxy_host" && -n "$proxy_port" ]]; then
            SSH_BIND+=(--bind "$SCRIPT_DIR/scripts/ssh-proxy-connect.py:/ssh-proxy-connect.py:ro")
            GIT_SSH_COMMAND="ssh -o ProxyCommand='/ssh-proxy-connect.py ${proxy_host} ${proxy_port} %h %p'"
        fi
    fi

    if [[ -f "$HOME/.gitconfig" ]]; then
        SSH_BIND+=(--bind "$HOME/.gitconfig:$AR_SANDBOX_HOME/.gitconfig:ro")
    fi
    if [[ -f "$HOME/.bashrc" ]]; then
        SSH_BIND+=(--bind "$HOME/.bashrc:$AR_SANDBOX_HOME/.bashrc:ro")
    fi
}
setup_research_binds() {
    RESEARCH_BINDS=()
}
sanitize_mount_name() {
    local raw_name="$1"
    local sanitized

    sanitized="$(printf '%s' "$raw_name" | tr -c 'A-Za-z0-9._-' '_')"
    if [[ -z "$sanitized" ]]; then
        sanitized="mount"
    fi

    printf '%s\n' "$sanitized"
}
setup_workspace_mount_root() {
    WORKSPACE_MOUNT_PLACEHOLDER_DIR="$WORKSPACE_DIR/.mount"
    WORKSPACE_MOUNT_STATE_DIR="$STATE_ROOT/workspace-mounts/$(printf '%s' "$WORKSPACE_DIR" | cksum | awk '{print $1}')"

    mkdir -p "$WORKSPACE_MOUNT_PLACEHOLDER_DIR" "$WORKSPACE_MOUNT_STATE_DIR"
    EXTRA_DIR_ROOT_BIND=(--bind "$WORKSPACE_MOUNT_STATE_DIR:/workspace/.mount")
}
setup_optional_binds() {
    DATASET_BINDS=()

    # Extra directories from config (colon-separated after normalization)
    EXTRA_DIR_ROOT_BIND=()
    EXTRA_DIR_BINDS=()
    EXTRA_DIR_DEBUG_MOUNTS=()
    if [[ "$AR_SANDBOX" == "none" ]]; then
        if [[ -n "${AR_EXTRA_BIND_DIRS:-}" ]]; then
            echo "No-sandbox mode: AR_EXTRA_BIND_DIRS is ignored because host paths are directly accessible."
        fi
        return
    fi
    if [[ -n "${AR_EXTRA_BIND_DIRS:-}" ]]; then
        local used_mount_names=()

        # Normalize: accept commas, spaces, or colons as separators
        local normalized
        normalized=$(echo "$AR_EXTRA_BIND_DIRS" | tr ',' ':' | tr ' ' ':' | sed 's/::/:/g; s/^://; s/:$//')
        IFS=':' read -ra dirs <<< "$normalized"
        setup_workspace_mount_root
        for dir in "${dirs[@]}"; do
            local mount_name host_mount_dir container_mount_dir

            [[ -z "$dir" ]] && continue
            if [[ "$dir" == "$WORKSPACE_DIR/.mount" || "$dir" == "$WORKSPACE_DIR/.mount/"* ]]; then
                echo "Warning: Skipping extra bind inside reserved workspace mount root: $dir"
                continue
            fi
            if [[ -d "$dir" ]]; then
                mount_name="$(sanitize_mount_name "$(basename "$dir")")"
                if [[ " ${used_mount_names[*]} " == *" $mount_name "* ]]; then
                    echo "Warning: Skipping extra bind with duplicate mount name '$mount_name': $dir"
                    continue
                fi

                used_mount_names+=("$mount_name")
                host_mount_dir="$WORKSPACE_MOUNT_STATE_DIR/$mount_name"
                container_mount_dir="/workspace/.mount/$mount_name"
                mkdir -p "$host_mount_dir"

                EXTRA_DIR_BINDS+=(--bind "$dir:$container_mount_dir")
                EXTRA_DIR_DEBUG_MOUNTS+=("$dir -> $container_mount_dir")
            else
                echo "Warning: Extra bind directory not found: $dir"
            fi
        done
    fi
}
build_env_args() {
    ENV_ARGS=(
        --env UV_CACHE_DIR=/uv-cache
        --env UV_PYTHON_INSTALL_DIR=/uv-python
        --env UV_TOOL_DIR=/uv-tools
        --env UV_LINK_MODE=symlink
        --env "HF_HOME=$HF_HOME"
        --env "TRITON_CACHE_DIR=$TRITON_CACHE_DIR"
        --env "WANDB_DIR=$WANDB_DIR"
        --env "TERM=${TERM:-xterm-256color}"
        --env "USER=$USER"
        --env "GIT_SSH_COMMAND=$GIT_SSH_COMMAND"
        --env "AR_SANDBOX=$AR_SANDBOX"
        --env "AR_SANDBOX_HOME=$AR_SANDBOX_HOME"
        --env "AR_INSTALL_DIR=$(ar_install_env_path)"
        --env "AR_NOTES_CLI=$(ar_notes_cli_env_path)"
        --env "AR_TOOL_CLI=$(ar_tool_cli_env_path)"
        --env "AR_PROVIDER_REFRESH_CLI=$(provider_refresh_cli_env_path)"
        --env "AR_JOB_BACKEND=${JOB_BACKEND:-none}"
        --env "AR_STATE_ROOT=$STATE_ROOT"
        --env "AR_ORG_NOTES_REPO=${AR_ORG_NOTES_REPO:-}"
        --env "AR_MAIN_AGENT=${AR_MAIN_AGENT:-research-coordinator}"
        --env "AR_INSTRUCTION_PROVIDERS=${AR_INSTRUCTION_PROVIDERS:-agentic-notes,experiment-log}"
        --env "AR_AGENT_BRANCH=${AR_AGENT_BRANCH:-}"
        --env "AR_AGENT_BRANCH_ID=${AR_AGENT_BRANCH_ID:-}"
        --env "AR_AGENT_TOPIC=${AR_AGENT_TOPIC:-}"
        --env "AR_AGENT_BRANCH_PREFIX=${AR_AGENT_BRANCH_PREFIX:-}"
        --env "AR_BRANCH_OWNERSHIP=${AR_BRANCH_OWNERSHIP:-exclusive}"
        --env "AR_SESSION_ID=${AR_SESSION_ID:-}"
        --env "AR_USER_ID=${AR_USER_ID:-$USER}"
        --env "AR_PROJECT_ID=${AR_PROJECT_ID:-}"
        --env "AR_AGENTIC_STATE_BRANCH=${AR_AGENTIC_STATE_BRANCH:-agentic/state}"
        --env "AR_NOTES_AUTO_REFRESH=${AR_NOTES_AUTO_REFRESH:-true}"
        --env "AR_NOTES_REFRESH_MODE=${AR_NOTES_REFRESH_MODE:-periodic}"
        --env "AR_NOTES_REFRESH_INTERVAL_SECONDS=${AR_NOTES_REFRESH_INTERVAL_SECONDS:-120}"
        --env "AR_RESOLVER_GIT_NAME=${AR_RESOLVER_GIT_NAME:-}"
        --env "AR_RESOLVER_GIT_EMAIL=${AR_RESOLVER_GIT_EMAIL:-}"
        --env "AR_NOTES_GIT_NAME=${AR_NOTES_GIT_NAME:-}"
        --env "AR_NOTES_GIT_EMAIL=${AR_NOTES_GIT_EMAIL:-}"
    )

    # Proxy
    if [[ -n "${AR_HTTPS_PROXY:-}" ]]; then
        ENV_ARGS+=(--env "https_proxy=$AR_HTTPS_PROXY" --env "http_proxy=${AR_HTTP_PROXY:-$AR_HTTPS_PROXY}")
    elif [[ -n "${HTTPS_PROXY:-}" ]]; then
        ENV_ARGS+=(--env "https_proxy=$HTTPS_PROXY" --env "http_proxy=${HTTP_PROXY:-$HTTPS_PROXY}")
    fi

    cli_call add_env_args

    # Extra user-defined environment variables (pipe-separated KEY=VALUE pairs)
    if [[ -n "${AR_EXTRA_ENV:-}" ]]; then
        local IFS='|'
        for entry in $AR_EXTRA_ENV; do
            [[ -n "$entry" ]] && ENV_ARGS+=(--env "$entry")
        done
    fi
}
print_debug_launch() {
    if [[ "$DEBUG_LAUNCH" != "true" ]]; then
        return
    fi

    echo "Launch debug:"
    echo "  Sandbox:        $AR_SANDBOX"
    echo "  Tool:           $AR_CLI_TOOL"
    echo "  Agent branch:   ${AR_AGENT_BRANCH:-none}"
    echo "  Current branch: ${WORKSPACE_GIT_BRANCH:-none}"
    echo "  Ownership:      ${AR_BRANCH_OWNERSHIP:-exclusive}"
    echo "  Job backend:    ${JOB_BACKEND:-none}"
    echo "  Workspace:      $WORKSPACE_DIR"
    echo "  State root:     $STATE_ROOT"
    if [[ "$AR_SANDBOX" == "docker" || "$AR_SANDBOX" == "podman" ]]; then
        echo "  Container image: agentic-researcher:latest"
    elif [[ "$AR_SANDBOX" == "none" ]]; then
        echo "  Container image: none (sandbox none)"
    else
        echo "  Container:      $CONTAINER_IMAGE"
    fi
    echo "  Tool args:      ${TOOL_ARGS[*]:-(none)}"
    if [[ ${#EXTRA_DIR_DEBUG_MOUNTS[@]} -gt 0 ]]; then
        echo "  Extra mounts:"
        for mount_line in "${EXTRA_DIR_DEBUG_MOUNTS[@]}"; do
            echo "    $mount_line"
        done
    fi
    if [[ -n "${AR_EXTRA_ENV:-}" ]]; then
        echo "  Extra env:      $AR_EXTRA_ENV"
    fi
    echo ""
}
native_tool_command() {
    cli_call_required native_command
}

