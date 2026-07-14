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
    REPO_ROOT / "capabilities" / "agentic-notes" / "package",
    REPO_ROOT / "capabilities" / "experiment-log" / "package",
    REPO_ROOT / "capabilities" / "research-coordinator" / "package",
]
sys.path.insert(0, str(WORKFLOW_LIB))

from workflow_source import (  # noqa: E402
    WorkflowRenderer,
    WorkflowSourceError,
    manifest,
    parse_workflow_definition,
    render_workflow,
)

import workflow_source  # noqa: E402


def test_tool_implementations_do_not_depend_on_imperative_workflows() -> None:
    forbidden = re.compile(r"^\s*(?:from|import)\s+agentic_workflows\b", re.MULTILINE)
    offenders: list[str] = []
    for capability in (REPO_ROOT / "capabilities").iterdir():
        for directory in (capability / "bin", capability / "lib"):
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if path.is_file() and forbidden.search(path.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_research_manifest_walks_public_and_implementation_modules() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "research-coordinator.md"

    result = manifest(source, package_roots=PACKAGE_ROOTS)

    assert result["interface"] == (
        "agentic_workflows.research.research_coordinator:ResearchCoordinator"
    )
    assert result["implementation"] == (
        "agentic_workflows.research.workflows.research_coordinator:ResearchCoordinatorWorkflow"
    )
    module_names = [module["name"] for module in result["modules"]]
    assert module_names[0] == "agentic_workflows.contract"
    assert "agentic_workflows.research.research_finalizer" in module_names
    assert "agentic_workflows.research.workflows.research_finalizer" not in module_names
    assert module_names[-1] == "agentic_workflows.research.workflows.research_coordinator"


def test_rendered_finalizer_contains_semantic_inputs_and_private_dependencies() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "research-finalizer.md"

    rendered = render_workflow(source, package_roots=PACKAGE_ROOTS)

    assert "```python agentic-workflow" not in rendered
    assert "class ResearchFinalizer(SubagentWorkflow[ResearchFinalizerResult]):" in rendered
    assert 'summary: str = Value("Compact topic hints, at most 80 characters")' in rendered
    assert "class FinalizationApplyTool" in rendered
    assert "class ResearchFinalizerWorkflow(ResearchFinalizer):" in rendered
    assert "workspace: FinalizationWorkspace" in rendered
    assert "experiment_log.code.branch = applied.code_branch" in rendered
    assert "experiment_log.code.commit = applied.code_commit" in rendered
    assert rendered.index("FinalizationReadyTool(") < rendered.index("ReportAppendTool(")
    assert rendered.index("FinalizationApplyTool(") < rendered.index("experiment_log.run()")
    assert "experiment_log_state" not in rendered
    assert "BranchSnapshotAfterCommit" not in rendered
    assert "class NoteUpdaterWorkflow" not in rendered


def test_coordinator_launches_finalizer_without_tracking_or_waiting() -> None:
    source = WORKFLOW_ROOT / "capabilities" / "research-coordinator" / "agents" / "research-coordinator.md"

    rendered = render_workflow(source, package_roots=PACKAGE_ROOTS)

    assert "ResearchFinalizer(" in rendered
    assert "self.fire_and_forget(" in rendered
    assert rendered.index("code_snapshot = BranchSnapshotTool(") < rendered.index("workspace: FinalizationWorkspace = FinalizationForkTool(")
    assert rendered.index("workspace: FinalizationWorkspace = FinalizationForkTool(") < rendered.index("self.fire_and_forget(\n                ResearchFinalizer")
    assert "ReportAppendTool(" not in rendered
    assert "experiment_log: ExperimentLogAppendTool = self.fill" not in rendered
    assert "BranchSnapshotAfterCommit" not in rendered
    assert "after_commit=" not in rendered
    assert "finalizer: Job" not in rendered
    assert "discards the platform handle" in rendered
    assert "immediately continues with the next Python statement" in rendered
    assert "never wait, poll, list, message, follow up with, or depend on" in rendered
    assert "follows the contract named by its `agent_name`" in rendered
    assert "Preserve inherited history when supported" in rendered
    assert "explicitly direct the history-forked child" in rendered


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
    assert data["interface"].endswith(":NoteUpdater")
    assert data["implementation"].endswith(":NoteUpdaterWorkflow")


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
