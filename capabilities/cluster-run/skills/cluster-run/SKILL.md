---
name: "cluster-run"
description: "Place and manage GPU jobs with the cluster-run command."
---

# Cluster Run GPU Jobs

Use `cluster-run` for independent GPU experiments on remote/backend GPUs when this capability is active.
Run `cluster-run --help` when you need the full current command reference.

Start each work batch by checking local GPUs with `nvidia-smi`, then `rocm-smi` if needed. Check remote/backend capacity separately:

```bash
cluster-run status
cluster-run status --verbose
```

If no local GPU is visible, you can still launch GPU work through `cluster-run` when status shows available backend capacity.

Submit detached jobs for long experiments so you can continue implementation work:

```bash
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
cluster-run auto 2 --detach --name sweep-a -- uv run python train.py --sweep sweep-a
```

Let the runner allocate rendezvous ports for distributed launchers:

```bash
cluster-run --detach --num-gpus 8 --ports 1 --name distributed-eval -- \
  uv run accelerate launch --main_process_port {port} evaluate.py
```

Use hard placement only when you intentionally need a specific node or GPU set:

```bash
cluster-run dev-shared-research-2.dev-training.svc.cluster.local 0 -- uv run python train.py
cluster-run dev-shared-research-2.dev-training.svc.cluster.local 0,1 -- ./train.sh
```

Inspect and manage jobs with the run ID printed at submission:

```bash
cluster-run logs RUN_ID
cluster-run logs --follow RUN_ID
cluster-run cancel RUN_ID
```

Notes:

- Foreground `cluster-run` follows logs and interrupting it requests cancellation. Use `--detach` for background jobs.
- Use `--ports N` for jobs that need allocated ports. The runner exports `MASTER_PORT`, `CLUSTER_RUN_PORT_START`, `CLUSTER_RUN_PORT_END`, `CLUSTER_RUN_PORT_COUNT`, `CLUSTER_RUN_PORTS`, `CLUSTER_RUN_NODE`, and `CLUSTER_RUN_GPUS`.
- You can use `{port}`, `{node}`, and `{gpus}` in command arguments when a command needs the final placement.
- Do not hardcode rendezvous ports; request them with `--ports` and use `{port}` or the exported variables.
- If the workspace has `shell.nix`, the installed wrapper may run commands through that shell automatically. Do not reimplement that behavior.
- Only dispatch independent experiments. Keep dependent work in one job or run it sequentially.
