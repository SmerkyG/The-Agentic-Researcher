"""Ordered declarative requests made at one agent execution boundary.

Workflow authors declare an ``AgentRequest`` class with ordered ``step``,
``local``, ``result``, and ``guidance`` statements, then execute it with
``self.agent_request(RequestType)``. Construction is model-free. ``local``
answers remain in agent context; ``result`` answers are also returned to Python.
External values are queued by the workflow before this boundary and rendered as
an observation preamble, never declared inside the request class.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, fields, is_dataclass
import inspect
import json
import types
from typing import Any, Literal, Mapping, Union, get_args, get_origin, get_type_hints

from agentic_workflows.contract import WorkflowRecord


class FillSpecError(ValueError):
    """Raised when an agent-request declaration or response is invalid."""


@dataclass(frozen=True, init=False)
class Step:
    """One ordered group of agent-native actions."""

    actions: tuple[str, ...]
    guidance: str | None

    def __init__(self, *actions: str, guidance: str | None = None) -> None:
        normalized = tuple(action.strip() for action in actions)
        if not normalized or any(not action for action in normalized):
            raise FillSpecError("step() requires one or more non-empty action strings")
        object.__setattr__(self, "actions", normalized)
        object.__setattr__(self, "guidance", _optional_text(guidance, kind="step guidance"))


@dataclass(frozen=True, init=False)
class Assignment:
    """One explicit agent answer, either context-local or returned to Python."""

    name: str
    value_spec: object
    description: str | None
    guidance: str | None
    exposure: Literal["local", "result"]

    def __init__(
        self,
        name: str,
        value_spec: object,
        description: str | None,
        *,
        exposure: Literal["local", "result"],
        guidance: str | None = None,
    ) -> None:
        _validate_name(name, kind=exposure)
        if value_spec is None:
            raise FillSpecError(f"{exposure} {name!r} requires a type")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value_spec", value_spec)
        object.__setattr__(
            self,
            "description",
            _optional_text(description, kind=f"description for {exposure} {name!r}"),
        )
        object.__setattr__(
            self,
            "guidance",
            _optional_text(guidance, kind=f"guidance for {exposure} {name!r}"),
        )
        object.__setattr__(self, "exposure", exposure)


@dataclass(frozen=True, init=False)
class GuidanceScope:
    """Ordered nodes qualified by one trailing guidance footer."""

    items: tuple[RequestNode, ...]
    guidance: str

    def __init__(self, *items: RequestNode, guidance: str) -> None:
        if not items:
            raise FillSpecError("guidance() requires at least one enclosed declaration")
        object.__setattr__(self, "items", tuple(items))
        object.__setattr__(self, "guidance", _required_text(guidance, kind="guidance"))


RequestNode = Step | Assignment | GuidanceScope


@dataclass(frozen=True)
class AgentObservation:
    """One external value queued for an agent request, with optional prose."""

    value: object
    desc: str | None = None
    must_consume: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "desc",
            _optional_text(self.desc, kind="agent observation description"),
        )


@dataclass(frozen=True)
class AgentRequestSpec:
    """One complete ordered model boundary."""

    items: tuple[RequestNode, ...]
    name: str | None = None
    observations: tuple[AgentObservation, ...] = ()

    def __post_init__(self) -> None:
        if not self.items:
            raise FillSpecError("agent request requires at least one declaration")
        if self.name is not None:
            _validate_name(self.name, kind="agent request")
        names = [item.name for item in iter_assignments(self)]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise FillSpecError(
                "duplicate agent-request identifiers: " + ", ".join(duplicates)
            )


@dataclass
class _Draft:
    items: list[RequestNode]


class _PendingAssignment:
    """Class-body placeholder bound to its Python assignment name."""

    def __init__(
        self,
        description: str | None,
        *,
        exposure: Literal["local", "result"],
        guidance: str | None = None,
    ) -> None:
        self.description = _optional_text(description, kind=f"{exposure} description")
        self.guidance = _optional_text(guidance, kind=f"{exposure} guidance")
        self.exposure = exposure
        self.name: str | None = None

    def bind(self, name: str) -> None:
        if self.name is not None:
            raise FillSpecError(
                f"agent-request declaration is already bound to {self.name!r}"
            )
        _validate_name(name, kind=self.exposure)
        self.name = name

    def __format__(self, format_spec: str) -> str:
        if format_spec:
            raise FillSpecError(
                "agent-request references do not support f-string format specifiers"
            )
        if self.name is None:
            raise FillSpecError(
                "agent-request declaration cannot be referenced before assignment"
            )
        return f"`{self.name}`"

    def __str__(self) -> str:
        return self.__format__("")

    def __repr__(self) -> str:
        return self.__format__("")

    def __get__(self, instance: object, owner: type[object] | None = None) -> object:
        if instance is None:
            return self
        assert self.name is not None
        raise AttributeError(
            f"context-local agent-request value {self.name!r} is not returned to Python"
        )


class _RequestNamespace(dict[str, object]):
    """Ordered namespace used while Python executes one request class body."""

    def __init__(self) -> None:
        super().__init__()
        self.root = _Draft([])
        self.drafts: list[_Draft] = [self.root]
        self.bindings: list[_PendingAssignment] = []
        self.bound_names: set[str] = set()

    @property
    def current_draft(self) -> _Draft:
        return self.drafts[-1]

    def __setitem__(self, name: str, value: object) -> None:
        if isinstance(value, _PendingAssignment):
            if name in self.bound_names:
                raise FillSpecError(f"duplicate agent-request identifier: {name}")
            value.bind(name)
            draft = self.current_draft
            draft.items.append(value)  # type: ignore[arg-type]
            self.bindings.append(value)
            self.bound_names.add(name)
        super().__setitem__(name, value)

    def finish(self, request_type: type[object]) -> AgentRequestSpec:
        hints = get_type_hints(request_type)
        pending_names = {binding.name for binding in self.bindings}
        annotations = dict(self.get("__annotations__", {}))
        undeclared = sorted(
            name
            for name in annotations
            if not name.startswith("_") and name not in pending_names
        )
        if undeclared:
            raise FillSpecError(
                "agent-request annotations must use local() or result(): "
                + ", ".join(undeclared)
            )
        assignments: dict[str, Assignment] = {}
        for binding in self.bindings:
            name = binding.name
            assert name is not None
            if name not in hints:
                raise FillSpecError(
                    f"agent-request declaration {name!r} requires an explicit annotation"
                )
            assignments[name] = Assignment(
                name,
                hints[name],
                binding.description,
                exposure=binding.exposure,
                guidance=binding.guidance,
            )
        public_values = sorted(
            name
            for name, value in self.items()
            if not name.startswith("_") and not isinstance(value, _PendingAssignment)
        )
        if public_values:
            raise FillSpecError(
                "agent-request classes may contain only declarations: "
                + ", ".join(public_values)
            )
        def resolve(items: list[RequestNode]) -> tuple[RequestNode, ...]:
            resolved: list[RequestNode] = []
            for item in items:
                if isinstance(item, _PendingAssignment):
                    assert item.name is not None
                    resolved.append(assignments[item.name])
                elif isinstance(item, GuidanceScope):
                    resolved.append(
                        GuidanceScope(*resolve(list(item.items)), guidance=item.guidance)
                    )
                else:
                    resolved.append(item)
            return tuple(resolved)

        return AgentRequestSpec(resolve(self.root.items), name=request_type.__name__)


class AgentRequestMeta(type):
    """Compile a sequential class body into one immutable request spec."""

    @classmethod
    def __prepare__(
        metaclass,
        name: str,
        bases: tuple[type[object], ...],
        **kwargs: object,
    ) -> _RequestNamespace:
        return _RequestNamespace()

    def __new__(
        metaclass,
        name: str,
        bases: tuple[type[object], ...],
        namespace: _RequestNamespace,
        **kwargs: object,
    ) -> AgentRequestMeta:
        request_type = super().__new__(metaclass, name, bases, dict(namespace))
        if bases:
            request_type.__request_spec__ = namespace.finish(request_type)
        return request_type


class AgentRequest(metaclass=AgentRequestMeta):
    """One ordered aggregate model boundary declared by its class body."""

    __request_spec__: AgentRequestSpec


def _class_namespace() -> _RequestNamespace | None:
    frame = inspect.currentframe()
    try:
        frame = frame.f_back if frame is not None else None
        while frame is not None:
            namespace = frame.f_locals
            if isinstance(namespace, _RequestNamespace):
                return namespace
            frame = frame.f_back
    finally:
        del frame
    return None


def _current_draft() -> _Draft:
    namespace = _class_namespace()
    if namespace is not None:
        return namespace.current_draft
    raise FillSpecError(
        "declarative agent-request statements require an AgentRequest class body"
    )


class _GuidanceBuilder:
    def __init__(self, text: str, namespace: _RequestNamespace) -> None:
        self.text = _required_text(text, kind="guidance")
        self._namespace = namespace
        self._parent: _Draft | None = None
        self._draft: _Draft | None = None

    def __enter__(self) -> _GuidanceBuilder:
        self._parent = self._namespace.current_draft
        self._draft = _Draft([])
        self._namespace.drafts.append(self._draft)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        if self._parent is None or self._draft is None:
            raise FillSpecError("guidance() block exited without being entered")
        if self._namespace.current_draft is not self._draft:
            raise FillSpecError("unbalanced guidance() block exit")
        self._namespace.drafts.pop()
        if exc_type is None:
            self._parent.items.append(
                GuidanceScope(*self._draft.items, guidance=self.text)
            )


def step(*actions: str, guidance: str | None = None) -> None:
    """Declare ordered agent-native work."""

    _current_draft().items.append(Step(*actions, guidance=guidance))


def local(
    description: str | None = None,
    *,
    guidance: str | None = None,
) -> Any:
    """Declare an annotated answer retained only in the agent's context."""

    if _class_namespace() is None:
        raise FillSpecError("local() requires an AgentRequest class body")
    return _PendingAssignment(
        description,
        exposure="local",
        guidance=guidance,
    )


def result(
    description: str | None = None,
    *,
    guidance: str | None = None,
) -> Any:
    """Declare an annotated answer also returned to imperative Python."""

    if _class_namespace() is None:
        raise FillSpecError("result() requires an AgentRequest class body")
    return _PendingAssignment(
        description,
        exposure="result",
        guidance=guidance,
    )


def guidance(text: str) -> _GuidanceBuilder:
    """Qualify the enclosed statements without introducing variable scope."""

    namespace = _class_namespace()
    if namespace is None:
        raise FillSpecError("guidance() requires an AgentRequest class body")
    return _GuidanceBuilder(text, namespace=namespace)


def iter_assignments(value: AgentRequestSpec | GuidanceScope) -> tuple[Assignment, ...]:
    """Return assignments in depth-first declaration order."""

    result: list[Assignment] = []
    for item in value.items:
        if isinstance(item, Assignment):
            result.append(item)
        elif isinstance(item, GuidanceScope):
            result.extend(iter_assignments(item))
    return tuple(result)


def _validate_name(name: str, *, kind: str) -> None:
    if not isinstance(name, str) or not name.isidentifier():
        raise FillSpecError(f"{kind} name must be a Python identifier: {name!r}")


def _required_text(value: str, *, kind: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FillSpecError(f"{kind} must not be empty")
    return value.strip()


def _optional_text(value: str | None, *, kind: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, kind=kind)


def _annotation_name(annotation: object) -> str:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Literal:
        return "Literal[" + ", ".join(repr(item) for item in arguments) + "]"
    if origin in {list, tuple, set}:
        item_name = _annotation_name(arguments[0]) if arguments else "Any"
        return f"{origin.__name__}[{item_name}]"
    if origin in {Union, types.UnionType}:
        return " | ".join(_annotation_name(item) for item in arguments)
    if annotation is type(None):
        return "None"
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _indented_json(value: object, indent: str) -> list[str]:
    rendered = json.dumps(_jsonable(value), indent=2, sort_keys=False, ensure_ascii=False)
    return [indent + line for line in rendered.splitlines()]


class AgentRequestRenderer:
    """Render one ordered request into instructions for a tool-using agent."""

    def render(self, value: AgentRequestSpec) -> str:
        lines = [
            "Review this complete agent request before acting. Then process its",
            "numbered nodes in declaration order. You may anticipate later declared",
            "requirements while answering earlier ones, but must not assume future",
            "operation results.",
            "",
            "Every `local` and `result` is an explicit structured assignment. A `local`",
            "is retained for later nodes in this request; a `result` is also returned",
            "to imperative Python. Backticked names refer to these exact identifiers.",
        ]
        if value.observations:
            lines.extend(
                [
                    "",
                    "External observations queued for this request:",
                ]
            )
            for index, observation in enumerate(value.observations, start=1):
                label = f"Observation {index} ({type(observation.value).__name__})"
                if observation.desc:
                    lines.append(f"{label} — {observation.desc}")
                else:
                    lines.append(label + ":")
                lines.extend(_indented_json(observation.value, "  "))
        lines.extend(
            [
                "",
                (
                    f"Process agent request `{value.name}`:"
                    if value.name is not None
                    else "Process this agent request:"
                ),
            ]
        )
        lines.extend(self._items(value.items, prefix=(), indent=""))
        assignments = iter_assignments(value)
        names = ", ".join(item.name for item in assignments) or "(none)"
        lines.extend(
            [
                "",
                "After all steps have genuinely completed, return one JSON object with",
                f"exactly these assignments: {names}.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _items(
        self,
        items: tuple[RequestNode, ...],
        *,
        prefix: tuple[int, ...],
        indent: str,
    ) -> list[str]:
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            number = ".".join(str(component) for component in (*prefix, index))
            if isinstance(item, Step):
                lines.append(f"{indent}{number}. Perform these actions in order:")
                for action_index, action in enumerate(item.actions, start=1):
                    lines.append(f"{indent}   {action_index}. {action}")
                if item.guidance:
                    lines.extend(
                        [
                            f"{indent}   Guidance for this step:",
                            f"{indent}     {item.guidance}",
                        ]
                    )
                continue
            if isinstance(item, GuidanceScope):
                lines.append(f"{indent}{number}. Process this guided scope:")
                lines.extend(
                    self._items(
                        item.items,
                        prefix=(*prefix, index),
                        indent=indent + "   ",
                    )
                )
                lines.extend(
                    [
                        f"{indent}   Guidance for this scope:",
                        f"{indent}     {item.guidance}",
                    ]
                )
                continue
            label = "context-local value" if item.exposure == "local" else "returned result"
            lines.append(
                f"{indent}{number}. Assign {label} `{item.name}` "
                f"({_annotation_name(item.value_spec)}):"
            )
            if item.description:
                lines.append(f"{indent}   {item.description}")
            if item.guidance:
                lines.extend(
                    [
                        f"{indent}   Guidance for this assignment:",
                        f"{indent}     {item.guidance}",
                    ]
                )
        return lines


def render_agent_request(value: AgentRequestSpec) -> str:
    """Render one agent request."""

    return AgentRequestRenderer().render(value)


def assignment_schema(
    value: AgentRequestSpec,
    *,
    fields_only: bool = False,
) -> dict[str, object]:
    """Build a JSON schema for all assignments or only Python-returned fields."""

    properties: dict[str, object] = {}
    required: list[str] = []
    for item in iter_assignments(value):
        if fields_only and item.exposure != "result":
            continue
        schema = _schema_for_spec(item.value_spec)
        if item.description:
            schema["description"] = item.description
        if item.guidance:
            schema["x-guidance"] = item.guidance
        properties[item.name] = schema
        required.append(item.name)
    result: dict[str, object] = {
        "type": "object",
        "title": value.name or "AgentRequestAssignments",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def output_schema(value: AgentRequestSpec) -> dict[str, object]:
    """Project only returned fields from an agent request."""

    return assignment_schema(value, fields_only=True)


def decode_assignments(
    value: AgentRequestSpec,
    data: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate all assignments and split context variables from fields."""

    assignments = iter_assignments(value)
    expected = {item.name for item in assignments}
    unknown = sorted(set(data) - expected)
    missing = sorted(expected - set(data))
    if unknown:
        raise FillSpecError("unexpected assignments: " + ", ".join(unknown))
    if missing:
        raise FillSpecError("missing assignments: " + ", ".join(missing))

    from agentic_workflows.execution import decode_value

    variables: dict[str, object] = {}
    returned: dict[str, object] = {}
    for item in assignments:
        try:
            decoded = decode_value(item.value_spec, data[item.name])
        except (TypeError, ValueError) as error:
            raise FillSpecError(f"invalid assignment {item.name!r}: {error}") from error
        target = variables if item.exposure == "local" else returned
        target[item.name] = decoded
    return variables, returned


def _schema_for_spec(spec: object) -> dict[str, object]:
    if spec is str:
        return {"type": "string"}
    if spec is int:
        return {"type": "integer"}
    if spec is float:
        return {"type": "number"}
    if spec is bool:
        return {"type": "boolean"}

    origin = get_origin(spec)
    arguments = get_args(spec)
    if origin is Literal:
        return {"enum": list(arguments)}
    if origin in {list, tuple, set}:
        item_spec = arguments[0] if arguments else Any
        return {"type": "array", "items": _schema_for_spec(item_spec)}
    if origin in {Union, types.UnionType}:
        variants = [_schema_for_spec(item) for item in arguments]
        return {"anyOf": variants}
    if spec is type(None):
        return {"type": "null"}
    if isinstance(spec, type) and issubclass(spec, WorkflowRecord):
        hints = get_type_hints(spec)
        properties: dict[str, object] = {}
        required: list[str] = []
        for item in fields(spec):
            schema = _schema_for_spec(hints.get(item.name, item.type))
            description = item.metadata.get("description") if item.metadata else None
            item_guidance = item.metadata.get("guidance") if item.metadata else None
            if description:
                schema["description"] = str(description)
            if item_guidance:
                schema["x-guidance"] = str(item_guidance)
            if item.default is not MISSING:
                schema["default"] = _jsonable(item.default)
            properties[item.name] = schema
            if item.default is MISSING and item.default_factory is MISSING:
                required.append(item.name)
        result: dict[str, object] = {
            "type": "object",
            "title": spec.__name__,
            "properties": properties,
            "additionalProperties": False,
        }
        class_guidance = getattr(spec, "guidance", "")
        if class_guidance:
            result["x-guidance"] = class_guidance
        if required:
            result["required"] = required
        return result
    return {"type": "object", "x-python-type": _annotation_name(spec)}
