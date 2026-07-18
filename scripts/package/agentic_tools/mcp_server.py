"""MCP transport for package-native tools from enabled capabilities."""

from __future__ import annotations

import asyncio

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from agentic_tools.catalog import discover_tools
from agentic_tools.data import record_data, record_from_data, record_schema


SERVER_INSTRUCTIONS = (
    "These are Agentic Team tools supplied by enabled capabilities. Use their typed "
    "arguments directly; do not run command wrappers or ask for --help first."
)


def build_server() -> Server:
    registrations = discover_tools()
    server = Server("agentic-tools", instructions=SERVER_INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=registration.name,
                description=(registration.tool_type.__doc__ or "").strip() or None,
                inputSchema=record_schema(registration.tool_type),
            )
            for registration in registrations.values()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
        registration = registrations.get(name)
        if registration is None:
            raise ValueError(f"unknown Agentic Team tool: {name}")
        tool = record_from_data(
            registration.tool_type,
            arguments,
            reject_unknown=True,
        )
        result = await asyncio.to_thread(tool.execute)
        data = record_data(result)
        if isinstance(data, dict):
            return data
        return {"result": data}

    return server


async def run() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
