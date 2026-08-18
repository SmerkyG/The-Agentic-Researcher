"""Research Coordinator contract and workflow."""

from __future__ import annotations

import os
from typing import ClassVar, Literal

from agentic_workflows.contract import (
    CommandResult,
    Job,
    UserFacingWorkflow,
)
from agentic_workflows.request_spec import (
    AgentRequest,
    guidance,
    local,
    result,
    step,
)
from agentic_notes.tools.read import AgenticNotesReadTopicTool
from experiment_log.tools.correct import ExperimentLogCorrectTool
from experiment_log.tools.summary import (
    ExperimentLogSummaryResult,
    ExperimentLogSummaryTool,
)
from agentic_workflows.research.finalization_start import FinalizationStart
from agentic_workflows.research.git import GitRecentLogTool, GitStatusShortTool
from agentic_workflows.research.gpu import (
    LocalGpuCapacity,
    discover_local_gpu_capacity,
)
from agentic_workflows.research.research_finalizer import ResearchFinalizer
from agentic_workflows.research.research_state import ResearchStateInitializeTool
from research_finalization.records import FinalizationTicket
from research_finalization.tools.reconcile import FinalizationReconcileTool


class ResearchCoordinator(UserFacingWorkflow[None]):
    """Coordinate autonomous research through aggregate declarative boundaries."""

    agent_name: ClassVar[str] = "research-coordinator"

    def on_startup(self) -> None:
        self.read_in_on_state()

    def on_compaction(self) -> None:
        self.read_in_on_state()

    def read_in_on_state(self) -> None:
        FinalizationReconcileTool(project_dir=".").run()
        summary_job: Job[ExperimentLogSummaryResult] = self.launch(
            ExperimentLogSummaryTool()
        )
        log_job: Job[CommandResult] = self.launch(GitRecentLogTool(count=20))
        status_job: Job[CommandResult] = self.launch(GitStatusShortTool())
        self.wait_all([summary_job, log_job, status_job])

        class InitialState(AgentRequest):
            step(
                "Read the active research plan, TODO.md, condensed_report.md, latest "
                "report page, and relevant older pages. Skip missing records and "
                "inspect figures when relevant."
            )
            relevant_note_topics: list[str] = result(
                "relevant on-demand Agentic Notes topics",
                guidance="Request only topics that can affect the immediate research direction.",
            )
            state_action: Literal["use_existing", "interactive_setup"] = result(
                "whether existing work-branch Project Instructions are complete enough "
                "to resume or fresh interactive setup is required",
            )

        initial_state = self.agent_request(InitialState)

        if initial_state.state_action == "interactive_setup":
            self.ask_user(
                "Ask at most three concise questions needed to establish this research "
                "branch's goal and context: the research goal, primary metric and which "
                "direction is better, and current codebase state. Use retained context "
                "from the invocation, omit questions already answered there, and briefly "
                "confirm already-known items instead of asking for them again."
            )
            self.ask_user(
                "Ask at most three concise follow-up questions needed to establish evaluation "
                "and constraints: the exact evaluation command, known baseline, fixed "
                "constraints, and target improvement. Use the original request and preceding "
                "answers, combine related items, and omit questions already answered."
            )
            self.ask_user(
                "Ask at most three concise final setup questions needed to establish approach, "
                "scope, and compute: preferred approaches, papers or prior attempts, minimum "
                "decision scale, off-limits areas, and compute budget. Use all retained answers, "
                "combine related items, and omit questions already answered."
            )

            class DraftProjectInstructions(AgentRequest):
                plan: str = result(
                    "complete work-branch Project Instructions synthesized from the original "
                    "request and all interactive setup answers",
                    guidance=(
                        "Write Markdown with: title and work branch; goal; primary metric name, "
                        "direction, evaluation command, and baseline; fixed constraints; target "
                        "improvement; minimum decision scale; prioritized initial approaches; "
                        "references and prior attempts; compute budget; off-limits files or "
                        "areas; current next steps; and additional notes. Mark genuinely unknown "
                        "values TBD rather than inventing them."
                    ),
                )

            draft = self.agent_request(DraftProjectInstructions)
            plan = draft.plan
            approved = False
            while not approved:
                self.ask_user(
                    "Present the following proposed work-branch Project Instructions clearly, "
                    "then ask the user to approve them or describe specific changes. Do not "
                    f"silently alter the proposal:\n\n{plan}"
                )

                class PlanReview(AgentRequest):
                    decision: Literal["approve", "revise"] = result(
                        "whether the user approved the displayed plan or requested changes",
                    )

                review = self.agent_request(PlanReview)
                if review.decision == "approve":
                    approved = True
                else:
                    class PlanRevision(AgentRequest):
                        revised_plan: str = result(
                            "revised complete plan incorporating the requested changes",
                        )

                    revision = self.agent_request(PlanRevision)
                    plan = revision.revised_plan

            ResearchStateInitializeTool(plan=plan).run()

        note_jobs: list[Job[CommandResult]] = []
        for topic in initial_state.relevant_note_topics:
            note_job: Job[CommandResult] = self.launch(
                AgenticNotesReadTopicTool(topic=topic)
            )
            note_jobs.append(note_job)
        self.wait_all(note_jobs)

    def check_gpu(self) -> str:
        local_capacity: LocalGpuCapacity = discover_local_gpu_capacity()
        backend_name = os.environ.get("AR_JOB_BACKEND", "none").strip() or "none"
        self.queue_agent_observation(local_capacity)
        if backend_name != "none":

            class BackendStatus(AgentRequest):
                step(
                    f"Read the configured {backend_name} backend skill and run its "
                    "status or list command."
                )
                backend_evidence: str = local(
                    "concise backend-status evidence for the classification",
                )
                backend_capacity: Literal[
                    "available", "unavailable", "unknown"
                ] = local(
                    "remote GPU capacity classification from backend status",
                )

            self.agent_request(BackendStatus)
        return backend_name

    def workflow(self) -> None:
        backend_name = self.check_gpu()

        while True:
            class Iteration(AgentRequest):
                with guidance("Prefer a cheap experiment changing exactly one variable."):
                    experiment: str = local(
                        "next focused experiment from the plan, report, TODO, or latest "
                        f"result with external job backend {backend_name}",
                    )
                    hypothesis: str = local(f"testable hypothesis for {experiment}")
                    changed_variable: str = local(
                        f"the single experimental variable to change in {experiment}",
                    )
                    metric: str = local(f"decision metric for {experiment}")
                    direction: str = local(f"desired direction for {metric}")
                    baseline: str = local(f"baseline for {metric}")
                    minimum_decision_scale: str = local(
                        f"minimum scale needed for a decision about {experiment}",
                    )
                    commands: list[str] = local(
                        "tiered debugging, signal, full-decision, and verification "
                        f"commands for {experiment}",
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
                        step(f"Implement {experiment}, changing only {changed_variable}.")
                        with guidance(
                            "GPU based tiers expected to take more than 10 seconds should be "
                            "done in parallel. If one fails, cancel the rest."
                        ):
                            step(
                                f"Run the debugging, signal, and full-decision tiers in {commands}."
                            )
                            step(
                                "Fix implementation failures and rerun until genuine results exist."
                            )
                        step(
                            f"Run the verification work in {commands} for nontrivial claims."
                        )

                    evidence: list[str] = local(
                        "concrete measurements, artifact paths, and verification "
                        f"results obtained for {experiment}",
                        guidance=(
                            "Include only evidence actually obtained during the preceding steps."
                        ),
                    )
                    verification_grade: Literal[
                        "verified", "partially-verified", "unverified"
                    ] = local(
                        f"verification grade justified by {evidence}",
                    )
                    report: str = local(
                        f"analysis of {evidence} against {hypothesis}, {baseline}, "
                        f"{metric}, {direction}, and {minimum_decision_scale}",
                        guidance="Report regressions and negative results honestly.",
                    )
                    experiment_summary: str = local(
                        f"honest decision-grade conclusion supported by {evidence}",
                        guidance=(
                            "Describe genuinely completed work; never substitute expected results."
                        ),
                    )

                    correction: ExperimentLogCorrectTool | None = result(
                        "append-only correction for a previously logged experiment, or null",
                        guidance="Never rewrite an existing experiment record.",
                    )
                    finalization: FinalizationStart = result(
                        "finalization request for this completed result",
                        guidance=(
                            "Use explicit code paths, a focused commit message, non-redundant "
                            "immutable-snapshot checks, and branch-records-relative report asset paths. "
                            "When code_paths is empty, use a null commit_message and empty checks. "
                            "For standard-library-only Python checks use `uv run --no-project "
                            "python ...`; use ordinary `uv run` only when project dependencies "
                            "are required."
                        ),
                    )
                    continuation: Literal[
                        "continue_research", "ask_user", "research_complete"
                    ] = result(
                        "what to do after handing off finalization",
                        guidance=(
                            "Re-analyze the result for productive autonomous work before choosing "
                            "research_complete. Choose ask_user only for a genuine blocker or "
                            "consequential choice."
                        ),
                    )

            iteration = self.agent_request(Iteration)

            if iteration.correction is not None:
                iteration.correction.run()

            ticket: FinalizationTicket = iteration.finalization.run()
            accepted_finalizer = self.admit(ResearchFinalizer(ticket=ticket))
            self.detach(accepted_finalizer)

            if iteration.continuation == "ask_user":
                self.ask_user(
                    "Using the completed experiment and retained research context, explain the "
                    "specific blocker or consequential choice, why autonomous work cannot decide "
                    "it safely, and ask for the exact user input needed to continue."
                )
            elif iteration.continuation == "research_complete":
                self.ask_user(
                    "Give the user a concise synthesis of the completed research track grounded "
                    "in retained verified results, then ask what new track of experiments they "
                    "would like to begin."
                )
