if [[ -z "${DISPATCH_DIR:-}" ]]; then
    return 0
fi

echo ""
echo "Shutting down remote-run dispatcher..."
if [[ -n "${REMOTE_RUN_DISPATCHER_PID:-}" ]]; then
    kill "$REMOTE_RUN_DISPATCHER_PID" 2>/dev/null || true
    wait "$REMOTE_RUN_DISPATCHER_PID" 2>/dev/null || true
fi

for pid_file in "$DISPATCH_DIR/jobs"/*.pid; do
    [[ -f "$pid_file" ]] || continue
    pid="$(cat "$pid_file")"
    kill "$pid" 2>/dev/null || true
done

echo "Dispatch directory preserved at: $DISPATCH_DIR"
echo "  (delete manually when done reviewing logs)"
