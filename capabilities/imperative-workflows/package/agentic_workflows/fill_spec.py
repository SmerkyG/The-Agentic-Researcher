"""Ordered declarative requests made at one agent execution boundary.

Workflow authors use ``with self.agent_request()`` and append statements with
``observe``, ``step``, ``var``, and ``field``.  ``with guidance(...)`` groups
related statements and renders its qualification after the statements it
qualifies.  Construction is model-free; the active workflow executor submits
the immutable specification only after the outer block exits successfully.

``var`` and ``field`` deliberately use the same assignment mechanism.  Both
are explicit model outputs, but only fields are projected into the result made
available to Python.  Variables remain context-local answers for later nodes
inside the same agent request.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import MISSING, asdict, dataclass, fields, is_dataclass
import json
import types
from typing import Any, Callable, Literal, Mapping, Union, get_args, get_origin, get_type_hints

from agentic_workflows.contract import WorkflowRecord


class FillSpecError(ValueError):
    """Raised when an agent-request declaration or response is invalid."""


@dataclass(frozen=True, init=False)
class Observe:
    """External observations made visible at this position in a request."""

    values: tuple[tuple[str, object], ...]

    def __init__(self, **values: object) -> None:
        if not values:
            raise FillSpecError("observe() requires at least one named external value")
        for name in values:
            _validate_name(name, kind="observation")
        object.__setattr__(self, "values", tuple(values.items()))


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
    exposure: Literal["var", "field"]

    def __init__(
        self,
        name: str,
        value_spec: object,
        description: str | None,
        *,
        exposure: Literal["var", "field"],
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


RequestNode = Observe | Step | Assignment | GuidanceScope


@dataclass(frozen=True)
class AgentRequestSpec:
    """One complete ordered model boundary."""

    items: tuple[RequestNode, ...]
    name: str | None = None

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


_ACTIVE_DRAFTS: ContextVar[tuple[_Draft, ...]] = ContextVar(
    "agentic_workflows_agent_request_drafts",
    default=(),
)


def _current_draft() -> _Draft:
    drafts = _ACTIVE_DRAFTS.get()
    if not drafts:
        raise FillSpecError(
            "declarative agent-request statements require an active agent_request_spec() "
            "or self.agent_request() block"
        )
    return drafts[-1]


class AgentRequestSpecBuilder:
    """Model-free builder used by tests and by the callback workflow runtime."""

    def __init__(
        self,
        name: str | None = None,
        *,
        initial_observations: Mapping[str, object] | None = None,
        on_complete: Callable[[AgentRequestSpec], Mapping[str, object]] | None = None,
    ) -> None:
        if name is not None:
            _validate_name(name, kind="agent request")
        self.name = name
        self._initial_observations = dict(initial_observations or {})
        self._on_complete = on_complete
        self._draft: _Draft | None = None
        self._token: Token[tuple[_Draft, ...]] | None = None
        self._spec: AgentRequestSpec | None = None
        self._returned: dict[str, object] | None = None

    def __enter__(self) -> AgentRequestSpecBuilder:
        if self._token is not None or self._spec is not None:
            raise FillSpecError("an AgentRequestSpecBuilder may be entered only once")
        if _ACTIVE_DRAFTS.get():
            raise FillSpecError("a root agent request cannot be nested")
        initial: list[RequestNode] = []
        if self._initial_observations:
            initial.append(Observe(**self._initial_observations))
        self._draft = _Draft(initial)
        self._token = _ACTIVE_DRAFTS.set((self._draft,))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        if self._token is None or self._draft is None:
            raise FillSpecError("agent request exited without being entered")
        drafts = _ACTIVE_DRAFTS.get()
        if drafts != (self._draft,):
            _ACTIVE_DRAFTS.reset(self._token)
            self._token = None
            raise FillSpecError("unbalanced guidance() block at agent-request exit")
        _ACTIVE_DRAFTS.reset(self._token)
        self._token = None
        if exc_type is not None:
            return
        self._spec = AgentRequestSpec(tuple(self._draft.items), name=self.name)
        if self._on_complete is not None:
            self._returned = dict(self._on_complete(self._spec))

    @property
    def spec(self) -> AgentRequestSpec:
        if self._spec is None:
            raise FillSpecError("agent-request specification is unavailable before block exit")
        return self._spec

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        if self._returned is None:
            raise FillSpecError(
                f"agent-request result {name!r} is unavailable before successful block exit"
            )
        try:
            return self._returned[name]
        except KeyError as error:
            raise AttributeError(name) from error


class _GuidanceBuilder:
    def __init__(self, text: str) -> None:
        self.text = _required_text(text, kind="guidance")
        self._parent: _Draft | None = None
        self._draft: _Draft | None = None
        self._token: Token[tuple[_Draft, ...]] | None = None

    def __enter__(self) -> _GuidanceBuilder:
        drafts = _ACTIVE_DRAFTS.get()
        if not drafts:
            raise FillSpecError("guidance() requires an active agent request")
        self._parent = drafts[-1]
        self._draft = _Draft([])
        self._token = _ACTIVE_DRAFTS.set((*drafts, self._draft))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        if self._token is None or self._parent is None or self._draft is None:
            raise FillSpecError("guidance() block exited without being entered")
        drafts = _ACTIVE_DRAFTS.get()
        if not drafts or drafts[-1] is not self._draft:
            _ACTIVE_DRAFTS.reset(self._token)
            self._token = None
            raise FillSpecError("unbalanced guidance() block exit")
        _ACTIVE_DRAFTS.reset(self._token)
        self._token = None
        if exc_type is None:
            self._parent.items.append(
                GuidanceScope(*self._draft.items, guidance=self.text)
            )


def agent_request_spec(name: str | None = None) -> AgentRequestSpecBuilder:
    """Open a model-free root declaration for one agent request."""

    return AgentRequestSpecBuilder(name)


def observe(**values: object) -> None:
    """Expose external values at the current declaration position."""

    _current_draft().items.append(Observe(**values))


def step(*actions: str, guidance: str | None = None) -> None:
    """Declare ordered agent-native work."""

    _current_draft().items.append(Step(*actions, guidance=guidance))


def var(
    name: str,
    value_spec: object,
    description: str | None = None,
    *,
    guidance: str | None = None,
) -> None:
    """Declare an explicit answer retained only in the agent's context."""

    _current_draft().items.append(
        Assignment(name, value_spec, description, exposure="var", guidance=guidance)
    )


def field(
    name: str,
    value_spec: object,
    description: str | None = None,
    *,
    guidance: str | None = None,
) -> None:
    """Declare an explicit answer returned to imperative Python."""

    _current_draft().items.append(
        Assignment(name, value_spec, description, exposure="field", guidance=guidance)
    )


def guidance(text: str) -> _GuidanceBuilder:
    """Qualify the enclosed statements without introducing variable scope."""

    return _GuidanceBuilder(text)


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
            "observations or operation results.",
            "",
            "Every `var` and `field` is an explicit structured assignment. A `var`",
            "is retained for later nodes in this request; a `field` is also returned",
            "to imperative Python. Backticked names refer to these exact identifiers.",
            "",
            (
                f"Process agent request `{value.name}`:"
                if value.name is not None
                else "Process this agent request:"
            ),
        ]
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
            if isinstance(item, Observe):
                lines.append(f"{indent}{number}. Observe external results:")
                for name, value in item.values:
                    lines.append(f"{indent}   {name}:")
                    lines.extend(_indented_json(value, indent + "     "))
                continue
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
            label = "context variable" if item.exposure == "var" else "returned field"
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
        if fields_only and item.exposure != "field":
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
        target = variables if item.exposure == "var" else returned
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


# Transitional aliases for code that imported the first prototype names.
FillSpec = AgentRequestSpec
FillSpecBuilder = AgentRequestSpecBuilder
FillSpecRenderer = AgentRequestRenderer
render_fill = render_agent_request
fill_spec = agent_request_spec
