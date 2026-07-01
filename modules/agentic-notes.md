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

When you make a meaningful mistake and learn something reusable while
correcting it, launch the `note-updater` subagent and follow its rendered
contract.
Use `all-agents` notes for package-specific lessons, architecture optimization
lessons, and broad organization, project, or work-branch lessons. Use agent-type notes for
guidance that applies only to one main agent or subagent type. Use
`always-injected.md` only for short guidance that should be injected into every
future context for that scope and agent type.

Do not edit org, project, or work-branch source notes directly from the main agent.
Use `note-updater` so pulls, semantic merging, commits, pushes, and instruction
refresh happen consistently.
