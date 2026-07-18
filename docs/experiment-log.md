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

The YAML record contains the generated user and work-branch metadata together
with the typed request fields: code identity, command, status, metrics, and
artifact paths.

## Logging Flow

Working agents do not edit experiment-log state directly. The capability's
canonical Python API is `experiment_log.tools`:

- `ExperimentLogAppendTool` records completed experiment results.
- `ExperimentLogCorrectTool` appends corrections to existing experiment files.
- `ResearchFinalizer` commits a code snapshot, fills the resulting branch and
  commit hash into `ExperimentLogAppendTool`, and then invokes it explicitly.

When logging an experiment, the append tool pulls latest work-branch state,
reads the counter, writes one YAML file, increments the counter, appends one row
to `SUMMARY.md`, commits, and pushes.

Append and correction requests are decoded against their structured Python tool schemas.
Missing required fields, unknown fields, and wrong scalar or collection types
are rejected before state is changed. Successful native-tool and command
responses are JSON objects containing `experiment_id` or `correction_id`.

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

The tools are ordinary `PythonTool` classes and do not depend on the imperative
workflow runtime. Callback-managed workflows import and execute those same
objects in-process. The capability also exposes a thin command selector over
the common JSON/YAML tool runner:

```bash
experiment-log append < REQUEST.yaml
experiment-log correct < CORRECTION.yaml
printf '{"project_dir":".","work_branch":"my-work"}' | experiment-log summary
experiment-log append --schema
```

For human inspection, `experiment-log summary --project-dir PATH --work-branch
WORK_BRANCH` prints the summary Markdown directly. The command contains no
experiment-log domain logic or independent validation path.

Research workflows often keep `condensed_report.md`, numbered report files
(`report_page1.md` oldest and the highest number current), `TODO.md`, and
report-ready figures under `images/`
on the same work-branch state branch. Those files are mutable
synthesis/checklist/report-asset records owned by the research workflow, not by
the experiment-log capability. `condensed_report.md` is deliberately distinct
from the experiment-log-owned `experiment-log/SUMMARY.md`.
