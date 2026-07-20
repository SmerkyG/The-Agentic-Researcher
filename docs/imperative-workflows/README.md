# Imperative Agent Workflows

An imperative workflow is valid Python executed by a conforming runtime.
Ordinary Python ordering, scope, branches, loops, calls, and return values are
authoritative.

Callback-capable Codex, Claude, Gemini, OpenCode, and Pi sessions receive the
first request normally. A local worker then executes Python and yields only
aggregate agent, user-input, and native-subagent boundaries. See
[Callback-Managed Agent Workflows](../callback-managed-agent-workflows.md) for
the protocol, class-declared `AgentRequest` syntax, current limitations, and
migration path, and [Imperative Workflows by Example](../imperative-workflows-by-example.md)
for a compact model-visible walkthrough. Skills activate their receiver's
callback workflow. A CLI without the callback adapter can still use plain
Markdown agents but does not execute Python agent workflows.

Each imperative agent is one Python class containing its typed fields and
`workflow()` implementation. Its optional Markdown manifest points to that
class with `workflow: module:Class` and retains launcher metadata and prose.
An imperative skill similarly uses `workflow: module:function` together with
`workflow_receiver: module:AgentClass`; its Markdown contains discovery fields
and guidance, while executable Python remains in the package tree. Inline
`python agentic-workflow` blocks are retained only as a migration format.

See [Executable Operation Workflows](../executable-operation-workflows.md) for
the model-free tool-composition runtime and the intended authoring migration
path from inline agent workflows to executable or parallel operation groups.

The persistent worker resolves registered workflow classes beneath the
colon-separated package roots in `$AR_WORKFLOW_PATH`. General structured tools
use the same enabled capability package roots through `$AR_TOOL_PATH`. Agent callers exchange
typed operation inputs and callback events; they do not interpret imported
subagent workflow bodies.

`YAMLArgvTool.run()` owns serialization of declared fields. The runtime sends
declared values as JSON stdin to the exact argv; JSON is valid YAML and safely
quotes arbitrary strings.

Operation invocations are shown automatically at the next `AgentRequest` with
their type, action, typed inputs, status, and result. Operations default to
`agent_visibility = "shown"`; definitions and individual calls may select
`"hidden"`. Nested operations inside an `ExecutableWorkflow` are encapsulated
behind the outer operation. Use `queue_agent_observation()` only for derived or
external values that are not already operation results.

Use `self.launch(operation)` only for tracked asynchronous work and assign its
result to an annotated `Job[...]`. For a detached subagent, use `admit()` then
`detach()`, or the `fire_and_forget()` shorthand; the caller must never wait,
poll, message, follow up with, or depend on that child. Detached ordinary
operations are not supported by the current callback runtime unless the tool
itself owns durable background execution. A `SubagentWorkflow` emits a native
subagent boundary containing its `agent_name` and typed fields. The callback
adapter starts the child and never executes its `workflow()` body inside the
caller's worker or model context.

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
