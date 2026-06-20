---
name: "remote-run"
description: "Dispatch GPU jobs to remote nodes in an Apptainer plus Slurm allocation."
---

# Remote Run GPU Jobs

Use `remote-run` only when `AR_GPU_BACKEND=remote-run` and `AR_DISPATCH_DIR` is set.
This backend is created by `agentic-researcher --multi-node` inside an active multi-node Slurm allocation.

Start each work batch by checking local GPUs with `nvidia-smi`, then `rocm-smi` if needed. Discover remote/backend nodes separately:

```bash
remote-run --nodes
remote-run --status
```

If no local GPU is visible, you can still launch GPU work through `remote-run` when remote nodes are available.

Submit independent jobs to remote nodes:

```bash
remote-run htc-gpuXXX --bg -- uv run python train.py --exp E005
remote-run htc-gpuXXX --gpus 2 --bg -- uv run python train.py
```

Monitor or stop jobs:

```bash
remote-run --status
remote-run --logs 001
remote-run --tail 001
remote-run --kill 001
```

Use `--bg` for non-blocking dispatch. Without it, `remote-run` waits for completion.
Only dispatch independent experiments; dependent work must run sequentially on the same node.
