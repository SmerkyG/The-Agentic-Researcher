from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "capabilities" / "imperative-workflows" / "package"
EXECUTABLE = REPO_ROOT / "capabilities" / "imperative-workflows" / "bin" / "imperative-workflows-run"
BRANCH_BIN = REPO_ROOT / "capabilities" / "branch" / "bin"
FINALIZATION_BIN = REPO_ROOT / "capabilities" / "research-coordinator" / "bin"
RESEARCH_PACKAGE = REPO_ROOT / "capabilities" / "research-coordinator" / "package"
sys.path.insert(0, str(PACKAGE_ROOT))

from agentic_workflows.contract import (  # noqa: E402
    AgentWorkflow,
    ArgvTool,
    CommandResult,
    ExecutableWorkflow,
    ExecutableWorkflowImplementation,
    Job,
    Value,
    WorkflowRecord,
    YAMLArgvTool,
)
from agentic_workflows.execution import (  # noqa: E402
    OperationExecutionError,
    OperationExecutor,
    operation_result_type,
)


class Number(WorkflowRecord):
    value: int


class NumberTool(YAMLArgvTool[Number]):
    command: str
    value: int

    def argv(self) -> list[str]:
        return [self.command]


class SequentialNumbers(ExecutableWorkflow[Number]):
    workflow_implementation = f"{__name__}:SequentialNumbersWorkflow"
    command: str = Value("Test command")
    value: int = Value("Starting value")


class SequentialNumbersWorkflow(
    SequentialNumbers,
    ExecutableWorkflowImplementation[SequentialNumbers],
):
    def workflow(self) -> Number:
        first: Number = NumberTool(command=self.command, value=self.value).run()
        return NumberTool(command=self.command, value=first.value).run()


class ParallelNumbers(ExecutableWorkflow[Number]):
    workflow_implementation = f"{__name__}:ParallelNumbersWorkflow"
    command: str = Value("Test command")


class ParallelNumbersWorkflow(
    ParallelNumbers,
    ExecutableWorkflowImplementation[ParallelNumbers],
):
    def workflow(self) -> Number:
        first_job: Job[Number] = self.launch(NumberTool(command=self.command, value=2))
        second_job: Job[Number] = self.launch(NumberTool(command=self.command, value=5))
        results: list[Number] = self.wait_all([first_job, second_job])
        return Number(value=sum(result.value for result in results))


class UnsupportedAgent(AgentWorkflow[None]):
    agent_name = "unsupported-agent"


def number_command(tmp_path: Path) -> Path:
    command = tmp_path / "number-command"
    command.write_text(
        "#!/usr/bin/env python3\n"
        "import json, re, sys\n"
        "text = sys.stdin.read()\n"
        "match = re.search(r'^value: ([0-9]+)$', text, re.MULTILINE)\n"
        "print(json.dumps({'value': int(match.group(1)) + 1}))\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return command


def test_executor_runs_sequential_typed_tool_dataflow(tmp_path: Path) -> None:
    command = number_command(tmp_path)

    with OperationExecutor() as executor:
        result = executor.run(SequentialNumbers(command=str(command), value=3))

    assert result == Number(value=5)
    assert operation_result_type(SequentialNumbers) is Number


def test_executor_runs_parallel_tools_and_preserves_job_order(tmp_path: Path) -> None:
    command = number_command(tmp_path)

    with OperationExecutor() as executor:
        result = executor.run(ParallelNumbers(command=str(command)))

    assert result == Number(value=9)


def test_executor_rejects_agent_workflows() -> None:
    with OperationExecutor() as executor:
        with pytest.raises(OperationExecutionError, match="cannot run or launch agent workflows"):
            executor.run(UnsupportedAgent())


def test_command_result_reports_missing_command_without_aborting_workflow() -> None:
    class MissingCommand(ArgvTool[CommandResult]):
        argv_template = ("definitely-not-an-agentic-team-command",)

    with OperationExecutor() as executor:
        result = executor.run(MissingCommand())

    assert result.returncode == 127
    assert "No such file or directory" in result.stderr


def test_command_result_preserves_nonzero_status_for_python_control_flow() -> None:
    class FalseCommand(ArgvTool[CommandResult]):
        argv_template = ("sh", "-c", "printf failure >&2; exit 3")

    with OperationExecutor() as executor:
        result = executor.run(FalseCommand())

    assert result.returncode == 3
    assert result.stderr == "failure"


def test_executable_workflow_argv_uses_generic_runner() -> None:
    operation = SequentialNumbers(command="number-command", value=1)

    assert operation.argv() == [
        "imperative-workflows-run",
        f"{__name__}:SequentialNumbers",
    ]


def test_cli_imports_and_executes_registered_workflow(tmp_path: Path) -> None:
    module = tmp_path / "demo_workflow.py"
    module.write_text(
        "from agentic_workflows.contract import ArgvTool, CommandResult, ExecutableWorkflow\n"
        "class PrintTool(ArgvTool[CommandResult]):\n"
        "    argv_template = ('printf', 'hello')\n"
        "class DemoWorkflow(ExecutableWorkflow[CommandResult]):\n"
        "    workflow_implementation = 'demo_workflow:DemoWorkflowImplementation'\n"
        "class DemoWorkflowImplementation(DemoWorkflow):\n"
        "    def workflow(self) -> CommandResult:\n"
        "        return PrintTool().run()\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["AR_WORKFLOW_PATH"] = f"{tmp_path}:{PACKAGE_ROOT}"

    result = subprocess.run(
        [str(EXECUTABLE), "demo_workflow:DemoWorkflow"],
        input="{}\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"returncode": 0, "stderr": "", "stdout": "hello"}


def test_composed_finalization_snapshots_commits_and_captures(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = tmp_path / "state"
    project.mkdir()
    (state / "images").mkdir(parents=True)
    for repository in (project, state):
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)

    (project / "result.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "result.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=project, check=True)
    subprocess.run(["git", "switch", "-qc", "kernel-search"], cwd=project, check=True)
    (project / "result.txt").write_text("result\n", encoding="utf-8")

    (state / "README.md").write_text("state\n", encoding="utf-8")
    (state / "images" / "result.png").write_bytes(b"png")
    subprocess.run(["git", "add", "."], cwd=state, check=True)
    subprocess.run(["git", "commit", "-qm", "state"], cwd=state, check=True)
    subprocess.run(["git", "switch", "-qc", "agentic/work-state/kernel-search"], cwd=state, check=True)

    env = os.environ.copy()
    env["PATH"] = f"{BRANCH_BIN}:{FINALIZATION_BIN}:{env['PATH']}"
    env["AR_WORKFLOW_PATH"] = f"{PACKAGE_ROOT}:{RESEARCH_PACKAGE}"
    env["AR_WORKSPACE_ROOT"] = str(tmp_path / "workspace")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["AR_WORK_STATE_DIR"] = str(state)
    request = {
        "code_paths": ["result.txt"],
        "commit_message": "test: composed finalization",
        "checks": ["test -f result.txt"],
        "report_assets": ["images/result.png"],
        "project_dir": str(project),
        "work_state_dir": str(state),
    }

    result = subprocess.run(
        [
            str(EXECUTABLE),
            "agentic_workflows.research.finalization_start:FinalizationStart",
        ],
        input=yaml.safe_dump(request, sort_keys=False),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    ticket = json.loads(result.stdout)
    assert ticket["state"] == "captured"
    assert subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip() == "test: composed finalization"

    committed_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    replay = subprocess.run(
        [
            str(EXECUTABLE),
            "agentic_workflows.research.finalization_start:FinalizationStart",
        ],
        input=yaml.safe_dump(request, sort_keys=False),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["code_commit"] == committed_head
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip() == committed_head
