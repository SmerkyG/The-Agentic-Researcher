## Agentic Notes

Agentic Notes are Markdown files stored in Git-backed organization, project,
and active-work-branch state checkouts under `agent-notes/all-agents/` and
`agent-notes/<agent_type>/`.

This document may include a generated **Agentic Notes** section below.
Injected `always-injected.md` note content is already part of the instruction context.
Never open source note files named `always-injected.md` directly. The generated section
also lists on-demand note topics with terse `Topic hints` metadata when available.
On-demand notes are read-before-acting guidance. Before taking an action whose
tool, package, runtime, backend, architecture, project convention, or work item
plausibly matches a listed topic or hint, use the generated `agentic-notes
read-note` command to read the rendered note if you have not read it since the
last compaction. This applies to setup checks and routine workflow actions too,
not only implementation work. Avoid re-reading a note already read since the
last compaction unless you need to verify changed content.
Rendered notes dynamically combine all available organization, project, and
work-branch note portions for `all-agents` plus the current agent type.

Before final response, and after correcting any wrong assumption, failed
workflow, missing setup step, undocumented tool behavior, or user correction,
ask whether the lesson would help a future agent. If yes, launch the
`note-updater` subagent and follow its rendered contract before reporting
completion. This is a required subagent handoff under the standing user request
in the subagent catalog: try to spawn `note-updater`, retry once if spawning
fails, and alert the user if it still cannot be spawned. Do not replace it with
a direct `agentic-notes` command from the parent agent. Do not wait for the
user to ask for a note. Prefer a terse project or work-branch note over losing
reusable knowledge. Notes should be short reusable guidance, not incident
reports.
Choose the target scope when creating the note. Use the narrowest scope that
will help future agents: `work` for the active work branch only, `project` for
future work in this repository, and `org` only for lessons that apply across
projects. Ordinary working agents do not promote, move, or copy existing notes
between scopes. On-demand topic lists are merged and do not show which scope
introduced a topic; `agentic-notes read-note` output labels the scope of each rendered note
portion after you read it.
Use `all-agents` notes for package-specific lessons, architecture optimization
lessons, and broad organization, project, or work-branch lessons. Use agent-type notes for
guidance that applies only to one main agent or subagent type. Use
`always-injected.md` only for short guidance that should be injected into every
future context for that scope and agent type.
Do not create notes for one-off command output, transient task status, or
speculation that has not been verified.
Do not create durable notes for temporary workarounds or fix-needed defects. If
a command, dependency, service, environment, policy, or other system is
confusing or broken and a user, sysadmin, upstream maintainer, or tool owner
could fix it, record an actionable fix request in the appropriate local work
record (`HELP.md`, issue tracker, or final user report) and alert the
user/sysadmin instead of creating a project or work-branch note. Use an org note
only when the workaround is durable across projects and no near-term fix can be
expected.

Do not edit org, project, or work-branch source notes directly from the main agent.
Use `note-updater` so pulls, duplicate checks, optional rare cleanup rewrites,
commits, pushes, and instruction refresh happen consistently.
