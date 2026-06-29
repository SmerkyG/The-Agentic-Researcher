#!/bin/bash

oci_image_exists() {
    local oci_runtime="$1"
    command -v "$oci_runtime" >/dev/null 2>&1 || return 1
    "$oci_runtime" image inspect agentic-researcher:latest >/dev/null 2>&1
}

oci_build_image() {
    local oci_runtime="$1"
    "$SCRIPT_DIR/container/build.sh" --runtime "$oci_runtime"
}

oci_launch() {
    local oci_runtime="$1"
    local mode="${2:-run}"
    local host_uid host_gid host_user host_group

    if ! command -v "$oci_runtime" >/dev/null 2>&1; then
        echo "Error: $oci_runtime sandbox selected, but '$oci_runtime' is not installed or not on PATH."
        echo ""
        echo "Install $oci_runtime on the host, then rerun:"
        echo "  $SCRIPT_DIR/container/build.sh --runtime $oci_runtime"
        exit 1
    fi

    host_uid="$(id -u)"
    host_gid="$(id -g)"
    host_user="$(id -un)"
    host_group="$(id -gn)"

    local OCI_ARGS=(
        "$oci_runtime" run --rm
        --init
        -v "$WORKSPACE_DIR:/workspace"
        -v "$SCRIPT_DIR:$AR_INSTALL_CONTAINER_DIR:ro"
        -v "$UV_CACHE_DIR:/uv-cache"
        -v "$UV_PYTHON_INSTALL_DIR:/uv-python"
        -v "$UV_TOOL_DIR:/uv-tools"
        -v "$STATE_ROOT:$STATE_ROOT"
        -v "$AR_CONFIG_STORE:$AR_SANDBOX_HOME"
        -w /workspace
    )

    if [[ -t 0 && -t 1 ]]; then
        OCI_ARGS+=(-it)
    fi

    if [[ "$oci_runtime" == "podman" ]]; then
        OCI_ARGS+=(--userns keep-id)
    fi

    # Only request Docker GPU support when the host plausibly has an NVIDIA runtime.
    if [[ "$oci_runtime" == "docker" ]]; then
        case "${AR_DOCKER_GPUS:-auto}" in
            all)
                OCI_ARGS+=(--gpus all)
                ;;
            auto)
                if [[ "$(uname -s)" == "Linux" ]] && command -v nvidia-smi >/dev/null 2>&1; then
                    OCI_ARGS+=(--gpus all)
                fi
                ;;
            none)
                ;;
        esac
    fi

    # Extra bind dirs. The EXTRA_DIR_*_BIND arrays are built for Apptainer, where
    # each mount is stored as two separate array elements ("--bind" and
    # "host:container"). Skip the flag markers and pass only the spec to -v.
    local dir_bind
    for dir_bind in "${EXTRA_DIR_ROOT_BIND[@]}" "${EXTRA_DIR_BINDS[@]}"; do
        [[ -n "$dir_bind" ]] || continue
        [[ "$dir_bind" == "--bind" ]] && continue
        OCI_ARGS+=(-v "$dir_bind")
    done

    OCI_ARGS+=(
        -e "UV_CACHE_DIR=/uv-cache"
        -e "UV_PYTHON_INSTALL_DIR=/uv-python"
        -e "UV_TOOL_DIR=/uv-tools"
        -e "UV_LINK_MODE=symlink"
        -e "HF_HOME=$HF_HOME"
        -e "TRITON_CACHE_DIR=$TRITON_CACHE_DIR"
        -e "WANDB_DIR=$WANDB_DIR"
        -e "TERM=${TERM:-xterm-256color}"
        -e "HOME=$AR_SANDBOX_HOME"
        -e "HOST_UID=$host_uid"
        -e "HOST_GID=$host_gid"
        -e "HOST_USER=$host_user"
        -e "HOST_GROUP=$host_group"
        -e "SANDBOX_TOOL=$AR_CLI_TOOL"
        -e "AR_SANDBOX=$AR_SANDBOX"
        -e "AR_SANDBOX_HOME=$AR_SANDBOX_HOME"
        -e "AR_INSTALL_DIR=$(ar_install_env_path)"
        -e "AR_NOTES_CLI=$(ar_notes_cli_env_path)"
        -e "AR_JOB_BACKEND=${JOB_BACKEND:-none}"
        -e "AR_STATE_ROOT=$STATE_ROOT"
        -e "AR_ORG_NOTES_REPO=${AR_ORG_NOTES_REPO:-}"
        -e "AR_MAIN_AGENT=${AR_MAIN_AGENT:-research-coordinator}"
        -e "AR_USER_ID=${AR_USER_ID:-$USER}"
        -e "AR_PROJECT_ID=${AR_PROJECT_ID:-}"
        -e "AR_AGENTIC_STATE_BRANCH=${AR_AGENTIC_STATE_BRANCH:-agentic/state}"
        -e "AR_NOTES_AUTO_REFRESH=${AR_NOTES_AUTO_REFRESH:-true}"
        -e "AR_RESOLVER_GIT_NAME=${AR_RESOLVER_GIT_NAME:-}"
        -e "AR_RESOLVER_GIT_EMAIL=${AR_RESOLVER_GIT_EMAIL:-}"
        -e "AR_NOTES_GIT_NAME=${AR_NOTES_GIT_NAME:-}"
        -e "AR_NOTES_GIT_EMAIL=${AR_NOTES_GIT_EMAIL:-}"
    )

    if [[ -n "${AR_HTTPS_PROXY:-}" ]]; then
        OCI_ARGS+=(-e "https_proxy=$AR_HTTPS_PROXY" -e "http_proxy=${AR_HTTP_PROXY:-$AR_HTTPS_PROXY}")
    fi

    if [[ -n "${AR_EXTRA_ENV:-}" ]]; then
        local IFS='|'
        local entry
        for entry in $AR_EXTRA_ENV; do
            [[ -n "$entry" ]] && OCI_ARGS+=(-e "$entry")
        done
    fi

    cli_call add_oci_args

    if [[ -d "$HOME/.ssh" ]]; then
        OCI_ARGS+=(-v "$HOME/.ssh:$AR_SANDBOX_HOME/.ssh:ro")
    fi
    if [[ -f "$HOME/.gitconfig" ]]; then
        OCI_ARGS+=(-v "$HOME/.gitconfig:$AR_SANDBOX_HOME/.gitconfig:ro")
    fi

    if [[ "$mode" == "test" ]]; then
        OCI_ARGS+=(--entrypoint /bin/bash)
        OCI_ARGS+=(-v "$SCRIPT_DIR/scripts/test_sandbox.sh:/test_sandbox.sh:ro")
        OCI_ARGS+=(-e "AR_CLI_TOOL=$AR_CLI_TOOL")
        "${OCI_ARGS[@]}" agentic-researcher:latest /test_sandbox.sh
    else
        "${OCI_ARGS[@]}" agentic-researcher:latest "${TOOL_ARGS[@]}"
    fi
}
