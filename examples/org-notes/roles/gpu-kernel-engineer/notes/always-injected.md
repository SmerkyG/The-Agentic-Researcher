# GPU Kernel Engineer Role Notes

Use this file for guidance that should apply whenever an agent runs with the
`gpu-kernel-engineer` role id.

Example guidance:

- Verify correctness on small inputs before benchmarking performance.
- Record GPU model, driver/runtime versions, tensor shapes, and baseline timing
  for performance-sensitive experiments.
- Keep bulky profiler traces and generated benchmark logs outside the source
  tree unless the project explicitly asks otherwise.
