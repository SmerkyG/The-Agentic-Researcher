# Imperative Agent Workflows

An imperative workflow is valid Python that may be followed directly by an
agent or executed by a conforming runtime. Follow the selected workflow class
statement by statement; ordinary Python ordering, scope, branches, loops,
calls, and return values are authoritative.

The generated instructions include the minimal public contract and workflow
source. Contract docstrings define model-operation semantics. They do not add
workflow steps.

See [Executable Operation Workflows](../executable-operation-workflows.md) for
the model-free tool-composition runtime and the intended authoring migration
path from inline agent workflows to executable or parallel operation groups.

Top-level agents and subagents include their transitive workflow modules because
they start new contexts. Skills run inside an existing main-agent context and
include only their own workflow module. If a skill imports a definition that is
not already in the active instructions, resolve and read that module from the
colon-separated package roots in `$AR_WORKFLOW_PATH` by replacing dots with `/`
and appending `.py`.

Keep operation modules narrow enough that transitive inclusion exposes only
the contracts used by that workflow. Separate read, mutation, and worker-only
operations when they belong to different agents; do not use an aggregate module
that gives a caller unrelated capabilities merely for import convenience.

`YAMLArgvTool.run()` owns serialization of declared fields. In agent-follow
mode, never invent fields or hand-format YAML. When native structured dispatch
is unavailable, send the declared values as JSON stdin to the exact argv; JSON
is valid YAML and safely quotes arbitrary strings.

Use `self.launch(operation)` only for tracked asynchronous work and assign its
result to an annotated `Job[...]`. Use bare `self.fire_and_forget(operation)`
to start a tool or subagent asynchronously, discard its platform handle, and
immediately execute the next statement. The caller must never wait, poll, list,
message, follow up with, or depend on that operation. A `SubagentWorkflow`
starts a separate child that follows the contract named by `agent_name` and
receives its typed constructor fields. Resolve `agent_name` through the
`Available Subagents` catalog and use its matching `Contract:` path; do not
search the filesystem or installation for an agent contract. Preserve inherited
history when the platform supports it. If a native named role cannot inherit
history, explicitly pass that exact rendered contract path to the history-forked
child and direct it to follow that file. The child reads that path directly and
must not search for another contract. Its body must never run in the calling
agent's context.

Detached workflows must not discover their inputs from mutable caller
worktrees. Commit durable code inputs before launch, freeze any remaining
explicit assets, and pass typed commit and ticket identities to the subagent.
When multiple detached workflows update one branch, serialize temporary
worktree publication in capture order and expose durable status independent of
the discarded child handle.

Deterministic helper behavior is authoritative, followed by workflow code,
then declarative Markdown guidance. Agent-definition YAML frontmatter is
launcher metadata: Agentic Team consumes it before stripping it from the
model-facing instruction body.
