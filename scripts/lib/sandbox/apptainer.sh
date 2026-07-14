#!/bin/bash

register_sandbox_adapter apptainer 30

sandbox_apptainer_validate_host() {
    local host_os
    host_os="$(uname -s)"

    if [[ "$host_os" != "Linux" ]]; then
        echo "Error: Apptainer is only supported on Linux hosts. Current host: $host_os"
        echo ""
        echo "Use Docker on this machine instead:"
        echo "  agentic-team --sandbox docker ..."
        echo ""
        echo "To test Apptainer, run the launcher on a Linux workstation, WSL2 instance, or cluster node."
        exit 1
    fi

    if ! command -v apptainer >/dev/null 2>&1; then
        echo "Error: Apptainer sandbox selected, but 'apptainer' is not installed or not on PATH."
        echo ""
        echo "Install Apptainer on the Linux host, then rerun:"
        echo "  $SCRIPT_DIR/container/build.sh --runtime apptainer"
        exit 1
    fi
}

sandbox_apptainer_image_exists() {
    [[ -f "$SCRIPT_DIR/container/agentic_team.sif" ]]
}

sandbox_apptainer_setup_storage() {
    APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$STATE_ROOT/apptainer_cache}"
    CONTAINER_TMP="${APPTAINER_TMPDIR:-$APPTAINER_CACHEDIR/container-tmp}"
    export APPTAINER_CACHEDIR
    mkdir -p -m 700 "$APPTAINER_CACHEDIR" "$CONTAINER_TMP"
}

sandbox_apptainer_build_image() {
    sandbox_apptainer_validate_host

    local state_root="${AR_STATE_ROOT:-$HOME/.cache/agentic-team}"
    APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$state_root/apptainer_cache}"
    APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$state_root/apptainer_tmp}"
    export APPTAINER_CACHEDIR APPTAINER_TMPDIR
    mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"

    echo "Building Apptainer container..."
    echo "This may take 5-10 minutes on first build."
    echo ""

    apptainer build \
        --force \
        "$SCRIPT_DIR/container/agentic_team.sif" \
        "$SCRIPT_DIR/container/agentic_team.def"

    echo ""
    echo "Container built successfully: $SCRIPT_DIR/container/agentic_team.sif"
    echo "Generating integrity checksum..."
    (
        cd "$SCRIPT_DIR/container"
        sha256sum agentic_team.sif > agentic_team.sif.sha256
    )
    echo "Checksum saved to: $SCRIPT_DIR/container/agentic_team.sif.sha256"
}

sandbox_apptainer_validate() {
    sandbox_apptainer_validate_host
    CONTAINER_IMAGE="$SCRIPT_DIR/container/agentic_team.sif"
    if [[ ! -f "$CONTAINER_IMAGE" ]]; then
        echo "Error: Container image not found after build: $CONTAINER_IMAGE"
        exit 1
    fi

    if [[ -f "$CONTAINER_IMAGE.sha256" ]]; then
        if ! (cd "$SCRIPT_DIR/container" && sha256sum -c "agentic_team.sif.sha256" &>/dev/null); then
            echo "Error: Container image integrity check failed!"
            echo "The container may have been tampered with."
            exit 1
        fi
    else
        echo "Warning: No checksum file found. Skipping integrity verification."
    fi

    if [[ ! -x "$SCRIPT_DIR/scripts/pty-wrapper.py" ]]; then
        echo "Error: pty-wrapper.py not found or not executable"
        exit 1
    fi
}

sandbox_apptainer_launch() {
    local mode="${1:-run}"

    local BIND_ARGS=(
        --nv
        --compat
        --no-mount home
        --home "$AR_SANDBOX_HOME"
        "${SSH_BIND[@]}"
        --bind "$WORKSPACE_DIR:/workspace"
        --bind "$SCRIPT_DIR:$AR_INSTALL_CONTAINER_DIR:ro"
        --bind "$CONTAINER_TMP:/tmp"
        --bind "$STATE_ROOT:$STATE_ROOT"
        --bind "$AR_WORKSPACE_ROOT:$AR_WORKSPACE_ROOT"
        --bind "$AR_RUNTIME_ROOT:$AR_RUNTIME_ROOT"
        --bind "$AR_ARTIFACTS_DIR:$AR_ARTIFACTS_DIR"
        "${DATASET_BINDS[@]}"
        "${EXTRA_DIR_ROOT_BIND[@]}"
        "${EXTRA_DIR_BINDS[@]}"
        "${CAPABILITY_BINDS[@]}"
        --pwd /workspace
    )
    append_storage_bind_args BIND_ARGS --bind

    cli_call add_apptainer_binds

    ENV_ARGS+=("${CAPABILITY_ENV[@]}")

    if [[ "$mode" == "test" ]]; then
        BIND_ARGS+=(
            --bind "$SCRIPT_DIR/scripts/test_sandbox.sh:/test_sandbox.sh:ro"
        )
        ENV_ARGS+=(--env "AR_CLI=$AR_CLI")

        apptainer exec \
            "${BIND_ARGS[@]}" \
            "${ENV_ARGS[@]}" \
            "$CONTAINER_IMAGE" \
            /bin/bash /test_sandbox.sh
    else
        "$SCRIPT_DIR/scripts/pty-wrapper.py" apptainer run \
            "${BIND_ARGS[@]}" \
            "${ENV_ARGS[@]}" \
            "$CONTAINER_IMAGE" \
            "${CLI_ARGS[@]}"
    fi
}
