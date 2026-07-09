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
for example `self.do(["create branch-snapshot"])`. Conditional work is represented
by `if` statements. Failure policy is represented by exceptions, `try` /
`except`, explicit fallback calls, or explicit blocker returns.

## Workflow Source

A workflow spec MUST be written as normal Python control flow. The workflow
source may use helper methods supplied by the runtime, but it should still read
like an ordinary function. Workflows that launch subagents or asynchronous tools
SHOULD use normal Python `async` / `await` syntax:

```python
async def complete_result(self, result):
    self.do(["update work-state report.md and TODO.md"])

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
                self.do(["revise branch-snapshot request"])
            elif decision.choice == "stop":
                raise NeedsUser("User stopped after unexpected snapshot files")

    finalizer_status = await ResearchFinalizer()(
        finalizer_context=finalizer_context,
        has_code_changes=has_code_changes,
        lesson_kind=lesson_kind,
        needs_experiment_log=needs_experiment_log,
        experiment_log=experiment_log,
        note_request=note_request,
        snapshot=snapshot,
    )
```

Examples use `self` intentionally. The receiver represents the active workflow
or agent object. Class-backed subagents or subworkflows are invoked by
constructing the workflow object and passing request data to `__call__`, e.g.
`await workflow(request=...)`. Implementations may still delegate to a separate context
object internally, but the published workflow should read like ordinary Python
agent behavior.

The order of these statements is the order of the workflow. No English string in
the example is responsible for establishing the ordering.

Every function and method in workflow source MUST declare an explicit return
type annotation. Use `-> None` for side-effect-only workflow steps. Helper
functions that return domain values MUST name those values in the type system,
not only through function names or comments.

Every `AgentWorkflow.__call__` override MUST expose its launch contract as
normal typed positional-or-keyword parameters. It MUST NOT use `/`, `*`,
`*args`, or `**kwargs`. The call site MAY still pass those parameters by name
for clarity, but the function signature itself must be direct and inspectable.
The parameter and return annotations MUST NOT use `Any`, `dict`, `Dict`, or
`dict[...]`. Use explicit scalar parameters for simple values and dataclass
request/result contracts for structured values.

Workflow code SHOULD NOT extract a single-use phase into a helper method merely
to name the phase. Inline one-off control flow at the caller. Extract a helper
only when it is reused, deterministic and testable, or represents a real
workflow/subagent boundary with its own `__call__` entrypoint.

Workflow code SHOULD prefer linear statements over redirects through small
classes, helper methods, or named phases. A human should be able to read the
workflow top to bottom and understand the intent and recipe without jumping
elsewhere, except when crossing a real tool, subagent, or durable data-contract
boundary.

## Runtime Interface

Workflow source MUST be actual Python against the real `AgentWorkflow`
interface, not pseudocode with ad hoc fake functions. Method semantics belong
in the interface docstrings:

```python
def Value(description: str, *, default=MISSING, default_factory=MISSING):
    """Describe one dataclass field filled by self.evaluate(SchemaType)."""


class AgentWorkflow:
    async def __call__(self):
        """
        Run the workflow object's declared entrypoint.

        Subclasses override this with explicit typed positional-or-keyword
        parameters. They must not use keyword-only markers, *args, or **kwargs.
        """

    def do(self, actions: Sequence[str], **kwargs):
        """
        Synchronously give the current agent one or more related plain-language
        side-effecting actions.

        The actions argument must be a literal list or tuple of strings in
        workflow source and must contain at least one string.
        """

    def context(self, facts: dict[str, object] | None = None, **kwargs: object):
        """
        Narrow or disambiguate named input facts for enclosed evaluate calls.

        Normal Python lexical scope is already evaluation context. Use this only
        when a workflow needs to deliberately narrow or clarify that scope.
        """

    def evaluate(self, subject: str | type[Any]):
        """
        Non-mutating model judgment over current context.

        For direct facts, subject is one declarative string and the assigned
        variable annotation must be bool, int, float, str, Literal[...] or
        list[...] over a basic scalar type. For structured facts, subject is a
        dataclass schema whose fields use Value(...) descriptions, and the
        assigned variable annotation must match the schema.
        """

    def run_tool(self, name: str, **kwargs):
        """Synchronously execute one specific registered tool."""

    async def start_tool(self, name: str, **kwargs):
        """Launch one specific registered tool and return a job handle."""

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

Every `AgentWorkflow` subclass MUST define `__call__` as its launch entrypoint.
Do not make the launcher know about role-specific method names such as
`finalize`, `review`, `append`, or `integrate`. Deterministic helper logic
SHOULD be plain functions or tested helper classes rather than extra `self`
methods that blur the workflow contract.

Workflow specs MUST NOT invent domain-specific method names as stand-ins for
English instructions. Use a declarative evaluation string and a suggestive
return value:

```python
usable_gpu_count: int = self.evaluate("Number of usable local GPUs.")
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

## Actions And Evaluations

`self.do(...)` is deliberately side-effect-only. It describes synchronous
workflow work such as updating a report, creating a snapshot, or recording a
warning:

```python
self.do(["update condensed report"])
```

`self.do(...)` MUST NOT be assigned, returned, or used as an expression value.
When the workflow needs a model-derived fact, use `self.evaluate(...)` instead.

`self.evaluate(...)` is non-mutating. It may appear in adjacent statements
because adjacent evaluations are independent declarative judgments, not hidden
side-effect ordering:

```python
requires_user: bool = self.evaluate("True when research continuation needs user input.")
has_autonomous_work: bool = self.evaluate(
    "True when an actionable autonomous experiment, TODO, or analysis step remains.",
)
```

Direct `self.evaluate("...")` calls MUST use annotated assignment, and the
annotation MUST be `bool`, `int`, `float`, `str`, `Literal[...]`, or
`list[...]` / `List[...]` over a basic scalar type. The evaluation description
MUST be a literal declarative string. It describes the value to produce, not a
workflow action to perform:

```python
relevant_note_topics: list[str] = self.evaluate(
    "On-demand Agentic Notes topics relevant to the active work.",
)
backend_capacity_status: Literal["available", "unavailable", "unknown"] = self.evaluate(
    "Backend GPU capacity classification from the active backend status/list output.",
)
```

Use direct evaluations when named variables make the recipe clearer than a
temporary schema. When one evaluation truly needs a durable bundle of related
fields, define a dataclass schema and pass the schema to `self.evaluate(...)`.
Every schema field MUST have a real Python type and a `Value(...)` description:

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class ExperimentResultAnalysis:
    has_code_changes: bool = Value(
        "True when code files changed in the completed experiment.",
    )
    intended_variable: str = Value(
        "Single experimental variable changed by this experiment.",
    )
    baseline_metric_text: str = Value(
        "Baseline metric value from matching baseline evidence, or missing.",
    )
    candidate_metric_text: str = Value(
        "Candidate metric value from the current run evidence, or missing.",
    )
    eval_config_status: Literal["matched", "changed", "unknown"] = Value(
        "Evaluation configuration match status for benchmark, scale, seeds, metric, and evaluation flags.",
    )
    evidence_paths: list[str] = Value(
        "List of evidence file paths for the completed experiment.",
    )

analysis: ExperimentResultAnalysis = self.evaluate(ExperimentResultAnalysis)
```

Schema field names, types, and `Value(...)` descriptions define the individual
values to fill. This mirrors structured JSON/tool-call behavior: the model
receives one coherent request plus a typed field schema, and the runtime
validates the resulting object shape.

`Value(...)` descriptions are comments about the value, not commands to the
agent. Prefer declarative noun phrases such as `Experiment log title`, `List of
explicit code snapshot paths`, or `True when code files changed`. Avoid
imperative descriptions such as `Write the experiment log title` or `List
explicit code snapshot paths`.

Allowed evaluation schema field types are `bool`, `int`, `float`, `str`,
`Literal[...]` over basic scalar values, and `list[...]` / `List[...]` of basic
scalar values. Use list-valued fields for arrays instead of serializing them
into newline-separated strings. Boundary dataclasses that are never passed to
`self.evaluate(...)` may use richer ordinary Python types when the workflow
needs them.

When a structured evaluation needs to mention several evidence sources or
criteria, put that grounding in the field descriptions rather than in sequential
`do(...)` calls:

```python
@dataclass
class ResultsAnalysis:
    summary: str = Value(
        "Results analysis summary grounded in scoped experiment records, condensed report, relevant report pages, TODO records, baseline metric comparison, valid/invalid run separation, and missing-control analysis.",
    )
    recommendation: str = Value(
        "Next recommended research action, or explanation that no autonomous action remains, grounded in the same scoped records and controls.",
    )

analysis: ResultsAnalysis = self.evaluate(ResultsAnalysis)
```

The evaluation descriptions are for non-mutating judgment. They MUST NOT encode
workflow ordering, branching, retry behavior, or concurrency; those remain
Python control flow.

Workflow control still belongs in Python after schema validation:

```python
baseline_metric = parse_optional_float(analysis.baseline_metric_text)
candidate_metric = parse_optional_float(analysis.candidate_metric_text)

if analysis.eval_config_status != "matched":
    conclusion = "inconclusive"
elif baseline_metric is None or candidate_metric is None:
    conclusion = "inconclusive"
elif candidate_metric < baseline_metric:
    conclusion = "improved"
else:
    conclusion = "not_improved"

result = ExperimentResult(
    baseline_metric=baseline_metric,
    candidate_metric=candidate_metric,
    conclusion=conclusion,
)
```

Structured evaluations MUST NOT use an undeclared aggregate type, an
unannotated assignment, an untyped dictionary, or a dataclass whose fields lack
`Value(...)` descriptions. The model supplies scalar facts and schema fields.
Python owns branching, validation, aggregation, and side effects.

Workflow specs MUST NOT hide structured state in string packets such as
`context_packet: str`. If several facts need to cross a workflow boundary, define
a dataclass with typed fields for those facts and pass that dataclass directly.

Avoid one-use structured evaluations when direct annotated variables are
clearer. If a one-use structured evaluation is still warranted, define the
schema dataclass in the same Python block immediately before the single
statement that consumes it. No unrelated workflow statement, tool call,
assignment, branch, or loop may appear between the schema definition and the
consuming `self.evaluate(...)` statement:

```python
async def __call__(self) -> None:
    relevant_note_topics: list[str] = self.evaluate(
        "Relevant on-demand Agentic Notes topics.",
    )
    for topic in relevant_note_topics:
        self.run_tool("agentic-notes", subcommand="read-note", topic=topic)

    next_research_step: str = self.evaluate(
        "Immediate autonomous research step implied by loaded notes, records, Git status, and capacity.",
    )
```

Module-level schema dataclasses SHOULD be reserved for reusable contracts,
cross-method values, or subagent/tool boundaries. When a local schema is still
clearer than direct annotated variables, keep it adjacent to the exact call site
without inventing an additional inline schema language.

`self.evaluate(...)` with a dataclass subject MUST name a dataclass schema as its
first argument, and the assigned variable annotation MUST match that schema:

```python
analysis: ExperimentResultAnalysis = self.evaluate(ExperimentResultAnalysis)
```

Normal Python lexical scope is the default context for `self.evaluate(...)`.
Prefer nearby named variables over explicit context wrappers:

```python
next_research_step: str = self.evaluate(
    "Immediate autonomous research step implied by loaded notes, records, Git status, and capacity.",
)
experiment_plan: ExperimentRunnerPlan = self.evaluate(ExperimentRunnerPlan)
```

Use a `with self.context(...):` block only when normal lexical scope is
ambiguous, too broad, or intentionally needs to be narrowed for the enclosed
evaluations:

```python
with self.context(evidence_paths=ablation_evidence_paths):
    ablation_summary: str = self.evaluate("Ablation summary grounded only in the selected evidence paths.")
```

Context inputs are facts used to make the evaluation, not schema field
overrides. `self.evaluate(...)` MUST NOT accept arbitrary context keywords such
as `backend_capacity_status=...`, `runner_result=...`, or `context=dict(...)`.
Use nearby lexical variables by default, and use `self.context(...)` only when
it adds real clarity. If a fact is already known and should be part of the
output, construct the output dataclass in ordinary Python; do not also ask the
model to fill it.

`self.do([])` is never valid. Side-effect calls, scalar returns, and structured
actions MUST include at least one literal action string.

Do not define a local schema dataclass and then immediately copy the same fields
into an equivalent module-level dataclass. If a reusable return type already
exists, put the `Value(...)` field descriptions on that reusable dataclass and
assign the `self.evaluate(...)` result directly to it.

## Explicit Tool Calls

Use `self.run_tool(...)` or `self.start_tool(...)` when the workflow must
execute a specific registered tool or command rather than ask the agent to
satisfy an English action.
The tool name MUST identify a real tool known to the runtime. Tool arguments
SHOULD be structured values, not shell snippets or prose.

Repeated deterministic command sequences SHOULD be extracted into a capability
bin command rather than spelled out as a chain of workflow-level tool calls. For
example, research-coordinator work-state record commits should use a helper such
as `research-coordinator-work-state-commit`, and branch integration Git plumbing
should use a helper such as `research-coordinator-branch-integrate`. The
workflow should show the semantic boundary; the helper should own the exact
`git fetch`, `git add`, `git commit`, `git push`, merge, cherry-pick, and check
sequence.

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
- committing and pushing work-state records
- fetching, merging or cherry-picking, checking, and optionally pushing an
  integration worktree
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
`self.start_tool(...)`, `self.wait_all(...)`, and `self.wait_any(...)` when
those calls are defined by the workflow runtime or by surrounding instruction
text. Subagents and subworkflows should appear as ordinary workflow objects
whose invocation parameters are passed to `__call__`:
`result = await SomeWorkflow()(request=...)`.

### Rendered Prose

Generated prose is a convenience layer for readability, not the source of truth.
It SHOULD be used to summarize the workflow, define helper meanings, and provide
model-facing prompts. It SHOULD NOT be the only representation of a high-risk
workflow whose ordering or failure behavior matters.

## English Work Items

English strings passed to imperative execution helpers are action descriptions.
Each string in a `self.do([...])` actions list MUST describe one atomic work
item at the level of the workflow interface.

Valid atomic work-item strings include `update work-state report.md and
TODO.md`, `create branch-snapshot`, `inspect branch-snapshot name-status`, and
`append experiment-log correction`.

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

- `self.do(["create branch-snapshot before launching finalizer"])` violates the
  ordering rule.
- `self.do(["if code changed, inspect the snapshot"])` violates the condition
  rule.
- `self.do(["update TODO.md after writing report.md"])` violates the ordering
  rule.
- `self.do(["try note-updater unless no reusable lesson exists"])` violates both
  the failure-policy rule and the condition rule.

If an operation genuinely has internal order, either split it into multiple
workflow statements or call a declared tool/helper whose implementation owns
that internal order. When a specific tool is required for correctness, use
`self.run_tool(...)` or `self.start_tool(...)` instead of describing the tool
call in English.

`self.do(...)` statements MUST NOT be adjacent in the same Python statement
block. Adjacent opaque model-facing actions usually mean related work has been
split across calls without a typed contract tying the pieces together. Use one
`self.do([...])` call with multiple actions for related prompt decomposition, or
put a real Python/tool/subworkflow boundary between truly separate operations.

## Synchronous and Asynchronous Actions

Workflow code SHOULD distinguish blocking and non-blocking work through normal
Python `async` / `await` syntax and declared runtime primitives, not through
prose inside the work-item string.

Use `self.do(...)` for synchronous work. The operation must finish, fail, or
return a blocker before the next workflow statement runs:

```python
snapshot = self.run_tool("branch-snapshot", stdin=snapshot_request)
status = snapshot.name_status
```

Construct a workflow object and call its `__call__` entrypoint for subagent or
subworkflow launches. The workflow class owns whether that call blocks until
completion or returns a queued job/status handle:

```python
finalizer_status = await ResearchFinalizer()(
    finalizer_context=finalizer_context,
    has_code_changes=has_code_changes,
    lesson_kind=lesson_kind,
    needs_experiment_log=needs_experiment_log,
    experiment_log=experiment_log,
    note_request=note_request,
    snapshot=snapshot,
)
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
self.do(["prepare integration handoff"], commit=commit_result.commit)
```

`start_tool(...)` and workflow `__call__` methods are async when they may
perform real enqueue, setup, or subagent launch work before returning a job
handle. The parent workflow waits for background completion only by awaiting
that returned job handle or by calling `await self.wait_all(...)` /
`await self.wait_any(...)`.

## Conditions and Returned Facts

Workflow applicability MUST be represented with code-level conditionals:

```python
if lesson_kind != "none":
    await NoteUpdater()(request=note_request)
```

If deciding the condition requires model judgment, the workflow SHOULD bind the
result to a suggestive variable name. Use `self.evaluate(...)` for non-mutating
facts:

```python
@dataclass
class GpuStatus:
    has_local_gpus: bool = Value(
        "True when the local GPU probe found usable NVIDIA or ROCm devices.",
    )
    has_backend_gpus: bool = Value(
        "True when the configured external GPU backend reports usable GPU capacity.",
    )

gpu_status: GpuStatus = self.evaluate(GpuStatus)

if gpu_status.has_local_gpus:
    self.do(["launch local GPU experiments"])
elif gpu_status.has_backend_gpus:
    self.do(["launch backend GPU experiments"])
```

Use `self.run_tool(...)` when the exact tool is part of the workflow contract:

```python
nvidia_status = self.run_tool("nvidia-smi", args=["--query-gpu=index,name"])
```

Each action string still describes one atomic side-effecting work item. The
variable name and structured evaluation result explain what facts later branches
expect.

## SHOULD and MAY Behavior

`SHOULD` and `MAY` requirements are not special execution primitives.

A SHOULD-level action is represented by a condition plus an explicit failure
response:

```python
if lesson_kind != "none":
    try:
        await NoteUpdater()(request=note_request)
    except SubagentUnavailable as exc:
        self.do(["record note-updater blocker"])
```

A MAY-level action is represented by a condition where skipping the action is a
valid branch:

```python
can_queue_finalizer: bool = self.evaluate("True when finalizer handoff can be queued independently.")
if can_queue_finalizer:
    await ResearchFinalizer()(
        finalizer_context=finalizer_context,
        has_code_changes=has_code_changes,
        lesson_kind=lesson_kind,
        needs_experiment_log=needs_experiment_log,
        experiment_log=experiment_log,
        note_request=note_request,
        snapshot=snapshot,
    )
```

Generated instructions may use the words `SHOULD` and `MAY` when rendering these
branches for a model, but the source of truth remains the code branch and its
failure behavior.

## Action, Tool, and Subagent Use

Tools and subagents are workflow operations.

Use an agent-level synchronous action when later workflow steps depend on a
result but the exact tool is not part of the contract:

```python
snapshot = self.run_tool("branch-snapshot", stdin=snapshot_request)
status = snapshot.name_status
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
finalizer_status = await ResearchFinalizer()(
    finalizer_context=finalizer_context,
    has_code_changes=has_code_changes,
    lesson_kind=lesson_kind,
    needs_experiment_log=needs_experiment_log,
    experiment_log=experiment_log,
    note_request=note_request,
    snapshot=snapshot,
)
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
    self.do(["revise branch-snapshot request"])
elif decision.choice == "stop":
    raise NeedsUser("User stopped after unexpected snapshot files")
```

Use `NeedsUser` when the current workflow cannot make meaningful progress until
the user or outside world changes something:

Blocking preconditions MUST be checked before durable side effects such as
commits, pushes, background commit handoffs, external job submissions, or
state/log writes. A workflow should not discover that a required
`snapshot`, `experiment_log`, or `note_request` is missing only after it has
already committed work-state records or queued other irreversible bookkeeping.

Workflows SHOULD catch expected failure classes near the point where the policy
is clear:

```python
try:
    snapshot = self.run_tool("branch-snapshot", stdin=snapshot_request)
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
- `self.do([...])` uses only literal lists or tuples of literal strings, and
  those strings do not contain forbidden flow-control terms.
- `self.do([...])` action lists are non-empty.
- `self.do([...])` is side-effect-only and is not assigned, returned, or used as
  an expression value.
- Direct `self.evaluate("...")` calls are assigned to variables annotated as
  `bool`, `int`, `float`, `str`, `Literal[...]`, or `list[...]` over a basic
  scalar type.
- `self.evaluate(SchemaType, ...)` is assigned to a variable annotated with the
  same schema type, and that schema has declarative `Value(...)` field
  descriptions using only allowed evaluation field types.
- `self.evaluate(...)` accepts only the subject; evaluations use ordinary
  Python lexical scope by default, with `self.context(...)` reserved for explicit
  scope narrowing or disambiguation.
- Local schema dataclasses appear immediately before the `self.evaluate(...)`
  statement that consumes them.
- Adjacent `self.do(...)` statements in the same Python statement block are
  rejected; related model-facing substeps use one grouped actions list.
- Adjacent `self.evaluate(...)` statements are allowed because evaluations are
  non-mutating.
- Required trace order is produced by the workflow code.
- Conditional branches produce the expected traces for true and false cases.
- Failure branches produce explicit blockers or fallback work.
- Blocking preconditions are checked before durable side effects such as
  commits, pushes, external submissions, background commit handoffs, or
  state/log writes.
- Subagents that must not own an operation do not have access to that operation
  in their workflow.
- Embedded code and rendered prose contain the expected operations and
  conditions from the workflow source.
- Executable helpers enforce the deterministic invariants they replace.
- Synchronous or asynchronous execution policy is represented by helper choice
  such as `self.do(...)`, `self.run_tool(...)`, `self.start_tool(...)`,
  workflow object `__call__`, `await job`, `self.wait_all(...)`, or
  `self.wait_any(...)`, not by words in the work-item string.
- Additional runtime primitives are declared in the base workflow contract and
  are generic workflow controls, not domain-specific hidden procedures.
- Workflow source calls only methods declared by the base workflow contract.
- Tool names passed to `self.run_tool(...)` and `self.start_tool(...)` resolve
  to real registered tools or commands in the target runtime.
- `AgentWorkflow.__call__` overrides use explicit typed positional-or-keyword
  parameters only; no keyword-only marker, positional-only marker, `*args`, or
  `**kwargs`.
- `AgentWorkflow.__call__` parameters and return types do not use `Any` or
  dictionary annotations; structured launch and result data use dataclass
  contracts.
- Workflow schemas do not use `context_packet` or similar string packet fields
  to smuggle structured state across boundaries.

For example, the research finalization workflow should have tests proving:

- work-state report and TODO updates happen before finalizer launch
- code changes cause `branch-snapshot` before finalizer launch
- snapshot inspection happens before any background commit or finalizer launch
- the finalizer workflow cannot create its own branch snapshot
- background commit/finalizer requests are not immediately polled unless a later
  step explicitly needs their result
