# Agentic Records

Agentic Records is the shared Git-backed storage substrate used by Agentic Team capabilities. It owns visible records worktree locations, records branch names, local locks, and Git synchronization. It does not decide what a note, experiment, report, checklist, or capability-specific record means.

Capabilities decide what files and schemas they store in Agentic Records. Built-in examples are [Agentic Notes](agentic-notes.md), which owns `agent-notes/`, and [Experiment Log](experiment-log.md), which owns `experiment-log/`.

## Scopes

| Scope | Backing Git location | Typical contents |
|-------|----------------------|------------------|
| Org | Optional org repo configured by `AR_ORG_NOTES_REPO` | Org agents, org capabilities, org-wide and agent-type notes |
| Project | Project repo orphan branch `agentic/project-records` | Project-wide and project agent-type Agentic Notes |
| Branch | Project repo orphan branch `agentic/branch-records/<branch>` | Branch-local Agentic Notes plus capability-owned records such as experiment logs |

The org repo is a separate Git repo. Project and branch scopes are stored in the project repo on orphan records branches separate from normal code branches.

## Repository Creation

Create a self-contained AT repository explicitly. AT does not adopt a normal
local checkout:

```bash
agentic-team init ~/treeattention-at
agentic-team clone https://github.com/example/treeattention.git ~/treeattention-at
```

## AT Workspace Layout

Agentic Team keeps its bare repository, code worktrees, and human-facing state
worktrees in one visible root:

```text
treeattention-at/
  .agentic-team.json                 # format marker
  repo.git/                          # AT-owned bare repository
  artifacts/
    project/                         # shared bulky experiment artifacts
  project-records/                   # worktree for agentic/project-records
  branches/
    main/
      code/                          # code worktree for main
      records/                       # worktree for agentic/branch-records/main
    agent/kdtree-bounds/
      code/                          # code worktree for agent/kdtree-bounds
      records/                       # matching records worktree
      client/                        # external client context
  .runtime/                          # hidden project-local operational state
```

The launcher discovers this root from `-C AT_DIR` or from a managed code
checkout and exports:

```bash
AR_PROJECT_RECORDS_DIR="$AR_WORKSPACE_ROOT/project-records"
AR_BRANCH_RECORDS_DIR="$AR_WORKSPACE_ROOT/branches/$AR_WORK_BRANCH/records"
AR_RUNTIME_ROOT="$AR_WORKSPACE_ROOT/.runtime"
AR_ARTIFACTS_DIR="$AR_WORKSPACE_ROOT/artifacts/project"
```

`agentic-team checkout` materializes the code branch and its records branch;
`agentic-team run` only launches an already materialized branch:

```bash
agentic-team -C ~/treeattention-at checkout main
agentic-team -C ~/treeattention-at checkout -b agent/kdtree-bounds main
agentic-team -C ~/treeattention-at run agent/kdtree-bounds
```

`AR_ARTIFACTS_DIR` is not Git-backed records storage. It is an AT-workspace-local shared project artifact bucket for bulky reusable experiment outputs such as traces, datasets, checkpoints, and raw logs. Agents should create unique run or experiment subdirectories there and keep report-ready figures in the branch records `images/` directory instead.

## Project Runtime and Global Cache

Project-local operational data lives under `$AR_RUNTIME_ROOT`, which defaults to `$AR_WORKSPACE_ROOT/.runtime`:

```text
$AR_RUNTIME_ROOT/
  commit-snapshots/                     # branch-snapshot metadata, patches, and logs
  commit-worktrees/                     # temporary branch-commit Git worktrees
  finalizations/                        # ordered finalizer tickets, staged assets, and records worktrees
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
project/branch records worktrees:

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

Imperative workflows call the corresponding native Python tools in
`agentic_workflows.branch` directly. These commands are thin JSON/YAML wrappers
over the same implementation for non-workflow agents and shell automation.

`branch-temporary-worktree create` makes a detached linked worktree from a named
source worktree's current commit. `publish` creates one commit and advances the
captured source branch only when it still points to the captured base commit;
`drop` removes the linked worktree. This is the generic isolation primitive used
by ordered research-state finalization.

## Records Worktrees and Branches

When Agentic Team creates `agentic/project-records` or `agentic/branch-records/<branch>` for the first time, it creates an orphan branch with no parent commit and an empty starting fileset. The first records commit contains only the capability-owned records for that scope. It does not include the code tree.

If a records branch already exists on the remote, Agentic Team creates a linked worktree for it instead of recreating it.

The agent's code worktree stays on its code branch. Agentic Team never switches it to a records branch.

## Typical Layouts

The project records branch commonly contains project Agentic Notes:

```text
agent-notes/
  all-agents/
    always-injected.md
  research-coordinator/
    always-injected.md
```

A branch records branch can contain Agentic Notes plus capability-owned records:

```text
agent-notes/
  all-agents/
    always-injected.md
  research-coordinator/
    always-injected.md
condensed_report.md                     # research workflow condensed report, when created
report_pageN.md                # numbered report pages; page1 is oldest, highest N is current
TODO.md                        # research workflow checklist, when created
images/                        # report-ready figures referenced by report pages
experiment-log/                 # experiment-log capability, when used
```

These are examples, not launcher requirements. Capabilities own their own file layouts.

## Multiple Worktrees and Agents

Multiple top-level agents work on separate AT branches. Their code worktrees and materialized instruction files stay independent, while project records updates go through the shared visible `project-records/` worktree.

Branch records are scoped by code branch. Updates to `agentic/branch-records/feature/kernel-search` do not share commit cadence with updates to `agentic/branch-records/paper/draft`.

Each main agent has one top-level agent per work branch. This is a workflow convention enforced by local branch guard prompts, not a global distributed lock. Git remains the real conflict mechanism.

## Locking and Refresh

Local locks serialize updates to the same records scope inside one Agentic Team installation:

- org updates lock the org checkout
- project updates lock the project records worktree
- branch updates lock the active branch records worktree

The remote repository remains the cross-machine coordination point. Push rejection is handled by capability commands by fetching latest state, retrying semantic or append-only updates where possible, and reporting conflicts when needed.

By default, one project-scoped background refresh loop checks org, project, and active-work-branch state every 120 seconds while any agent for that project is running. Multiple agents in the same project do not multiply remote Git checks.

## Materialized Instructions

Records branches do not store `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`. Those files are per-code-worktree materialized views generated by the launcher from:

- shared Agentic Team base instructions
- the selected main agent definition
- rendered subagent definitions
- enabled capability instruction sections
- rendered Agentic Notes

On context compaction, the selected CLI's hook refreshes configured capability state under local locks, rematerializes the instruction file for that exact invocation, tells the model that compaction just occurred, and asks it to read the refreshed file before continuing.
