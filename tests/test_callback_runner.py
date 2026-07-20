from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import time

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
        "from agentic_workflows.request_spec import AgentRequest, local, result, step\n\n\n"
        "class Demo(UserFacingWorkflow[str]):\n"
        "    prefix: str\n\n"
        "    def workflow(self) -> str:\n"
        "        self.queue_agent_observation(\n"
        "            {'source': 'tool', 'value': 7},\n"
        "            desc='Focused tool result.',\n"
        "        )\n"
        "        class Request(AgentRequest):\n"
        "            internal: int = local('one internal answer')\n"
        "            step('Perform one declarative action.')\n"
        "            answer: str = result('returned answer')\n"
        "        response = self.agent_request(Request)\n"
        "        user_answer = self.ask_user(\n"
        "            'Ask the user to confirm the generated answer and explain any correction.'\n"
        "        )\n"
        "        return self.prefix + ':' + response.answer + ':' + user_answer\n",
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
    assert "External observations queued for this request" in first["instructions"]
    assert "Focused tool result." in first["instructions"]
    assert '"source": "tool"' in first["instructions"]

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

    requested, question = _invoke(
        env,
        "resume",
        str(retried["run_id"]),
        str(retried["boundary_id"]),
        payload={"assignments": {"internal": 7, "answer": "done"}},
    )
    assert requested.returncode == 0, requested.stderr
    assert question["status"] == "ask_user"
    assert question["instructions"] == (
        "Ask the user to confirm the generated answer and explain any correction."
    )
    assert "question" not in question

    completed, final = _invoke(
        env,
        "resume",
        str(question["run_id"]),
        str(question["boundary_id"]),
        payload={"answer": "confirmed"},
    )
    assert completed.returncode == 0, completed.stderr
    assert final == {
        "boundary_id": None,
        "result": "kept:done:confirmed",
        "run_id": first["run_id"],
        "status": "complete",
    }


def test_agent_request_runs_granted_python_tools_and_reuses_definitions(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (bundle / "capability.toml").write_text(
        '[tools]\nadd_numbers = "demo_tools:AddNumbers"\n'
        'touch_file = "demo_tools:TouchFile"\n',
        encoding="utf-8",
    )
    (package / "demo_tools.py").write_text(
        "from pathlib import Path\n"
        "from agentic_tools import PythonTool, Record, Value\n\n"
        "class Sum(Record):\n"
        "    total: int\n\n"
        "class AddNumbers(PythonTool[Sum]):\n"
        "    \"\"\"Add two integers.\"\"\"\n"
        "    left: int = Value('Left operand')\n"
        "    right: int = Value('Right operand')\n\n"
        "    def execute(self) -> Sum:\n"
        "        return Sum(total=self.left + self.right)\n\n"
        "class TouchFile(PythonTool[Sum]):\n"
        "    \"\"\"Write one detached marker.\"\"\"\n"
        "    path: str = Value('Marker path')\n\n"
        "    def execute(self) -> Sum:\n"
        "        Path(self.path).write_text('detached', encoding='utf-8')\n"
        "        return Sum(total=1)\n",
        encoding="utf-8",
    )
    (package / "demo_workflow.py").write_text(
        "from agentic_workflows.contract import UserFacingWorkflow\n"
        "from agentic_workflows.request_spec import AgentRequest, result\n"
        "from demo_tools import AddNumbers, TouchFile\n\n"
        "class Demo(UserFacingWorkflow[str]):\n"
        "    def workflow(self) -> str:\n"
        "        class First(AgentRequest):\n"
        "            answer: str = result('first answer')\n"
        "        first = self.agent_request(\n"
        "            First, tools=[AddNumbers, TouchFile], detachable_tools=[TouchFile]\n"
        "        )\n"
        "        class Second(AgentRequest):\n"
        "            answer: str = result('second answer')\n"
        "        second = self.agent_request(Second, tools=[AddNumbers])\n"
        "        return first.answer + ':' + second.answer\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        "---\nname: demo\nkind: main\nrenderer: imperative-workflows\n"
        "workflow: demo_workflow:Demo\n---\n",
        encoding="utf-8",
    )
    marker = tmp_path / "detached.txt"
    env = os.environ.copy()
    env["AR_WORKFLOW_PATH"] = os.pathsep.join(
        [str(package), str(IMPERATIVE_PACKAGE)]
    )
    env["AR_TOOL_PATH"] = str(package)
    env["AR_RUNTIME_ROOT"] = str(tmp_path / "runtime")

    started, first = _invoke(env, "start", "demo_workflow:Demo", payload={})
    assert started.returncode == 0, started.stderr
    assert first["status"] == "agent_request"
    assert {item["name"] for item in first["available_tools"]} == {
        "add_numbers",
        "touch_file",
    }
    assert set(first["tool_definitions"]) == {"add_numbers", "touch_file"}
    assert first["tool_definitions"]["add_numbers"]["input_schema"]["required"] == [
        "left",
        "right",
    ]

    resumed, continued = _invoke(
        env,
        "resume",
        str(first["run_id"]),
        str(first["boundary_id"]),
        payload={
            "kind": "tool_requests",
            "requests": [
                {
                    "id": "sum",
                    "tool": "add_numbers",
                    "arguments": {"left": 19, "right": 23},
                    "mode": "await",
                },
                {
                    "id": "marker",
                    "tool": "touch_file",
                    "arguments": {"path": str(marker)},
                    "mode": "detach",
                },
            ],
        },
    )
    assert resumed.returncode == 0, resumed.stderr
    assert continued["status"] == "agent_request"
    assert continued["tool_definitions"] == {}
    by_id = {item["id"]: item for item in continued["tool_results"]}
    assert by_id["sum"]["result"] == {"total": 42}
    assert by_id["marker"]["status"] == "accepted"

    resumed, second = _invoke(
        env,
        "resume",
        str(continued["run_id"]),
        str(continued["boundary_id"]),
        payload={"assignments": {"answer": "first"}},
    )
    assert resumed.returncode == 0, resumed.stderr
    assert second["status"] == "agent_request"
    assert second["available_tools"] == [{"name": "add_numbers", "modes": ["await"]}]
    assert second["tool_definitions"] == {}

    reset, refreshed = _invoke(
        env,
        "reset-context",
        str(second["run_id"]),
        payload={},
    )
    assert reset.returncode == 0, reset.stderr
    assert refreshed["boundary_id"] == second["boundary_id"]
    assert set(refreshed["tool_definitions"]) == {"add_numbers"}

    completed, final = _invoke(
        env,
        "resume",
        str(refreshed["run_id"]),
        str(refreshed["boundary_id"]),
        payload={"assignments": {"answer": "second"}},
    )
    assert completed.returncode == 0, completed.stderr
    assert final["status"] == "complete"
    assert final["result"] == "first:second"
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.read_text(encoding="utf-8") == "detached"


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


def test_callback_rejects_unconsumed_queued_observations(tmp_path: Path) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (package / "demo_workflow.py").write_text(
        "from agentic_workflows.contract import UserFacingWorkflow\n\n"
        "class Demo(UserFacingWorkflow[None]):\n"
        "    def workflow(self) -> None:\n"
        "        self.queue_agent_observation({'unused': True})\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        "---\nname: demo\nkind: main\nrenderer: imperative-workflows\n"
        "workflow: demo_workflow:Demo\n---\n",
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
        "demo_workflow:Demo",
        payload={},
    )

    assert started.returncode == 1
    assert event["status"] == "failed"
    assert "unconsumed queued agent observations" in event["error"]


def test_callback_automatically_observes_top_level_operations_with_visibility_overrides(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (package / "demo_workflow.py").write_text(
        "import sys\n"
        "from agentic_workflows.contract import (\n"
        "    ArgvTool, CommandResult, ExecutableWorkflow, Job, UserFacingWorkflow,\n"
        ")\n"
        "from agentic_workflows.request_spec import AgentRequest, result\n\n\n"
        "class EchoTool(ArgvTool[CommandResult]):\n"
        "    \"\"\"Echo one typed input.\"\"\"\n"
        "    text: str\n\n"
        "    def argv(self) -> list[str]:\n"
        "        return [sys.executable, '-c', 'import sys; print(sys.argv[1])', self.text]\n\n\n"
        "class HiddenEchoTool(EchoTool):\n"
        "    agent_visibility = 'hidden'\n\n\n"
        "class EchoBundle(ExecutableWorkflow[CommandResult]):\n"
        "    \"\"\"Run an encapsulated echo operation.\"\"\"\n"
        "    text: str\n\n"
        "    def workflow(self) -> CommandResult:\n"
        "        return EchoTool(text=self.text).run()\n\n\n"
        "class Demo(UserFacingWorkflow[str]):\n"
        "    def workflow(self) -> str:\n"
        "        EchoTool(text='default-shown').run()\n"
        "        EchoTool(text='call-hidden').run(agent_visibility='hidden')\n"
        "        HiddenEchoTool(text='override-shown').run(agent_visibility='shown')\n"
        "        EchoBundle(text='nested-child-hidden').run()\n"
        "        job: Job[CommandResult] = self.launch(EchoTool(text='async-shown'))\n"
        "        self.wait(job)\n"
        "        class Request(AgentRequest):\n"
        "            answer: str = result('acknowledgement')\n"
        "        response = self.agent_request(Request)\n"
        "        EchoTool(text='unused-after-last-request').run()\n"
        "        return response.answer\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        "---\nname: demo\nkind: main\nrenderer: imperative-workflows\n"
        "workflow: demo_workflow:Demo\n---\n",
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
        "demo_workflow:Demo",
        payload={},
    )

    assert started.returncode == 0, started.stderr
    assert event["status"] == "agent_request"
    instructions = event["instructions"]
    assert "Echo one typed input." in instructions
    assert '"text": "default-shown"' in instructions
    assert '"text": "override-shown"' in instructions
    assert '"text": "async-shown"' in instructions
    assert '"status": "completed"' in instructions
    assert '"stdout": "async-shown\\n"' in instructions
    assert '"text": "call-hidden"' not in instructions
    assert '"text": "nested-child-hidden"' in instructions
    assert "Run an encapsulated echo operation." in instructions
    assert instructions.count("demo_workflow:EchoBundle") == 1
    # The child EchoTool is suppressed; the concrete text appears only as the
    # bundle's own typed input and result.
    nested_section = instructions.split("demo_workflow:EchoBundle", 1)[1]
    assert "demo_workflow:EchoTool" not in nested_section.split("Observation", 1)[0]

    completed, final = _invoke(
        env,
        "resume",
        str(event["run_id"]),
        str(event["boundary_id"]),
        payload={"assignments": {"answer": "seen"}},
    )
    assert completed.returncode == 0, completed.stderr
    assert final["status"] == "complete"
    assert final["result"] == "seen"


def test_callback_mcp_uses_structured_arguments_without_shell_stdin(tmp_path: Path) -> None:
    bundle = tmp_path / "demo"
    package = bundle / "package"
    agents = bundle / "agents"
    package.mkdir(parents=True)
    agents.mkdir()
    (package / "demo_workflow.py").write_text(
        "from agentic_workflows.contract import UserFacingWorkflow\n"
        "from agentic_workflows.request_spec import AgentRequest, local, result\n\n\n"
        "class Demo(UserFacingWorkflow[str]):\n"
        "    prefix: str\n\n"
        "    def workflow(self) -> str:\n"
        "        class Request(AgentRequest):\n"
        "            internal: str = local('a long internal answer')\n"
        "            answer: str = result('returned answer')\n"
        "        response = self.agent_request(Request)\n"
        "        return self.prefix + ':' + response.answer\n",
        encoding="utf-8",
    )
    (agents / "demo.md").write_text(
        """---
name: demo
kind: main
renderer: imperative-workflows
workflow: demo_workflow:Demo
---
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
                    "reset_workflow_context",
                }

                started = await session.call_tool(
                    "start_workflow",
                    {
                        "implementation": "demo_workflow:Demo",
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
