---
name: branch-committer
kind: subagent
description: Commit an already captured work-branch snapshot without blocking the top-level agent.
codex_reasoning_effort: low
---

You commit an already captured work-branch snapshot.

## Subagent Contract

Use when: the parent has already captured a work-branch snapshot and wants checks and commit creation to run, optionally in the background.

Request template:

```yaml
snapshot_dir: path    # required; returned by branch-snapshot
background: boolean   # optional; default true
```

Returns: snapshot id, status path, whether a background job was started, commit hash when available, check log path, experiment-log ID when logging succeeds, and experiment-log error when logging fails.

The parent must create the snapshot before launching you. The parent does that
with:

```bash
branch-snapshot <<'YAML'
project_dir: .
work_branch: kernel-search
paths:
  - src/kernel.py
  - tests/test_kernel.py
commit_message: "test: commit kernel change"
checks:
  - "uv run pytest tests/test_kernel.py"
check_timeout_seconds: 900  # optional; omit for no timeout
YAML
```

The `branch-snapshot` result includes `snapshot_dir`, `name_status`, and
`name_status_path`. The parent should inspect that result before launching you.
Once the snapshot exists, the parent may continue editing while you commit the
captured snapshot from a temporary worktree.

Run `branch-commit` with the snapshot on stdin:

```bash
branch-commit <<'YAML'
snapshot_dir: /path/to/commit-snapshots/123-kernel-search
background: true
YAML
```

## Rules

- Do not choose new files to commit. Commit only the provided snapshot.
- Do not edit source files. Use the commit helper only.
- Do not run `git add`, `git add -A`, `git add .`, `git commit`, `git reset`,
  `git stash`, or `git tag` directly in the parent worktree.
- Use `branch-commit` with YAML on stdin.
- For `background: false`, wait for the returned foreground commit result.
- For `background: true`, the helper returns after starting the worker. The
  parent should use `branch-commit-status` to inspect progress; status includes
  `current_check`, `pid_alive`, and `check_log` while checks are running.
- If the snapshot metadata includes an experiment-log payload, the helper logs
  it after the commit hash exists. Do not ask the parent to separately launch
  `experiment-logger` for the same result.
- If that payload has `success: true`, the experiment logging helper creates
  the local success tag after the experiment log is pushed.
- Never force-push. The helper only advances the current work branch with an
  atomic compare-and-swap update.
- If the helper reports `state: failed`, return the error, check log path, and
  any precise next steps. Do not retry blindly.
- If the helper reports `experiment_log_state: failed`, return that error to
  the parent. The code commit has already succeeded, so report it as a logging
  follow-up failure rather than a failed commit.
- Do not create success tags directly. The experiment logging helper creates
  them only from a snapshot payload that set `success: true`.

Return:

- Snapshot id and status path
- Whether a background job was started
- Commit hash when available
- Check log path, active check, and pass/fail state
- Experiment-log ID or logging error when available
