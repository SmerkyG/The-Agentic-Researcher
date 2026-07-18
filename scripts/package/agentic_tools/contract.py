"""Minimal contracts shared by standalone tools and agent workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from typing import Any, ClassVar, Generic, Literal, TypeVar


ResultT = TypeVar("ResultT")
AgentVisibility = Literal["shown", "hidden"]


def Value(
    description: str,
    *,
    guidance: str | None = None,
    default: object = ...,
    default_factory: object = ...,
) -> object:
    """Declare one typed JSON/YAML field and its human-facing description."""

    metadata = {"description": description}
    if guidance is not None:
        metadata["guidance"] = guidance
    kwargs: dict[str, object] = {"metadata": metadata}
    if default is not ...:
        kwargs["default"] = default
    if default_factory is not ...:
        kwargs["default_factory"] = default_factory
    return field(**kwargs)


class Record:
    """Typed structured data whose annotations define its wire schema."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__dataclass_fields__" not in cls.__dict__:
            dataclass(cls)


def _current_executor() -> Any:
    """Resolve a workflow executor only when a tool is called from a workflow."""

    try:
        execution = importlib.import_module("agentic_workflows.execution")
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "tool.run() requires an active workflow runtime; use execute() or agentic-tool"
        ) from error
    return execution.current_executor()


class Operation(Record, Generic[ResultT]):
    """One typed operation that can participate in an imperative workflow."""

    guidance: ClassVar[str] = ""
    agent_visibility: ClassVar[AgentVisibility] = "shown"

    def run(
        self,
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> ResultT:
        return _current_executor().run(self, agent_visibility=agent_visibility)

    def agent_observation(self, result: ResultT) -> object:
        return result


class PythonTool(Operation[ResultT], Generic[ResultT]):
    """Canonical structured tool implemented directly in Python."""

    def execute(self) -> ResultT:
        raise NotImplementedError
