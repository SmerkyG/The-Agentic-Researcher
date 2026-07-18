from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPERATIVE_CAPABILITY = REPO_ROOT / "capabilities" / "imperative-workflows"
WORKFLOW_LIB = IMPERATIVE_CAPABILITY / "lib"
WORKFLOW_ROOT = REPO_ROOT
PACKAGE_ROOTS = [
    IMPERATIVE_CAPABILITY / "package",
    REPO_ROOT / "capabilities" / "branch" / "package",
    REPO_ROOT / "capabilities" / "agentic-notes" / "package",
    REPO_ROOT / "capabilities" / "experiment-log" / "package",
    REPO_ROOT / "capabilities" / "research-coordinator" / "package",
]
sys.path.insert(0, str(WORKFLOW_LIB))

from workflow_source import (  # noqa: E402
    WorkflowRenderer,
    WorkflowSourceError,
    find_workflow_definition,
    manifest,
    parse_workflow_definition,
    render_workflow,
)

import workflow_source  # noqa: E402


def test_tool_domain_libraries_do_not_depend_on_imperative_workflows() -> None:
    forbidden = re.compile(r"^\s*(?:from|import)\s+agentic_workflows\b", re.MULTILINE)
    offenders: list[str] = []
    for capability in (REPO_ROOT / "capabilities").iterdir():
        directory = capability / "lib"
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and forbidden.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_research_manifest_uses_one_workflow_class() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "research-coordinator.md"

    result = manifest(source, package_roots=PACKAGE_ROOTS)

    assert result["workflow"] == (
        "agentic_workflows.research.research_coordinator:ResearchCoordinator"
    )
    module_names = [module["name"] for module in result["modules"]]
    assert "agentic_workflows.contract" in module_names
    assert "agentic_workflows.research.research_finalizer" in module_names
    assert "agentic_workflows.research.workflows.research_finalizer" not in module_names
    assert "agentic_workflows.research.research_coordinator" in module_names


def test_rendered_finalizer_contains_semantic_inputs_and_private_dependencies() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "research-finalizer.md"

    rendered = render_workflow(source, package_roots=PACKAGE_ROOTS)

    assert "```python agentic-workflow" not in rendered
    assert "class ResearchFinalizer(SubagentWorkflow[ResearchFinalizerResult]):" in rendered
    assert 'summary: str = Value("Compact topic hints, at most 80 characters")' in rendered
    assert "class FinalizationStateCommitTool" in rendered
    assert "class ExperimentLogAppendTool" in rendered
    assert "class AgenticNotesUpdateTool" in rendered
    assert "class ResearchFinalizer(SubagentWorkflow[ResearchFinalizerResult]):" in rendered
    assert "ticket: FinalizationTicket" in rendered
    assert "records.experiment_log.code.branch = workspace.code_branch" in rendered
    assert "records.experiment_log.code.commit = workspace.code_commit" in rendered
    workflow = rendered[rendered.index("class ResearchFinalizer(SubagentWorkflow") :]
    assert workflow.index("FinalizationReadyTool(") < workflow.index("ReportAppendTool(")
    assert workflow.index("FinalizationStateCommitTool(") < workflow.index("records.experiment_log.run()")
    assert workflow.index("FinalizationFinishTool(") < workflow.index("NoteUpdater(")
    assert "experiment_log_state" not in rendered
    assert "BranchSnapshotAfterCommit" not in rendered
    assert "class ExperimentLogSummaryTool" not in rendered
    assert "class ExperimentLogCorrectTool" not in rendered
    assert "class FinalizationCaptureTool" not in rendered
    assert "class ResearchStateInitializeTool" not in rendered


def test_coordinator_admits_and_detaches_finalizer_without_waiting() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "research-coordinator.md"

    rendered = render_workflow(source, package_roots=PACKAGE_ROOTS)

    assert "ResearchFinalizer(" in rendered
    assert "self.admit(ResearchFinalizer(ticket=ticket))" in rendered
    assert "self.detach(accepted_finalizer)" in rendered
    assert "class FinalizationStart(ExecutableWorkflow[FinalizationTicket]):" in rendered
    assert "FinalizationStartWorkflow" not in rendered
    assert "snapshot: Snapshot = BranchSnapshotTool(" in rendered
    assert "commit: BranchCommitResult = BranchCommitTool(" in rendered
    assert "return FinalizationCaptureTool(" in rendered
    assert rendered.index("ticket: FinalizationTicket = iteration.finalization.run()") < rendered.index(
        "self.admit(ResearchFinalizer(ticket=ticket))"
    )
    assert "the snapshot name-status contains unexpected files" not in rendered
    assert "experiment_log: ExperimentLogAppendTool = self.fill" not in rendered
    assert "relative to the work-state directory" in rendered
    assert "uv run --no-project python ..." in rendered
    assert "Use ordinary `uv run` only when the check imports project dependencies" in rendered
    assert "Do not add a separate `py_compile` check" in rendered
    assert "BranchSnapshotAfterCommit" not in rendered
    assert "after_commit=" not in rendered
    assert "self.wait(accepted_finalizer" not in rendered
    assert "discards the platform handle" in rendered
    assert "immediately continues with the next Python statement" in rendered
    assert "never wait, poll, list, message, follow up with, or depend on" in rendered
    assert "For `ExecutableWorkflow.run()`, execute the exact argv returned by `argv()`" in rendered
    assert "Do not run `--help`" in rendered
    assert "before attempting that declared invocation" in rendered
    assert "follows the contract named by its `agent_name`" in rendered
    assert "Resolve `agent_name` through the `Available Subagents` catalog" in rendered
    assert "use the matching `Contract:` path" in rendered
    assert "do not search the filesystem or installation for an agent contract" in rendered
    assert "Preserve inherited history when supported" in rendered
    assert "pass that exact rendered contract path" in rendered
    assert "must not search for another contract" in rendered


def test_related_workflows_share_one_module_index(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    index_modules = workflow_source.index_modules

    def count_index_modules(*args, **kwargs):
        nonlocal calls
        calls += 1
        return index_modules(*args, **kwargs)

    monkeypatch.setattr(workflow_source, "index_modules", count_index_modules)
    renderer = WorkflowRenderer(PACKAGE_ROOTS)
    agents = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents"

    renderer.render(agents / "note-updater.md")
    renderer.render(agents / "research-finalizer.md")

    assert calls == 1


def test_missing_registered_workflow_reports_searched_registry_roots(tmp_path: Path) -> None:
    package_root = tmp_path / "capability" / "package"
    package_root.mkdir(parents=True)

    with pytest.raises(WorkflowSourceError) as captured:
        find_workflow_definition(
            "demo.workflows.missing:MissingWorkflow",
            package_roots=[package_root],
        )

    message = str(captured.value)
    assert str(package_root) in message
    assert "Ensure AR_WORKFLOW_PATH is forwarded" in message


def test_modular_source_requires_exactly_one_tagged_block(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    source = tmp_path / "agents" / "demo.md"
    source.parent.mkdir()
    source.write_text(
        "---\n"
        "workflow_interface: demo:Demo\n"
        "workflow_module: demo.workflow\n"
        "workflow_entry: DemoWorkflow\n"
        "---\n\n"
        "```python agentic-workflow\nclass First: pass\n```\n"
        "```python agentic-workflow\nclass Second: pass\n```\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowSourceError, match="expected exactly one"):
        parse_workflow_definition(source)


def test_subagent_workflow_requires_explicit_subagent_interface(tmp_path: Path) -> None:
    package = tmp_path / "package" / "demo"
    package.mkdir(parents=True)
    (package / "contract.py").write_text(
        "class AgentWorkflow:\n    pass\n",
        encoding="utf-8",
    )
    (package / "helper.py").write_text(
        "from demo.contract import AgentWorkflow\n\n"
        "class Helper(AgentWorkflow):\n"
        "    pass\n",
        encoding="utf-8",
    )
    source = tmp_path / "agents" / "helper.md"
    source.parent.mkdir()
    source.write_text(
        "---\n"
        "kind: subagent\n"
        "workflow_interface: demo.helper:Helper\n"
        "workflow_module: demo.workflows.helper\n"
        "workflow_entry: HelperWorkflow\n"
        "---\n\n"
        "```python agentic-workflow\n"
        "from demo.helper import Helper\n\n"
        "class HelperWorkflow(Helper):\n"
        "    def workflow(self) -> None:\n"
        "        pass\n"
        "```\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowSourceError, match="must subclass SubagentWorkflow"):
        render_workflow(source)


def test_workflow_source_cli_emits_machine_readable_manifest() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "note-updater.md"

    result = subprocess.run(
        [
            sys.executable,
            str(WORKFLOW_LIB / "workflow_source.py"),
            "manifest",
            str(source),
            *(argument for root in PACKAGE_ROOTS for argument in ("--package-root", str(root))),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    data = json.loads(result.stdout)
    assert data["workflow"].endswith(":NoteUpdater")


def test_modular_skill_renders_current_context_function() -> None:
    source = (
        WORKFLOW_ROOT
        / "capabilities"
        / "research-coordinator"
        / "skills"
        / "do_research"
        / "SKILL.md"
    )

    data = manifest(source, package_roots=PACKAGE_ROOTS)
    rendered = render_workflow(source, package_roots=PACKAGE_ROOTS)

    assert data["kind"] == "skill"
    assert data["receiver"].endswith(":ResearchCoordinator")
    assert data["implementation"].endswith(":do_research")
    module_names = [module["name"] for module in data["modules"]]
    assert module_names == ["agentic_workflows.research.do_research"]
    assert "class ResearchCoordinator(UserFacingWorkflow[None]):" not in rendered
    assert "class ResearchStateInitializeTool" not in rendered
    assert "def do_research(self: ResearchCoordinator) -> None:" in rendered
    assert "`$AR_WORKFLOW_PATH`" in rendered
    assert "extends the current workflow context" in rendered
    assert "```python agentic-workflow" not in rendered


def test_modular_skill_requires_matching_receiver_annotation(tmp_path: Path) -> None:
    package = tmp_path / "package" / "demo"
    package.mkdir(parents=True)
    (package / "receiver.py").write_text("class Receiver: pass\n", encoding="utf-8")
    source = tmp_path / "skills" / "demo" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\n"
        "name: demo\n"
        "workflow_receiver: demo.receiver:Receiver\n"
        "workflow_module: demo.skill\n"
        "workflow_entry: demo\n"
        "---\n\n"
        "```python agentic-workflow\n"
        "def demo(self: str) -> None:\n"
        "    pass\n"
        "```\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowSourceError, match="first skill parameter"):
        render_workflow(source)
