### Job Backend: remote-run

The `remote-run` capability is active. Use `remote-run` for independent GPU jobs on remote nodes in the current Slurm allocation.

At session startup, still check local GPUs with `nvidia-smi` and then `rocm-smi`. Separately discover remote/backend GPUs with:

```bash
remote-run --nodes
remote-run --status
```

If no local GPU is visible, you can still submit GPU jobs through `remote-run` as long as remote nodes are available in the allocation.

Submit background jobs with:

```bash
remote-run NODE --bg -- uv run python train.py --exp E005
```

Use `remote-run --logs JOB_ID`, `remote-run --tail JOB_ID`, and `remote-run --kill JOB_ID` to manage jobs.
