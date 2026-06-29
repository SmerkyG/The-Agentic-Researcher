remote_run_die() {
    echo "Error: $*" >&2
    exit 1
}

remote_run_detect() {
    if [[ "$AR_SANDBOX" != "apptainer" ]]; then
        remote_run_die "remote-run optional skill requires --sandbox apptainer."
    fi

    if [[ -z "${SLURM_JOB_ID:-}" ]]; then
        remote_run_die "remote-run optional skill requires an active multi-node Slurm allocation."
    fi

    if [[ -z "${SLURM_JOB_NODELIST:-}" ]]; then
        remote_run_die "remote-run optional skill requires SLURM_JOB_NODELIST."
    fi

    if ! command -v scontrol >/dev/null 2>&1; then
        remote_run_die "remote-run optional skill requires 'scontrol' on PATH."
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
}

remote_run_write_dispatch_config() {
    DISPATCH_DIR="$STATE_ROOT/dispatch-$SLURM_JOB_ID"
    AR_SANDBOX_HOME="${AR_SANDBOX_HOME:-/agent-home}"
    mkdir -p "$DISPATCH_DIR/jobs"

    cat > "$DISPATCH_DIR/dispatch.conf" << DISPEOF
DISPATCH_DIR="$DISPATCH_DIR"
CONTAINER_IMAGE="$CONTAINER_IMAGE"
WORKSPACE_HOST="$WORKSPACE_DIR"
AR_INSTALL_HOST="$SCRIPT_DIR"
AR_INSTALL_CONTAINER="$AR_INSTALL_CONTAINER_DIR"
AR_SANDBOX_HOME="$AR_SANDBOX_HOME"
STATE_ROOT="$STATE_ROOT"
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
AR_ORG_NOTES_REPO="${AR_ORG_NOTES_REPO:-}"
AR_MAIN_AGENT="${AR_MAIN_AGENT:-research-coordinator}"
AR_AGENT_TOPIC="${AR_AGENT_TOPIC:-}"
AR_AGENT_BRANCH_PREFIX="${AR_AGENT_BRANCH_PREFIX:-}"
AR_SESSION_ID="${AR_SESSION_ID:-}"
AR_USER_ID="${AR_USER_ID:-$USER}"
AR_PROJECT_ID="${AR_PROJECT_ID:-}"
AR_AGENTIC_STATE_BRANCH="${AR_AGENTIC_STATE_BRANCH:-agentic/state}"
AR_NOTES_AUTO_REFRESH="${AR_NOTES_AUTO_REFRESH:-true}"
AR_RESOLVER_GIT_NAME="${AR_RESOLVER_GIT_NAME:-}"
AR_RESOLVER_GIT_EMAIL="${AR_RESOLVER_GIT_EMAIL:-}"
AR_NOTES_GIT_NAME="${AR_NOTES_GIT_NAME:-}"
AR_NOTES_GIT_EMAIL="${AR_NOTES_GIT_EMAIL:-}"
DISPEOF
}
