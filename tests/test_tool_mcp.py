from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_MCP = REPO_ROOT / "scripts" / "bin" / "agentic-tools-mcp"
HOOK_RUNNER = REPO_ROOT / "scripts" / "bin" / "agentic-hook"


def test_capability_declared_python_tool_is_exposed_over_mcp(tmp_path: Path) -> None:
    capability = tmp_path / "demo"
    package = capability / "package"
    package.mkdir(parents=True)
    (capability / "capability.toml").write_text(
        '[tools]\nadd_numbers = "demo_tools:AddNumbers"\n',
        encoding="utf-8",
    )
    (package / "demo_tools.py").write_text(
        "from agentic_tools.contract import PythonTool, Record, Value\n\n"
        "class Sum(Record):\n"
        "    total: int\n\n"
        "class AddNumbers(PythonTool[Sum]):\n"
        "    \"\"\"Add two integers.\"\"\"\n"
        "    left: int = Value('Left operand')\n"
        "    right: int = Value('Right operand')\n\n"
        "    def execute(self) -> Sum:\n"
        "        return Sum(total=self.left + self.right)\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["AR_TOOL_PATH"] = str(package)

    async def exercise() -> None:
        parameters = StdioServerParameters(command=str(TOOL_MCP), env=env)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                available = await session.list_tools()
                assert [tool.name for tool in available.tools] == ["add_numbers"]
                schema = available.tools[0].inputSchema
                assert schema["required"] == ["left", "right"]
                assert schema["properties"]["left"]["description"] == "Left operand"

                result = await session.call_tool(
                    "add_numbers",
                    {"left": 19, "right": 23},
                )
                assert result.structuredContent == {"total": 42}

    asyncio.run(exercise())


def test_python_hook_runner_provides_yaml_dependency(tmp_path: Path) -> None:
    capability = tmp_path / "demo"
    package = capability / "package"
    package.mkdir(parents=True)
    (capability / "capability.toml").write_text(
        '[hooks]\nsetup = "demo_hook:setup"\n',
        encoding="utf-8",
    )
    output = tmp_path / "hook-output.txt"
    (package / "demo_hook.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import yaml\n\n"
        "def setup():\n"
        "    value = yaml.safe_load('available: true')\n"
        "    Path(os.environ['HOOK_OUTPUT']).write_text(str(value['available']))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(HOOK_RUNNER), str(capability), "setup"],
        env={**os.environ, "HOOK_OUTPUT": str(output)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == "True"
