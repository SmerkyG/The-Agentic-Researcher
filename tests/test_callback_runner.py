from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]
CALLBACK = (
    REPO_ROOT
    / "capabilities"
    / "imperative-workflows"
    / "bin"
    / "imperative-workflows-callback"
)
CALLBACK_MCP = (
    REPO_ROOT
    / "capabilities"
    / "imperative-workflows"
    / "bin"
    / "imperative-workflows-mcp"
)
IMPERATIVE_PACKAGE = (
    REPO_ROOT / "capabilities" / "imperative-workflows" / "package"
)


def _invoke(
    env: dict[str, str],
    *args: str,
    payload: dict[str, object],
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [str(CALLBACK), *args],
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=30,
    )
    return result, json.loads(result.stdout)


def test_callback_cli_preserves_python_stack_across_agent_request(tmp_path: Path) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (package / "demo_workflow.py").write_text(
        "from agentic_workflows.contract import UserFacingWorkflow\n"
        "from agentic_workflows.fill_spec import field, step, var\n\n\n"
        "class Demo(UserFacingWorkflow[str]):\n"
        "    prefix: str\n\n"
        "    def workflow(self) -> str:\n"
        "        with self.agent_request() as result:\n"
        "            var('internal', int, 'one internal answer')\n"
        "            step('Perform one declarative action.')\n"
        "            field('answer', str, 'returned answer')\n"
        "        return self.prefix + ':' + result.answer\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        """---
name: demo
kind: main
renderer: imperative-workflows
workflow: demo_workflow:Demo
---

# Demo
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["AR_WORKFLOW_PATH"] = os.pathsep.join(
        [str(package), str(IMPERATIVE_PACKAGE)]
    )
    env["AR_RUNTIME_ROOT"] = str(tmp_path / "runtime")

    started, first = _invoke(
        env,
        "start",
        "demo_workflow:Demo",
        payload={"prefix": "kept"},
    )
    assert started.returncode == 0, started.stderr
    assert first["status"] == "agent_request"
    assert "Perform one declarative action" in first["instructions"]

    inspected, worker = _invoke(
        env,
        "status",
        str(first["run_id"]),
        payload={},
    )
    assert inspected.returncode == 0, inspected.stderr
    assert worker["phase"] == "waiting_resume"
    assert worker["pending_boundary"] == first["boundary_id"]
    assert worker["pending_event"]["boundary_id"] == first["boundary_id"]
    assert worker["pending_event"]["status"] == "agent_request"
    assert worker["process_alive"] is True

    invalid, retried = _invoke(
        env,
        "resume",
        str(first["run_id"]),
        str(first["boundary_id"]),
        payload={"assignments": {"answer": "done"}},
    )
    assert invalid.returncode == 0, invalid.stderr
    assert retried["status"] == "agent_request"
    assert "missing assignments" in retried["validation_error"]

    completed, final = _invoke(
        env,
        "resume",
        str(retried["run_id"]),
        str(retried["boundary_id"]),
        payload={"assignments": {"internal": 7, "answer": "done"}},
    )
    assert completed.returncode == 0, completed.stderr
    assert final == {
        "boundary_id": None,
        "result": "kept:done",
        "run_id": first["run_id"],
        "status": "complete",
    }


def test_callback_start_validates_typed_inputs_before_first_boundary(tmp_path: Path) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (package / "demo_contract.py").write_text(
        "from agentic_workflows.contract import UserFacingWorkflow\n\n"
        "class Demo(UserFacingWorkflow[None]):\n"
        "    required_input: str\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        """---
name: demo
kind: main
renderer: imperative-workflows
workflow_interface: demo_contract:Demo
workflow_module: demo_workflow
workflow_entry: DemoWorkflow
---

```python agentic-workflow
from demo_contract import Demo

class DemoWorkflow(Demo):
    def workflow(self) -> None:
        return None
```
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["AR_WORKFLOW_PATH"] = os.pathsep.join(
        [str(package), str(IMPERATIVE_PACKAGE)]
    )
    env["AR_RUNTIME_ROOT"] = str(tmp_path / "runtime")

    started, event = _invoke(
        env,
        "start",
        "demo_workflow:DemoWorkflow",
        payload={},
    )

    assert started.returncode == 1
    assert event["status"] == "request_error"
    assert "required_input" in event["error"]
    cancelled, cancellation = _invoke(
        env,
        "cancel",
        str(event["run_id"]),
        payload={},
    )
    assert cancelled.returncode == 0, cancelled.stderr
    assert cancellation["status"] == "cancelled"


def test_callback_mcp_uses_structured_arguments_without_shell_stdin(tmp_path: Path) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (package / "demo_contract.py").write_text(
        "from agentic_workflows.contract import UserFacingWorkflow\n\n\n"
        "class Demo(UserFacingWorkflow[str]):\n"
        "    prefix: str\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        """---
name: demo
kind: main
renderer: imperative-workflows
workflow_interface: demo_contract:Demo
workflow_module: demo_workflow
workflow_entry: DemoWorkflow
---

```python agentic-workflow
from agentic_workflows.fill_spec import field, var
from demo_contract import Demo


class DemoWorkflow(Demo):
    def workflow(self) -> str:
        with self.agent_request() as result:
            var("internal", str, "a long internal answer")
            field("answer", str, "returned answer")
        return self.prefix + ":" + result.answer
```
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["AR_WORKFLOW_PATH"] = os.pathsep.join(
        [str(package), str(IMPERATIVE_PACKAGE)]
    )
    env["AR_RUNTIME_ROOT"] = str(tmp_path / "runtime")

    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=str(CALLBACK_MCP),
            env=env,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                available = await session.list_tools()
                assert {tool.name for tool in available.tools} == {
                    "start_workflow",
                    "resume_workflow",
                    "workflow_status",
                    "cancel_workflow",
                }

                started = await session.call_tool(
                    "start_workflow",
                    {
                        "implementation": "demo_workflow:DemoWorkflow",
                        "inputs": {"prefix": "kept"},
                    },
                )
                first = started.structuredContent
                assert first is not None
                assert first["status"] == "agent_request"
                assert first["resume"]["tool"] == "resume_workflow"
                assert "command" not in first["resume"]

                inspected = await session.call_tool(
                    "workflow_status",
                    {"run_id": first["run_id"]},
                )
                status = inspected.structuredContent
                assert status is not None
                assert status["phase"] == "waiting_resume"
                assert status["pending_event"]["boundary_id"] == first["boundary_id"]
                assert status["pending_event"]["resume"]["tool"] == "resume_workflow"
                assert "command" not in status["pending_event"]["resume"]

                long_answer = "x" * 12_000
                completed = await session.call_tool(
                    "resume_workflow",
                    {
                        "run_id": first["run_id"],
                        "boundary_id": first["boundary_id"],
                        "payload": {
                            "assignments": {
                                "internal": long_answer,
                                "answer": "done",
                            }
                        },
                    },
                )
                final = completed.structuredContent
                assert final == {
                    "boundary_id": None,
                    "result": "kept:done",
                    "run_id": first["run_id"],
                    "status": "complete",
                }

    asyncio.run(exercise())
