"""Prototype imperative workflows for Agentic Team research roles.

This file is intentionally reviewable Python, not generated Markdown. It
translates the current research coordinator and research subagents into the
imperative workflow style from docs/imperative-workflow-specs.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Literal

from workflow_runtime import AgentWorkflow, CommandResult, NeedsUser, Value, WorkflowFailed


@dataclass
class Job:
    """Handle returned by an asynchronous tool or workflow launch"""

    name: str
    status_path: str | None = None


@dataclass
class SnapshotNameStatus:
    """Parsed name-status review for a captured branch snapshot"""

    has_unexpected_files: bool = False
    path: str = ""


@dataclass
class Snapshot:
    """Captured branch snapshot metadata"""

    path: str
    name_status: SnapshotNameStatus
    status_path: str | None = None


@dataclass
class FinalizerContext:
    """Structured context needed by the research finalizer"""

    result_summary: str = Value("Concise completed result summary")
    evidence_paths: list[str] = Value("List of evidence paths for the completed result")
    check_commands: list[str] = Value("List of verification or check commands run for the result")
    changed_paths: list[str] = Value("List of code or configuration paths changed for the result")
    work_state_updates: list[str] = Value("List of work-state records updated for this result")
    verification_status: Literal["passed", "failed", "partial", "not_run", "unknown"] = Value(
        "Verification status for the completed result",
    )
    followup_items: list[str] = Value("List of autonomous follow-up items implied by the result")


@dataclass
class LocalGpuCapacity:
    """Normalized local GPU capacity from NVIDIA or ROCm probes"""

    vendor: Literal["nvidia", "rocm", "none"]
    device_ids: list[str]
    status_text: str = ""

    @property
    def available(self) -> bool:
        return bool(self.device_ids)

    @property
    def device_count(self) -> int:
        return len(self.device_ids)


@dataclass
class BranchSnapshotRequest:
    """Typed payload for capturing a code-only branch snapshot"""

    paths: list[str] = Value("List of explicit code snapshot paths; no work-state records, directories, globs, or dot")
    commit_message: str = Value("Focused code commit message for the completed experiment change set")
    checks: list[str] = Value("List of branch commit check commands")
    after_commit_experiment_log_yaml: str = Value(
        "Experiment-log YAML for branch-commit after_commit, or empty string when no after-commit log is needed",
        default="",
    )


@dataclass
class ExperimentLogRequest:
    """Typed request for appending one completed experiment log entry"""

    title: str = Value("Experiment log title")
    hypothesis: str = Value("Compact hypothesis summary")
    metric_summary: str = Value("Compact metric summary with baseline, candidate, direction, and tier")
    outcome: Literal["success", "failure", "neutral", "inconclusive"] = Value(
        "Experiment outcome from verified evidence",
    )
    evidence_paths: list[str] = Value("List of experiment evidence paths")
    notes: str = Value("Concise experiment notes for the durable ledger")


@dataclass
class ExperimentLoggerResult:
    """Outcome of an experiment-log append"""

    status: str


@dataclass
class ExperimentCorrectionRequest:
    """Typed request for appending a correction to an experiment log entry"""

    experiment_id: str = Value("Experiment ID to correct")
    correction: str = Value("Correction text to append")
    rationale: str = Value("Reason this correction is needed")


@dataclass
class ExperimentCorrectionResult:
    """Outcome of an experiment-log correction"""

    status: str


@dataclass
class NoteUpdateRequest:
    """Typed request for updating one reusable Agentic Notes lesson"""

    kind: Literal["user_correction", "setup_gotcha", "tool_gotcha", "backend_gotcha", "workflow_rule"]
    target: str
    guidance: str
    rationale: str
    temporary_workaround: bool = False


@dataclass
class NoteUpdateResult:
    """Outcome of a note update request"""

    status: str


@dataclass
class ExperimentRunnerPlan:
    """Typed plan handed from coordinator to experiment runner"""

    code_findings: str = Value(
        "Code paths relevant to the cheap experiment chosen from the active TODOs, report frontier, and experiment-log summary",
    )
    hypothesis: str = Value("Hypothesis for the chosen cheap experiment")
    changed_variable: str = Value("Single experimental variable to change in the chosen cheap experiment")
    commands: list[str] = Value("Tiered commands or scripts to run for the chosen cheap experiment")
    metric: str = Value(
        "Metric, direction, baseline source, and minimum tier needed for a conclusion about the chosen cheap experiment",
    )


@dataclass
class ExperimentRunnerResult:
    """Outcome returned by a bounded experiment runner"""

    summary: str
    meaningful: bool


@dataclass
class GpuJobSpec:
    """One independent GPU job to submit"""

    name: str = Value("GPU job name")
    command: str = Value("GPU job command")
    env: list[str] = Value("List of KEY=VALUE environment assignments for the GPU job", default_factory=list)


@dataclass
class GpuJobRequest:
    """Typed request for GPU job placement or monitoring"""

    action: Literal["submit", "monitor", "cancel", "summarize"] = Value("GPU job runner action")
    backend_enabled: bool = Value("True when the external GPU job backend is enabled", default=False)
    backend_capacity_status: Literal["available", "unavailable", "unknown", "not_configured"] = "not_configured"
    jobs: list[GpuJobSpec] = field(default_factory=list)
    job_ids: list[str] = Value("List of GPU job IDs for monitor, cancel, or summarize actions", default_factory=list)


@dataclass
class GpuJobResult:
    """Outcome of a GPU job request"""

    status: str
    job_handles: list[Job] = field(default_factory=list)


@dataclass
class ResultsAnalysisRequest:
    """Typed request for results analysis"""

    scope: str = Value("Results analysis scope", default="active-work")


@dataclass
class ResultsAnalysisResult:
    """Results analyst recommendation"""

    summary: str
    recommendation: str


@dataclass
class LiteratureReviewRequest:
    """Typed request for a literature review"""

    question: str = Value("Literature review question")
    sources: list[str] = Value("List of literature sources to review", default_factory=list)


@dataclass
class LiteratureReviewResult:
    """Literature review output"""

    brief: str


@dataclass
class CodeReviewRequest:
    """Typed request for reviewing a code change"""

    paths: list[str] = Value("List of code paths to review")
    focus: str = Value("Code review focus", default="correctness, research validity, and missing tests")


@dataclass
class CodeReviewResult:
    """Code review output"""

    summary: str


@dataclass
class BranchIntegrationRequest:
    """Typed request for integrating a completed branch"""

    source_branch: str = Value("Source branch to integrate")
    target_branch: str = Value("Target development branch")
    strategy: Literal["merge", "cherry-pick"] = Value("Integration strategy")
    remote: str = Value("Git remote for integration work", default="origin")
    checks: list[str] = Value("List of integration check commands", default_factory=list)
    push: bool = Value("True when the integrated target branch should be pushed", default=False)


@dataclass
class BranchIntegrationResult:
    """Branch integration output"""

    status: str


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def tool_payload(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def normalize_job(name: str, value: object) -> Job:
    status_path = getattr(value, "status_path", None)
    return Job(name=name, status_path=status_path if isinstance(status_path, str) else None)


def env_assignments(values: list[str]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for value in values:
        key, separator, val = value.partition("=")
        if separator and key:
            assignments[key] = val
    return assignments


def branch_snapshot_payload(request: BranchSnapshotRequest) -> dict[str, object]:
    payload: dict[str, object] = {
        "paths": request.paths,
        "commit_message": request.commit_message,
        "checks": request.checks,
    }
    if request.after_commit_experiment_log_yaml:
        payload["after_commit"] = {
            "experiment_log": request.after_commit_experiment_log_yaml,
        }
    return payload


def parse_nvidia_device_ids(output: str) -> list[str]:
    return split_lines(output)


def parse_rocm_device_ids(output: str) -> list[str]:
    device_ids: list[str] = []
    for line in split_lines(output):
        label = line.split(",", 1)[0].strip()
        if label.lower().startswith(("card", "gpu")):
            device_ids.append(label)
    return device_ids


def discover_local_gpu_capacity(workflow: AgentWorkflow) -> LocalGpuCapacity:
    nvidia: CommandResult = workflow.run_tool(
        "nvidia-smi",
        args=["--query-gpu=index", "--format=csv,noheader"],
        check=False,
    )
    if nvidia.returncode == 0:
        nvidia_ids = parse_nvidia_device_ids(nvidia.stdout)
        if nvidia_ids:
            return LocalGpuCapacity(vendor="nvidia", device_ids=nvidia_ids, status_text=nvidia.stdout)

    rocm: CommandResult = workflow.run_tool("rocm-smi", args=["--showid", "--csv"], check=False)
    if rocm.returncode == 0:
        rocm_ids = parse_rocm_device_ids(rocm.stdout)
        if rocm_ids:
            return LocalGpuCapacity(vendor="rocm", device_ids=rocm_ids, status_text=rocm.stdout)

    status_text = "\n".join(part for part in [nvidia.stderr, rocm.stderr] if part)
    return LocalGpuCapacity(vendor="none", device_ids=[], status_text=status_text)


class ResearchCoordinator(AgentWorkflow):
    """Top-level autonomous research coordinator"""

    async def __call__(self) -> None:
        relevant_note_topics: list[str] = self.evaluate("On-demand Agentic Notes topics relevant to the active work.")
        for topic in relevant_note_topics:
            self.run_tool("agentic-notes", subcommand="read-note", topic=topic)
        self.run_tool("experiment-log", subcommand="summary")
        self.do(["read work-state report.md, TODO.md, condensed_report.md, and relevant report pages"])
        self.run_tool("git", args=["log", "--oneline", "-20"])
        self.run_tool("git", args=["status", "--short"])
        local_gpu_capacity = discover_local_gpu_capacity(self)
        backend_name: str = self.run_tool("env", name="AR_JOB_BACKEND", default="none")
        backend_capacity_status: Literal["available", "unavailable", "unknown", "not_configured"] = "not_configured"
        if backend_name != "none":
            self.run_tool("skill", subcommand="read", name=backend_name)
            self.run_tool("external-job-backend", subcommand="status", backend=backend_name)
            detected_backend_capacity_status: Literal["available", "unavailable", "unknown"] = self.evaluate(
                "Backend GPU capacity classification from the active backend status/list output.",
            )
            backend_capacity_status = detected_backend_capacity_status

        best_result: str = self.evaluate("Best known active-work result with source record, or unknown.")
        last_experiment: str = self.evaluate("Most recent active-work experiment or analysis step with source record, or none.")
        next_research_step: str = self.evaluate("Immediate autonomous research step implied by notes, experiment log, report, TODO, Git status, local_gpu_capacity, and backend_capacity_status.")

        while True:
            experiment_plan: ExperimentRunnerPlan = self.evaluate(ExperimentRunnerPlan)
            runner_result = await ExperimentRunner()(plan=experiment_plan)

            result_meaningful: bool = self.evaluate(
                "True only when the completed result has enough tier, metric evidence, verification output, or user-visible research value to preserve.",
            )
            has_code_changes: bool = self.evaluate("True when code files changed in the completed result.")
            has_actionable_followup: bool = self.evaluate("True when autonomous follow-up remains in TODO records or analysis.")
            needs_experiment_log: bool = self.evaluate(
                "True when the completed result needs an experiment-log entry using meaningful tiered evaluation, durable metric evidence, or committed code result.",
            )
            lesson_kind: Literal[
                "none",
                "user_correction",
                "setup_gotcha",
                "tool_gotcha",
                "backend_gotcha",
                "workflow_rule",
            ] = self.evaluate("Reusable lesson source kind; none for ordinary experiment outcomes.")

            experiment_log: ExperimentLogRequest | None = None
            if needs_experiment_log:
                evaluated_experiment_log: ExperimentLogRequest = self.evaluate(ExperimentLogRequest)
                experiment_log = evaluated_experiment_log

            note_request: NoteUpdateRequest | None = None
            if lesson_kind != "none":
                note_target: str = self.evaluate("Reusable note target path.")
                note_guidance: str = self.evaluate("Reusable guidance that would help future agents avoid the same issue.")
                note_rationale: str = self.evaluate("Source correction, setup lesson, tool gotcha, or workflow rule behind the guidance.")
                temporary_workaround: bool = self.evaluate("True when this is only a local workaround and should not update notes.")
                note_request = NoteUpdateRequest(
                    kind=lesson_kind,
                    target=note_target,
                    guidance=note_guidance,
                    rationale=note_rationale,
                    temporary_workaround=temporary_workaround,
                )

            finalizer_context: FinalizerContext = self.evaluate(FinalizerContext)

            self.run_tool("research-coordinator-report-rollover", work_state_dir="$AR_WORK_STATE_DIR")
            self.do(
                [
                    "update condensed report",
                    "update current report page",
                    "update work-state TODO",
                ],
            )
            if has_actionable_followup:
                self.do(["record follow-up TODO"])

            if result_meaningful:
                snapshot: Snapshot | None = None
                if has_code_changes:
                    snapshot_request: BranchSnapshotRequest = self.evaluate(BranchSnapshotRequest)
                    if needs_experiment_log:
                        experiment_log_yaml: str = self.evaluate(
                            "Experiment-log payload YAML text for branch-commit after_commit",
                        )
                        snapshot_request.after_commit_experiment_log_yaml = experiment_log_yaml
                    snapshot = self.run_tool("branch-snapshot", stdin=branch_snapshot_payload(snapshot_request))
                    if snapshot.name_status.has_unexpected_files:
                        raise NeedsUser("Branch snapshot contains unexpected files")

                await ResearchFinalizer()(
                    finalizer_context=finalizer_context,
                    has_code_changes=has_code_changes,
                    lesson_kind=lesson_kind,
                    needs_experiment_log=needs_experiment_log,
                    experiment_log=experiment_log,
                    note_request=note_request,
                    snapshot=snapshot,
                )

            requires_user: bool = self.evaluate("True when research continuation needs user input.")
            has_autonomous_work: bool = self.evaluate("True when an actionable autonomous experiment, TODO, or analysis step remains.")
            if requires_user:
                raise NeedsUser("Research continuation requires user input")
            if has_autonomous_work:
                continue

            has_autonomous_recommendation: bool = self.evaluate("True when the planned response describes a next step that should be started autonomously.")
            if has_autonomous_recommendation:
                self.do(["record follow-up TODO"])
                continue

            has_actionable_todo_items: bool = self.evaluate("True when work-state TODO contains unchecked items that are actionable without user input.")
            if has_actionable_todo_items:
                continue

            self.do(["prepare final response"])
            return


class ResearchFinalizer(AgentWorkflow):
    """Finalize a completed research result after user-visible records exist"""

    async def __call__(
        self,
        finalizer_context: FinalizerContext,
        has_code_changes: bool,
        lesson_kind: Literal[
            "none",
            "user_correction",
            "setup_gotcha",
            "tool_gotcha",
            "backend_gotcha",
            "workflow_rule",
        ],
        needs_experiment_log: bool,
        experiment_log: ExperimentLogRequest | None = None,
        note_request: NoteUpdateRequest | None = None,
        snapshot: Snapshot | None = None,
    ) -> None:
        if needs_experiment_log and not has_code_changes and experiment_log is None:
            raise WorkflowFailed("Experiment logging requires an experiment log request")
        if lesson_kind != "none" and note_request is None:
            raise WorkflowFailed("Reusable lessons require a note update request")
        if note_request is not None and note_request.temporary_workaround:
            raise NeedsUser(
                "Temporary workaround needs a local fix request, issue, TODO, or user/sysadmin alert, not durable notes"
            )
        if has_code_changes and snapshot is None:
            raise NeedsUser("Code finalization needs captured branch snapshot")

        self.do(["inspect structured finalizer context"], finalizer_context=finalizer_context)

        records_reflect_result: bool = self.evaluate("True when work-state records reflect the completed result.")
        has_actionable_prose_only: bool = self.evaluate(
            "True when work-state prose contains actionable next-work prose not represented in TODO records.",
        )
        if not records_reflect_result:
            self.run_tool("research-coordinator-report-rollover", work_state_dir="$AR_WORK_STATE_DIR")
            self.do(["repair work-state research records"])

        if has_actionable_prose_only:
            self.do(["record finalizer warning"])

        with self.lock("work-state"):
            self.run_tool(
                "research-coordinator-work-state-commit",
                args=[
                    "--work-state-dir",
                    "$AR_WORK_STATE_DIR",
                    "--message",
                    "work-state: update research records",
                ],
            )

        if needs_experiment_log and not has_code_changes:
            await ExperimentLogger()(request=experiment_log)
        if lesson_kind != "none":
            await NoteUpdater()(request=note_request)
        if has_code_changes:
            await self.start_tool("branch-commit", stdin={
                "snapshot_dir": snapshot.path,
                "background": True,
            })


class ExperimentLogger(AgentWorkflow):
    """Append one completed meaningful experiment to the work-branch log"""

    async def __call__(self, request: ExperimentLogRequest) -> ExperimentLoggerResult:
        self.do(["validate completed experiment payload"])
        self.run_tool("experiment-log", subcommand="append", stdin=tool_payload(request))
        return ExperimentLoggerResult(status="logged")


class ExperimentCorrector(AgentWorkflow):
    """Append one correction to an existing experiment log entry"""

    async def __call__(self, request: ExperimentCorrectionRequest) -> ExperimentCorrectionResult:
        self.do(["validate experiment correction payload"])
        self.run_tool("experiment-log", subcommand="correct", stdin=tool_payload(request))
        return ExperimentCorrectionResult(status="corrected")


class NoteUpdater(AgentWorkflow):
    """Merge one durable lesson into Agentic Notes"""

    async def __call__(self, request: NoteUpdateRequest) -> NoteUpdateResult:
        if request.temporary_workaround:
            raise NeedsUser(
                "Temporary workaround needs a local fix request, issue, TODO, or user/sysadmin alert, not durable notes"
            )
        self.run_tool("agentic-notes", subcommand="update-note", stdin=tool_payload(request))
        rendered = self.run_tool("agentic-notes", subcommand="read-note", stdin=request.target)
        if rendered.needs_cleanup:
            cleaned: str = self.evaluate("Cleaned note content")
            self.run_tool("agentic-notes", subcommand="rewrite-note", stdin=cleaned)
        return NoteUpdateResult(status="updated")


class ExperimentRunner(AgentWorkflow):
    """Run one bounded experiment assigned by the coordinator"""

    async def __call__(self, plan: ExperimentRunnerPlan) -> ExperimentRunnerResult:
        self.do(
            [
                "validate experiment scope",
                "inspect allowed files",
                "implement assigned experiment",
            ],
        )
        for command in plan.commands:
            self.run_tool("shell", command=command)

        signal_meaningful: bool = self.evaluate(
            "True when the assigned experiment has meaningful signal using metric evidence and verification output.",
        )
        signal_summary: str = self.evaluate("Assigned experiment summary.")
        if signal_meaningful:
            log_request: ExperimentLogRequest = self.evaluate(ExperimentLogRequest)
            await ExperimentLogger()(request=log_request)
        self.do(["update local experiment notes"])
        return ExperimentRunnerResult(summary=signal_summary, meaningful=signal_meaningful)


class GpuJobRunner(AgentWorkflow):
    """Place, monitor, summarize, or cancel independent GPU jobs"""

    async def __call__(self, request: GpuJobRequest) -> GpuJobResult:
        local = discover_local_gpu_capacity(self)
        backend_available = request.backend_enabled and request.backend_capacity_status == "available"

        action = request.action
        if action == "submit":
            job_handles: list[Job] = []
            for job in request.jobs:
                if local.available:
                    started = await self.start_tool(
                        "shell",
                        command=job.command,
                        env=env_assignments(job.env),
                    )
                    job_handles.append(normalize_job(job.name, started))
                elif backend_available:
                    started = await self.start_tool("external-job-backend", job=tool_payload(job))
                    job_handles.append(normalize_job(job.name, started))
                else:
                    raise NeedsUser("GPU job submission needs available GPU capacity")
            status_summary: str = self.evaluate("GPU submission status summary")
            return GpuJobResult(status=status_summary, job_handles=job_handles)
        if action == "monitor":
            self.do(["summarize running GPU jobs"])
            return GpuJobResult(status="summarized")
        if action == "cancel":
            self.do(["cancel selected GPU jobs"])
            return GpuJobResult(status="cancelled")
        if action == "summarize":
            self.do(["summarize GPU job results"])
            return GpuJobResult(status="summarized")
        raise WorkflowFailed(f"Unknown GPU job action: {action}")


class ResultsAnalyst(AgentWorkflow):
    """Analyze experiment records and recommend research direction"""

    async def __call__(self, request: ResultsAnalysisRequest | None = None) -> ResultsAnalysisResult:
        self.run_tool("experiment-log", subcommand="summary")

        summary: str = self.evaluate(
            "Results analysis summary grounded in scoped experiment records, condensed report, relevant report pages, TODO records, baseline metric comparison, valid/invalid run separation, and missing-control analysis.",
        )
        recommendation: str = self.evaluate(
            "Next recommended research action, or explanation that no autonomous action remains, grounded in the same scoped records and controls.",
        )
        return ResultsAnalysisResult(summary=summary, recommendation=recommendation)


class LiteratureReviewer(AgentWorkflow):
    """Review papers and prior work for one research question"""

    async def __call__(self, request: LiteratureReviewRequest) -> LiteratureReviewResult:
        brief: str = self.evaluate(
            "Literature brief grounded in the assigned sources, with methods, assumptions, metrics, ablations, implementation implications, and uncertainty labels.",
        )
        return LiteratureReviewResult(brief=brief)


class CodeReviewer(AgentWorkflow):
    """Review code changes without modifying them"""

    async def __call__(self, request: CodeReviewRequest) -> CodeReviewResult:
        summary: str = self.evaluate(
            "Ranked code review summary grounded in the requested review scope, with correctness risks, research validity issues, missing tests, and severity ordering.",
        )
        return CodeReviewResult(summary=summary)


class BranchIntegrator(AgentWorkflow):
    """Integrate completed work into a target development branch"""

    async def __call__(self, request: BranchIntegrationRequest) -> BranchIntegrationResult:
        source = request.source_branch
        target = request.target_branch
        strategy = request.strategy

        worktree_path: str = self.evaluate(
            "Integration worktree path for the requested source, target, and strategy.",
        )
        integration_checks: list[str] = self.evaluate(
            "List of integration check commands for the requested source, target, and strategy.",
        )
        integration_args = [
            "--worktree-path",
            worktree_path,
            "--source-branch",
            source,
            "--target-branch",
            target,
            "--strategy",
            strategy,
            "--remote",
            request.remote,
        ]
        if strategy == "cherry-pick":
            cherry_pick_commits: list[str] = self.evaluate(
                "List of cherry-pick commit hashes in application order for this integration.",
            )
            for commit in cherry_pick_commits:
                integration_args.extend(["--commit", commit])

        checks = request.checks
        if not checks:
            checks = integration_checks
        for check in checks:
            integration_args.extend(["--check", check])

        if request.push:
            integration_args.append("--push")

        self.run_tool("research-coordinator-branch-integrate", args=integration_args)
        status_summary: str = self.evaluate("Integration status summary")
        return BranchIntegrationResult(status=status_summary)
