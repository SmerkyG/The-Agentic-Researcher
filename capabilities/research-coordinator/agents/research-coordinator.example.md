# Research Coordinator — Declarative Agent-Boundary Example

> Design example only. It intentionally has no agent frontmatter and does not
> use the `python agentic-workflow` fence. The syntax is executable through the
> initial Codex callback runtime, but this file itself is not a registered agent.

This example uses one rule to separate model work from external effects:

- Every model boundary is one `with self.agent_request()` block. Submission
  occurs only after the complete block has been declared successfully.
- `observe(...)`, `step(...)`, `var(...)`, and `field(...)` append ordered
  declarative nodes; none independently invokes the model.
- `observe(...)` introduces new external facts at an exact position. A
  model-free `self.observe(...)` retains facts until the next request.
- `step(...)` performs ordered agent-native work but returns no value.
- `var(...)` records an explicit answer for later nodes in the same model
  context. `field(...)` uses the same answer mechanism and additionally returns
  the value to imperative Python.
- `with guidance(...)` qualifies its enclosed declarations without creating a
  Python or identifier scope. A `guidance=` argument qualifies one node.
- `T | None` is a model decision about whether a field applies. `A | B | C` is
  a choice of exactly one typed shape.
- An `Operation` or `SubagentWorkflow` returned by a field is inert request
  data. It runs only through a later explicit `run`, `launch`, or `admit` call.
- Ordinary Python owns loops, branches over fields, operation ordering, waits,
  user suspension, and process lifecycles.

The author chooses the size of each model request by choosing the contents of
the outer block. Nested guidance managers construct an immutable request tree
at runtime; there is no workflow-AST compilation or separately authored wire
schema. The runtime derives a temporary response schema from declared types.

The value bound by `as` is a deferred result handle. It cannot be read inside
the block. After successful exit it exposes only validated `field(...)` values;
`var(...)` values remain model-context answers. Exceptions discard the partial
declaration and do not submit it.

The nodes, schema projections, prompt renderer, and response validator live in
`agentic_workflows.fill_spec`. `AgentWorkflow.agent_request()` connects them to
the persistent callback worker.

## Ordered Agent-Request Evaluation

An agent request is an ordered declarative program, not an order-insensitive
schema. The agent follows this advisory evaluation method:

1. Inspect the complete request, all guidance, new observations, and retained
   context before beginning work.
2. Process observation, step, variable, field, and guidance-scope nodes in
   declaration order. Complete a guidance scope before its next sibling.
3. Treat earlier observations, completed steps, and assignments as concrete
   context for later nodes without requesting another model boundary.
4. Anticipate later declared requirements when answering earlier nodes, but
   never assume a future observation or operation result already exists.
5. At an optional field, choose null or its shape. At a union field, select
   exactly one variant. Steps and observations never appear in Python's result.
6. Before resuming Python, check the complete assignment object for consistency
   with observations, retained context, and all applicable guidance.

Declaration order is workflow semantics. If a judgment needs the result of an
operation returned by a field, exit the request, run the operation imperatively,
and expose its result before a new request.

## Guidance Rendering

Guidance is trailing qualification, not timed work. Render a node's description
or action first and its guidance immediately afterward. Render a guidance
scope's qualification after its complete child sequence. Initial full-request
inspection still makes later qualification visible before execution.

If a constraint must become active only at one position, express it as a
`step(...)` or start a later request. Do not encode sequencing in guidance.

## Agent Context and Observations

A model assignment is already knowledge in the producing agent's context.
Python may consume returned fields for control flow or external execution, but
must not pass those answers back to the same agent as later inputs. User replies
likewise enter the active context automatically.

Inject only information newly obtained outside that context: tool or subagent
results, deterministic host values, or durable state recovered after restart or
compaction. The runtime is responsible for context continuity and recovery;
passing model knowledge through workflow inputs is not a substitute.

```python
from __future__ import annotations

from typing import Literal

from agentic_workflows.contract import CommandResult, Job, Value, WorkflowRecord
from agentic_workflows.fill_spec import field, guidance, observe, step, var
from agentic_workflows.research.agentic_notes_read import AgenticNotesReadTopicTool
from agentic_workflows.research.experiment_log_correct import ExperimentLogCorrectTool
from agentic_workflows.research.experiment_log_summary import ExperimentLogSummaryTool
from agentic_workflows.research.finalization import FinalizationTicket
from agentic_workflows.research.finalization_start import FinalizationStart
from agentic_workflows.research.git import GitRecentLogTool, GitStatusShortTool
from agentic_workflows.research.gpu import (
    LocalGpuCapacity,
    ReadEnvironmentVariableTool,
    discover_local_gpu_capacity,
)
from agentic_workflows.research.research_coordinator import ResearchCoordinator
from agentic_workflows.research.research_finalizer import ResearchFinalizer


class ContinueResearch(WorkflowRecord):
    next_step: str = Value("Next productive autonomous experiment or analysis")


class AskUser(WorkflowRecord):
    question: str = Value(
        "Specific blocker or consequential choice and the exact user input needed"
    )


class ResearchComplete(WorkflowRecord):
    summary: str = Value("Concise synthesis of the completed research track")


class ResearchCoordinatorWorkflow(ResearchCoordinator):
    """Coordinator whose model boundaries are aggregate declarative requests."""

    def on_startup(self) -> None:
        self.read_in_on_state()

    def on_compaction(self) -> None:
        self.read_in_on_state()

    def read_in_on_state(self) -> None:
        # These independent reads are imperative operations. Their results are
        # new external observations for the following agent request.
        summary_job: Job[CommandResult] = self.launch(ExperimentLogSummaryTool())
        log_job: Job[CommandResult] = self.launch(GitRecentLogTool(count=20))
        status_job: Job[CommandResult] = self.launch(GitStatusShortTool())
        summary, recent_log, status = self.wait_all(
            [summary_job, log_job, status_job]
        )

        with self.agent_request() as initial_state:
            observe(
                experiment_summary=summary,
                recent_code_history=recent_log,
                worktree_status=status,
            )
            step(
                "Read the active research plan, TODO.md, condensed_report.md, latest "
                "report page, and relevant older pages. "
                "Skip missing records and inspect figures when relevant."
            )
            field(
                "relevant_note_topics",
                list[str],
                "relevant on-demand Agentic Notes topics",
                guidance=(
                    "Request only topics that can affect the immediate research direction."
                ),
            )

        # The selected topics are now concrete data, so ordinary Python owns
        # the fan-out and wait. Their observations require a new request boundary.
        note_jobs: list[Job[CommandResult]] = []
        for topic in initial_state.relevant_note_topics:
            note_job: Job[CommandResult] = self.launch(
                AgenticNotesReadTopicTool(topic=topic)
            )
            note_jobs.append(note_job)
        note_results = self.wait_all(note_jobs)
        self.observe(rendered_notes=note_results)

    def check_gpu(self) -> None:
        local: LocalGpuCapacity = discover_local_gpu_capacity()
        backend_result: CommandResult = ReadEnvironmentVariableTool(
            name="AR_JOB_BACKEND",
            default="none",
        ).run()
        backend_name = backend_result.stdout.strip() or "none"
        self.observe(
            local_gpu_capacity=local,
            configured_job_backend=backend_name,
        )

        if backend_name == "none":
            return

        with self.agent_request():
            step("Read the configured backend skill and run its status or list command.")
            var(
                "evidence",
                str,
                "concise backend-status evidence for the classification",
            )
            var(
                "capacity",
                Literal["available", "unavailable", "unknown"],
                "remote GPU capacity classification from backend status",
            )

    def workflow(self) -> None:
        self.check_gpu()

        while True:
            with self.agent_request() as iteration:
                with guidance("Prefer a cheap experiment changing exactly one variable."):
                    var("experiment", str, "next focused experiment from the plan, report, TODO, or latest result")
                    var("hypothesis", str, "testable hypothesis for the experiment")
                    var("changed_variable", str, "the single experimental variable to change")
                    var("metric", str, "`experiment` metric")
                    var("direction", str, "`experiment` direction")
                    var("baseline", str, "`experiment` baseline")
                    var("min_decision_scale", str, "`experiment` minimum decision scale")
                    var("commands", list[str], "tiered debugging, signal, full-decision, and verification commands")

                with guidance(
                    "Use the retained agent context and the active workspace. Complete the research work before returning the record."
                ):
                    with guidance(
                            "Debugging results are for fixing the implementation, not "
                            "drawing conclusions. Do useful independent work instead "
                            "of waiting idly during long jobs."
                        ):
                        step("Implement `experiment`.")
                        step("Run debugging, signal, and full-decision evaluation tiers.")
                        step("Fix implementation failures and rerun until genuine results exist.")
                        step("Verify nontrivial mathematical or algorithmic claims.")

                    with guidance("Include only evidence actually obtained during the preceding steps."):
                        var("evidence", list[str], "concrete measurements, artifact paths, and verification results")

                    var("verification_grade", Literal["verified", "partially-verified", "unverified"],
                        "verification grade justified by the completed checks")

                    with guidance(
                            "`report` and `summary` must describe a genuinely completed experiment. "
                            "Do not fill evidence or conclusions from expected results."
                        ):
                        with guidance("Report regressions and negative results honestly."):
                            var("report", str,
                                "Analyze the recorded evidence against the `hypothesis`, `baseline`, `metric`, `min_decision_scale`.")
                        var("summary", str, "honest decision-grade conclusion supported by the evidence")

                    with guidance("Never rewrite an existing experiment record."):
                        field("correction", ExperimentLogCorrectTool | None,
                            "append-only correction for a previously logged experiment, or null when none is needed",
                        )
                    with guidance(
                            "Use explicit code paths, a focused commit message, non-redundant "
                            "immutable-snapshot checks, and work-state-relative report asset paths. "
                            "For standard-library-only Python checks use `uv run --no-project "
                            "python ...`; use ordinary `uv run` only when project dependencies "
                            "are required."
                        ):
                        field("finalization", FinalizationStart)

                    with guidance(
                            "Re-analyze the result for additional productive autonomous work before "
                            "choosing ResearchComplete. Choose AskUser only for a genuine blocker or "
                            "consequential choice."
                        ):
                        field("continuation", ContinueResearch | AskUser | ResearchComplete,
                            "what the coordinator should do after handing off finalization",
                        )

            # Agent-native effects requested by step() have completed. Returned
            # workflow operations and lifecycle transitions remain explicit,
            # imperative, and validated below.
            if iteration.correction is not None:
                iteration.correction.run()

            ticket: FinalizationTicket = iteration.finalization.run()

            # Admission waits for receiver-side contract validation and durable
            # launcher acceptance. Detach transfers completion ownership to the
            # launcher; the coordinator never polls or waits for this finalizer.
            accepted_finalizer = self.admit(ResearchFinalizer(ticket=ticket))
            self.detach(accepted_finalizer)

            # This is ordinary host-owned pattern matching over a concrete union.
            match iteration.continuation:
                case ContinueResearch():
                    continue
                case AskUser(question=question):
                    self.ask_user(question)
                    continue
                case ResearchComplete(summary=summary):
                    self.ask_user(
                        summary
                        + "\n\nWhat new track of experiments would you like me to begin?"
                    )
                    continue
```

## Runtime Bridge

`agentic_workflows.fill_spec` also exposes a model-free builder for renderer,
schema, and validation tests. It uses the same lowercase declarations:

```python
from agentic_workflows.fill_spec import (
    agent_request_spec,
    assignment_schema,
    field,
    guidance,
    output_schema,
    render_agent_request,
    step,
    var,
)

with agent_request_spec("iteration") as declaration:
    with guidance("Describe completed work, not expected results."):
        var("hypothesis", str, "testable hypothesis")
        step("Run the focused experiment.")
        field("evidence", list[str], "measurements actually obtained")
    field("continuation", ContinueResearch | AskUser | ResearchComplete)

spec = declaration.spec
request_text = render_agent_request(spec)
resume_schema = assignment_schema(spec)
result_schema = output_schema(spec)
```

`agent_request_spec(...)` builds the immutable tree without invoking a model.
`render_agent_request` preserves node order and trailing guidance.
`assignment_schema` includes both variables and fields for callback validation;
`output_schema` projects only fields made available to Python.

For Codex, the `agentic_workflows.start_workflow` MCP tool launches a persistent worker.
The worker executes ordinary Python until it reaches `agent_request()`, renders
the request and yields it as JSON, then blocks with the Python stack intact.
Codex performs the steps and calls the supplied `resume` command once with all
assignments. The worker validates them, exposes fields on the deferred handle,
and continues Python until the next boundary. One request is one semantic model
boundary, not necessarily one raw inference.

## Standing Research Guidance

A runnable replacement would retain the declarative Research Modules, Strategy,
Experiment Logging and Research Record, Verification Protocol, Git Discipline,
Directory and File Conventions, and Troubleshooting sections from
`research-coordinator.md`. They are intentionally not duplicated here because
this example is focused on fill and execution-boundary semantics.
