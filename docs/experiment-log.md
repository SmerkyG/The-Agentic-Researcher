# Experiment Log

Experiment Log is the built-in research logging capability. It uses Agentic State for storage and owns the `experiment-log/` layout on the active work-branch state branch.

See [agentic-state.md](agentic-state.md) for the state branch and locking model.

## Storage

Experiments are stored under the active work state branch:

```text
agentic/work-state/<work-branch>
```

The capability-owned layout is:

```text
experiment-log/
  COUNTER.yaml
  SUMMARY.md
  experiments/
    E0001_short-description.yaml
```

`COUNTER.yaml` tracks `next_experiment_number` for one work branch. `SUMMARY.md` is append-maintained during normal logging. It is not regenerated from all experiment files.

## Experiment IDs

Experiment IDs are local to a work branch:

```text
E0001_block-sparse-baseline
E0002_tilelang-power2-shape-test
```

Use `::`-qualified references outside the current work branch:

```text
feature/kernel-search::E0001_block-sparse-baseline
```

Agent and user metadata, including `work_branch`, `user_id`, invocation IDs, branch names, commits, commands, metrics, and artifacts, lives inside the YAML file.

## Logging Flow

Working agents do not write experiment-log state directly. They use subagents:

- `experiment-logger` records completed meaningful experiment results.
- `experiment-corrector` appends corrections to existing experiment files.
- `branch-commit` can finalize an experiment log entry automatically after a code commit hash exists, when the snapshot includes an `after_commit.experiment_log` payload.

Generated instructions treat `experiment-logger` and `experiment-corrector` as
required subagent handoffs: the parent agent should try to spawn the named
subagent, retry once if spawning fails, and alert the user if it still cannot be
spawned rather than silently calling `experiment-log` directly.

When logging an experiment, the experiment logger pulls latest work-branch state, reads the counter, writes one YAML file, increments the counter, appends one row to `SUMMARY.md`, commits, and pushes.

If a push is rejected, the helper retries from the latest remote state. If it cannot safely merge the requested append, it reports the error instead of rewriting existing experiment history.

## Corrections

Corrections append entries to the original experiment YAML file under `corrections:` with IDs such as:

```text
E0001_R001
```

The correction flow also appends one correction row to `SUMMARY.md` that links back to the corrected experiment file. Existing experiment fields are left intact.

## Success Tags

If the experiment request sets `success: true` and includes `code.commit`, the experiment logger creates a local Git tag named:

```text
exp/<work-branch>/<experiment-id>-success
```

Completed negative or neutral experiments should omit `success` or set it to `false`.

## Commands

Agents usually route writes through subagents, but the capability also exposes one direct command with subcommands for inspection and request handling:

```text
experiment-log append --request REQUEST.yaml --project-dir PATH --work-branch WORK_BRANCH
experiment-log correct --request REQUEST.yaml --project-dir PATH --work-branch WORK_BRANCH
experiment-log summary --project-dir PATH --work-branch WORK_BRANCH
```

Research workflows often keep `condensed_report.md`, paginated report files
(`report_page1.md` oldest, `report.md` newest/current and rolled over whole
after it passes 300 lines), `TODO.md`, and report-ready figures under `images/`
on the same work-branch state branch. Those files are mutable
synthesis/checklist/report-asset records owned by the research workflow, not by
the experiment-log capability. `condensed_report.md` is deliberately distinct
from the experiment-log-owned `experiment-log/SUMMARY.md`.
