"""Reference contract for callback-executed imperative workflows."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
import types
from typing import Any, ClassVar, Literal, Sequence, Union, get_args, get_origin, get_type_hints


AgentVisibility = Literal["shown", "hidden"]


def Value(
    description: str,
    *,
    guidance: str | None = None,
    default: object = MISSING,
    default_factory: object = MISSING,
) -> object:
    """
    Describe one typed structured field and its human-facing contract.

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
    """A typed tool, executable-workflow, or subagent invocation."""

    guidance: ClassVar[str] = ""
    agent_visibility: ClassVar[AgentVisibility] = "shown"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__dataclass_fields__" not in cls.__dict__:
            dataclass(cls)

    def run(self, *, agent_visibility: AgentVisibility | None = None) -> Any:
        """Start this tool or subagent synchronously and return its result."""
        raise NotImplementedError

    def agent_observation(self, result: Any) -> object:
        """Project a completed result for automatic agent-visible provenance."""
        return result


class CommandResult(WorkflowRecord):
    """Default response from a command-backed tool."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class WorkflowTool(Operation):
    """Generic tool operation."""


class PythonTool(WorkflowTool):
    """Deterministic tool implemented directly in Python."""

    def execute(self) -> Any:
        raise NotImplementedError


class ArgvTool(WorkflowTool):
    """Command-backed tool whose invocation is represented as argv."""

    argv_template: ClassVar[tuple[str, ...]]

    def argv(self) -> list[str]:
        """Return command argv for this invocation."""

        return list(self.argv_template)


class YAMLArgvTool(ArgvTool):
    """Run exact argv with declared fields serialized as YAML stdin.

    The operation owns serialization. Do not invent fields or hand-format YAML.
    Encode declared field values as JSON stdin, which is valid YAML and safely
    quotes strings.
    """


class Workflow(Operation):
    """Shared orchestration vocabulary for executable and agent workflows."""

    def workflow(self) -> Any:
        raise NotImplementedError

    def launch(
        self,
        operation: Operation,
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job:
        raise NotImplementedError

    def fire_and_forget(
        self,
        operation: Operation,
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> None:
        raise NotImplementedError

    def wait(self, job: Job, timeout_seconds: float | None = None) -> Any:
        raise NotImplementedError

    def wait_all(self, jobs, timeout_seconds=None) -> Any:
        raise NotImplementedError

    def wait_any(self, jobs, timeout_seconds=None) -> Any:
        raise NotImplementedError

    def cancel(self, job) -> None:
        raise NotImplementedError


class ExecutableWorkflow(YAMLArgvTool, Workflow):
    """Model-free Python composition of tools and nested executable workflows."""

    def argv(self) -> list[str]:
        return ["imperative-workflows-run", f"{type(self).__module__}:{type(self).__qualname__}"]


class AgentWorkflow(Workflow):
    """
    Callback-executed workflow with explicit model and user boundaries.

    A persistent Python worker executes workflow source. The active CLI agent
    handles only emitted agent-request, user-input, and subagent boundaries.
    """

    def on_startup(self) -> None:
        """Execute once before workflow() at session startup."""

    def on_compaction(self) -> None:
        """Execute after compaction before resuming the interrupted boundary."""

    def workflow(self) -> Any:
        """Execute this workflow body in the persistent worker."""

        raise NotImplementedError

    def agent_request(
        self,
        request_type: type[Any],
        name: str | None = None,
        *,
        tools: Sequence[type[PythonTool]] = (),
        detachable_tools: Sequence[type[PythonTool]] = (),
    ) -> Any:
        """Execute one ordered aggregate model boundary."""
        raise NotImplementedError

    def launch(
        self,
        operation: Operation,
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job:
        """Start a tool or named subagent asynchronously and return its tracked Job."""
        raise NotImplementedError

    def fire_and_forget(
        self,
        operation: Operation,
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> None:
        """Detach a natively admitted subagent and continue now.

        The current callback runtime rejects ordinary detached operations.
        """
        raise NotImplementedError

    def admit(
        self,
        operation: Operation,
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job:
        """Wait for receiver-side acceptance of an asynchronous subagent."""
        raise NotImplementedError

    def detach(self, job: Job) -> None:
        """Transfer lifecycle ownership of an admitted child to the launcher."""
        raise NotImplementedError

    def queue_agent_observation(
        self,
        value: object,
        *,
        desc: str | None = None,
    ) -> None:
        """Queue a non-operation external value for the next agent request."""
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

    The runtime emits a native boundary containing agent_name and the typed
    constructor fields. The adapter starts the child; the caller never executes
    this workflow's body.
    """


class UserFacingWorkflow(AgentWorkflow):
    """Top-level workflow that can pause for visible user input."""

    def ask_user(self, question: str, **kwargs) -> str:
        """
        Have the active agent formulate a prompt, suspend, then resume.

        The question argument is the model-facing contract for what to ask, not
        necessarily verbatim user prose. It should be specific enough to render
        a concise user-facing prompt from retained context:
        describe the blocker or choice, why autonomous workflow should not
        decide it alone, what input shape is useful, and any stop/skip choices.
        """
        raise NotImplementedError
