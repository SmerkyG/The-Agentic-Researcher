# Imperative Workflow Specs

This document specifies how Agentic Team should define agent workflows that need
to stay analyzable, testable, executable where practical, and usable inside
agent instructions.

The core rule is simple: workflow control flow belongs in Python code. English
strings inside that code describe atomic work items or tool requests only. They
are not allowed to encode ordering, branching, retry policy, blocking policy, or
concurrency.

## Goals

- Make agent workflows readable as normal imperative programs.
- Keep ordering, conditions, loops, concurrency, and failure handling visible to
  static review and tests.
- Use the workflow source directly where possible: as executable tool code, as
  embedded code for the agent to mentally step through, or as generated prose
  when prose is the best presentation layer.
- Avoid maintaining a second, drifting English-language version of the same
  flow.
- Preserve enough English for model-facing task prompts, but keep that English
  out of the control-flow layer.

## Normative Keywords

The keywords `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` are used with
their ordinary RFC-style meanings in this spec. They are not workflow API names.

Required work in a workflow is represented by ordinary imperative statements,
for example `self.do("create branch-snapshot")`. Conditional work is represented
by `if` statements. Failure policy is represented by exceptions, `try` /
`except`, explicit fallback calls, or explicit blocker returns.

## Workflow Source

A workflow spec MUST be written as normal Python control flow. The workflow
source may use helper methods supplied by the runtime, but it should still read
like an ordinary function. Workflows that launch subagents or asynchronous tools
SHOULD use normal Python `async` / `await` syntax:

```python
async def complete_result(self, result):
    self.do("update work-state report.md and TODO.md")

    snapshot = None
    if result.has_code_changes:
        snapshot = self.run_tool("branch-snapshot", stdin=result.snapshot_request)
        status = snapshot.name_status

        if status.has_unexpected_files:
            decision = await self.ask_user(
                "Snapshot includes unexpected files. Continue, revise, or stop?",
                choices=["revise", "continue", "stop"],
            )
            if decision.choice == "revise":
                self.do("revise branch-snapshot request")
            elif decision.choice == "stop":
                raise NeedsUser("User stopped after unexpected snapshot files")

    await self.launch_workflow(ResearchFinalizer, snapshot=snapshot)
```

Examples use `self` intentionally. The receiver represents the active workflow
or agent object, leaving room for class-backed definitions such as
`ResearchCoordinator.complete_result(...)` or `ResearchFinalizer.finalize(...)`.
Implementations may still delegate to a separate context object internally, but
the published workflow should read like ordinary Python agent behavior.

The order of these statements is the order of the workflow. No English string in
the example is responsible for establishing the ordering.

## Runtime Interface

Workflow source MUST be actual Python against the real `AgentWorkflow`
interface, not pseudocode with ad hoc fake functions. Method semantics belong
in the interface docstrings:

```python
class AgentWorkflow:
    def do(self, action: str, **kwargs):
        """Synchronously give the current agent one plain-language action."""

    def run_tool(self, name: str, **kwargs):
        """Synchronously execute one specific registered tool."""

    async def start_tool(self, name: str, **kwargs):
        """Launch one specific registered tool and return a job handle."""

    async def launch_workflow(
        self,
        workflow_type: type["AgentWorkflow"],
        **kwargs,
    ):
        """Launch a subagent/workflow class and return a job handle."""

    async def wait_all(self, jobs, timeout_seconds=None):
        """Wait for every job, or raise a timeout failure."""

    async def wait_any(self, jobs, timeout_seconds=None):
        """Return completed jobs without cancelling unfinished jobs."""

    def cancel(self, job):
        """Request cancellation and record the cancellation attempt."""

    def lock(self, name):
        """Serialize a critical section for the named runtime scope."""

    def timeout(self, seconds):
        """Bound the enclosed operation and raise on timeout."""

    async def ask_user(self, prompt: str, **kwargs):
        """Suspend for user input, then resume with a structured response."""
```

Workflow exceptions are also part of the contract:

```python
class WorkflowBlocked(Exception):
    """The workflow cannot proceed without an external state change."""

class NeedsUser(WorkflowBlocked):
    """The workflow cannot proceed without user input."""

class WorkflowFailed(Exception):
    """The workflow failed and should not be resumed blindly."""
```

`NeedsUser` is for blocking cases where execution should stop and surface a
question or action request to the user. It does not automatically resume at the
same Python frame. If the workflow should continue after user input, use
`await self.ask_user(...)` instead.

Workflow specs MUST NOT call methods outside the declared workflow contract. A
new method is valid only if the base workflow contract defines it and tests cover
its semantics.

Workflow specs MUST NOT invent domain-specific method names as stand-ins for
English instructions. Use an action string and a suggestive return value:

```python
gpu_status = self.do("check local GPU status")
```

The following violates the contract because `determine_local_gpu_status` is an
undeclared domain-specific workflow method:

```python
gpu_status = self.determine_local_gpu_status()
```

Concrete implementations may subclass the base workflow, record traces for
tests, execute deterministic helper commands, or render embedded code for an
agent to follow. The same workflow source should be importable by tests, even
when some operations are mocked by the workflow runtime.

## Explicit Tool Calls

Use `self.run_tool(...)` or `self.start_tool(...)` when the workflow must
execute a specific registered tool or command rather than ask the agent to
satisfy an English action.
The tool name MUST identify a real tool known to the runtime. Tool arguments
SHOULD be structured values, not shell snippets or prose.

## Workflow Consumption Modes

The workflow source is not merely a Markdown generator. It is the canonical
contract for how the workflow should proceed. Agentic Team may expose that
contract in three forms.

### Executed Workflow Code

When a workflow step can be made reliable and fast enough, Agentic Team SHOULD
extract it into real executable code or a helper command. Examples include:

- validating a branch snapshot request
- inspecting `branch-snapshot` name-status output
- rolling over `report.md`
- appending structured experiment-log entries
- checking whether a work-state checkout has uncommitted record changes

Executable workflow code is preferred for deterministic bookkeeping, schema
validation, file movement, Git safety checks, and any task where a model would
otherwise be asked to simulate a small program by reading prose.

### Embedded Workflow Code

When the agent must make judgment calls, coordinate subagents, or use tools that
cannot be hidden behind one deterministic command, Agentic Team MAY embed the
workflow code itself in the rendered instructions. In that mode the agent reads
and mentally steps through the code.

Embedded code is still better than prose-only instructions because ordering,
conditions, and failure behavior remain visible as code. The embedded code may
use abstract helper calls such as `self.do(...)`, `self.run_tool(...)`,
`self.start_tool(...)`, `self.launch_workflow(...)`, `self.wait_all(...)`, and
`self.wait_any(...)` when those calls are defined by the workflow runtime or by
surrounding instruction text.

### Rendered Prose

Generated prose is a convenience layer for readability, not the source of truth.
It SHOULD be used to summarize the workflow, define helper meanings, and provide
model-facing prompts. It SHOULD NOT be the only representation of a high-risk
workflow whose ordering or failure behavior matters.

## English Work Items

English strings passed to imperative execution helpers are action descriptions.
They MUST describe one atomic work item at the level of the workflow interface.

Valid atomic work-item examples:

```python
self.do("update work-state report.md and TODO.md")
self.do("create branch-snapshot")
self.do("inspect branch-snapshot name-status")
self.do("append experiment-log correction")
```

An English work item MUST NOT contain workflow control such as:

- ordering: `before`, `after`, `then`, `next`, `first`, `last`, `once`
- conditions: `if`, `when`, `unless`, `only if`, `provided that`
- loops: `while`, `until`, `repeat`, `for each`
- failure policy: `try`, `retry`, `fallback`, `otherwise`, `on failure`
- concurrency policy: `background`, `parallel`, `wait for`, `fire and forget`

The normative `MUST NOT` rule above is enforced by `workflow-lint`, which parses
workflow Python source and checks literal strings passed to `self.do(...)`.
The linter is an implementation of this rule, not a replacement for it.

Rule violations:

- `self.do("create branch-snapshot before launching finalizer")` violates the
  ordering rule.
- `self.do("if code changed, inspect the snapshot")` violates the condition
  rule.
- `self.do("update TODO.md after writing report.md")` violates the ordering
  rule.
- `self.do("try note-updater unless no reusable lesson exists")` violates both
  the failure-policy rule and the condition rule.

If an operation genuinely has internal order, either split it into multiple
workflow statements or call a declared tool/helper whose implementation owns
that internal order. When a specific tool is required for correctness, use
`self.run_tool(...)` or `self.start_tool(...)` instead of describing the tool
call in English.

## Synchronous and Asynchronous Actions

Workflow code SHOULD distinguish blocking and non-blocking work through normal
Python `async` / `await` syntax and declared runtime primitives, not through
prose inside the work-item string.

Use `self.do(...)` for synchronous work. The operation must finish, fail, or
return a blocker before the next workflow statement runs:

```python
snapshot = self.do("create branch-snapshot")
status = self.do("inspect branch-snapshot name-status")
```

Use `await self.launch_workflow(...)` for asynchronous subagent or workflow
launches. It launches the requested workflow and returns an awaitable job handle
after launch; it does not wait for that workflow to complete:

```python
finalizer_job = await self.launch_workflow(ResearchFinalizer, snapshot=snapshot)
commit_job = await self.start_tool("branch-commit", stdin={
    "snapshot_dir": snapshot.path,
    "background": True,
})
```

Await an individual job, or use `await self.wait_all(...)` /
`await self.wait_any(...)`, only when a later workflow step mechanically needs
the result:

```python
commit_result = await commit_job
self.do("prepare integration handoff", commit=commit_result.commit)
```

`start_tool(...)` and `launch_workflow(...)` are async because they may perform
real enqueue, setup, or subagent launch work before returning a job handle. The
workflow waits for completion only by awaiting that job handle or by calling
`await self.wait_all(...)` / `await self.wait_any(...)`.

## Conditions and Returned Facts

Workflow applicability MUST be represented with code-level conditionals:

```python
if result.has_reusable_lesson:
    await self.launch_workflow(NoteUpdater, lesson=result.lesson)
```

If deciding the condition requires work, the workflow SHOULD bind the result to
a suggestive variable name. Use `self.do(...)` when the agent may choose how to
perform the work:

```python
gpu_status = self.do("check local GPU status")

if gpu_status.has_local_gpus:
    self.do("launch local GPU experiments")
elif self.job_backend.enabled:
    self.do("launch backend GPU experiments")
```

Use `self.run_tool(...)` when the exact tool is part of the workflow contract:

```python
nvidia_status = self.run_tool("nvidia-smi", args=["--query-gpu=index,name"])
```

The action string still describes one atomic work item. The variable name and
structured return value explain what facts later branches expect from that work.

## SHOULD and MAY Behavior

`SHOULD` and `MAY` requirements are not special execution primitives.

A SHOULD-level action is represented by a condition plus an explicit failure
response:

```python
if result.has_reusable_lesson:
    try:
        await self.launch_workflow(NoteUpdater, lesson=result.lesson)
    except SubagentUnavailable as exc:
        self.do("record note-updater blocker")
```

A MAY-level action is represented by a condition where skipping the action is a
valid branch:

```python
if self.can_overlap_bookkeeping_with_research:
    await self.launch_workflow(ResearchFinalizer, snapshot=snapshot)
```

Generated instructions may use the words `SHOULD` and `MAY` when rendering these
branches for a model, but the source of truth remains the code branch and its
failure behavior.

## Action, Tool, and Subagent Use

Tools and subagents are workflow operations.

Use an agent-level synchronous action when later workflow steps depend on a
result but the exact tool is not part of the contract:

```python
snapshot = self.do("create branch-snapshot")
status = self.do("inspect branch-snapshot name-status")
```

Use an explicit synchronous tool call when the exact command is part of the
contract:

```python
self.run_tool("branch-snapshot", stdin=snapshot_request)
```

Use async tool or workflow launch when the workflow only needs the request to be
durably queued:

```python
commit_job = await self.start_tool("branch-commit", stdin={
    "snapshot_dir": snapshot.path,
})
finalizer_job = await self.launch_workflow(ResearchFinalizer, snapshot=snapshot)
```

A fire-and-forget operation MUST return or record enough status information for
later troubleshooting. The launching workflow MUST NOT immediately poll it just
to turn the background operation back into foreground work.

Subagent requests MUST be typed at the workflow boundary. The subagent's prompt
or contract may be English, but the parent workflow's decision to launch it,
wait for it, ignore it, or handle failure belongs in code.

## Failure Handling

Required work fails closed by default: an uncaught exception blocks the workflow.
Workflow code has two ways to involve the user:

- `await self.ask_user(...)` suspends the workflow and resumes at the next
  statement when the user answers.
- `raise NeedsUser(...)` or `raise WorkflowBlocked(...)` stops this workflow and
  returns a structured blocked result to the caller.

Use `ask_user` when the workflow can continue after a bounded decision or missing
value is supplied:

```python
decision = await self.ask_user(
    "Snapshot includes unexpected files. Continue, revise, or stop?",
    choices=["revise", "continue", "stop"],
)

if decision.choice == "revise":
    self.do("revise branch-snapshot request")
elif decision.choice == "stop":
    raise NeedsUser("User stopped after unexpected snapshot files")
```

Use `NeedsUser` when the current workflow cannot make meaningful progress until
the user or outside world changes something:

Workflows SHOULD catch expected failure classes near the point where the policy
is clear:

```python
try:
    snapshot = self.do("create branch-snapshot")
except DirtyIndex as exc:
    raise NeedsUser("Code index is not safe to snapshot") from exc
```

Failure strings may explain the blocker to a human. They may include causal
language, but they MUST NOT become hidden workflow instructions.

## Publishing Workflow Contracts

Agent-facing instructions may include workflow contracts in several forms:

- executable command names for deterministic pieces
- embedded workflow code for model-stepped procedures
- generated prose summaries for readability

The rendered instructions may contain prose like:

```text
If code changes exist, create a branch snapshot, inspect its name-status, and
launch the research-finalizer with the returned snapshot path.
```

That prose is a presentation target, not the source of truth. If the prose, the
embedded code, and the executable helper disagree, the most executable form is
authoritative: real helper code beats embedded code, and embedded code beats
prose. The disagreement should be treated as a bug in the weaker presentation
layer.

Published workflow sections SHOULD include a marker showing the workflow source
file and generator version so stale hand-edited instructions are easier to spot.

## Static Checks

Agentic Team SHOULD provide tests or linters for at least these properties:

- English work-item strings do not contain forbidden flow-control terms.
- Required trace order is produced by the workflow code.
- Conditional branches produce the expected traces for true and false cases.
- Failure branches produce explicit blockers or fallback work.
- Subagents that must not own an operation do not have access to that operation
  in their workflow.
- Embedded code and rendered prose contain the expected operations and
  conditions from the workflow source.
- Executable helpers enforce the deterministic invariants they replace.
- Synchronous or asynchronous execution policy is represented by helper choice
  such as `self.do(...)`, `self.run_tool(...)`, `self.start_tool(...)`,
  `self.launch_workflow(...)`, `await job`, `self.wait_all(...)`, or
  `self.wait_any(...)`, not by words in the work-item string.
- Additional runtime primitives are declared in the base workflow contract and
  are generic workflow controls, not domain-specific hidden procedures.
- Workflow source calls only methods declared by the base workflow contract.
- Tool names passed to `self.run_tool(...)` and `self.start_tool(...)` resolve
  to real registered tools or commands in the target runtime.

For example, the research finalization workflow should have tests proving:

- work-state report and TODO updates happen before finalizer launch
- code changes cause `branch-snapshot` before finalizer launch
- snapshot inspection happens before any background commit or finalizer launch
- the finalizer workflow cannot create its own branch snapshot
- background commit/finalizer requests are not immediately polled unless a later
  step explicitly needs their result
