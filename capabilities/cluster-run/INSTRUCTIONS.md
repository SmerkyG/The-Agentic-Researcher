### Job Backend: cluster-run

The `cluster-run` capability is active. Use the `cluster-run` skill and the `cluster-run` command for remote/backend GPU placement.

At session startup, still check local GPUs with `nvidia-smi` and then `rocm-smi`. Separately run `cluster-run status` to inspect remote/backend quotas, free GPUs, and active jobs. If no local GPU is visible, you can still submit GPU jobs through `cluster-run`.

Submit long experiments with `--detach`, monitor with `cluster-run logs` or `cluster-run logs --follow`, and cancel stuck jobs with `cluster-run cancel`.

Prefer auto placement for routine work:

```bash
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

For distributed launchers, request an allocated port and pass the runner's
placeholder directly as a command argument:

```bash
cluster-run --detach --num-gpus 8 --ports 1 --name distributed-eval -- \
  uv run accelerate launch --main_process_port {port} evaluate.py
```

Do not hardcode rendezvous ports. The runner replaces `{port}` with the first
allocated port and also exports `MASTER_PORT`, `CLUSTER_RUN_PORT_START`,
`CLUSTER_RUN_PORT_END`, `CLUSTER_RUN_PORT_COUNT`, and `CLUSTER_RUN_PORTS`.

Use hard node/GPU placement only when necessary:

```bash
cluster-run NODE GPU_LIST -- uv run python train.py
```
