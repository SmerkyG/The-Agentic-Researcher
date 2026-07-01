## Agentic Notes

Agentic Notes are Markdown files stored in Git-backed organization, project,
and active-work-branch state checkouts under `agent-notes/all-agents/` and
`agent-notes/<agent_type>/`.

This document may include a generated **Agentic Notes** section below.
Injected `always-injected.md` note content is already part of the instruction context.
Never open source note files named `always-injected.md` directly. The generated section
also lists on-demand note topics. Before working on a package, library,
architecture, benchmark, project convention, or other work item that appears
related to a listed on-demand note topic, use the generated `read-note`
command to read the rendered note if you have not read it since the last
compaction.
Rendered notes dynamically combine all available organization, project, and
work-branch note portions for `all-agents` plus the current agent type.

Before final response, and after correcting any wrong assumption, failed
workflow, missing setup step, undocumented tool behavior, or user correction,
ask whether the lesson would help a future agent. If yes, launch the
`note-updater` subagent and follow its rendered contract before reporting
completion. Do not wait for the user to ask for a note. Prefer a terse
project or work-branch note over losing reusable knowledge. Notes should be
short reusable guidance, not incident reports.
Choose the target scope when creating the note. Use the narrowest scope that
will help future agents: `work` for the active work branch only, `project` for
future work in this repository, and `org` only for lessons that apply across
projects. Ordinary working agents do not promote, move, or copy existing notes
between scopes. On-demand topic lists are merged and do not show which scope
introduced a topic; `read-note` output labels the scope of each rendered note
portion after you read it.
Use `all-agents` notes for package-specific lessons, architecture optimization
lessons, and broad organization, project, or work-branch lessons. Use agent-type notes for
guidance that applies only to one main agent or subagent type. Use
`always-injected.md` only for short guidance that should be injected into every
future context for that scope and agent type.
Do not create notes for one-off command output, transient task status, or
speculation that has not been verified.

Do not edit org, project, or work-branch source notes directly from the main agent.
Use `note-updater` so pulls, duplicate checks, optional rare cleanup rewrites,
commits, pushes, and instruction refresh happen consistently.
