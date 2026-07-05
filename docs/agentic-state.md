# Agentic State

Agentic State is the shared Git-backed storage substrate used by Agentic Team capabilities. It owns project identity, cached checkouts, state branch names, local locks, and Git synchronization. It does not decide what a note, experiment, report, checklist, or capability-specific record means.

Capabilities decide what files and schemas they store in Agentic State. Built-in examples are [Agentic Notes](agentic-notes.md), which owns `agent-notes/`, and [Experiment Log](experiment-log.md), which owns `experiment-log/`.

## Scopes

| Scope | Backing Git location | Typical contents |
|-------|----------------------|------------------|
| Org | Optional org repo configured by `AR_ORG_NOTES_REPO` | Org agents, org capabilities, org-wide and agent-type notes |
| Project | Project repo orphan branch `agentic/project-state` | Project-wide and project agent-type Agentic Notes |
| Work branch | Project repo orphan branch `agentic/work-state/<work-branch>` | Work-branch Agentic Notes plus capability-owned work-branch records such as experiment logs |

The org repo is a separate Git repo. Project and work-branch scopes are stored in the project repo, but on orphan state branches that are separate from normal code branches.

## Project Identity

Agentic Team derives `<project-id>` from the project Git `origin` repo name by default. Common remote forms such as `git@github.com:org/repo.git`, `https://github.com/org/repo`, and `ssh://git@github.com/org/repo.git` resolve to `repo`.

Agentic Team does not infer project identity from the directory name and does not require a `.agentic/project.yaml` file in the project repo. Use `agentic-team --project-id ID`, `AR_PROJECT_ID`, or config when:

- the project has no remote
- two unrelated repos share the same repo name
- multiple differently named repos should share one state checkout

## Cache Locations

Agentic Team keeps local state checkouts under `$AR_STATE_ROOT`, which defaults to `~/.cache/agentic-team`:

```text
$AR_STATE_ROOT/
  repos/
    org-agentic-notes/                  # optional org repo checkout
  projects/
    <project-id>/
      agentic-state/                    # checkout of agentic/project-state
      work-state/
        <work-branch>/                  # checkout of agentic/work-state/<work-branch>
  locks/
  branch-guards/
```

In container mode, the launcher mounts the Agentic Team install read-only at `/opt/agentic-team` and mounts `$AR_STATE_ROOT` read-write. The org checkout, project state checkout, and work-branch state checkouts live under that writable state root, not inside the read-only install mount.

## State Branches

When Agentic Team creates `agentic/project-state` or `agentic/work-state/<work-branch>` for the first time, it creates an orphan branch with no parent commit and an empty starting fileset. The first state commit contains only the relevant state files for that branch. It does not include the current code tree or any files from the agent's code branch.

If a state branch already exists on the remote, Agentic Team checks out and updates that existing state branch instead of recreating it.

The agent's normal project worktree stays on its code branch. Agentic Team does not switch the worktree to a state branch.

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
experiment-log/                 # experiment-log capability, when used
```

These are examples, not launcher requirements. Capabilities own their own file layouts.

## Multiple Worktrees and Agents

Multiple top-level agents should usually work in separate Git worktrees of the same project repo. Their code branches and materialized instruction files stay independent, while project state updates go through the shared cached `agentic/project-state` checkout.

Work-branch state is scoped by work branch. Updates to `agentic/work-state/feature/kernel-search` do not block or share commit cadence with updates to `agentic/work-state/paper/draft`.

Branch-exclusive main agents are intended to have one mutating top-level agent per work branch. This is a workflow convention enforced by local branch guard prompts, not a global distributed lock. Git remains the real conflict mechanism.

## Locking and Refresh

Local locks serialize updates to the same state scope inside one Agentic Team installation:

- org updates lock the org checkout
- project updates lock the project state checkout
- work-branch updates lock the active work-branch state checkout

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
