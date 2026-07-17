# Callback-Managed Agent Workflows

The initial Codex runtime executes an agent workflow in a persistent local
Python worker and uses structured MCP calls only at agent boundaries. It does
not take over the user's first turn: Codex receives the first user or
parent-agent request normally, then starts the registered workflow named in its
rendered instructions.

## Execution Model

The `start_workflow` MCP tool creates one private runtime directory, starts a
loopback-only worker, validates the workflow's typed constructor inputs, and
calls `on_startup()` followed by `workflow()`. The worker executes ordinary
Python until one of these boundaries occurs:

- `self.agent_request()` needs agent-native reasoning or actions.
- `self.ask_user()` needs visible user input.
- a synchronous `SubagentWorkflow.run()` needs a native child result.
- `self.admit(SubagentWorkflow(...))` needs launcher acceptance before detach.
- the workflow returns or raises.

At a boundary the worker emits one JSON event and blocks without unwinding the
Python stack. Codex performs the requested native work and calls the
`resume_workflow` MCP tool. The workflow, locals, loops, context managers,
pending tool jobs, and current statement remain in the persistent worker.

The worker protocol remains transport-neutral. The
`imperative-workflows-callback` CLI is retained for diagnostics and non-Codex
adapters, but rendered Codex agents use MCP. Structured MCP arguments avoid
shell quoting, interactive stdin/EOF handling, and terminal line-length limits;
MCP progress notifications also distinguish deterministic worker execution from
an idle callback boundary.

## Authoring One Agent Boundary

An agent request is an ordered declarative block:

```python
from agentic_workflows.fill_spec import field, guidance, observe, step, var

with self.agent_request() as result:
    observe(benchmark_status=status_result)
    with guidance("Prefer one cheap variable change."):
        var("experiment", str, "next focused experiment")
        var("hypothesis", str, "testable hypothesis for `experiment`")
        step("Implement and run `experiment` at decision scale.")
    field("finalization", FinalizationStart)

ticket = result.finalization.run()
```

The complete block is submitted once, after successful declaration. Nodes are
processed in source order, although the agent may inspect later declarations
while answering earlier ones.

- `observe(...)` inserts external tool or host results at that position.
- `step(...)` requests agent-native work and has no structured return.
- `var(...)` requires an explicit structured answer for later nodes in the same
  agent context. It is validated at resume but not exposed to Python.
- `field(...)` uses the same answer mechanism and is exposed on `result` after
  the block exits.
- `with guidance(...)` qualifies its enclosed sequence. It does not introduce
  an identifier scope; `var` and `field` names are unique within the whole
  request.

Backticked names in descriptions, such as `` `experiment` ``, refer to exact
request identifiers. The runtime asks Codex to resume with every variable and
field in one assignments object. This keeps one semantic agent boundary while
making all answers explicit and type-checkable.

Do not pass the agent's own earlier answers back as inputs to a later request.
They already exist in its retained context. Use `observe(...)` or
`self.observe(...)` only for new external facts such as tool results, subagent
results, deterministic host values, or state recovered after a restart.

## Operations Returned by Fields

Typed operations remain ordinary `WorkflowRecord` values. For example,
`field("finalization", FinalizationStart)` derives its shape from the public
`FinalizationStart` class and `Value(...)` metadata. The callback response
hydrates an inert `FinalizationStart` instance. It cannot execute while the
agent fills the request; only the following Python statement calls `run()`.

This preserves the boundary:

- agent work is declarative inside `agent_request()`;
- tools, executable workflows, subagent lifecycles, branches, and loops are
  imperative Python outside it.

## Codex MCP Protocol

Agentic Team registers the local `agentic_workflows` STDIO MCP server in the
Codex launch configuration. Project custom agents inherit that server from the
parent Codex session. The registration explicitly forwards the Agentic Team
runtime environment through the server's `env_vars` setting, including
`AR_WORKFLOW_PATH`, state/worktree locations, artifact locations, configured
storage caches, and user-supplied execution variables. Do not rely on the MCP
process inheriting launch-specific variables from Codex: explicitly name them
in the server configuration's `env_vars` list. `AR_WORKFLOW_PATH` is the
authoritative workflow registry; the server must not search an installation to
guess missing package roots.

Rendered Codex instructions call `start_workflow` with the exact implementation
reference and typed inputs:

```json
{
  "implementation": "agentic_workflows.research.workflows.research_coordinator:ResearchCoordinatorWorkflow",
  "inputs": {}
}
```

Each event contains `run_id` and `boundary_id` when resumption is possible.
Codex calls `resume_workflow` with those exact values and an event-specific
`payload`. Agent-request payloads are:

```json
{"assignments": {"experiment": "...", "finalization": {"code_paths": []}}}
```

for `agent_request`, and:

```json
{"answer": "user response"}
```

for `ask_user`. Invalid assignments produce another `agent_request` event with
`validation_error`; the live Python statement has not advanced.

`workflow_status` reports the worker phase, pending boundary, complete pending
event, timestamps, and process liveness without exposing the private connection
token. This lets Codex recover an event whose MCP response was interrupted
without replaying an already-consumed boundary. Long-running `start_workflow`
and `resume_workflow` calls emit periodic progress. `cancel_workflow` explicitly
ends a run. The callback CLI exposes equivalent `start`, `resume`, `status`, and
`cancel` commands for diagnostics, but rendered Codex instructions forbid
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

At coordinator startup, `research-coordinator-finalization reconcile` scans the
active work branch. A legacy or narrowly interrupted `committed` ticket is
completed automatically only when the state branch already contains a
post-capture experiment record with the ticket's exact frozen code commit.
Tickets that cannot be proven complete remain in `unresolved`; reconciliation
never guesses or silently discards research state.

`FinalizationStart` is replay-safe at the code boundary. When `code_paths` are
provided but all selected paths already match `HEAD`, it skips
`branch-snapshot` and `branch-commit` and captures the current commit. This is
the expected recovery behavior when a prior attempt committed the code and the
agent retries the same finalization request. `finish complete` is idempotent as
well, including cleanup.

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

1. Write a readable agent workflow in normal Python, even if it initially uses
   several small model operations.
2. Aggregate adjacent model reasoning and agent-native actions into one ordered
   `agent_request()` with `var`, `step`, and `field` declarations.
3. Move deterministic dependent tool sequences into an `ExecutableWorkflow`.
   The callback worker executes those sequences without another model boundary.
4. Launch independent tool operations with `launch()` and join them with
   `wait_all()` or `wait_any()` in Python.
5. Move context-independent model work into typed `SubagentWorkflow` calls.
   Use synchronous `run()` when a later statement needs the result. Use
   `admit()` followed by `detach()` when only validated launcher acceptance is
   required and later work must not depend on completion.
6. As managed runtimes improve, a native Codex app-server adapter can replace
   MCP without changing workflow source or boundary data.

The direction is from one monolithic agent turn toward larger declarative agent
requests separated by smaller deterministic or parallel imperative regions—not
toward a monolithic domain-specific tool.

## Initial Limitations

- Codex follows the returned event protocol cooperatively. The persistent worker
  owns workflow control flow, but MCP cannot force Codex to issue the next
  callback after every event.
- Native subagent admission is acknowledged through Codex's launcher. Durable
  receiver-side handshake and detached lifecycle supervision should eventually
  move into a launcher-owned process API.
- Run phase and the complete pending event are journaled for diagnosis and
  interrupted-response recovery, but Python stack state is not replayable after
  worker loss. Context compaction can continue an existing live run. Finalization
  has the narrow replay and reconciliation rules above; other workflows still
  need to restart from their own durable state after worker loss.
- On Codex, a skill whose receiver is a callback-managed agent activates that
  receiver's registered workflow instead of replaying the skill's Python body.
  Non-Codex CLIs retain the direct agent-follow rendering path.

These constraints are transport and lifecycle gaps, not reasons to put model
branches or process supervision back into English instructions.
