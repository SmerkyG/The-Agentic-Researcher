# Agentic Notes

Agentic Notes is the built-in capability for Git-backed learned knowledge. It owns the `agent-notes/` layout, renders `always-injected.md` content into agent startup instructions, lists on-demand note topics, and provides note read/update commands.

Agentic Notes uses Agentic State for storage. See [agentic-state.md](agentic-state.md) for workspace naming, org/project/work-branch scopes, orphan state branches, locks, refresh behavior, visible workspace locations, and operational cache locations.

## Layout

Every Agentic State scope that supports notes uses the same layout:

```text
agent-notes/
  all-agents/
    always-injected.md
    git.md
    pytorch.md
  research-coordinator/
    always-injected.md
    evaluation-policy.md
  systems-developer/
    always-injected.md
```

`agent-notes/all-agents/` applies to every agent in that scope. `agent-notes/<agent_type>/` applies only to that agent type. For top-level launches, the agent type is the selected `AR_MAIN_AGENT` value, which defaults to `research-coordinator`. For subagents, the agent type is the subagent `name`.

The same layout can appear in:

| Scope | Backing location |
|-------|------------------|
| Org | Optional org repo configured by `AR_ORG_NOTES_REPO` |
| Project | Project repo orphan branch `agentic/project-state` |
| Work branch | Project repo orphan branch `agentic/work-state/<work-branch>` |

## Note Types

`always-injected.md` is for short, high-value guidance that should be present in the model's startup context. Keep it concise.

Every other Markdown file in an `agent-notes/<agent_type>/` directory is an on-demand note topic. On-demand notes are listed in the generated instruction file, but their content is not injected until the agent asks for that topic. Add an optional `Topic hints:` line near the top of an on-demand note to make discovery reliable:

```markdown
# Local Gpu Runtime

Topic hints: rocm, pytorch hip visibility, local runtime, cluster backend

## Lessons

- Check PyTorch device visibility before local GPU-scale runs.
```

Keep `Topic hints:` to 80 characters or less. It should list the keywords,
tools, runtimes, packages, and action trigger that should cause an agent to read
the note; it is not a full summary.

## Instruction Generation

The `agentic-notes` capability renders an Agentic Notes section into the invocation-specific instruction file (`AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`). The rendered `always-injected.md` note combines available portions in this order:

1. org `agent-notes/all-agents/always-injected.md`
2. org `agent-notes/$AR_MAIN_AGENT/always-injected.md`
3. project `agent-notes/all-agents/always-injected.md`
4. project `agent-notes/$AR_MAIN_AGENT/always-injected.md`
5. work branch `agent-notes/all-agents/always-injected.md`
6. work branch `agent-notes/$AR_MAIN_AGENT/always-injected.md`

Missing files are skipped. On-demand topic listings are also merged across these scopes, excluding `always-injected`.
The merged topic list is intentionally compact and does not show which scope
introduced a topic. If multiple scopes provide `Topic hints:` for the same note
topic, the most-specific available hint is shown.

When a new AT work entry is forked from an existing AT work entry, Agentic Team
copies the source work branch's `agent-notes/` files into the new work-state
branch. Existing non-empty notes in the new work-state branch are not
overwritten.

The generated instruction file is a materialized view. Do not edit injected note text there directly.
Note updates change Git-backed note state only. Launcher startup and compaction
refresh rematerialize instruction files; Agentic Notes commands do not select or
rewrite CLI-specific instruction targets.

## Background Refresh and Steering

While an Agentic Team session is running, the `agentic-notes` refresh loop
periodically pulls organization, project, and active-work-branch note state in
the background. The loop compares rendered note-topic fingerprints for the
active agent type. When a topic changes after the session baseline, it records a
small runtime steering notice instead of injecting full note content.

CLI-specific steering hooks drain that notice at the next supported model-entry
boundary. For Codex this is a `PostToolUse` hook; for Gemini this is a
`BeforeModel` hook. The notice lists changed topics and tells the agent to run
`agentic-notes read-note` only when a listed topic is relevant to the next
action. If no notes changed, the hook emits nothing.

## Reading Notes

Agents should read rendered notes through `agentic-notes read-note`, not by opening raw note storage files:

```bash
agentic-notes read-note --project-dir . --agent-type research-coordinator TOPIC
```

`agentic-notes read-note` dynamically combines all available org/project/work-branch and `all-agents`/agent-type portions for the requested topic. This prevents an agent from accidentally reading only one scope's fragment of a note. The rendered output labels each portion's scope, so provenance is visible after the agent reads the note.

On-demand notes are read-before-acting guidance. If a listed topic or `Topic
hints` line plausibly matches the tool, package, runtime, backend,
architecture, project convention, or work item an agent is about to touch, the
agent should read the rendered note before acting unless it has already read
that note since the last compaction.

## Updating Notes

Working agents update notes through subagents rather than editing note files
directly. Research-coordinator result reporting and bookkeeping route together
through `research-finalizer`; standalone lessons route
through `note-updater` and its rendered contract. The trigger is broader than
mistakes: missing setup requirements, corrected assumptions, undocumented tool
or platform behavior, project conventions, and user corrections should become
notes when the lesson would help a future agent. This is a required subagent
handoff in generated instructions when a note is warranted: the parent agent
should try to spawn the relevant subagent, retry once if spawning fails, and
alert the user if it still cannot be spawned rather than silently calling
`agentic-notes` directly. Notes should be terse reusable guidance, not incident
reports: prefer one compact sentence and omit timestamps, long command output,
and rationale unless essential. The updater first runs the normal
`agentic-notes update-note` path, then reviews the rendered note chain. If that
made the chain worse through duplication, verbosity, or an obvious scope
mismatch, it may perform one rare cleanup rewrite of exactly one source note
with `agentic-notes rewrite-note`. It never force-pushes.

Agents choose the note scope when they create a note; Agentic Team does not
automatically promote notes between scopes. Use the narrowest useful scope:
`work` for the active work branch only, `project` for future work in the same
repository, and `org` only for lessons that should apply across projects in the
organization. Promotion or consolidation of existing notes should be a separate
curation workflow, not an implicit side effect of ordinary note updates.
Do not record temporary workarounds or fix-needed defects as durable notes. If a
command, dependency, service, environment, policy, or other system is confusing
or broken and a user, sysadmin, upstream maintainer, or tool owner could fix it,
record an actionable fix request in the appropriate local work record
(`HELP.md`, issue tracker, or final user report) and alert the
user/sysadmin instead. Use an org note only when the workaround is durable
across projects and no near-term fix can be expected.

The agent-facing command provided by this capability is `agentic-notes`:

```text
agentic-notes read-note --project-dir PATH --agent-type AGENT_TYPE TOPIC
agentic-notes update-note < request.yaml
agentic-notes rewrite-note < request.yaml
```

`agentic-notes rewrite-note` is for the `note-updater` cleanup pass after normal note
capture. Setup, refresh, rendering, and note-state maintenance are internal
capability mechanics invoked by launcher hooks or the `note-updater` subagent,
not commands that main agents should call directly.

Use `agent-notes/all-agents/<topic>.md` for package-specific lessons, architecture notes, and broad organization, project, or work-branch lessons. Use `agent-notes/<agent_type>/always-injected.md` or `agent-notes/<agent_type>/<topic>.md` for guidance that applies only to one main agent or subagent type.

Org note updates require `AR_ORG_NOTES_REPO`; project and work-branch note updates do not.
