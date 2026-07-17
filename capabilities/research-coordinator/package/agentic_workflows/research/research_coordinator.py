"""Research Coordinator contract and workflow."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import (
    CommandResult,
    Job,
    UserFacingWorkflow,
    Value,
    WorkflowRecord,
)
from agentic_workflows.fill_spec import field, guidance, observe, step, var
from agentic_workflows.research.agentic_notes_read import AgenticNotesReadTopicTool
from agentic_workflows.research.experiment_log_correct import ExperimentLogCorrectTool
from agentic_workflows.research.experiment_log_summary import ExperimentLogSummaryTool
from agentic_workflows.research.finalization import FinalizationTicket
from agentic_workflows.research.finalization_reconcile import FinalizationReconcileTool
from agentic_workflows.research.finalization_start import FinalizationStart
from agentic_workflows.research.git import GitRecentLogTool, GitStatusShortTool
from agentic_workflows.research.gpu import (
    LocalGpuCapacity,
    ReadEnvironmentVariableTool,
    discover_local_gpu_capacity,
)
from agentic_workflows.research.research_finalizer import ResearchFinalizer
from agentic_workflows.research.research_state import ResearchStateInitializeTool


class ContinueResearch(WorkflowRecord):
    next_step: str = Value("Next productive autonomous experiment or analysis")


class AskUser(WorkflowRecord):
    question: str = Value(
        "Specific blocker or consequential choice and the exact user input needed"
    )


class ResearchComplete(WorkflowRecord):
    summary: str = Value("Concise synthesis of the completed research track")


class UseExistingResearchState(WorkflowRecord):
    reason: str = Value("Evidence that an active research plan already exists")


class InitializeResearchState(WorkflowRecord):
    plan: str = Value("Complete proposed research plan derived from the user's request")
    already_approved: bool = Value(
        "True only when the user explicitly supplied or approved this complete plan"
    )
    approval_question: str = Value(
        "Specific request to approve the plan or describe required changes"
    )


class ApprovePlan(WorkflowRecord):
    confirmation: str = Value("Why the user's response approves the displayed plan")


class RevisePlan(WorkflowRecord):
    plan: str = Value("Revised complete plan incorporating the user's requested changes")
    approval_question: str = Value("Specific request to approve this revision or change it")


class ResearchCoordinator(UserFacingWorkflow[None]):
    """Coordinate autonomous research through aggregate declarative boundaries."""

    agent_name: ClassVar[str] = "research-coordinator"

    def on_startup(self) -> None:
        self.read_in_on_state()

    def on_compaction(self) -> None:
        self.read_in_on_state()

    def read_in_on_state(self) -> None:
        reconciliation = FinalizationReconcileTool(project_dir=".").run()
        summary_job: Job[CommandResult] = self.launch(ExperimentLogSummaryTool())
        log_job: Job[CommandResult] = self.launch(GitRecentLogTool(count=20))
        status_job: Job[CommandResult] = self.launch(GitStatusShortTool())
        summary, recent_log, status = self.wait_all(
            [summary_job, log_job, status_job]
        )

        with self.agent_request() as initial_state:
            observe(
                finalization_reconciliation=reconciliation,
                experiment_summary=summary,
                recent_code_history=recent_log,
                worktree_status=status,
            )
            step(
                "Read the active research plan, TODO.md, condensed_report.md, latest "
                "report page, and relevant older pages. Skip missing records and "
                "inspect figures when relevant."
            )
            field(
                "relevant_note_topics",
                list[str],
                "relevant on-demand Agentic Notes topics",
                guidance="Request only topics that can affect the immediate research direction.",
            )
            field(
                "state_action",
                UseExistingResearchState | InitializeResearchState,
                "whether to use the existing active plan or initialize missing research state",
            )

        match initial_state.state_action:
            case UseExistingResearchState():
                pass
            case InitializeResearchState(
                plan=plan,
                already_approved=already_approved,
                approval_question=approval_question,
            ):
                while not already_approved:
                    self.ask_user(plan + "\n\n" + approval_question)
                    with self.agent_request() as review:
                        field(
                            "decision",
                            ApprovePlan | RevisePlan,
                            "whether the user approved the displayed plan or requested changes",
                        )
                    match review.decision:
                        case ApprovePlan():
                            already_approved = True
                        case RevisePlan(
                            plan=revised_plan,
                            approval_question=revised_question,
                        ):
                            plan = revised_plan
                            approval_question = revised_question
                initialized: CommandResult = ResearchStateInitializeTool(plan=plan).run()
                if initialized.returncode != 0:
                    raise RuntimeError(
                        "research state initialization failed: "
                        + (initialized.stderr or initialized.stdout).strip()
                    )

        note_jobs: list[Job[CommandResult]] = []
        for topic in initial_state.relevant_note_topics:
            note_job: Job[CommandResult] = self.launch(
                AgenticNotesReadTopicTool(topic=topic)
            )
            note_jobs.append(note_job)
        self.observe(rendered_notes=self.wait_all(note_jobs))

    def check_gpu(self) -> None:
        local_capacity: LocalGpuCapacity = discover_local_gpu_capacity()
        backend: CommandResult = ReadEnvironmentVariableTool(
            name="AR_JOB_BACKEND",
            default="none",
        ).run()
        backend_name = backend.stdout.strip() or "none"
        self.observe(
            local_gpu_capacity=local_capacity,
            configured_job_backend=backend_name,
        )
        if backend_name != "none":
            with self.agent_request():
                step("Read the configured backend skill and run its status or list command.")
                var(
                    "backend_evidence",
                    str,
                    "concise backend-status evidence for the classification",
                )
                var(
                    "backend_capacity",
                    Literal["available", "unavailable", "unknown"],
                    "remote GPU capacity classification from backend status",
                )

    def workflow(self) -> None:
        self.check_gpu()

        while True:
            with self.agent_request() as iteration:
                with guidance("Prefer a cheap experiment changing exactly one variable."):
                    var(
                        "experiment",
                        str,
                        "next focused experiment from the plan, report, TODO, or latest result",
                    )
                    var("hypothesis", str, "testable hypothesis for `experiment`")
                    var(
                        "changed_variable",
                        str,
                        "the single experimental variable to change in `experiment`",
                    )
                    var("metric", str, "decision metric for `experiment`")
                    var("direction", str, "desired direction for `metric`")
                    var("baseline", str, "baseline for `metric`")
                    var(
                        "minimum_decision_scale",
                        str,
                        "minimum scale needed for a decision about `experiment`",
                    )
                    var(
                        "commands",
                        list[str],
                        "tiered debugging, signal, full-decision, and verification commands",
                    )

                with guidance(
                    "Use retained agent context and the active workspace. Complete the "
                    "research work before returning assignments."
                ):
                    with guidance(
                        "Debugging results are for fixing the implementation, not drawing "
                        "conclusions. Do useful independent work instead of waiting idly "
                        "during long jobs."
                    ):
                        step("Implement `experiment`, changing only `changed_variable`.")
                        with guidance(
                            "GPU based tiers expected to take more than 10 seconds should be "
                            "done in parallel. If one fails, cancel the rest."
                        ):
                            step(
                                "Run the debugging, signal, and full-decision tiers in `commands`."
                            )
                            step(
                                "Fix implementation failures and rerun until genuine results exist."
                            )
                        step("Run the verification work in `commands` for nontrivial claims.")

                    var(
                        "evidence",
                        list[str],
                        "concrete measurements, artifact paths, and verification results",
                        guidance=(
                            "Include only evidence actually obtained during the preceding steps."
                        ),
                    )
                    var(
                        "verification_grade",
                        Literal["verified", "partially-verified", "unverified"],
                        "verification grade justified by `evidence`",
                    )
                    var(
                        "report",
                        str,
                        "analysis of `evidence` against `hypothesis`, `baseline`, `metric`, "
                        "`direction`, and `minimum_decision_scale`",
                        guidance="Report regressions and negative results honestly.",
                    )
                    var(
                        "summary",
                        str,
                        "honest decision-grade conclusion supported by `evidence`",
                        guidance=(
                            "Describe genuinely completed work; never substitute expected results."
                        ),
                    )

                    field(
                        "correction",
                        ExperimentLogCorrectTool | None,
                        "append-only correction for a previously logged experiment, or null",
                        guidance="Never rewrite an existing experiment record.",
                    )
                    field(
                        "finalization",
                        FinalizationStart,
                        guidance=(
                            "Use explicit code paths, a focused commit message, non-redundant "
                            "immutable-snapshot checks, and work-state-relative report asset paths. "
                            "When code_paths is empty, use a null commit_message and empty checks. "
                            "For standard-library-only Python checks use `uv run --no-project "
                            "python ...`; use ordinary `uv run` only when project dependencies "
                            "are required."
                        ),
                    )
                    field(
                        "continuation",
                        ContinueResearch | AskUser | ResearchComplete,
                        "what to do after handing off finalization",
                        guidance=(
                            "Re-analyze the result for productive autonomous work before choosing "
                            "ResearchComplete. Choose AskUser only for a genuine blocker or "
                            "consequential choice."
                        ),
                    )

            if iteration.correction is not None:
                iteration.correction.run()

            ticket: FinalizationTicket = iteration.finalization.run()
            accepted_finalizer = self.admit(ResearchFinalizer(ticket=ticket))
            self.detach(accepted_finalizer)

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
