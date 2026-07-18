# Executable Operation Workflows

`ExecutableWorkflow` is the model-free composition boundary for imperative
workflows. It lets an author replace a sequence of individually agent-dispatched
tools with one typed Python operation without combining their implementations
into a monolithic command.

An executable workflow uses ordinary Python ordering, branches, loops, typed
results, and exceptions. Its body may call command-backed tools and nested
executable workflows. It must not call model primitives such as `do`,
`evaluate`, `fill`, or `ask_user`.

One deterministic operation implemented directly in Python should use
`PythonTool`, not an `ExecutableWorkflow` and not a Python command wrapped in
`ArgvTool`. Its `execute()` method owns the implementation and returns a typed
result:

```python
from agentic_tools import PythonTool, Record, Value


class Metadata(Record):
    version: str


class ReadMetadata(PythonTool[Metadata]):
    path: str = Value("Metadata file path")

    def execute(self) -> Metadata:
        payload = json.loads(Path(self.path).read_text(encoding="utf-8"))
        return Metadata(version=str(payload["version"]))
```

The persistent callback executor calls `execute()` in-process. Native tools may
still invoke true external programs such as Git through `subprocess`; the point
is to avoid launching another Python interpreter, serializing YAML, and
reinstalling script dependencies merely to run Python code.

Any importable `PythonTool` can also be exposed to non-workflow agents by
declaring it in its capability manifest:

```toml
[tools]
read_metadata = "package.module:ReadMetadata"
```

The launcher combines enabled declarations into one `agentic_tools` MCP server
for Codex, Claude, Gemini, OpenCode, and Pi. This is the primary agent-facing surface: the
model receives the derived JSON Schema and native structured result without
discovering or invoking a command wrapper. The generic command adapter remains
available for shell callers and CLIs without MCP:

```bash
agentic-tool package.module:ToolClass <<'JSON'
{"path": "metadata.json"}
JSON
```

The adapter accepts a JSON or YAML mapping, validates it against the tool's
annotated fields, executes `execute()` in-process, and emits the typed result as
JSON. JSON is valid YAML, so modern structured tool callers do not require a
separate transport or an argparse flag for every field. A capability may place
a thin named wrapper in its `bin/` directory when a stable command name is more
convenient. Handwritten argparse interfaces remain appropriate only when a
human-facing positional or formatted interface is materially better.
The launcher provides this adapter and the `agentic_tools` contract even when
the imperative-workflows capability is not enabled. Use `--schema` to emit the
tool's input JSON Schema.

Executable workflows must be top-level classes in importable package modules
available through `$AR_WORKFLOW_PATH`. Their typed fields and `workflow()` body
live together in that class. Do not define them only inside an agent Markdown
workflow block: the generic CLI imports the class and executes its body.

```python
from agentic_workflows.branch import BranchCommitTool, BranchSnapshotTool, Snapshot


class PublishResult(ExecutableWorkflow[PublishTicket]):
    paths: list[str]
    message: str
    checks: list[str]
    assets: list[str]

    def workflow(self) -> PublishTicket:
        snapshot: Snapshot = BranchSnapshotTool(
            paths=self.paths,
            commit_message=self.message,
            checks=self.checks,
        ).run()
        BranchCommitTool(
            snapshot_dir=snapshot.snapshot_dir,
            background=False,
        ).run()
        return CaptureTool(report_assets=self.assets).run()
```

To an agent, the class is one `YAMLArgvTool`: its argv is
`imperative-workflows-run module:Class`, and its declared fields are serialized
as YAML stdin. The declared argv is authoritative: the caller attempts it
directly, without first running `--help`, searching for another command,
inspecting the implementation, or manually decomposing the workflow.
Usage and command-resolution diagnostics are appropriate only after that exact
invocation fails. The generic executor imports the class and dispatches each
child tool. Child results are reconstructed as their declared `WorkflowRecord`
types, so later statements use normal attribute access rather than string
references or an external DAG language.

## Authoring Migration Path

The intended development path starts with clarity and moves orchestration out
of the agent only after behavior is established.

1. Write the complete process inline in one `AgentWorkflow`. Keep every tool
   call, branch, model judgment, and failure decision visible.
2. Identify a contiguous region whose remaining inputs and decisions are
   explicit. Model-derived values should be computed before the boundary and
   passed through typed constructor fields.
3. Define one `ExecutableWorkflow` class with typed constructor fields and move
   that region, with the same Python ordering, into its `workflow()` method.
   Replace the inline statements with one `.run()` call.
4. Compose additional executable workflows when a deterministic region has a
   useful independent contract. Do not extract one-line wrappers merely to name
   phases.
5. Use `launch` plus `wait`, `wait_all`, or `wait_any` inside an executable
   workflow for independent tool operations. Keep dependent operations as
   ordinary sequential statements.
6. When a region still needs model judgment but can proceed independently,
   extract it as a `SubagentWorkflow` and launch it from an agent workflow.
7. When a future executor can launch subagents, model-free executable workflows
   may become the orchestration layer for parallel tool and subagent groups
   without changing their Python control flow.

This progression keeps the original readable program as the source of truth.
It does not require authors to translate data dependencies into `Ref(...)`
objects or maintain a second graph representation.

## Current Executor Boundary

The generic CLI currently supports:

- native `PythonTool` operations;
- synchronous `ArgvTool` and `YAMLArgvTool` calls;
- nested `ExecutableWorkflow` calls;
- tracked parallel tool calls through `launch`, `wait`, `wait_all`, and
  `wait_any`;
- fail-fast propagation of command and decoding errors.

`imperative-workflows-run` is the `ExecutableWorkflow` adapter. The
`agentic_tools` MCP server and core `agentic-tool` compatibility command are two
transports over the same `PythonTool` records and result encoding.

It intentionally does not support:

- `AgentWorkflow` or `SubagentWorkflow` execution or launch;
- detached `fire_and_forget` work;
- model primitives;
- automatic retry or crash-resume of partially completed side effects.

Keep subagent and detached launches in the surrounding `AgentWorkflow`. A tool
that owns durable background execution may still expose that behavior through
its normal request fields.

## Failure and Concurrency Rules

A child failure aborts the executable workflow before subsequent statements
run. Authors should catch an exception only when the recovery policy is itself
deterministic and safe. The executor does not automatically replay completed
side effects.

Tracked parallel operations are joined before the CLI exits. `wait_all`
returns results in input-job order. Cancellation is best effort and cannot undo
an external side effect that has already occurred.

Every child remains an independently invocable and testable tool. Composition
owns ordering and failure policy; it does not take ownership of the child's
request validation, persistence format, or domain implementation.
