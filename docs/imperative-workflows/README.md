# Imperative Agent Workflows

An imperative workflow is valid Python that may be followed directly by an
agent or executed by a conforming runtime. Follow the selected workflow class
statement by statement; ordinary Python ordering, scope, branches, loops,
calls, and return values are authoritative.

The generated instructions include the minimal public contract and workflow
source. Contract docstrings define model-operation semantics. They do not add
workflow steps.

Top-level agents and subagents include their transitive workflow modules because
they start new contexts. Skills run inside an existing main-agent context and
include only their own workflow module. If a skill imports a definition that is
not already in the active instructions, resolve and read that module from the
colon-separated package roots in `$AR_WORKFLOW_PATH` by replacing dots with `/`
and appending `.py`.

Use `launch()` only for tracked asynchronous work and assign its result to an
annotated `Job[...]`. Use bare `launch_detached()` for fire-and-forget work; it
returns no handle and the caller must not wait or poll it.

Deterministic helper behavior is authoritative, followed by workflow code,
then declarative Markdown guidance. Agent-definition YAML frontmatter is
launcher metadata: Agentic Team consumes it before stripping it from the
model-facing instruction body.
