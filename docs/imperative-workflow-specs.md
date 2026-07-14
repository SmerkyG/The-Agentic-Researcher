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
- Embed the workflow source for the agent to follow, while extracting
  deterministic steps into executable tools where practical.
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

Agent definition YAML frontmatter is outside the workflow language. It MUST be
consumed by the launcher as role metadata and MUST NOT be interpreted as tool
input or imperative agent behavior. The Markdown body supplies standing
declarative guidance; the embedded workflow supplies control flow.

A workflow spec MUST be written as normal Python control flow. The workflow
source may use helper methods supplied by the runtime, but it should still read
like an ordinary function. Workflows that invoke subagents or tools SHOULD
construct the exact operation object. Call `operation.run()` for synchronous
work, `self.launch(operation)` for tracked asynchronous work, or
`self.fire_and_forget(operation)` when no handle or result is needed:

```python
def complete_result(self, result) -> None:
    self.do(["update work-state report page and TODO.md"])

    snapshot = None
    if result.has_code_changes:
        snapshot = BranchSnapshot(
            paths=result.snapshot_paths,
            commit_message=result.snapshot_commit_message,
            checks=result.snapshot_checks,
        ).run()
        status = snapshot.name_status

        if status.has_unexpected_files:
            decision = self.ask_user(
                "Snapshot includes unexpected files. Continue, revise, or stop?",
                choices=["revise", "continue", "stop"],
            )
            if decision.choice == "revise":
                self.do(["revise branch-snapshot request"])
            elif decision.choice == "stop":
                self.do(
                    ["prepare final response"],
                    guidance="The user stopped after reviewing unexpected snapshot files.",
                )
                return

    self.fire_and_forget(
        ResearchFinalizer(
            experiment_log=experiment_log,
            note_update=note_update,
            code_snapshot=snapshot,
        )
    )
```

Examples use `self` intentionally. The receiver represents the active workflow
or agent object. Class-backed subagents or subworkflows are configured by
constructing the workflow object with typed fields, e.g.
`self.fire_and_forget(ResearchFinalizer(...))` or
`workflow = ResearchFinalizer(...)`.
Implementations may still delegate to a separate context object internally, but
the published workflow should read like ordinary Python agent behavior.

The order of these statements is the order of the workflow. No English string in
the example is responsible for establishing the ordering.

Every function and method in workflow source MUST declare an explicit return
type annotation. Use `-> None` for side-effect-only workflow steps. Helper
functions that return domain values MUST name those values in the type system,
not only through function names or comments.

Every `AgentWorkflow.workflow` override MUST take only `self`. Workflow launch
configuration belongs in typed constructor fields on the workflow class. Those
fields and the return annotation MUST NOT use `Any`, `dict`, `Dict`, or
`dict[...]`. Use explicit scalar fields for simple values and `WorkflowRecord`
request/result contracts for structured values.

Workflow code SHOULD NOT extract a single-use phase into a helper method merely
to name the phase. Inline one-off control flow at the caller. Extract a helper
only when it is reused, deterministic and testable, or represents a real
workflow/subagent boundary with its own `run` entrypoint.

Workflow code SHOULD prefer linear statements over redirects through small
classes, helper methods, or named phases. A human should be able to read the
workflow top to bottom and understand the intent and recipe without jumping
elsewhere, except when crossing a real tool, subagent, or durable data-contract
boundary.

## Interpreter Interface

Workflow source MUST be valid Python against the declared `AgentWorkflow`
interface, not pseudocode with ad hoc fake functions. The workflow is followed
by the agent rather than executed as a local Python program. Method semantics
belong in the interface docstrings and the agent-facing interpreter guide:

```python
def Value(description: str, *, default=MISSING, default_factory=MISSING):
    """Describe one WorkflowRecord field filled by self.evaluate(SchemaType)."""


class WorkflowRecord:
    """Base class for structured workflow values."""


class Job(WorkflowRecord):
    """
    Opaque handle returned by an asynchronous tool or workflow launch.

    Workflow code passes Job values to wait_all, wait_any, or cancel to track
    progress and receive results. Workflow code must not inspect implementation
    details such as process IDs, backend IDs, or status file paths.
    """


class OperationNotice(WorkflowRecord):
    """Out-of-band instructions followed before an operation's normal result."""

    instructions: str


class Operation(WorkflowRecord):
    """A runnable workflow operation, implemented by a tool or subagent."""

    guidance: ClassVar[str] = ""

    def run(self):
        """Start this tool or subagent synchronously and return its result."""


class WorkflowTool(Operation):
    """Generic tool operation."""


class ArgvTool(WorkflowTool):
    """Command-backed tool whose invocation is represented as argv."""

    argv_template: ClassVar[tuple[str, ...]]

    def argv(self):
        """Return command argv for this invocation."""


class YAMLArgvTool(ArgvTool):
    """Run exact argv with this operation's structured fields as YAML stdin."""


class AgentWorkflow(Operation):
    def on_startup(self):
        """Lifecycle hook followed once before workflow() at session startup."""

    def on_compaction(self):
        """Lifecycle hook followed after compaction before resuming workflow()."""

    def workflow(self):
        """Follow or execute this agent context's workflow body."""

    def do(self, actions: Sequence[str], guidance: str | None = None):
        """
        Synchronously give the current agent one or more related plain-language
        side-effecting actions.

        The actions argument must be a literal list or tuple of strings in
        workflow source and must contain at least one string.

        The optional guidance argument is literal declarative context for the
        action group. It may contain explanatory policy wording, but it is not
        workflow control flow.
        """

    def evaluate(self, subject: str | type[Any], guidance: str | None = None):
        """
        Non-mutating model judgment over current context.

        For direct facts, subject is one declarative string and the assigned
        variable annotation must be bool, int, float, str, Literal[...] or
        list[...] over a basic scalar type. For structured facts, subject is a
        WorkflowRecord schema whose fields use Value(...) descriptions, and the
        assigned variable annotation must match the schema.

        The optional guidance argument is literal declarative context for the
        judgment. It is not a second subject and not a place to pass hidden
        structured inputs.
        """

    def fill(self, record_type: type[WorkflowRecord], guidance: str | None = None):
        """
        Construct and fill one typed record from current context.

        The optional guidance argument is literal declarative context for
        filling the record. Field meanings still belong on Value(...)
        descriptions.
        """

    def launch(self, operation: Operation):
        """Start a tool or named subagent asynchronously and return its tracked Job."""

    def fire_and_forget(self, operation: Operation) -> None:
        """Start asynchronously, discard its platform handle, and continue now.

        Immediately follow the next Python statement. Never wait for, poll,
        list, message, follow up with, or otherwise inspect this operation. No
        later action or response may depend on its completion or result.
        """

    def wait_all(self, jobs, timeout_seconds=None):
        """Wait for every job and return completion/progress results."""

    def wait_any(self, jobs, timeout_seconds=None):
        """Return completed jobs without cancelling unfinished jobs."""

    def cancel(self, job):
        """Request cancellation and record the cancellation attempt."""

    def lock(self, name):
        """Serialize a critical section for the named runtime scope."""

    def timeout(self, seconds):
        """Bound the enclosed operation with an explicit timeout policy."""


class SubagentWorkflow(AgentWorkflow):
    """A workflow that must run in a separately started subagent context.

    The child follows the contract named by agent_name and receives the typed
    constructor fields as its request. Preserve inherited history when the
    platform supports it. If a native named role cannot inherit history, a
    history fork must be explicitly directed to follow the named contract.
    The caller must never execute this workflow's body.
    """


class UserFacingWorkflow(AgentWorkflow):
    """Top-level workflow that can pause for visible user input."""

    def ask_user(self, question: str, **kwargs):
        """
        Suspend for user input, then resume with the user's response.

        The question is the model-facing contract for what to ask. It should be
        specific enough to render a user-facing prompt from current context:
        describe the blocker or choice, why autonomous workflow should not
        decide it alone, what input shape is useful, and any stop/skip choices.
        """
```

Workflow specs MUST NOT call methods that are neither part of the declared
workflow contract nor defined on the current workflow class. Reused ordinary
Python helper methods are valid; invented runtime primitives are not.

Every agent implementation subclass MUST define `workflow` as its entrypoint.
`Operation.run()` dispatches a tool or subagent and MUST NOT enter the called
agent's workflow body in the current context.
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

The optional `guidance=` argument supplies related declarative policy or
background for the whole `self.do(...)` action group:

```python
self.do(
    ["evaluate tiered experiment commands"],
    guidance=(
        "Use small-scale runs to catch implementation bugs. Draw conclusions "
        "only at the project-defined minimum scale."
    ),
)
```

Unlike `actions`, `guidance` is not linted for words such as `if`, `when`,
`before`, or `after`, because declarative policy often needs that language.
However, `guidance` MUST NOT be the only place that workflow ordering,
branching, retry behavior, or concurrency is defined. Those still belong in
Python control flow, declared tool implementations, or launched subworkflows.

`self.evaluate(...)` is non-mutating. Boolean evaluations may be used directly
as `if` or `while` tests when the result is not needed elsewhere:

```python
if self.evaluate("True when research continuation needs user input."):
    user_direction: str = self.ask_user(
        "Ask for the research-continuation input needed right now. Describe the blocker or choice, explain why autonomous research should not decide it alone, list the kind of answer needed, and say the user may reply stop.",
    )

while not self.evaluate("True when no actionable autonomous work remains."):
    self.do(["continue research loop"])
```

Adjacent assigned evaluations are also valid because they are independent
declarative judgments, not hidden side-effect ordering.

Use `guidance=` on `self.evaluate(...)` when a scalar judgment needs a policy
constraint that would make the subject string too crowded:

```python
experiment: str = self.evaluate(
    "The next experiment to run.",
    guidance=(
        "Change exactly one experimental variable. If two things change and "
        "the metric improves, the cause is unknown."
    ),
)
```

Direct `self.evaluate("...")` calls MUST either be used directly as an `if` or
`while` condition, or use annotated assignment. Conditional evaluations are
implicitly boolean. Assigned direct evaluations MUST annotate the target as
`bool`, `int`, `float`, `str`, `Literal[...]`, or `list[...]` / `List[...]`
over a basic scalar type. The evaluation description MUST be a literal
declarative string. It describes the value to produce, not a workflow action to
perform:

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
fields, define a `WorkflowRecord` schema and pass the schema to
`self.evaluate(...)`. Every schema field MUST have a real Python type and a
`Value(...)` description:

```python
from typing import Literal

class ExperimentResultAnalysis(WorkflowRecord):
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
into newline-separated strings. Boundary `WorkflowRecord` classes that are
never passed to `self.evaluate(...)` may use richer ordinary Python types when
the workflow needs them.

When a structured evaluation needs to mention several evidence sources or
criteria, put that grounding in the field descriptions rather than in sequential
`do(...)` calls:

```python
class ResultsAnalysis(WorkflowRecord):
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
unannotated assignment, an untyped dictionary, or a `WorkflowRecord` whose
fields lack `Value(...)` descriptions. The model supplies scalar facts and
schema fields. Python owns branching, validation, aggregation, and side effects.

Workflow specs MUST NOT hide structured state in string packets such as
`context_packet: str`. If several facts need to cross a workflow boundary, define
a `WorkflowRecord` with typed fields for those facts and pass that record
directly.

Avoid one-use structured evaluations when direct annotated variables are
clearer. If a one-use structured evaluation is still warranted, define the
`WorkflowRecord` schema in the same Python block immediately before the single
statement that consumes it. No unrelated workflow statement, tool call,
assignment, branch, or loop may appear between the schema definition and the
consuming `self.evaluate(...)` statement:

```python
def workflow(self) -> None:
    relevant_note_topics: list[str] = self.evaluate(
        "Relevant on-demand Agentic Notes topics.",
    )
    for topic in relevant_note_topics:
        AgenticNotesReadTopic(topic=topic).run()

    next_research_step: str = self.evaluate(
        "Immediate autonomous research step implied by loaded notes, records, Git status, and capacity.",
    )
```

Module-level `WorkflowRecord` schemas SHOULD be reserved for reusable contracts,
cross-method values, or subagent/tool boundaries. When a local schema is still
clearer than direct annotated variables, keep it adjacent to the exact call site
without inventing an additional inline schema language.

`self.evaluate(...)` with a structured subject MUST name a `WorkflowRecord`
schema as its first argument, and the assigned variable annotation MUST match
that schema:

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

`self.evaluate(...)` MUST NOT accept arbitrary context keywords such as
`backend_capacity_status=...`, `runner_result=...`, or `context=dict(...)`.
Use nearby lexical variables. If a fact is already known and should be part of the
output, construct the output `WorkflowRecord` in ordinary Python; do not also ask the
model to fill it.

`self.do([])` is never valid. Side-effect calls, scalar returns, and structured
actions MUST include at least one literal action string.

Do not define a local `WorkflowRecord` schema and then immediately copy the
same fields into an equivalent module-level `WorkflowRecord`. If a reusable
return type already exists, put the `Value(...)` field descriptions on that
reusable `WorkflowRecord` and assign the `self.evaluate(...)` result directly
to it.

## Explicit Tool Calls

Use a typed operation object's `run()` method for synchronous execution. Use
`self.launch(operation)` or `self.fire_and_forget(operation)` for asynchronous
execution. Do not pass tool names as strings, loose keyword arguments, argv
lists, or untyped dictionaries from workflow code:

```python
note_update.run()
self.fire_and_forget(experiment_log)
self.fire_and_forget(BranchCommit(snapshot_dir=snapshot.snapshot_dir, background=True))
```

A command-backed tool MUST subclass `ArgvTool`. Use `YAMLArgvTool` when the
tool's fields become YAML stdin. `argv_template` MUST identify a real command
known to the runtime. Tool input SHOULD be structured `WorkflowRecord` values, not untyped
dictionaries, ad hoc shell snippets, or prose. YAML examples may still be
rendered for human-facing docs, but JSON Schema generated from the
`WorkflowRecord` is the preferred agent-facing invocation contract.

An imperative-workflow tool class is an agent-facing adapter, not part of the
tool implementation. Executable commands and their runtime libraries MUST NOT
import `agentic_workflows` or depend on `WorkflowRecord`, `Value`, workflow
rendering, or workflow interpretation. They MUST own their request validation,
domain types, execution, and persisted-record formats independently. The
adapter MAY mirror that external command contract and tests SHOULD detect drift,
but dependency flow is one-way: imperative workflows know how to invoke tools;
tools do not know that imperative workflows exist.

Repeated deterministic command sequences SHOULD be extracted into a capability
bin command rather than spelled out as a chain of workflow-level tool calls. For
example, isolated research result integration should use a helper such as
`research-coordinator-finalization`, and branch integration Git plumbing
should use a helper such as `research-coordinator-branch-integrate`. The
workflow should show the semantic boundary; the helper should own the exact
`git fetch`, `git add`, `git commit`, `git push`, merge, cherry-pick, and check
sequence.

## Workflow Consumption Modes

The workflow source is not merely a Markdown generator. It is the canonical
contract for how the workflow should proceed. Agentic Team may expose that
contract in three forms.

### Executable Helpers

When a workflow step can be made reliable and fast enough, Agentic Team SHOULD
extract it into real executable code or a helper command. Examples include:

- validating a branch snapshot request
- inspecting `branch-snapshot` name-status output
- appending to and paginating numbered report pages
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
use abstract helper calls such as `self.do(...)`, `self.wait_all(...)`, and
`self.wait_any(...)` when those calls are defined by the workflow runtime or by
surrounding instruction text. Tools, subagents, and subworkflows should appear
as ordinary constructor-configured operation objects:
`job: Job[SomeResult] = self.launch(SomeWorkflow(config=config))`.

### Rendered Prose

Generated prose is a convenience layer for readability, not the source of truth.
It SHOULD be used to summarize the workflow, define helper meanings, and provide
model-facing prompts. It SHOULD NOT be the only representation of a high-risk
workflow whose ordering or failure behavior matters.

## English Work Items

English strings passed to imperative execution helpers are action descriptions.
Each string in a `self.do([...])` actions list MUST describe one atomic work
item at the level of the workflow interface.

Valid atomic work-item strings include `update work-state report page and
TODO.md`, `create branch-snapshot`, `inspect branch-snapshot name-status`, and
`append experiment-log correction`.

An English work item MUST NOT contain workflow control such as:

- ordering: `before`, `after`, `then`, `next`, `first`, `last`, `once`
- conditions: `if`, `when`, `unless`, `only if`, `provided that`
- loops: `while`, `until`, `repeat`, `for each`
- failure policy: `try`, `retry`, `fallback`, `otherwise`, `on failure`
- concurrency policy: `background`, `parallel`, `wait for`, `fire and forget`

The normative `MUST NOT` rule above is enforced by
`imperative-workflows-lint`, which parses workflow Python source and checks
literal strings passed to `self.do(...)`.
The linter is an implementation of this rule, not a replacement for it.

Rule violations:

- `self.do(["create branch-snapshot before launching finalizer"])` violates the
  ordering rule.
- `self.do(["if code changed, inspect the snapshot"])` violates the condition
  rule.
- `self.do(["update TODO.md after writing the report page"])` violates the ordering
  rule.
- `self.do(["try note-updater unless no reusable lesson exists"])` violates both
  the failure-policy rule and the condition rule.

If an operation genuinely has internal order, either split it into multiple
workflow statements or call a declared tool/helper whose implementation owns
that internal order. When a specific tool is required for correctness,
construct the typed tool and call its `run()` method or pass it to
`self.launch(...)` / `self.fire_and_forget(...)` instead of describing the
tool call in English.

`self.do(...)` statements MUST NOT be adjacent in the same Python statement
block. Adjacent opaque model-facing actions usually mean related work has been
split across calls without a typed contract tying the pieces together. Use one
`self.do([...])` call with multiple actions for related prompt decomposition, or
put a real Python/tool/subworkflow boundary between truly separate operations.

## Synchronous and Asynchronous Actions

Workflow code SHOULD distinguish blocking and non-blocking work through
declared runtime primitives, not through prose inside the work-item string.

Use `self.do(...)` for synchronous work. The operation must finish, fail, or
return a blocker before the next workflow statement runs:

```python
snapshot = BranchSnapshot(
    paths=snapshot_paths,
    commit_message=snapshot_commit_message,
    checks=snapshot_checks,
).run()
status = snapshot.name_status
```

Construct a workflow object and call `run()` for synchronous subagent
invocations. Pass it to `self.launch(...)` or `self.fire_and_forget(...)` for
asynchronous invocation. Use typed tool objects for structured background tool
handoffs:

```python
finalizer_job: Job[ResearchFinalizerResult] = self.launch(
    ResearchFinalizer(
        experiment_log=experiment_log,
        note_update=note_update,
        code_snapshot=snapshot,
    )
)
commit_job: Job[BranchCommitResult] = self.launch(
    BranchCommit(snapshot_dir=snapshot.snapshot_dir, background=True)
)
```

An operation may emit an `OperationNotice` separately from its normal return
value. The calling agent MUST suspend the call, follow the notice instructions,
and then resume the call to receive its normal result. Notices do not change the
declared result type and do not permit a subagent to address the user directly.

Wait on an individual job, or use `self.wait_all(...)` / `self.wait_any(...)`,
only when a later workflow step mechanically needs the result:

```python
commit_result = self.wait_all([commit_job])
self.do(["prepare integration handoff"], commit=commit_result.commit)
```

The parent workflow waits for background completion only by calling
`self.wait_all(...)` / `self.wait_any(...)` or another explicit status helper.

## Conditions and Returned Facts

Workflow applicability MUST be represented with code-level conditionals:

```python
if lesson_kind != "none":
    self.fire_and_forget(NoteUpdater(note_update=note_update))
```

If deciding the condition requires model judgment, the workflow SHOULD bind the
result to a suggestive variable name. Use `self.evaluate(...)` for non-mutating
facts:

```python
class GpuStatus(WorkflowRecord):
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

Use a typed tool operation when the exact tool is part of the workflow contract:

```python
nvidia_status = NvidiaSmiGpuIds().run()
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
    note_job: Job[NoteUpdaterResult] = self.launch(NoteUpdater(note_update=note_update))
    note_status = self.wait_all([note_job])
    if note_status.failed:
        self.do(["record note-updater blocker"])
```

A MAY-level action is represented by a condition where skipping the action is a
valid branch:

```python
can_queue_finalizer: bool = self.evaluate("True when finalizer handoff can be queued independently.")
if can_queue_finalizer:
    self.fire_and_forget(
        ResearchFinalizer(
            experiment_log=experiment_log,
            note_update=note_update,
            code_snapshot=snapshot,
        )
    )
```

Generated instructions may use the words `SHOULD` and `MAY` when rendering these
branches for a model, but the source of truth remains the code branch and its
failure behavior.

## Action, Tool, and Subagent Use

Tools and subagents are workflow operations.

Use `self.do(...)` when the agent owns an action and the exact tool is not part
of the contract:

```python
self.do(["inspect branch-snapshot name-status"])
```

Use a typed `WorkflowTool` when the exact operation and input shape are part of
the contract. Use `YAMLArgvTool` or `ArgvTool` for command-backed tools:

```python
snapshot = BranchSnapshot(
    paths=snapshot_paths,
    commit_message=snapshot_commit_message,
    checks=snapshot_checks,
).run()
status = snapshot.name_status

commit = BranchCommit(snapshot_dir=snapshot.snapshot_dir, background=False).run()
if commit.state == "committed" and commit.commit is not None:
    experiment_log.code.branch = snapshot.branch
    experiment_log.code.commit = commit.commit
    experiment_log.run()
```

Use `self.fire_and_forget(operation)` when the workflow only needs the request
to be durably queued:

```python
self.fire_and_forget(
    BranchCommit(snapshot_dir=snapshot.snapshot_dir, background=True)
)
self.fire_and_forget(
    ResearchFinalizer(
        experiment_log=experiment_log,
        note_update=note_update,
        code_snapshot=snapshot,
    )
)
```

`self.launch(operation)` starts tracked asynchronous work. Its direct return
value MUST be assigned to an explicitly annotated `Job[...]` variable that
later workflow code may wait on or cancel. `self.fire_and_forget(operation)`
MUST be a bare expression. The launching workflow MUST discard the underlying
platform handle and immediately execute the next Python statement. It MUST NOT
wait for, poll, list, message, follow up with, or otherwise inspect that
operation, and no later action or parent response may depend on its completion
or result. The operation MUST independently record enough status information
for later troubleshooting.

A subagent contract MUST subclass `SubagentWorkflow`. Starting one through
`run()`, `self.launch(...)`, or `self.fire_and_forget(...)` MUST use the
platform's subagent mechanism. The child MUST follow the contract named by
`agent_name` and receive the typed constructor fields as its invocation
request. The launcher SHOULD preserve inherited history. If a native named
role cannot inherit history, a history-forked child MUST be explicitly directed
to follow the named contract. The caller MUST NOT execute the subagent's
workflow body itself.

Subagent requests MUST be typed at the workflow boundary. The subagent's prompt
or contract may be English, but the parent workflow's decision to launch it,
wait for it, ignore it, or handle failure belongs in code.

## Failure Handling

Expected workflow blockers SHOULD be represented as ordinary Python branches,
loops, status values, and calls to `self.ask_user(...)`. Asking the user is a
continuation point: `self.ask_user(...)` suspends the workflow and resumes at
the next statement when the user answers.

Only `UserFacingWorkflow` subclasses may call `ask_user`. Subagents often run
behind CLI/tooling boundaries where the user will never see their prompts, so a
subagent that needs user input MUST return a typed status/request for its parent
to surface. It must not call `ask_user` itself.

Use `ask_user` in a user-facing workflow when a bounded decision or missing
value is needed. The question argument MUST describe what the user-facing prompt
must contain: the blocker or choice, why the workflow should not decide it
autonomously, what kind of answer is needed, and any stop/skip choices. It may
refer to current lexical variables or tool outputs; the workflow does not need a
separate `self.evaluate(...)` just to draft the prompt:

```python
decision = self.ask_user(
    "Ask how to handle unexpected branch snapshot files. Describe the unexpected files, explain why committing them may be unsafe, and ask for one of revise, accept, or stop.",
    choices=["revise", "accept", "stop"],
)

if decision.choice == "revise":
    self.do(["revise branch-snapshot request"])
elif decision.choice == "stop":
    self.do(
        ["prepare final response"],
        guidance="The user stopped after reviewing unexpected snapshot files.",
    )
    return
```

Blocking preconditions MUST be checked before durable side effects such as
commits, pushes, background commit handoffs, external job submissions, or
state/log writes. A workflow should not discover that a required
`snapshot`, `experiment_log`, or `note_update` is missing only after it has
already committed work-state records or queued other irreversible bookkeeping.

Workflows SHOULD handle expected operation failures near the point where the
policy is clear:

```python
snapshot = BranchSnapshot(
    paths=snapshot_paths,
    commit_message=snapshot_commit_message,
    checks=snapshot_checks,
).run()

if snapshot.name_status.has_unexpected_files:
    decision = self.ask_user(
        "Snapshot includes unexpected files. Revise, accept, or stop?",
        choices=["revise", "accept", "stop"],
    )
    if decision.choice == "revise":
        self.do(["revise branch-snapshot request"])
    elif decision.choice == "stop":
        self.do(["prepare final response"])
        return
```

Unexpected Python exceptions may still occur from implementation bugs, broken
tools, or violated invariants, but they are not the normal workflow language for
asking the user, retrying, or continuing after a decision.

## Publishing Workflow Contracts

Agent-facing instructions may include workflow contracts in several forms:

- executable command names for deterministic pieces
- embedded workflow code for model-stepped procedures
- generated prose summaries for readability

The rendered instructions may contain prose like:

```text
If code changes exist, create a branch snapshot and inspect its name-status.
Fork an isolated finalization workspace from the accepted snapshot and explicit
report assets, then launch the research-finalizer with that workspace handle.
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
- `self.evaluate(...)` accepts only the subject and optional guidance;
  evaluations use ordinary Python lexical scope.
- Local `WorkflowRecord` schemas appear immediately before the `self.evaluate(...)`
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
  such as `self.do(...)`, `operation.run()`, `self.launch(operation)`,
  `self.fire_and_forget(operation)`, `self.wait_all(...)`, or
  `self.wait_any(...)`, not by words in the work-item string.
- Additional runtime primitives are declared in the base workflow contract and
  are generic workflow controls, not domain-specific hidden procedures.
- Workflow source calls only methods declared by the base workflow contract.
- `YAMLArgvTool.argv_template` and `ArgvTool.argv_template` values resolve
  to real command-backed tools in the target runtime.
- `AgentWorkflow.workflow` overrides take only `self`; launch configuration is
  represented by typed constructor fields.
- `AgentWorkflow` constructor fields and return types do not use `Any` or
  dictionary annotations; structured launch and result data use
  `WorkflowRecord` or `WorkflowTool` contracts.
- Workflow schemas do not use `context_packet` or similar string packet fields
  to smuggle structured state across boundaries.

For example, the research finalization workflow should have tests proving:

- code changes cause `branch-snapshot` before finalization workspace creation
- snapshot inspection happens before finalizer launch
- the coordinator freezes explicit report assets before continuing
- the finalizer authors reports and TODOs only in its private state worktree
- finalizers refresh and integrate in capture order
- code checks pass before private research records are integrated
- durable finalization status survives the discarded child handle
- the coordinator does not poll or wait for the detached finalizer
