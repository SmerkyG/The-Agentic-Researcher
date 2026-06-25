# Dynamic Notes

Agentic Researcher stores learned organization, role, and project knowledge as Git-backed Markdown notes. Notes are not CLI skills. Skills remain for durable procedures and tool affordances; learned facts, package gotchas, role conventions, and project-local lessons live in notes so they can be reviewed, merged, committed, and shared like normal text.

The launcher generates instruction and subagent config files that tell the model what notes exist and when to read them.

## Layouts

Organization notes are checked out under `$AR_STATE_ROOT/repos/org-agentic-notes/` from `AR_ORG_NOTES_REPO`:

```text
notes/
  always-injected.md
  triton.md
  pytorch.md
  git.md
  transformer-architecture.md
roles/
  gpu-kernel-engineer/
    notes/
      always-injected.md
      triton.md
      kernel-optimization.md
      benchmarking.md
```

Role notes live inside the organization notes repo at `roles/<role_id>/notes/`. Role `always-injected.md` is injected for agents running that role; other notes are listed for on-demand reading.

Project notes and experiment logs live on the project `agentic/state` branch, cached at `$AR_STATE_ROOT/projects/$AR_PROJECT_ID/agentic-state/`:

```text
.agentic/
  notes/
    always-injected.md
    evaluation.md
    data-loading.md
    cluster.md
  experiment-log/
    COUNTER.yaml
    SUMMARY.md
    experiments/
      E0001_alice_triton-power2-shape-test.yaml
```

`AR_PROJECT_ID` is required. Provide it through `agentic-researcher --project-id ID`, an environment variable, or config. AR does not infer project identity from the directory name and does not require a `.agentic/project.yaml` file in the project repo.

## Project Setup and Multiple Worktrees

For shared project notes and experiment logs, the project should be an ordinary Git repository with a remote. AR uses the remote to create and push the `agentic/state` branch from the cached state checkout. The agent's normal project worktree remains on its code branch; AR does not switch it to `agentic/state`.

When AR creates `agentic/state` for the first time, it uses an orphan branch with no parent commit and an empty starting fileset. The first state commit contains only the `.agentic/` notes and experiment-log layout. It does not include the current code tree or any files from the agent's code branch. If `agentic/state` already exists, AR checks out that existing branch and updates it.

Launch AR from the project worktree and pass the same project id for every launch that should share notes and experiment logs:

```bash
agentic-researcher --project-id my-project-2026 .
```

Multiple projects are supported in one AR installation. They are separated by `$AR_PROJECT_ID` under `$AR_STATE_ROOT/projects/`. Missing project ids are rejected so separate Git worktrees cannot silently become separate AR projects because of directory-name differences.

Multiple top-level agents may work in separate Git worktrees of the same project as long as they share the same project id. Code changes stay isolated in each agent worktree. Note updates and experiment logging go through the shared cached project state checkout and are serialized with local state locks before pulling, committing, and pushing.

Subagents inherit the parent launch's project id and rendered note list. They do not need separate project-state configuration unless they are launched as independent top-level agents.

In container mode, the launcher mounts the AR runtime read-only at `/opt/agentic-researcher` and mounts `$AR_STATE_ROOT` read-write. The org notes checkout and each project's cached `agentic/state` checkout live under that writable state root, not inside the read-only runtime mount.

## Instruction Generation

The launcher keeps the existing `INSTRUCTIONS.md` behavior for `CLAUDE.md`, `GEMINI.md`, and `AGENTS.md`. It appends a managed "Agentic Notes" section that injects the full text of available `always-injected.md` files:

- organization `notes/always-injected.md`
- current role `roles/$AR_ROLE_ID/notes/always-injected.md`
- project `.agentic/notes/always-injected.md`

Other notes are not injected. They are listed by source directory and filename, excluding `always-injected.md`, so the working agent can read only the notes relevant to the current task. Agents should not open source `always-injected.md` note files directly; their contents are already injected when available.

The launcher also renders a managed compaction hook for the selected CLI. The hook pulls the org notes and project `agentic/state` checkouts under local locks, rematerializes the invocation-specific instruction file in the worktree, tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary for note-reading rules, and asks the model to read the refreshed file before resuming the interrupted task. This gives post-compaction sessions a concrete refresh path without relying on a vague instruction to remember injected context.

Subagent configs are rendered through the existing launcher machinery. When a subagent is rendered, its note section uses that subagent's role name, plus org and project notes.

## Note Updates

Working agents do not edit note files directly. When a reusable lesson is learned, they spawn the `note-updater` subagent with a `note_update_request`. The subagent updates exactly one note, pulls latest, semantically merges concise text, commits, pushes, and refreshes the parent worktree instructions. It never force-pushes.

If a push is rejected, the updater fetches latest, re-reads the target note, reapplies the semantic merge, recommits, and pushes again. If a semantic conflict remains, it stops and reports the conflict.

Use package notes for package-specific lessons, architecture notes for architecture optimization lessons, role `always-injected.md` for role-wide lessons, org `always-injected.md` for org-wide lessons, and project notes for project-only lessons.

## Experiment Logs

Project experiments are one YAML file per experiment on the `agentic/state` branch. The `experiment-logger` subagent assigns counter-based IDs:

```text
E0001_<user_id>_<short-description-slug>
E0002_<user_id>_<short-description-slug>
```

Agent metadata, including `source.actor_id`, invocation IDs, branch names, commits, commands, metrics, and artifacts, lives inside the YAML file.

Working agents do not write experiment-log state directly. When a completed meaningful experiment should be recorded, they spawn the `experiment-logger` subagent with an `experiment_result_request`. For corrections, they spawn the same subagent with an `experiment_correction_request`.

`COUNTER.yaml` tracks `next_experiment_number`. When logging an experiment, the experiment logger pulls latest, reads the counter, writes one YAML file, increments the counter, appends one row to `SUMMARY.md`, commits, and pushes.

`SUMMARY.md` is append-maintained during normal logging. It is not regenerated from all experiment files. Agents should read `SUMMARY.md` first and open detailed experiment YAML files only when needed.

Corrections append entries to the original experiment YAML file under `corrections:` with IDs such as:

```text
E0001_R001
```

The experiment logger also appends one correction row to `SUMMARY.md` that links back to the corrected experiment file. Existing experiment fields are left intact; only the append-only `corrections:` list is extended.

`SUMMARY.md` and the per-experiment YAML files are the shared cross-agent
experiment history. `report.tex` and `TODO.md` remain ordinary files in the
project code worktree. They are useful for branch-local narrative analysis,
derivations, verification details, and local checklists, but AR does not lock
them and they should not be treated as a shared multi-agent queue or canonical
experiment index.

## Commands

Inside launched agents, `$AR_NOTES_CLI` points at the invocation's Agentic Notes helper (`scripts/ar-notes` in native mode, `/opt/agentic-researcher/scripts/ar-notes` in container mode). From an AR source checkout you can also run `scripts/ar-notes` directly. It provides these commands:

```text
init-org-notes --repo PATH_OR_URL
refresh --project-dir PATH
generate-instructions --project-dir PATH --role ROLE --tool TOOL
list-notes --scope org|role|project
update-note --request REQUEST.yaml
ensure-project-state --project-dir PATH
log-experiment --request REQUEST.yaml --project-dir PATH
log-correction --request REQUEST.yaml --project-dir PATH
```

These are low-level helper commands used by generated subagents and hooks. Working agents normally route note updates through `note-updater` and experiment log writes through `experiment-logger`.

All networked Git operations are ordinary Git clone, fetch, pull, commit, and push operations. There is no shared inbox, no org resolver process, no live overlay, and no generated learned skill tree.
