### GPU Job Backend: cluster-run

`AR_GPU_BACKEND=cluster-run` is active. Use the `cluster-run` project skill and the `cluster-run` command for remote/backend GPU placement.

At session startup, still check local GPUs with `nvidia-smi` and then `rocm-smi`. Separately run `cluster-run status` to inspect remote/backend quotas, free GPUs, and active jobs. If no local GPU is visible, you can still submit GPU jobs through `cluster-run`.

Submit long experiments with `--detach`, monitor with `cluster-run logs` or `cluster-run logs --follow`, and cancel stuck jobs with `cluster-run cancel`.

Prefer auto placement for routine work:

```bash
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

Use hard node/GPU placement only when necessary:

```bash
cluster-run NODE GPU_LIST -- uv run python train.py
```
