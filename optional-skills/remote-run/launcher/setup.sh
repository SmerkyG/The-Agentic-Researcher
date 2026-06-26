source "$SCRIPT_DIR/optional-skills/remote-run/launcher/common.sh"
remote_run_detect
remote_run_write_dispatch_config

OPTIONAL_SKILL_BINDS+=(
    --bind "$DISPATCH_DIR:$DISPATCH_DIR"
    --bind "$SCRIPT_DIR/scripts/remote-run:/usr/local/bin/remote-run:ro"
)
OPTIONAL_SKILL_ENV+=(
    --env "AR_DISPATCH_DIR=$DISPATCH_DIR"
    --env "AR_JOB_BACKEND=remote-run"
    --env "AR_GPUS_PER_NODE=$REMOTE_RUN_GPUS_PER_NODE"
    --env "AR_NUM_NODES=$REMOTE_RUN_NUM_NODES"
    --env "AR_HEAD_NODE=$REMOTE_RUN_HEAD_NODE"
    --env "SLURM_JOB_NODELIST=$REMOTE_RUN_NODELIST"
)
