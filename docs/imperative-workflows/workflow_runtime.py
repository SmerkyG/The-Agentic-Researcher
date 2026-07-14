"""Interpreter contract for agent-followed imperative workflows."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
import types
from typing import Any, ClassVar, Literal, Sequence, Union, get_args, get_origin, get_type_hints


def Value(
    description: str,
    *,
    guidance: str | None = None,
    default: object = MISSING,
    default_factory: object = MISSING,
) -> object:
    """
    Describe one WorkflowRecord field that a non-mutating workflow evaluation fills.

    The Python annotation supplies the field type. The Value description supplies
    the model-facing field contract. When neither default nor default_factory is
    provided, the field remains required.
    """
    metadata = {"description": description}
    if guidance is not None:
        metadata["guidance"] = guidance
    kwargs: dict[str, object] = {"metadata": metadata}
    if default is not MISSING:
        kwargs["default"] = default
    if default_factory is not MISSING:
        kwargs["default_factory"] = default_factory
    return field(**kwargs)


class WorkflowRecord:
    """
    Base class for structured workflow values.

    Subclasses automatically receive dataclass behavior so workflow source can
    use one visible schema marker instead of a decorator plus an otherwise empty
    base class.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__dataclass_fields__" not in cls.__dict__:
            dataclass(cls)


class Example(WorkflowRecord):
    """One example value for a WorkflowRecord schema or tool input."""

    value: WorkflowRecord
    description: str = ""


def _record_fields_data(value: WorkflowRecord) -> dict[str, object]:
    data: dict[str, object] = {}
    for item in fields(value):
        field_value = getattr(value, item.name)
        if field_value is None:
            continue
        data[item.name] = _field_data(field_value)
    return data


def _field_data(value: object) -> object:
    if isinstance(value, WorkflowRecord):
        return _record_fields_data(value)
    if isinstance(value, list):
        return [_field_data(item) for item in value]
    if isinstance(value, tuple):
        return [_field_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _field_data(item) for key, item in value.items() if item is not None}
    return value


def record_data(value: object) -> object:
    """Convert WorkflowRecord values into JSON/YAML-serializable data."""

    return _field_data(value)


def _schema_for_annotation(annotation: object) -> dict[str, object]:
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        values = list(args)
        schema: dict[str, object] = {"enum": values}
        if values and all(isinstance(value, str) for value in values):
            schema["type"] = "string"
        return schema
    if origin in {list, Sequence}:
        item_type = args[0] if args else Any
        return {"type": "array", "items": _schema_for_annotation(item_type)}
    if origin in {Union, types.UnionType}:
        non_none = [item for item in args if item is not type(None)]
        if len(non_none) == 1 and len(non_none) != len(args):
            schema = _schema_for_annotation(non_none[0])
            schema["nullable"] = True
            return schema
        return {"anyOf": [_schema_for_annotation(item) for item in non_none]}
    if isinstance(annotation, type) and issubclass(annotation, WorkflowRecord):
        return record_json_schema(annotation)
    return {"type": "object"}


def record_json_schema(record_type: type[WorkflowRecord]) -> dict[str, object]:
    """Render a WorkflowRecord class as a small JSON Schema object."""

    hints = get_type_hints(record_type)
    properties: dict[str, object] = {}
    required: list[str] = []
    for item in fields(record_type):
        annotation = hints.get(item.name, item.type)
        schema = _schema_for_annotation(annotation)
        description = item.metadata.get("description") if item.metadata else None
        if description:
            schema = {**schema, "description": str(description)}
        guidance = item.metadata.get("guidance") if item.metadata else None
        if guidance:
            schema = {**schema, "x-guidance": str(guidance)}
        properties[item.name] = schema
        if item.default is MISSING and item.default_factory is MISSING:
            required.append(item.name)
    result: dict[str, object] = {
        "type": "object",
        "title": record_type.__name__,
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    examples = getattr(record_type, "examples", None)
    if examples:
        result["examples"] = [record_data(example.value if isinstance(example, Example) else example) for example in examples]
    return result


class Job(WorkflowRecord):
    """
    Opaque handle returned by an asynchronous tool or workflow launch.

    Workflow code passes Job values to wait_all, wait_any, or cancel to track
    progress and receive results. Workflow code must not inspect implementation
    details such as process IDs, backend IDs, or status file paths.
    """


class OperationNotice(WorkflowRecord):
    """Out-of-band instructions emitted before an operation's normal result."""

    instructions: str


class Operation(WorkflowRecord):
    """A tool or subagent invocation interpreted by the current agent."""

    guidance: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__dataclass_fields__" not in cls.__dict__:
            dataclass(cls)

    def run(self) -> Any:
        """Start this tool or subagent synchronously and return its result."""
        raise NotImplementedError


class CommandResult(WorkflowRecord):
    """Default response from a command-backed tool."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class WorkflowTool(Operation):
    """Generic tool operation."""


class ArgvTool(WorkflowTool):
    """Command-backed tool whose invocation is represented as argv."""

    argv_template: ClassVar[tuple[str, ...]]

    def argv(self) -> list[str]:
        """Return command argv for this invocation."""

        return list(self.argv_template)


class YAMLArgvTool(ArgvTool):
    """Run exact argv with this operation's structured fields as YAML stdin."""


class AgentWorkflow(Operation):
    """
    Agent-followed workflow vocabulary.

    The methods below describe how the agent interprets workflow source; they
    are not local implementations of the workflow.
    """

    def on_startup(self) -> None:
        """Lifecycle hook followed once before workflow() at session startup."""

    def on_compaction(self) -> None:
        """Lifecycle hook followed after compaction before resuming workflow()."""

    def workflow(self) -> Any:
        """Follow or execute this agent context's workflow body."""

        raise NotImplementedError

    def do(self, actions: Sequence[str], guidance: str | None = None) -> None:
        """
        Synchronously give the current agent one or more related plain-language
        side-effecting actions.

        The actions argument must be a literal list or tuple of strings in
        workflow source and must contain at least one string. Multiple strings
        are prompt decomposition inside one model-facing task, not workflow
        control flow.

        Guidance is optional literal declarative context for the action group.
        It is not a hidden return channel and not workflow control flow.
        """
        raise NotImplementedError

    def evaluate(self, subject: str, guidance: str | None = None) -> Any:
        """
        Non-mutating model judgment over current context.

        Subject is one declarative string. Conditional use in if/while is
        implicitly boolean. Assigned results must use an explicit annotation:
        bool, int, float, str, Literal[...] or list[...] over a basic scalar
        type. Guidance is optional literal declarative context for the judgment.
        """
        raise NotImplementedError

    def fill(self, record_type: type[WorkflowRecord], guidance: str | None = None) -> Any:
        """
        Construct an instance of the passed record type and fill its fields from
        current context.

        Record fields use Value(...) descriptions for field semantics. Guidance
        is optional literal declarative context for the whole fill request.
        """
        raise NotImplementedError

    def launch(self, operation: Operation) -> Job:
        """Start a tool or named subagent asynchronously and return its tracked Job."""
        raise NotImplementedError

    def fire_and_forget(self, operation: Operation) -> None:
        """Start asynchronously, discard its platform handle, and continue now.

        Immediately follow the next Python statement. Never wait for, poll,
        list, message, follow up with, or otherwise inspect this operation. No
        later action or response may depend on its completion or result.
        """
        raise NotImplementedError

    def wait_all(self, jobs, timeout_seconds=None) -> Any:
        """Wait for every job and return completion/progress results."""
        raise NotImplementedError

    def wait_any(self, jobs, timeout_seconds=None) -> Any:
        """Return completed jobs without cancelling unfinished jobs."""
        raise NotImplementedError

    def cancel(self, job) -> None:
        """Request cancellation and record the cancellation attempt."""
        raise NotImplementedError

    def lock(self, name) -> Any:
        """Serialize a critical section for the named runtime scope."""
        raise NotImplementedError

    def timeout(self, seconds) -> Any:
        """Bound the enclosed operation with an explicit timeout policy."""
        raise NotImplementedError


class SubagentWorkflow(AgentWorkflow):
    """A workflow that must run in a separately started subagent context.

    The child follows the contract named by agent_name and receives the typed
    constructor fields as its request. Preserve inherited history when the
    platform supports it. If a native named role cannot inherit history, a
    history fork must be explicitly directed to follow the named contract.
    The caller must never execute this workflow's body.
    """


class UserFacingWorkflow(AgentWorkflow):
    """Top-level workflow that can pause for visible user input."""

    def ask_user(self, question: str, **kwargs) -> str:
        """
        Suspend for user input, then resume with the user's response.

        The question is the model-facing contract for what to ask. It should be
        specific enough to render a user-facing prompt from current context:
        describe the blocker or choice, why autonomous workflow should not
        decide it alone, what input shape is useful, and any stop/skip choices.
        """
        raise NotImplementedError
