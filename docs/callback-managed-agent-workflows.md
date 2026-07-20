# Callback-Managed Agent Workflows

For a shorter source-to-model-output tour, see
[Imperative Workflows by Example](imperative-workflows-by-example.md).

The selected CLI executes an agent workflow in a persistent local
Python worker and uses structured MCP calls only at agent boundaries. It does
not take over the user's first turn: the agent receives the first user or
parent-agent request normally, then starts the registered workflow named in its
rendered instructions.

## Execution Model

The `start_workflow` MCP tool creates one private runtime directory, starts a
loopback-only worker, validates the workflow's typed constructor inputs, and
calls `on_startup()` followed by `workflow()`. The worker executes ordinary
Python until one of these boundaries occurs:

- `self.agent_request(RequestType)` needs agent-native reasoning or actions.
- `self.ask_user()` needs visible user input.
- a synchronous `SubagentWorkflow.run()` needs a native child result.
- `self.admit(SubagentWorkflow(...))` needs launcher acceptance before detach.
- the workflow returns or raises.

At a boundary the worker emits one JSON event and blocks without unwinding the
Python stack. The active agent performs the requested native work and calls the
`resume_workflow` MCP tool. The workflow, locals, loops, context managers,
pending tool jobs, and current statement remain in the persistent worker.

The worker protocol remains transport-neutral. The
`imperative-workflows-callback` CLI is retained for diagnostics, but rendered
agents use MCP. Structured MCP arguments avoid
shell quoting, interactive stdin/EOF handling, and terminal line-length limits;
MCP progress notifications also distinguish deterministic worker execution from
an idle callback boundary.

## Authoring One Agent Boundary

An agent request is an ordered declarative class body:

```python
from agentic_workflows.request_spec import (
    AgentRequest,
    guidance,
    local,
    result,
    step,
)

status_result = StatusTool().run()

class Iteration(AgentRequest):
    with guidance("Prefer one cheap variable change."):
        experiment: str = local("next focused experiment")
        hypothesis: str = local(f"testable hypothesis for {experiment}")
        step(f"Implement and run {experiment} at decision scale.")
    finalization: FinalizationStart = result("finalization request")

iteration = self.agent_request(Iteration)
ticket = iteration.finalization.run()
```

Selected registered PythonTools can be granted with the `tools=` argument;
`detachable_tools=` is an explicitly authorized subset. The model can request a
tool wave and continue this same aggregate boundary after Python returns the
results. It never receives the enabled tool catalog as a global MCP surface.

Python executes the complete class body once and its metaclass freezes the
request. Nodes are processed in source order, although the agent may inspect
later declarations while answering earlier ones.

- `step(...)` requests agent-native work and has no structured return.
- `local(...)` requires an explicitly annotated answer for later nodes in the
  same agent context. It is validated at resume but not exposed to Python.
- `result(...)` uses the same answer mechanism and is exposed on the returned
  request instance after the callback resumes.
- `with guidance(...)` qualifies its enclosed sequence. It does not introduce
  an identifier scope; `local` and `result` names are unique within the whole
  request. Assignment names are ordinary class-local Python names.

Top-level operations are shown to the next agent request automatically. The
runtime records the operation type, its one-line action from the class
docstring, typed inputs, lifecycle status, and completed result. Synchronous and
asynchronous operation events share one chronological stream with explicit
observations. If an asynchronous operation completes before that stream is
rendered, its launch entry is replaced by the completed entry; if its launch was
already rendered, completion becomes a later entry.

`self.queue_agent_observation(value, desc=None)` remains available for external
values that did not come directly from an operation, such as a normalized value
derived from several probes. Repeated calls preserve order. The optional `desc`
is presentation prose attached to the value, not a model-facing variable name
or symbolic identifier. Explicit observations must be consumed by a subsequent
agent request; unused automatic operation entries do not prevent a workflow
from completing.

Operations default to `agent_visibility = "shown"`. An operation definition may
set `agent_visibility = "hidden"`, and a call may override either default:

```python
class NoisyProbe(ArgvTool[CommandResult]):
    agent_visibility = "hidden"

normalized = NoisyProbe().run()
AuditTool().run(agent_visibility="hidden")
job = self.launch(OptionalTraceTool(), agent_visibility="shown")
```

Only the outer operation is shown when an `ExecutableWorkflow` calls nested
operations. This makes the executable workflow an observation boundary rather
than leaking every implementation detail. An operation may override
`agent_observation(result)` to project a smaller or clearer completed result.
Visibility controls presentation, not access control or secret redaction;
sensitive values must not be placed in operation records or results.

An earlier declaration interpolated through an f-string emits its exact name
surrounded by backticks. For example, interpolating `experiment` into
`"hypothesis for ..."` renders the description as “hypothesis for
`experiment`” without textual name duplication. The runtime asks the agent to
resume with every local and result in one assignments object.

Ordinary Python values already exist while the request class is constructed and
may be interpolated directly. For example,
`step(f"Read the report from {workspace.state_dir}.")` emits the concrete path.
Model-produced `local()` and `result()` declarations do not exist yet, so their
f-string placeholders emit backticked symbolic names.

Do not queue the agent's own earlier answers back as inputs to a later request.
They already exist in its retained context. Queue only new external facts that
the runtime cannot infer from an operation, such as derived deterministic host
values or state recovered after a restart.

## Operations Returned by Results

Typed operations remain ordinary `WorkflowRecord` values. For example,
`finalization: FinalizationStart = result(...)` derives its shape from the
public `FinalizationStart` class and `Value(...)` metadata. The callback response
hydrates an inert `FinalizationStart` instance. It cannot execute while the
agent fills the request; only the following Python statement calls `run()`.

This preserves the boundary:

- agent work is declarative inside an `AgentRequest` class;
- tools, executable workflows, subagent lifecycles, branches, and loops are
  imperative Python outside it.

## MCP Protocol

Agentic Team registers the local `agentic_workflows` STDIO MCP server in the
launch configuration for Codex, Claude, Gemini, OpenCode, and Pi. Pi uses the
configured `pi-mcp-extension` bridge. Registrations preserve the Agentic Team
runtime environment, including `AR_WORKFLOW_PATH`, `AR_TOOL_PATH`,
state/worktree and artifact locations, configured storage caches, and
user-supplied execution variables. Codex names these explicitly through its
`env_vars` setting; the other local stdio transports inherit the prepared CLI
environment. `AR_WORKFLOW_PATH` is the authoritative workflow registry; the
server must not search an installation to guess missing package roots.

Rendered instructions call `start_workflow` with the exact implementation
reference and typed inputs:

```json
{
  "implementation": "agentic_workflows.research.research_coordinator:ResearchCoordinator",
  "inputs": {}
}
```

## Agent Source Layout

An imperative agent has one ordinary Python class containing both its typed
constructor fields and its executable `workflow()` method:

```python
class ResearchFinalizer(SubagentWorkflow[ResearchFinalizerResult]):
    agent_name = "research-finalizer"
    ticket: FinalizationTicket

    def workflow(self) -> ResearchFinalizerResult:
        ...
```

Its optional Markdown agent file retains launcher metadata and prose guidance,
and points to that class with one reference:

```yaml
renderer: imperative-workflows
workflow: agentic_workflows.research.research_finalizer:ResearchFinalizer
```

There is no separately authored interface/header class or implementation
subclass. The callback worker imports and executes the referenced class. Agent
callers submit typed operations through callback events and never interpret the
callee's Python body. Plain Markdown agents remain valid without a `workflow`
field, allowing authors to introduce an imperative class only when they need
executed ordering, branches, typed boundaries, or process lifecycle control.

Each event contains `run_id` and `boundary_id` when resumption is possible.
The active agent calls `resume_workflow` with those exact values and an event-specific
`payload`. Agent-request payloads are:

```json
{"assignments": {"experiment": "...", "finalization": {"code_paths": []}}}
```

for `agent_request`, and:

```json
{
  "kind": "tool_requests",
  "requests": [
    {"id": "status", "tool": "git_status", "arguments": {}, "mode": "await"}
  ]
}
```

when the current event grants request-scoped PythonTools. The worker validates
the packet, launches independent requests concurrently, and returns another
`agent_request` event containing `tool_results`. `await` calls complete before
that continuation; an explicitly permitted `detach` call returns only launcher
acceptance and must not be depended on later.

Every request repeats its current `available_tools` grant. Full definitions are
sent in `tool_definitions` only when a name is new or its schema changed in the
retained agent context. Remembering a definition never grants authority: the
worker rejects any name or mode absent from the current event. PythonTools are
not separately exposed to callback agents over MCP.

After CLI context compaction, call `reset_workflow_context` once with the active
run ID. It clears the worker's definition cache and returns the unchanged
pending boundary with every currently granted definition restored. It does not
consume or replay that boundary.

Workflow Python grants tools at the call site:

```python
response = self.agent_request(
    InspectState,
    tools=[GitStatusTool, ReadArtifactTool, RefreshNotesTool],
    detachable_tools=[RefreshNotesTool],
)
```

The ordinary user response payload is:

```json
{"answer": "user response"}
```

for `ask_user`. Invalid assignments produce another `agent_request` event with
`validation_error`; the live Python statement has not advanced.

An `ask_user` event carries model-facing `instructions`, not necessarily the
literal final question. The active agent uses retained conversation and
operation context to formulate a concise user-facing prompt satisfying those
instructions, asks it, and ends the turn. This boundary can therefore perform
question wording and contextual explanation directly; do not add an
`AgentRequest` solely to draft prose for a following `ask_user()` call.

`workflow_status` reports the worker phase, pending boundary, complete pending
event, timestamps, and process liveness without exposing the private connection
token. This lets the active agent recover an event whose MCP response was interrupted
without replaying an already-consumed boundary. Long-running `start_workflow`
and `resume_workflow` calls emit periodic progress. `cancel_workflow` explicitly
ends a run. The callback CLI exposes equivalent `start`, `resume`, `status`, and
`cancel` commands for diagnostics, but rendered instructions forbid
interactive CLI use.

Worker connection metadata is stored under
`$AR_RUNTIME_ROOT/workflow-callbacks/<run-id>/` with private permissions. The
socket listens only on loopback and each request carries a random per-run token.

## Finalization Recovery and Replay

Research finalization deliberately separates its required transaction from
optional enrichment. The required order is:

1. publish the temporary report/TODO state;
2. append the experiment record;
3. mark the finalization ticket `complete` and remove its temporary worktree;
4. only then run an optional note-updater subagent.

An interruption or failure in optional note work therefore cannot leave the
ticket nonterminal or block later finalizations. A note failure is still
returned by the finalizer, but it does not roll back or downgrade already
durable research records.

At coordinator startup, the package-native `FinalizationReconcileTool` scans
the active work branch. A legacy or narrowly interrupted `committed` ticket is
completed automatically only when the state branch already contains a
post-capture experiment record with the ticket's exact frozen code commit.
Tickets that cannot be proven complete remain in `unresolved`; reconciliation
never guesses or silently discards research state.

Capture, readiness, state publication, terminal cleanup, status, and
reconciliation are Python tools under `research_finalization.tools`. Workflows
invoke those classes directly in-process. The
`research-coordinator-finalization` command is a JSON/YAML adapter over the
same classes for diagnostics and non-workflow callers; it contains no separate
finalization state machine.

`FinalizationStart` is replay-safe at the code boundary. When `code_paths` are
provided but all selected paths already match `HEAD`, it skips
`branch-snapshot` and `branch-commit` and captures the current commit. This is
the expected recovery behavior when a prior attempt committed the code and the
agent retries the same finalization request. `finish complete` is idempotent as
well, including cleanup. When `code_paths` is empty, code-only
`commit_message` or `checks` values are ignored: they cannot prevent capture of
a result that legitimately changed no code.

For diagnosis, inspect a ticket with:

```sh
printf '%s\n' '{"root":"/path/to/finalization-ticket"}' \
  | research-coordinator-finalization status
```

Run reconciliation explicitly with:

```sh
printf '%s\n' '{"project_dir":".","work_branch":"my-work-branch"}' \
  | research-coordinator-finalization reconcile
```

An `unresolved` ticket means required durable evidence is absent or ambiguous;
it requires resuming its live callback or an explicit recovery decision rather
than starting a duplicate finalizer blindly.

## Authoring Migration Path

The intended migration remains incremental:

1. Start with a readable plain Markdown agent and keep its domain guidance.
2. When executed ordering becomes useful, add one Python agent class and point
   the existing Markdown manifest to it with `workflow: module:Class`. The first
   workflow may contain a broad `AgentRequest` that relies on the retained
   Markdown guidance.
3. Aggregate adjacent model reasoning and agent-native actions into one ordered
   request class with `local`, `step`, and `result` declarations.
4. Move deterministic dependent tool sequences into an `ExecutableWorkflow`.
   The callback worker executes those sequences without another model boundary.
5. Launch independent tool operations with `launch()` and join them with
   `wait_all()` or `wait_any()` in Python.
6. Move context-independent model work into typed `SubagentWorkflow` calls.
   Use synchronous `run()` when a later statement needs the result. Use
   `admit()` followed by `detach()` when only validated launcher acceptance is
   required and later work must not depend on completion.
7. As managed runtimes improve, a native launcher process API can replace
   MCP without changing workflow source or boundary data.

The direction is from one monolithic agent turn toward larger declarative agent
requests separated by smaller deterministic or parallel imperative regions—not
toward a monolithic domain-specific tool.

## Initial Limitations

- The active CLI agent follows the returned event protocol cooperatively. The
  persistent worker owns workflow control flow, but MCP cannot force the agent to issue the next
  callback after every event.
- Native subagent admission is acknowledged through the active CLI's agent
  mechanism. Durable
  receiver-side handshake and detached lifecycle supervision should eventually
  move into a launcher-owned process API.
- Run phase and the complete pending event are journaled for diagnosis and
  interrupted-response recovery, but Python stack state is not replayable after
  worker loss. Context compaction can continue an existing live run. Finalization
  has the narrow replay and reconciliation rules above; other workflows still
  need to restart from their own durable state after worker loss.
- On every supported CLI, a skill whose receiver is a callback-managed agent
  activates that receiver's registered workflow instead of replaying the
  skill's Python body. A CLI without an MCP adapter can still use plain Markdown
  agents but cannot execute imperative agent workflows.

These constraints are transport and lifecycle gaps, not reasons to put model
branches or process supervision back into English instructions.
