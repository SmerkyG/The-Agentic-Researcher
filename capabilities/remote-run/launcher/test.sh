source "$SCRIPT_DIR/capabilities/remote-run/launcher/common.sh"
remote_run_detect
remote_run_write_dispatch_config

echo "Testing remote-run setup..."
echo ""
echo "Nodes in allocation:"
scontrol show hostnames "$REMOTE_RUN_NODELIST" | while read -r node; do
    if [[ "$node" == "$REMOTE_RUN_HEAD_NODE" ]]; then
        echo "  $node (head)"
    else
        echo "  $node (remote)"
    fi
done

echo ""
echo "Testing container on head node..."
apptainer exec --nv --no-mount home --home "$AR_SANDBOX_HOME" \
    --bind "$WORKSPACE_DIR:/workspace" \
    --bind "$SCRIPT_DIR:$AR_INSTALL_CONTAINER_DIR:ro" \
    --bind "$CONTAINER_TMP:/tmp" \
    --pwd /workspace \
    "$CONTAINER_IMAGE" \
    bash -c 'echo "  Container OK: $(python3 --version), GPUs: $(nvidia-smi -L 2>/dev/null | wc -l)"'

echo ""
echo "Testing dispatch to remote nodes..."
scontrol show hostnames "$REMOTE_RUN_NODELIST" | while read -r node; do
    [[ "$node" == "$REMOTE_RUN_HEAD_NODE" ]] && continue
    echo -n "  $node: "
    srun --overlap --nodes=1 --ntasks=1 --nodelist="$node" \
        --gres="gpu:$REMOTE_RUN_GPUS_PER_NODE" --cpu-bind=none \
        apptainer exec --nv --no-mount home --home "$AR_SANDBOX_HOME" \
            --bind "$WORKSPACE_DIR:/workspace" \
            --bind "$SCRIPT_DIR:$AR_INSTALL_CONTAINER_DIR:ro" \
            --bind "$STATE_ROOT:$STATE_ROOT" \
            --bind "$CONTAINER_TMP:/tmp" \
            --pwd /workspace \
            "$CONTAINER_IMAGE" \
            bash -c 'echo "OK - $(nvidia-smi -L 2>/dev/null | wc -l) GPUs"' \
        || echo "FAILED (see error above)"
done

echo ""
echo "Dispatch directory: $DISPATCH_DIR"
echo ""
echo "remote-run test complete."
