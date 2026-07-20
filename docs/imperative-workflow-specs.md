# Imperative Workflow Specification

Imperative workflows are ordinary Python programs whose control flow is
executed by Agentic Team. Model work is requested through explicit aggregate
boundaries; tools and subagents are typed operations.

For a compact walkthrough showing the corresponding model-visible payloads,
see [Imperative Workflows by Example](imperative-workflows-by-example.md).
For transport and worker details, see
[Callback-Managed Agent Workflows](callback-managed-agent-workflows.md).

## Principles

1. Python owns ordering, branches, loops, retries, concurrency, and returns.
2. An `AgentRequest` owns model judgment and agent-native actions.
3. An `Operation` owns a typed tool, executable workflow, or subagent call.
4. Only explicit boundaries and visible operation observations are sent to the
   model.
5. Workflow source is the executable source of truth. Markdown supplies role
   metadata and standing declarative guidance, not duplicate control flow.

The terms `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative.

## Workflow Classes

One class contains a workflow's typed inputs, result type, and implementation:

```python
from typing import ClassVar

from agentic_workflows.contract import AgentWorkflow, WorkflowRecord


class ReviewResult(WorkflowRecord):
    summary: str


class Reviewer(AgentWorkflow[ReviewResult]):
    agent_name: ClassVar[str] = "reviewer"
    target: str

    def workflow(self) -> ReviewResult:
        ...
```

Do not create a separate interface or header class merely to hide
`workflow()`. A workflow class MUST be a top-level importable symbol. Constructor
fields and results MUST have concrete typed schemas rather than unstructured
`dict` or `Any` values.

The optional Markdown agent file points to the same class:

```yaml
renderer: imperative-workflows
workflow: my_package.review:Reviewer
```

Plain Markdown agents remain valid without a `workflow` field. This permits a
piecemeal migration from prose instructions to executed Python.

## Agent Requests

Model work MUST be declared in an `AgentRequest` class and submitted as one
boundary:

```python
from agentic_workflows.request_spec import (
    AgentRequest,
    guidance,
    local,
    result,
    step,
)


class Investigation(AgentRequest):
    with guidance("Prefer the cheapest decisive check."):
        hypothesis: str = local("testable hypothesis")
        command: str = local(f"command that tests {hypothesis}")
    step(f"Run {command} and inspect the result.")
    conclusion: str = result("conclusion supported by the observed result")


investigation = self.agent_request(Investigation)
print(investigation.conclusion)
```

The class body is a declarative sequence:

- `step(...)` requests one or more ordered agent-native actions and returns no
  value.
- `local(...)` declares a typed answer retained in the agent's context for
  later nodes in this request.
- `result(...)` declares a typed answer that is also returned to Python as an
  attribute on the request instance.
- `with guidance(...)` adds trailing policy to its enclosed sequence. It does
  not create a name scope.

Every `local()` and `result()` MUST have an explicit annotation. Names MUST be
unique across the entire request. A request class may contain only these
declarations, steps, guidance scopes, and an optional docstring. Runtime loops,
branches, observations, tool calls, and subagent calls belong outside it.

Formatting a prior `local()` or `result()` declaration in an f-string emits its
exact identifier surrounded by backticks. It does not access an as-yet unfilled
Python value. Format specifications are forbidden. Ordinary Python values that
already exist may be interpolated directly and produce their concrete string
representation.

The agent processes nodes in declaration order, but MAY consider later
requirements while filling earlier values. It MUST NOT assume the results of
operations that have not executed. After completing the request it returns one
assignments object containing every `local` and `result`. The runtime validates
the complete object and returns only `result` values to Python.

The legacy `do()`, `evaluate()`, and `fill()` vocabulary is not the current
callback authoring surface. New and migrated workflows SHOULD aggregate such
model work into `agent_request()`.

## Observations

An external or derived value can be queued for exactly the next request:

```python
capacity = inspect_capacity()
self.queue_agent_observation(capacity, desc="normalized compute capacity")
decision = self.agent_request(ChooseBackend)
```

The optional `desc` is presentation prose, not a variable name. Repeated calls
preserve order. Explicit observations MUST be consumed by a subsequent agent
request before the workflow returns.

Do not queue the agent's own prior answers back to it. They remain in retained
conversation context. Do not manually queue an operation result that the
runtime already exposes automatically.

## Operations and Visibility

An operation is a typed unit of executable work:

```python
result = CheckTool(path="result.json").run()

job = self.launch(BuildTool(target="release"))
result = self.wait(job)
```

Operation semantics are:

- `operation.run()` executes synchronously.
- `self.launch(operation)` starts tracked asynchronous work and returns a
  `Job`.
- `self.wait(job)` returns one result.
- `self.wait_all(jobs)` returns results in input order.
- `self.wait_any(jobs)` returns currently completed results without cancelling
  unfinished jobs.
- `self.cancel(job)` requests best-effort cancellation.

Top-level operations default to `agent_visibility = "shown"`. Their operation
type, one-line docstring action, typed inputs, lifecycle status, and result are
queued for the next agent request. A definition or invocation may select
`agent_visibility = "hidden"` to suppress that observation:

```python
class NoisyProbe(PythonTool[ProbeResult]):
    agent_visibility = "hidden"
    ...

NoisyProbe().run()
AuditTool().run(agent_visibility="hidden")
```

Visibility is presentation control, not secret redaction. Sensitive data MUST
NOT be placed in operation inputs or results merely because visibility is
hidden.

Nested operations inside an `ExecutableWorkflow` are encapsulated. An agent
workflow observes only the outer executable workflow operation.

## Python Tools Requested by the Agent

A `PythonTool` is implemented by `execute()` and registered under a stable name
in an enabled capability:

```toml
[tools]
read_artifact = "my_package.tools:ReadArtifactTool"
```

Registration does not globally expose the tool over MCP. Workflow Python grants
selected tool classes to one request:

```python
review = self.agent_request(
    Review,
    tools=[ReadArtifactTool, RefreshIndexTool],
    detachable_tools=[RefreshIndexTool],
)
```

`detachable_tools` MUST be a subset of `tools`. The request always receives the
current allowed names and modes. Full JSON Schema definitions are sent only
when new or changed in the retained context, and are resent after compaction.
Remembering a definition never preserves authorization for a later request.

The agent may return a `tool_requests` packet before its final assignments. The
runtime validates names, arguments, and modes, runs independent `await` calls
concurrently, and resumes the same agent request with structured results. A
permitted `detach` request returns acceptance only; later work MUST NOT depend
on its completion or result.

## Executable Workflows

An `ExecutableWorkflow` composes deterministic operations without model turns:

```python
class Publish(ExecutableWorkflow[PublishResult]):
    paths: list[str]

    def workflow(self) -> PublishResult:
        checked = CheckPathsTool(paths=self.paths).run()
        return PublishTool(paths=checked.paths).run()
```

It MAY use ordinary Python dataflow and tracked tool concurrency. The generic
executor supports tools and nested executable workflows, but not agent
requests, subagents, or detached work. See
[Executable Operation Workflows](executable-operation-workflows.md).

## Subagents

A `SubagentWorkflow` is a typed operation that MUST run in a separate native
agent context. The caller never executes its `workflow()` body.

```python
result = Reviewer(target="report.md").run()
```

Synchronous `run()` waits for the typed result. For a validated asynchronous
handoff:

```python
job = self.admit(Reviewer(target="report.md"))
self.detach(job)
```

`admit()` resumes only after the launcher accepts the child. `detach()` then
transfers lifecycle ownership to the launcher. For subagents,
`fire_and_forget()` is the shorthand for admission followed by detach. The
caller MUST NOT wait, poll, message, or otherwise depend on a detached child.
The current callback runtime rejects detached ordinary operations; a tool that
needs background execution must own a durable launch or be explicitly granted
as a detachable agent-request tool.

## User Input

Only a `UserFacingWorkflow` may call `ask_user()`:

```python
answer = self.ask_user(
    "Ask which baseline is authoritative and explain why the choice matters."
)
```

The argument is a model-facing question contract, not necessarily the literal
visible prompt. The active agent uses its retained context to formulate the
question, asks the user, and resumes Python with the answer. Subagents MUST NOT
ask the user directly.

## Lifecycle and Control Flow

`on_startup()` executes once before `workflow()`. `on_compaction()` executes
after CLI context compaction before the interrupted model boundary resumes.
Normal Python locals, calls, branches, loops, exceptions, and returns are
authoritative and produce no model prose by themselves.

Workflow functions SHOULD have explicit return annotations. Retry and failure
policy MUST be represented with Python loops, exceptions, typed results, or
user boundaries—not encoded implicitly inside English action strings.

The callback worker retains the live Python stack while waiting at a boundary.
Its current pending event is durable enough to recover an interrupted callback
response, but the Python stack is not currently replayable after worker death.
Durable operations SHOULD therefore be idempotent or expose explicit
reconciliation.

## Source and Registration

The launcher exposes enabled workflow package roots through
`$AR_WORKFLOW_PATH` and tool package roots through `$AR_TOOL_PATH`. It MUST load
the exact registered import reference and MUST NOT search the installation for
a similarly named implementation.

Skills may activate a receiver workflow without becoming separate agents:

```yaml
renderer: imperative-workflows
workflow: my_package.skills:run_research
workflow_receiver: my_package.coordinator:Coordinator
```

The selected CLI receives the user's first turn normally. It then starts or
resumes the registered workflow through the callback adapter and follows each
returned boundary until the workflow completes, fails, is cancelled, or pauses
for user input.

## Validation

Static and runtime validation SHOULD reject:

- missing or duplicate request assignment names;
- request annotations without `local()` or `result()`;
- request classes containing arbitrary public statements;
- invalid f-string format specifications on declaration placeholders;
- unknown or missing assignments in a response;
- unregistered or ungranted PythonTools;
- `detach` modes not explicitly allowed for the request;
- unconsumed explicit observations;
- `detach()` applied to a job not returned by `admit()`;
- attempts to execute a subagent body in the caller context; and
- unsupported agent or detached operations inside an `ExecutableWorkflow`.

The runtime validates structured data at every boundary. English guidance does
not override Python control flow, typed operation contracts, or authorization.
