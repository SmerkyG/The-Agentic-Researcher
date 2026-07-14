echo "Starting remote-run dispatcher daemon..."
bash "$SCRIPT_DIR/capabilities/remote-run/launcher/dispatcher.sh" "$DISPATCH_DIR/dispatch.conf" \
    >> "$DISPATCH_DIR/dispatcher.log" 2>&1 &
REMOTE_RUN_DISPATCHER_PID=$!
sleep 2

if ! kill -0 "$REMOTE_RUN_DISPATCHER_PID" 2>/dev/null; then
    echo "Error: remote-run dispatcher failed to start. Check $DISPATCH_DIR/dispatcher.log"
    exit 1
fi

echo "remote-run dispatcher running (pid $REMOTE_RUN_DISPATCHER_PID)"
echo ""
echo "Inside the container, use 'remote-run' to dispatch to other nodes:"
echo "  remote-run --nodes                              # List nodes"
echo "  remote-run htc-gpuXXX -- uv run python train.py # Run on remote node"
echo "  remote-run htc-gpuXXX --bg -- command           # Run in background"
echo "  remote-run --status                             # Check all jobs"
echo ""
