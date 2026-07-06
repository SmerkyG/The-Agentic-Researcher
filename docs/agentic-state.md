# Agentic State

Agentic State is the shared Git-backed storage substrate used by Agentic Team capabilities. It owns visible state worktree locations, state branch names, local locks, and Git synchronization. It does not decide what a note, experiment, report, checklist, or capability-specific record means.

Capabilities decide what files and schemas they store in Agentic State. Built-in examples are [Agentic Notes](agentic-notes.md), which owns `agent-notes/`, and [Experiment Log](experiment-log.md), which owns `experiment-log/`.

## Scopes

| Scope | Backing Git location | Typical contents |
|-------|----------------------|------------------|
| Org | Optional org repo configured by `AR_ORG_NOTES_REPO` | Org agents, org capabilities, org-wide and agent-type notes |
| Project | Project repo orphan branch `agentic/project-state` | Project-wide and project agent-type Agentic Notes |
| Work branch | Project repo orphan branch `agentic/work-state/<work-branch>` | Work-branch Agentic Notes plus capability-owned work-branch records such as experiment logs |

The org repo is a separate Git repo. Project and work-branch scopes are stored in the project repo, but on orphan state branches that are separate from normal code branches.

## Workspace Naming

The AT workspace path is the local namespace for a project. When you launch from a normal project checkout and do not set `AR_WORKSPACE_ROOT`, Agentic Team chooses a sibling AT workspace directory from the checkout directory name, such as `treeattention-at` for a checkout named `treeattention`.

To choose a different namespace, pass or configure the AT workspace root directly. Once an AT workspace exists, launch by naming it, for example `agentic-team ~/treeattention-at research-main`.

## AT Workspace Layout

Agentic Team keeps code worktrees and human-facing state worktrees in one visible AT workspace root. By default, launching from a normal checkout of project `treeattention` creates or uses a sibling `treeattention-at/` directory:

```text
treeattention/                       # normal user checkout, often main
treeattention-at/
  project -> ../treeattention        # pointer back to the normal checkout
  artifacts/
    project/                         # shared bulky experiment artifacts
  project-state/                     # worktree for agentic/project-state
  research-main/
    code/                            # code worktree, e.g. branch agent/research-main
    state/                           # worktree for agentic/work-state/agent/research-main
  kdtree-bounds/
    code/                            # code worktree for a parallel effort
    state/                           # matching work-state worktree
  .runtime/                          # hidden project-local operational state
```

Set `AR_WORKSPACE_ROOT` to override the AT workspace root for one launch or local configuration. This is the only supported layout for project and work-branch state worktrees. The launcher exports:

```bash
AR_PROJECT_STATE_DIR="$AR_WORKSPACE_ROOT/project-state"
AR_WORK_STATE_DIR="$AR_WORKSPACE_ROOT/$AR_WORK_NAME/state"
AR_RUNTIME_ROOT="$AR_WORKSPACE_ROOT/.runtime"
AR_ARTIFACTS_DIR="$AR_WORKSPACE_ROOT/artifacts/project"
```

`agentic-team AT_DIR WORK_NAME --from REF_OR_WORK` creates a new `<work-name>/code` worktree and `<work-name>/state` worktree when missing, then launches that named work entry. If `--from` names an existing AT work entry, enabled capabilities can inherit relevant context; if it names only a Git ref, the new work starts with clean state by default. Use `--state clean` to skip inherited context when creating from an AT work entry. If the requested code branch is already checked out in the original project directory, Agentic Team may place a `code` symlink in the AT workspace instead of moving the existing checkout.

`AR_ARTIFACTS_DIR` is not Git-backed state. It is an AT-workspace-local shared project artifact bucket for bulky reusable experiment outputs such as traces, datasets, checkpoints, and raw logs. Agents should create unique run or experiment subdirectories there and keep report-ready figures in the work-state `images/` directory instead.

## Project Runtime and Global Cache

Project-local operational data lives under `$AR_RUNTIME_ROOT`, which defaults to `$AR_WORKSPACE_ROOT/.runtime`:

```text
$AR_RUNTIME_ROOT/
  commit-snapshots/                     # branch-snapshot metadata, patches, and logs
  commit-worktrees/                     # temporary branch-commit Git worktrees
  workspace-mounts/                     # generated mount placeholders
  refresh-heartbeats/
  logs/
  tmp/
  locks/
  branch-guards/
  dispatch/
```

Global caches and organization-level storage remain under `$AR_STATE_ROOT`, which defaults to `~/.cache/agentic-team`:

```text
$AR_STATE_ROOT/
  repos/
    org-agentic-notes/                  # optional org repo checkout
  uv/
  hf_home/
  triton_cache/
  wandb/
  apptainer_cache/
  locks/                               # org-level locks
```

In container mode, the launcher mounts the Agentic Team install read-only at `/opt/agentic-team` and mounts `$AR_STATE_ROOT`, `$AR_WORKSPACE_ROOT`, and `$AR_RUNTIME_ROOT` read-write.

Commit snapshots and temporary commit worktrees are local operational artifacts.
They are useful for status checks and debugging after `branch-commit`, but they
are not durable project records. Use `branch-commit-cleanup` to dry-run and prune
old committed, failed, or abandoned snapshot artifacts without removing the
project/work-branch state worktrees:

```bash
branch-commit-cleanup <<'YAML'
dry_run: true
older_than_days: 7
YAML

branch-commit-cleanup <<'YAML'
dry_run: false
older_than_days: 7
YAML
```

## State Worktrees and Branches

When Agentic Team creates `agentic/project-state` or `agentic/work-state/<work-branch>` for the first time, it creates an orphan branch with no parent commit and an empty starting fileset. The first state commit contains only the relevant state files for that branch. It does not include the current code tree or any files from the agent's code branch.

If a state branch already exists on the remote, Agentic Team creates a linked worktree for that existing state branch instead of recreating it.

The agent's normal project worktree stays on its code branch. Agentic Team does not switch the code worktree to a state branch.

## Typical Layouts

The project state branch commonly contains project Agentic Notes:

```text
agent-notes/
  all-agents/
    always-injected.md
  research-coordinator/
    always-injected.md
```

A work-branch state branch can contain Agentic Notes plus capability-owned records:

```text
agent-notes/
  all-agents/
    always-injected.md
  research-coordinator/
    always-injected.md
report.md                      # research workflow, when created
TODO.md                         # research workflow, when created
images/                         # report-ready figures referenced by report.md
experiment-log/                 # experiment-log capability, when used
```

These are examples, not launcher requirements. Capabilities own their own file layouts.

## Multiple Worktrees and Agents

Multiple top-level agents work in separate AT workspace entries. Their code branches and materialized instruction files stay independent, while project state updates go through the shared visible `project-state/` worktree.

Work-branch state is scoped by work branch. Updates to `agentic/work-state/feature/kernel-search` do not block or share commit cadence with updates to `agentic/work-state/paper/draft`.

Each main agent has one top-level agent per work branch. This is a workflow convention enforced by local branch guard prompts, not a global distributed lock. Git remains the real conflict mechanism.

## Locking and Refresh

Local locks serialize updates to the same state scope inside one Agentic Team installation:

- org updates lock the org checkout
- project updates lock the project state worktree
- work-branch updates lock the active work-branch state worktree

The remote repository remains the cross-machine coordination point. Push rejection is handled by capability commands by fetching latest state, retrying semantic or append-only updates where possible, and reporting conflicts when needed.

By default, one project-scoped background refresh loop checks org, project, and active-work-branch state every 120 seconds while any agent for that project is running. Multiple agents in the same project do not multiply remote Git checks.

## Materialized Instructions

State branches do not store `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`. Those files are per-worktree materialized views generated by the launcher from:

- shared Agentic Team base instructions
- the selected main agent definition
- rendered subagent definitions
- enabled capability instruction sections
- rendered Agentic Notes

On context compaction, the selected CLI's hook refreshes configured capability state under local locks, rematerializes the instruction file for that exact invocation, tells the model that compaction just occurred, and asks it to read the refreshed file before continuing.
