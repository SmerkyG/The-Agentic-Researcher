#!/bin/bash

oci_image_exists() {
    local oci_runtime="$1"
    command -v "$oci_runtime" >/dev/null 2>&1 || return 1
    "$oci_runtime" image inspect agentic-team:latest >/dev/null 2>&1
}

oci_build_image() {
    local oci_runtime="$1"
    local first_char rest first_char_upper runtime_name

    if ! command -v "$oci_runtime" >/dev/null 2>&1; then
        echo "Error: '$oci_runtime' is not installed or not on PATH."
        echo ""
        echo "Install $oci_runtime on the host, then rerun:"
        echo "  $SCRIPT_DIR/container/build.sh --runtime $oci_runtime"
        return 1
    fi

    first_char="${oci_runtime%${oci_runtime#?}}"
    rest="${oci_runtime#?}"
    first_char_upper="$(printf '%s' "$first_char" | tr '[:lower:]' '[:upper:]')"
    runtime_name="${first_char_upper}${rest}"

    echo "Building ${runtime_name} container..."
    if [[ "$oci_runtime" == "podman" ]]; then
        "$oci_runtime" build --format docker -t agentic-team:latest "$SCRIPT_DIR/container"
    else
        "$oci_runtime" build -t agentic-team:latest "$SCRIPT_DIR/container"
    fi
    echo ""
    echo "${runtime_name} image built: agentic-team:latest"
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
        -v "$STATE_ROOT:$STATE_ROOT"
        -v "$AR_WORKSPACE_ROOT:$AR_WORKSPACE_ROOT"
        -v "$AR_RUNTIME_ROOT:$AR_RUNTIME_ROOT"
        -v "$AR_ARTIFACTS_DIR:$AR_ARTIFACTS_DIR"
        -v "$AR_CONFIG_STORE:$AR_SANDBOX_HOME"
        -w /workspace
    )
    append_storage_bind_args OCI_ARGS -v

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
        -e "UV_LINK_MODE=symlink"
        -e "TERM=${TERM:-xterm-256color}"
        -e "HOME=$AR_SANDBOX_HOME"
        -e "HOST_UID=$host_uid"
        -e "HOST_GID=$host_gid"
        -e "HOST_USER=$host_user"
        -e "HOST_GROUP=$host_group"
        -e "SANDBOX_CLI=$AR_CLI"
    )
    append_storage_env_args OCI_ARGS -e
    append_ar_runtime_env_args OCI_ARGS -e

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
        OCI_ARGS+=(-e "AR_CLI=$AR_CLI")
        "${OCI_ARGS[@]}" agentic-team:latest /test_sandbox.sh
    else
        "${OCI_ARGS[@]}" agentic-team:latest "${CLI_ARGS[@]}"
    fi
}
