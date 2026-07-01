# Agentic Notes

Agentic Notes is the built-in capability for Git-backed learned knowledge. It owns the `agent-notes/` layout, renders `always-injected.md` content into agent startup instructions, lists on-demand note topics, and provides note read/update commands.

Agentic Notes uses Agentic State for storage. See [agentic-state.md](agentic-state.md) for project identity, org/project/work-branch scopes, orphan state branches, locks, refresh behavior, and cache locations.

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

Every other Markdown file in an `agent-notes/<agent_type>/` directory is an on-demand note topic. On-demand notes are listed in the generated instruction file, but their content is not injected until the agent asks for that topic.

## Instruction Generation

The `agentic-notes` capability renders an Agentic Notes section into the invocation-specific instruction file (`AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`). The rendered `always-injected.md` note combines available portions in this order:

1. org `agent-notes/all-agents/always-injected.md`
2. org `agent-notes/$AR_MAIN_AGENT/always-injected.md`
3. project `agent-notes/all-agents/always-injected.md`
4. project `agent-notes/$AR_MAIN_AGENT/always-injected.md`
5. work branch `agent-notes/all-agents/always-injected.md`
6. work branch `agent-notes/$AR_MAIN_AGENT/always-injected.md`

Missing files are skipped. On-demand topic listings are also merged across these scopes, excluding `always-injected`.

The generated instruction file is a materialized view. Do not edit injected note text there directly.

## Reading Notes

Agents should read rendered notes through `read-note`, not by opening raw note storage files:

```bash
read-note --project-dir . --agent-type research-coordinator TOPIC
```

`read-note` dynamically combines all available org/project/work-branch and `all-agents`/agent-type portions for the requested topic. This prevents an agent from accidentally reading only one scope's fragment of a note.

## Updating Notes

Working agents should normally update notes by launching the `note-updater` subagent and following its rendered contract. The updater changes exactly one note, pulls latest state, semantically merges concise text, commits, pushes, and refreshes the parent worktree instructions. It never force-pushes.

The agent-facing commands provided by this capability are:

```text
read-note --project-dir PATH --agent-type AGENT_TYPE TOPIC
note-update < request.yaml
```

Setup, refresh, rendering, and note-state maintenance are internal capability
mechanics invoked by launcher hooks or the `note-updater` subagent, not commands
that main agents should call directly.

Use `agent-notes/all-agents/<topic>.md` for package-specific lessons, architecture notes, and broad organization, project, or work-branch lessons. Use `agent-notes/<agent_type>/always-injected.md` or `agent-notes/<agent_type>/<topic>.md` for guidance that applies only to one main agent or subagent type.

Org note updates require `AR_ORG_NOTES_REPO`; project and work-branch note updates do not.
