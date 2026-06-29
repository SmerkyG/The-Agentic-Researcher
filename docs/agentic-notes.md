# Agentic Notes

Agentic Researcher stores learned organization-wide, agent-type-specific, and project knowledge as Git-backed Markdown notes. Notes are not CLI skills. Skills remain for durable procedures and tool affordances; learned facts, package gotchas, agent-type conventions, and project-local lessons live in notes so they can be reviewed, merged, committed, and shared like normal text.

The launcher generates top-level instruction files and subagent config files that tell the model what notes exist and when to read them.

## Layouts

Org notes are optional. When `AR_ORG_NOTES_REPO` is set, they are checked out under `$AR_STATE_ROOT/repos/org-agentic-notes/`. An empty org notes repo is a valid blank shared memory: AR can create org and agent-type notes there over time via the note-updater flow. It just contributes no injected or listed org/agent-type guidance until notes have been added. A starter layout is available in [examples/org-notes/](../examples/org-notes/).

```text
agents/
  data-curator.md
  research-paper-author.md
agent-notes/
  all-agents/
    always-injected.md
    triton.md
    pytorch.md
    git.md
    transformer-architecture.md
  gpu-kernel-engineer/
    always-injected.md
    kernel-optimization.md
    benchmarking.md
```

Agent-type notes live inside the optional org notes repo at `agent-notes/<agent_type>/`. Use the predefined `all-agents` agent type for notes every agent should receive or see listed. `always-injected.md` is injected for agents running that agent type; other notes are listed as on-demand topics. For top-level launches, the agent type is the selected `AR_MAIN_AGENT` value, which defaults to `research-coordinator`. For subagents, the agent type is the subagent `name`.

Org-provided agents live at `agents/*.md` in the org repo. They use the same neutral Markdown format as built-in AR agents. `kind: main` agents are selectable with `AR_MAIN_AGENT`; `kind: subagent` agents are rendered into the selected CLI's subagent directory. AR loads built-in agents first and org agents second, so an org agent with the same `name` as a built-in agent overrides the built-in definition.

Project notes, topic leases, and topic-local experiment logs live on the project `agentic/state` branch, cached at `$AR_STATE_ROOT/projects/<project-id>/agentic-state/`:

```text
.agentic/
  agent-notes/
    all-agents/
      always-injected.md
      evaluation.md
      data-loading.md
      cluster.md
    research-coordinator/
      always-injected.md
      evaluation-policy.md
    research-paper-author/
      always-injected.md
  topics/
    kernel-search/
      ACTIVE.yaml
      experiment-log/
        COUNTER.yaml
        SUMMARY.md
        experiments/
          E0001_triton-power2-shape-test.yaml
```

Project notes under `.agentic/agent-notes/all-agents/` apply to every agent in the project. Project agent-type notes under `.agentic/agent-notes/<agent_type>/` apply only to that agent type in this project. The worktree instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`) is only a materialized view that combines the shared AR base, the selected main agent, active optional skill instructions, and injected Agentic Notes.

AR derives `<project-id>` from the project Git `origin` repo name by default. Common remote forms such as `git@github.com:org/repo.git`, `https://github.com/org/repo`, and `ssh://git@github.com/org/repo.git` resolve to `repo`. AR does not infer project identity from the directory name and does not require a `.agentic/project.yaml` file in the project repo. Use `agentic-researcher --project-id ID`, `AR_PROJECT_ID`, or config when the project has no remote, when two unrelated repos share the same repo name, or when multiple differently named repos should share one state checkout.

## Project Setup and Multiple Worktrees

For shared project notes and topic experiment logs, the project should be an ordinary Git repository with a remote. AR uses the remote to create and push the `agentic/state` branch from the cached state checkout. The agent's normal project worktree remains on its code branch; AR does not switch it to `agentic/state`.

When AR creates `agentic/state` for the first time, it uses an orphan branch with no parent commit and an empty starting fileset. The first state commit contains only the `.agentic/` notes/topic layout. It does not include the current code tree or any files from the agent's code branch. If `agentic/state` already exists, AR checks out that existing branch and updates it.

Launch AR from the project worktree on a branch named `agent/<topic>` or a child branch such as `agent/<topic>/exp/<experiment>`. Worktrees whose `origin` remotes have the same repo name share notes and topic state automatically:

```bash
git switch -c agent/kernel-search
agentic-researcher .
```

Multiple projects are supported in one AR installation. They are separated by resolved project id under `$AR_STATE_ROOT/projects/`. Projects without a Git remote must pass `--project-id` or set `AR_PROJECT_ID`; this prevents directory-name differences from silently defining project identity.

Multiple top-level agents may work in separate Git worktrees of the same project as long as they share the same resolved project id and use different topics. There must be only one active top-level agent per topic. Code changes and rendered instruction files stay isolated in each agent worktree. Project note updates and project agent-type note updates go through the shared cached project state checkout and are serialized with local state locks before pulling, committing, and pushing. Experiment logging is serialized by topic, so different topics do not block each other.

Run the relevant setup flow to create or revise the project agent-type note for that main agent. For the default coordinator, `setup_research_plan` writes `.agentic/agent-notes/research-coordinator/always-injected.md`. Additional top-level agents can join by launching AR from their own Git worktrees with the desired `--main-agent`; their worktree instruction file is regenerated for that invocation from the selected main agent plus the matching project agent-type notes.

The project `agentic/state` branch does not store `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`. Those files are per-worktree materialized views.

Subagents inherit the parent launch's project id, topic, and rendered note list. They do not need separate project-state configuration unless they are launched as independent top-level agents.

In container mode, the launcher mounts the AR install read-only at `/opt/agentic-researcher` and mounts `$AR_STATE_ROOT` read-write. The org notes checkout and each project's cached `agentic/state` checkout live under that writable state root, not inside the read-only install mount.

## Instruction Generation

The launcher starts from the shared `INSTRUCTIONS.md` base, inserts the selected `kind: main` agent section, and writes the invocation-specific top-level instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`) when needed. It appends a managed "Agentic Notes" section that injects the rendered `always-injected.md` note for the invocation. The rendered note combines available portions in this order:

- org `agent-notes/all-agents/always-injected.md`, when `AR_ORG_NOTES_REPO` is configured
- org `agent-notes/$AR_MAIN_AGENT/always-injected.md`, when `AR_ORG_NOTES_REPO` is configured
- project `.agentic/agent-notes/all-agents/always-injected.md`
- project `.agentic/agent-notes/$AR_MAIN_AGENT/always-injected.md`

Other notes are not injected. The generated section lists on-demand note topics, excluding `always-injected`, without exposing storage directories. When a working agent needs a topic, it should run the generated `read-note` command. `read-note` dynamically renders one final note by combining available portions in the same org all-agents, org agent-type, project all-agents, project agent-type order. Agents should not open source `always-injected.md` note files directly; their contents are already injected when available.

The launcher also renders a managed compaction hook for the selected CLI. The hook pulls the org notes and project `agentic/state` checkouts under local locks, rematerializes the invocation-specific instruction file in the worktree, tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary for note-reading rules, and asks the model to read the refreshed file before resuming the interrupted task. This gives post-compaction sessions a concrete refresh path without relying on a vague instruction to remember injected context.

Subagent configs are rendered through the same agent registry. When a subagent is rendered, its note section uses that subagent's agent type, plus org and project notes. Main-agent definitions are not rendered as subagents.

Use `${AR_NOTES_CLI:-scripts/ar-notes} replace-note --scope project --agent-type AGENT_TYPE --note-name always-injected --note-file NOTE.md --project-dir PATH --refresh-parent` to replace agent-type-specific project instructions. Use `--agent-type all-agents` for project guidance shared by every agent. Working agents should not edit injected note text in `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` directly.

## Note Updates

Working agents do not edit note files directly. When a reusable lesson is learned, they spawn the `note-updater` subagent with a `note_update_request`. The subagent updates exactly one note, pulls latest, semantically merges concise text, commits, pushes, and refreshes the parent worktree instructions. It never force-pushes.

If a push is rejected, the updater fetches latest, re-reads the target note, reapplies the semantic merge, recommits, and pushes again. If a semantic conflict remains, it stops and reports the conflict.

Use `agent-notes/all-agents/<topic>.md` for package-specific lessons, architecture notes, and broad organization or project lessons. Use `agent-notes/<agent_type>/always-injected.md` or `agent-notes/<agent_type>/<topic>.md` for guidance that applies only to one main agent or subagent type. Org note updates require `AR_ORG_NOTES_REPO`; project note updates do not.

## Experiment Logs

Project experiments are one YAML file per experiment under the active topic on the `agentic/state` branch. The `experiment-logger` subagent assigns topic-local counter-based IDs:

```text
E0001_<short-description-slug>
E0002_<short-description-slug>
```

Use slash-qualified references outside the current topic:

```text
kernel-search/E0001_triton-power2-shape-test
```

Agent and user metadata, including topic, `user_id`, `source.actor_id`, invocation IDs, branch names, commits, commands, metrics, and artifacts, lives inside the YAML file.

Working agents do not write experiment-log state directly. When a completed meaningful experiment should be recorded, they spawn the `experiment-logger` subagent with an `experiment_result_request`. For corrections, they spawn the same subagent with an `experiment_correction_request`.

`COUNTER.yaml` tracks `next_experiment_number` for one topic. When logging an experiment, the experiment logger pulls latest, reads the topic counter, writes one YAML file, increments the counter, appends one row to the topic `SUMMARY.md`, commits, and pushes.

`SUMMARY.md` is append-maintained during normal logging. It is not regenerated from all experiment files. Agents should read the active topic's `SUMMARY.md` first and open detailed experiment YAML files only when needed.

Corrections append entries to the original experiment YAML file under `corrections:` with IDs such as:

```text
E0001_R001
```

The experiment logger also appends one correction row to the topic `SUMMARY.md` that links back to the corrected experiment file. Existing experiment fields are left intact; only the append-only `corrections:` list is extended.

The active topic's `SUMMARY.md` and per-experiment YAML files are the durable
experiment history for that work lane. `report.tex` and `TODO.md` remain
ordinary files in the project code worktree. They are useful for branch-local
narrative analysis, derivations, verification details, and local checklists, but
AR does not lock them and they should not be treated as a shared multi-agent
queue or canonical experiment index. A project-wide aggregate can be derived
later from the topic logs.

## Commands

Inside launched agents, `$AR_NOTES_CLI` points at the invocation's Agentic Notes helper (`scripts/ar-notes` in none mode, `/opt/agentic-researcher/scripts/ar-notes` in container mode). From an AR source checkout you can also run `scripts/ar-notes` directly. It provides these commands:

```text
init-org-notes --repo PATH_OR_URL
refresh --project-dir PATH
generate-instructions --project-dir PATH --agent-type AGENT_TYPE --tool TOOL
read-note --project-dir PATH --agent-type AGENT_TYPE TOPIC
list-notes --scope org|project --agent-type AGENT_TYPE
update-note --request REQUEST.yaml
replace-note --scope org|project --agent-type AGENT_TYPE --note-name NAME --note-file FILE
ensure-project-state --project-dir PATH
acquire-topic --project-dir PATH --topic TOPIC --session-id SESSION
release-topic --project-dir PATH --topic TOPIC --session-id SESSION
log-experiment --request REQUEST.yaml --project-dir PATH --topic TOPIC
log-correction --request REQUEST.yaml --project-dir PATH --topic TOPIC
```

These are low-level helper commands used by generated subagents and hooks. Working agents normally route note updates through `note-updater` and experiment log writes through `experiment-logger`.

All networked Git operations are ordinary Git clone, fetch, pull, commit, and push operations. There is no shared inbox, no org resolver process, no live overlay, and no generated learned skill tree.
