## Environment Constraints

- **Package manager**: `uv` only (`uv sync`, `uv add`, `uv run` -- never pip)
- **GPU**: check local availability with `nvidia-smi` first, then `rocm-smi`
  if NVIDIA GPUs are absent. Check remote/backend availability through the active
  External Job Backend when configured.
- **Research record**: use Markdown with embedded LaTeX math when needed.
  Do not compile work-branch report pages; an actual paper-writing agent can
  produce LaTeX separately.
- **Tools**: git, gh, jq, rg, yq, python3, uv, curl, wget
- **Papers**: fetch from `https://arxiv.org/abs/XXXX.XXXXX` or `https://arxiv.org/html/XXXX.XXXXX`

### Storage rules
- **`.venv`**: managed by uv via symlinks into the cache. Do not manually modify
  it or any uv-managed cache/install directories.
- **Large files** (checkpoints, logs, datasets, generated data): never store in
  the code worktree. Use `$AR_ARTIFACTS_DIR` for bulky reusable project
  artifacts; by default it is `$AR_WORKSPACE_ROOT/artifacts/project`, shared
  across AT work entries for this project. Use a unique run or experiment
  subdirectory for new writes and do not overwrite existing artifacts unless
  that is intentional.
- **Report figures are state records**: report-ready PNG/PDF figures referenced
  by work-state report pages are expected Git records. Save and commit them
  under `$WORK_STATE_DIR/images/` even though they are binary files. This
  exception is for final report figures only; raw arrays, checkpoints, full
  logs, datasets, and other bulky generated artifacts still belong in
  artifact/cache storage.
- **Library caches**: the launcher or host environment may pre-configure cache
  environment variables (e.g., `HF_HOME`, `TRITON_CACHE_DIR`) to point outside
  the workspace. Do not override these with explicit `cache_dir=` arguments
  pointing into the project.
  Accidental caching inside the git working tree can create large binary files
  that bloat `.git/objects/` irreversibly.
