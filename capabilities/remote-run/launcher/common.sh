_remote_run_die() {
    echo "Error: $*" >&2
    exit 1
}

_remote_run_detect_allocation() {
    [[ "${REMOTE_RUN_ALLOCATION_DETECTED:-false}" == "true" ]] && return 0

    if [[ "$AR_SANDBOX" != "apptainer" ]]; then
        _remote_run_die "remote-run capability requires --sandbox apptainer."
    fi

    if [[ -z "${SLURM_JOB_ID:-}" ]]; then
        _remote_run_die "remote-run capability requires an active multi-node Slurm allocation."
    fi

    if [[ -z "${SLURM_JOB_NODELIST:-}" ]]; then
        _remote_run_die "remote-run capability requires SLURM_JOB_NODELIST."
    fi

    if ! command -v scontrol >/dev/null 2>&1; then
        _remote_run_die "remote-run capability requires 'scontrol' on PATH."
    fi

    REMOTE_RUN_NODELIST="$SLURM_JOB_NODELIST"
    REMOTE_RUN_NUM_NODES="$(scontrol show hostnames "$REMOTE_RUN_NODELIST" | wc -l | tr -d ' ')"
    REMOTE_RUN_HEAD_NODE="$(hostname -s)"

    REMOTE_RUN_GPUS_PER_NODE="${SLURM_GPUS_ON_NODE:-}"
    if [[ -z "$REMOTE_RUN_GPUS_PER_NODE" ]]; then
        REMOTE_RUN_GPUS_PER_NODE="$(scontrol show job "$SLURM_JOB_ID" 2>/dev/null \
            | tr ' ' '\n' \
            | sed -nE 's/^TresPerNode=gres\/gpu(:[A-Za-z0-9._-]+)?:([0-9]+).*/\2/p' \
            | tail -1)"
    fi
    if [[ -z "$REMOTE_RUN_GPUS_PER_NODE" ]]; then
        REMOTE_RUN_GPUS_PER_NODE="$(nvidia-smi -L 2>/dev/null | wc -l | tr -d ' ')"
    fi
    if [[ -z "$REMOTE_RUN_GPUS_PER_NODE" || "$REMOTE_RUN_GPUS_PER_NODE" -eq 0 ]]; then
        echo "Warning: Could not detect GPUs per node, defaulting to 4"
        REMOTE_RUN_GPUS_PER_NODE=4
    fi

    REMOTE_RUN_ALLOCATION_DETECTED=true
}

_remote_run_write_dispatch_config() {
    _remote_run_detect_allocation

    DISPATCH_DIR="$RUNTIME_ROOT/dispatch/$SLURM_JOB_ID"
    AR_SANDBOX_HOME="${AR_SANDBOX_HOME:-/agent-home}"
    mkdir -p "$DISPATCH_DIR/jobs"

    if [[ "${REMOTE_RUN_DISPATCH_CONFIG_WRITTEN:-false}" == "true" && -f "$DISPATCH_DIR/dispatch.conf" ]]; then
        return 0
    fi

    cat > "$DISPATCH_DIR/dispatch.conf" << DISPEOF
DISPATCH_DIR="$DISPATCH_DIR"
CONTAINER_IMAGE="$CONTAINER_IMAGE"
WORKSPACE_HOST="$WORKSPACE_DIR"
AR_INSTALL_HOST="$SCRIPT_DIR"
AR_INSTALL_CONTAINER="$AR_INSTALL_CONTAINER_DIR"
AR_SANDBOX_HOME="$AR_SANDBOX_HOME"
STATE_ROOT="$STATE_ROOT"
AR_WORKSPACE_ROOT="$AR_WORKSPACE_ROOT"
RUNTIME_ROOT="$RUNTIME_ROOT"
AR_ARTIFACTS_DIR="$AR_ARTIFACTS_DIR"
UV_CACHE_DIR="$UV_CACHE_DIR"
UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR"
UV_TOOL_DIR="$UV_TOOL_DIR"
HF_HOME="$HF_HOME"
TRITON_CACHE_DIR="$TRITON_CACHE_DIR"
WANDB_DIR="$WANDB_DIR"
HTTPS_PROXY="${AR_HTTPS_PROXY:-${HTTPS_PROXY:-}}"
HTTP_PROXY="${AR_HTTP_PROXY:-${HTTP_PROXY:-}}"
HEAD_NODE="$REMOTE_RUN_HEAD_NODE"
SLURM_JOB_ID="$SLURM_JOB_ID"
SLURM_JOB_NODELIST="$REMOTE_RUN_NODELIST"
DISPEOF

    write_ar_runtime_env_array_assignment AR_RUNTIME_ENV_PAIRS >> "$DISPATCH_DIR/dispatch.conf"
    REMOTE_RUN_DISPATCH_CONFIG_WRITTEN=true
}
