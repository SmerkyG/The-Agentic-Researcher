"""Lint Agentic Team imperative workflow sources."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence


DISALLOWED_ACTION_TERMS: dict[str, tuple[str, ...]] = {
    "ordering": ("before", "after", "then", "next", "first", "last", "once"),
    "conditions": ("if", "when", "unless", "only if", "provided that"),
    "loops": ("while", "until", "repeat", "for each"),
    "failure_policy": ("try", "retry", "fallback", "otherwise", "on failure"),
    "concurrency": ("background", "parallel", "wait for", "fire and forget"),
}

SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "node_modules"}
WORKFLOW_FENCE = re.compile(
    r"^```python agentic-workflow[ \t]*\n(?P<code>.*?)^```[ \t]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    col: int
    code: str
    message: str
    action: str | None = None
    category: str | None = None
    term: str | None = None

    def text(self) -> str:
        location = f"{self.path}:{self.line}:{self.col + 1}"
        suffix = f" action={self.action!r}" if self.action is not None else ""
        return f"{location}: {self.code}: {self.message}{suffix}"

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "code": self.code,
            "message": self.message,
        }
        if self.action is not None:
            data["action"] = self.action
        if self.category is not None:
            data["category"] = self.category
        if self.term is not None:
            data["term"] = self.term
        return data


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = r"\s+".join(re.escape(part) for part in term.split())
    return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)


TERM_PATTERNS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    category: tuple((term, _term_pattern(term)) for term in terms)
    for category, terms in DISALLOWED_ACTION_TERMS.items()
}
ALLOWED_SCHEMA_SCALARS = {"bool", "int", "float", "str"}
ALLOWED_SELF_METHODS = {
    "cancel",
    "do",
    "evaluate",
    "fill",
    "fire_and_forget",
    "launch",
    "lock",
    "timeout",
    "wait_all",
    "wait_any",
}


def _line_allowances(lines: Sequence[str], line: int) -> set[str]:
    if line < 1 or line > len(lines):
        return set()
    text = lines[line - 1]
    marker = "workflow-lint: allow"
    if marker not in text:
        return set()
    _head, _marker, tail = text.partition(marker)
    tail = tail.strip()
    if not tail:
        return {"all"}
    if tail.startswith("="):
        tail = tail[1:]
    return {
        item.strip().casefold()
        for item in re.split(r"[, ]+", tail)
        if item.strip()
    } or {"all"}


def _is_allowed(lines: Sequence[str], line: int, category: str, term: str) -> bool:
    allowances = _line_allowances(lines, line)
    return bool({"all", category.casefold(), term.casefold()} & allowances)


def disallowed_terms(action: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for category, term_patterns in TERM_PATTERNS.items():
        for term, pattern in term_patterns:
            if pattern.search(action):
                matches.append((category, term))
    return matches


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_literal_none(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_do_call(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "do"
    )


def _is_evaluate_call(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "evaluate"
    )


def _is_value_call(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Call) and _call_name(node.func) == "Value"


def _annotation_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _annotation_contains_name(node: ast.AST | None, names: set[str]) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return node.attr in names
    if isinstance(node, ast.Subscript):
        return _annotation_contains_name(node.value, names) or _annotation_contains_name(node.slice, names)
    if isinstance(node, ast.Tuple):
        return any(_annotation_contains_name(element, names) for element in node.elts)
    if isinstance(node, ast.List):
        return any(_annotation_contains_name(element, names) for element in node.elts)
    if isinstance(node, ast.BinOp):
        return _annotation_contains_name(node.left, names) or _annotation_contains_name(node.right, names)
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value in names
    return any(_annotation_contains_name(child, names) for child in ast.iter_child_nodes(node))


def _is_dict_annotation(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in {"dict", "Dict"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"dict", "Dict"}
    if isinstance(node, ast.Subscript):
        return _is_dict_annotation(node.value) or _is_dict_annotation(node.slice)
    if isinstance(node, ast.Tuple):
        return any(_is_dict_annotation(element) for element in node.elts)
    if isinstance(node, ast.BinOp):
        return _is_dict_annotation(node.left) or _is_dict_annotation(node.right)
    return any(_is_dict_annotation(child) for child in ast.iter_child_nodes(node))


def _is_loose_workflow_contract_annotation(node: ast.AST | None) -> bool:
    return _annotation_contains_name(node, {"Any"}) or _is_dict_annotation(node)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return None


def _is_literal_schema_type(node: ast.AST) -> bool:
    if not isinstance(node, ast.Subscript) or _call_name(node.value) != "Literal":
        return False
    elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    return bool(elements) and all(
        isinstance(element, ast.Constant)
        and isinstance(element.value, (bool, int, float, str))
        for element in elements
    )


def _is_none_type(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or _annotation_name(node) == "None"


def _is_union_schema_type(node: ast.AST, schema_names: set[str]) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = _flatten_union_members(node)
        non_none = [member for member in members if not _is_none_type(member)]
        return bool(non_none) and all(_is_allowed_schema_type(member, schema_names) for member in non_none)
    if isinstance(node, ast.Subscript) and _call_name(node.value) in {"Union", "Optional"}:
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        non_none = [member for member in members if not _is_none_type(member)]
        return bool(non_none) and all(_is_allowed_schema_type(member, schema_names) for member in non_none)
    return False


def _flatten_union_members(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_flatten_union_members(node.left), *_flatten_union_members(node.right)]
    return [node]


def _is_list_schema_type(node: ast.AST, schema_names: set[str]) -> bool:
    if not isinstance(node, ast.Subscript) or _call_name(node.value) not in {"list", "List"}:
        return False
    element_type = node.slice
    if isinstance(element_type, ast.Tuple):
        return False
    return _is_allowed_schema_type(element_type, schema_names)


def _is_classvar_annotation(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if _annotation_name(node) == "ClassVar":
        return True
    return isinstance(node, ast.Subscript) and _annotation_name(node.value) == "ClassVar"


def _is_allowed_schema_type(node: ast.AST | None, schema_names: set[str]) -> bool:
    if node is None:
        return False
    if _annotation_name(node) in ALLOWED_SCHEMA_SCALARS:
        return True
    if _annotation_name(node) in schema_names:
        return True
    if _is_literal_schema_type(node):
        return True
    if _is_union_schema_type(node, schema_names):
        return True
    return _is_list_schema_type(node, schema_names)


def _value_description(node: ast.Call) -> str | None:
    candidate: ast.AST | None = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "description":
            candidate = keyword.value
    return _literal_string(candidate)


def _is_schema_field(node: ast.AnnAssign, schema_names: set[str]) -> bool:
    if not _is_allowed_schema_type(node.annotation, schema_names):
        return False
    if not _is_value_call(node.value) or not isinstance(node.value, ast.Call):
        return False
    description = _value_description(node.value)
    return bool(description and description.strip())


def _is_workflow_record(node: ast.ClassDef) -> bool:
    return any(
        _call_name(base) in {"WorkflowRecord", "WorkflowTool", "YAMLArgvTool", "ArgvTool"}
        for base in node.bases
    )


def _is_agent_workflow(node: ast.ClassDef) -> bool:
    return any(
        _call_name(base) in {"AgentWorkflow", "SubagentWorkflow", "UserFacingWorkflow"}
        for base in node.bases
    )


def _is_user_facing_workflow(node: ast.ClassDef) -> bool:
    return any(_call_name(base) == "UserFacingWorkflow" for base in node.bases)


def _workflow_record_names(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_workflow_record(node)
    }


def _schema_fields(tree: ast.AST) -> dict[str, set[str]]:
    schemas: dict[str, set[str]] = {}
    schema_names = _workflow_record_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_workflow_record(node):
            continue
        fields = [
            item for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            and not _is_classvar_annotation(item.annotation)
        ]
        if fields and all(_is_schema_field(field, schema_names) for field in fields):
            schemas[node.name] = {
                field.target.id
                for field in fields
                if isinstance(field.target, ast.Name)
            }
    return schemas


class WorkflowVisitor(ast.NodeVisitor):
    def __init__(self, path: str, lines: Sequence[str], schema_fields: dict[str, set[str]]) -> None:
        self.path = path
        self.lines = lines
        self.schema_fields = schema_fields
        self.schema_classes = set(schema_fields)
        self.findings: list[Finding] = []
        self._agent_workflow_depth = 0
        self._user_facing_workflow_depth = 0
        self._workflow_method_stack: list[set[str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_workflow_entrypoint(node)
        self._check_workflow_config_fields(node)
        is_agent_workflow = _is_agent_workflow(node)
        is_user_facing_workflow = _is_user_facing_workflow(node)
        if is_agent_workflow:
            self._agent_workflow_depth += 1
            self._workflow_method_stack.append(
                {
                    item.name
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            )
        if is_user_facing_workflow:
            self._user_facing_workflow_depth += 1
        try:
            self.generic_visit(node)
        finally:
            if is_user_facing_workflow:
                self._user_facing_workflow_depth -= 1
            if is_agent_workflow:
                self._workflow_method_stack.pop()
                self._agent_workflow_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        if self._agent_workflow_depth > 0 and self._is_self_method_call(node):
            self._check_self_method_call(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "do":
            self._check_do_call(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "evaluate":
            self._check_evaluate_call(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "fill":
            self._check_fill_call(node)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"launch", "fire_and_forget", "launch_detached"}
        ):
            self._check_launch_call(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_context_packet_field(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_return_annotation(node)
        self._check_adjacent_do_statements(node.body)
        self._check_local_schema_adjacency(node.body)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_return_annotation(node)
        self._check_adjacent_do_statements(node.body)
        self._check_local_schema_adjacency(node.body)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_adjacent_do_statements(node.orelse)
        self._check_local_schema_adjacency(node.body)
        self._check_local_schema_adjacency(node.orelse)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_adjacent_do_statements(node.orelse)
        self._check_local_schema_adjacency(node.body)
        self._check_local_schema_adjacency(node.orelse)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_adjacent_do_statements(node.orelse)
        self._check_local_schema_adjacency(node.body)
        self._check_local_schema_adjacency(node.orelse)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_adjacent_do_statements(node.orelse)
        self._check_local_schema_adjacency(node.body)
        self._check_local_schema_adjacency(node.orelse)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_local_schema_adjacency(node.body)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_local_schema_adjacency(node.body)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._check_adjacent_do_statements(node.body)
        self._check_adjacent_do_statements(node.orelse)
        self._check_adjacent_do_statements(node.finalbody)
        self._check_local_schema_adjacency(node.body)
        self._check_local_schema_adjacency(node.orelse)
        self._check_local_schema_adjacency(node.finalbody)
        for handler in node.handlers:
            self._check_adjacent_do_statements(handler.body)
            self._check_local_schema_adjacency(handler.body)
        self.generic_visit(node)

    def _check_return_annotation(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.returns is not None:
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF301",
                message="workflow functions and methods must declare an explicit return type annotation",
            )
        )

    def _check_workflow_entrypoint(self, node: ast.ClassDef) -> None:
        if node.name in {"AgentWorkflow", "UserFacingWorkflow"}:
            return
        if not _is_agent_workflow(node):
            return
        workflow_methods = [
            item for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "workflow"
        ]
        if workflow_methods:
            for item in workflow_methods:
                self._check_workflow_signature(item)
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF401",
                message="AgentWorkflow implementation subclasses must define workflow as their entrypoint",
            )
        )

    def _check_workflow_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        if args.posonlyargs or args.vararg or args.kwarg or args.kwonlyargs or len(args.args) != 1:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF402",
                    message=(
                        "AgentWorkflow workflow signatures must take only self; "
                        "put launch configuration in typed constructor fields"
                    ),
                )
            )

        for arg in args.args[1:]:
            if arg.annotation is None:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=arg.lineno,
                        col=arg.col_offset,
                        code="WF403",
                        message="AgentWorkflow workflow parameters must have explicit type annotations",
                    )
                )
                continue
            if _is_loose_workflow_contract_annotation(arg.annotation):
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=arg.lineno,
                        col=arg.col_offset,
                        code="WF404",
                        message=(
                            "AgentWorkflow workflow parameters must not use Any or dict; "
                            "use explicit scalar parameters or typed WorkflowRecord contracts"
                        ),
                    )
                )

        if _is_loose_workflow_contract_annotation(node.returns):
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF405",
                    message=(
                        "AgentWorkflow workflow return types must not use Any or dict; "
                        "return None, a scalar, or a typed WorkflowRecord result"
                    ),
                )
            )

    def _check_workflow_config_fields(self, node: ast.ClassDef) -> None:
        if node.name in {"AgentWorkflow", "UserFacingWorkflow"} or not _is_agent_workflow(node):
            return
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            if _is_loose_workflow_contract_annotation(item.annotation):
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=item.lineno,
                        col=item.col_offset,
                        code="WF406",
                        message=(
                            "AgentWorkflow constructor fields must not use Any or dict; "
                            "use explicit scalar values, WorkflowRecord contracts, or WorkflowTool contracts"
                        ),
                    )
                )

    def _check_context_packet_field(self, node: ast.AnnAssign) -> None:
        if not isinstance(node.target, ast.Name) or node.target.id != "context_packet":
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF801",
                message=(
                    "context_packet hides structured state in a string; use typed WorkflowRecord "
                    "fields such as FinalizerContext instead"
                ),
            )
        )

    def _check_adjacent_do_statements(self, body: Sequence[ast.stmt]) -> None:
        previous_do: ast.stmt | None = None
        for statement in body:
            if self._is_do_statement(statement):
                if previous_do is not None:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=statement.lineno,
                            col=statement.col_offset,
                            code="WF601",
                            message=(
                                "adjacent self.do statements in the same block must be combined with "
                                "one actions list or separated by explicit Python control/tool work"
                            ),
                        )
                    )
                previous_do = statement
            else:
                previous_do = None

    def _is_do_statement(self, statement: ast.stmt) -> bool:
        if isinstance(statement, ast.Expr):
            return _is_do_call(statement.value)
        if isinstance(statement, ast.AnnAssign):
            return _is_do_call(statement.value)
        if isinstance(statement, ast.Assign):
            return _is_do_call(statement.value)
        return False

    def _check_local_schema_adjacency(self, body: Sequence[ast.stmt]) -> None:
        for index, statement in enumerate(body):
            if not isinstance(statement, ast.ClassDef):
                continue
            if statement.name not in self.schema_classes or not _is_workflow_record(statement):
                continue
            next_statement = body[index + 1] if index + 1 < len(body) else None
            if next_statement is not None and self._statement_consumes_schema(next_statement, statement.name):
                continue
            self.findings.append(
                Finding(
                    path=self.path,
                    line=statement.lineno,
                    col=statement.col_offset,
                    code="WF703",
                    message=(
                        "local WorkflowRecord schemas must be defined immediately before "
                        "the self.evaluate(...) statement that consumes them"
                    ),
                )
            )

    def _statement_consumes_schema(self, statement: ast.stmt, schema_name: str) -> bool:
        if not isinstance(statement, ast.AnnAssign):
            return False
        if _annotation_name(statement.annotation) != schema_name:
            return False
        value = statement.value
        if _is_evaluate_call(value) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "fill"
        ):
            schema_node: ast.AST | None = value.args[0] if value.args else None
            for keyword in value.keywords:
                if keyword.arg in {"subject", "record_type"}:
                    schema_node = keyword.value
            return _annotation_name(schema_node) == schema_name
        return False

    def _is_self_method_call(self, node: ast.Call) -> bool:
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        )

    def _check_self_method_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr == "ask_user":
            if self._user_facing_workflow_depth > 0:
                return
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF502",
                    message="self.ask_user(...) is only allowed in UserFacingWorkflow subclasses; subagents must return a status/request for the parent to surface",
                )
            )
            return
        if node.func.attr in ALLOWED_SELF_METHODS:
            return
        if self._workflow_method_stack and node.func.attr in self._workflow_method_stack[-1]:
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF501",
                message=(
                    f"self.{node.func.attr}(...) is not declared in the AgentWorkflow contract; "
                    "use a declared runtime primitive, a plain helper function, or operation.run()"
                ),
            )
        )

    def _check_launch_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        is_self_call = (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        )
        if node.func.attr == "launch_detached" or not is_self_call:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF802",
                    message=(
                        "start asynchronous operations through self.launch(operation) or "
                        "self.fire_and_forget(operation), not an operation-level launch method"
                    ),
                )
            )
            return
        if len(node.args) != 1 or node.keywords:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF802",
                    message=f"self.{node.func.attr}(...) requires exactly one positional operation",
                )
            )
            return
        parent = getattr(node, "_workflow_parent", None)
        if node.func.attr == "launch":
            if (
                isinstance(parent, ast.AnnAssign)
                and parent.value is node
                and _annotation_contains_name(parent.annotation, {"Job"})
            ):
                return
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF802",
                    message=(
                        "launch() starts tracked work and must be assigned with an explicit "
                        "Job[...] annotation; use self.fire_and_forget(operation) when no result is needed"
                    ),
                )
            )
            return
        if isinstance(parent, ast.Expr):
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF802",
                message="self.fire_and_forget(operation) must be a bare expression",
            )
        )

    def _check_do_call(self, node: ast.Call) -> None:
        actions_node: ast.AST | None = node.args[0] if node.args else None
        has_positional_actions = bool(node.args)
        guidance_node: ast.AST | None = node.args[1] if len(node.args) > 1 else None
        if len(node.args) > 2:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.args[2].lineno,
                    col=node.args[2].col_offset,
                    code="WF001",
                    message="self.do accepts actions plus optional guidance only",
                )
            )
        for keyword in node.keywords:
            if keyword.arg == "actions":
                if has_positional_actions:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=keyword.value.lineno,
                            col=keyword.value.col_offset,
                            code="WF001",
                            message="self.do actions must be supplied at most once",
                        )
                    )
                actions_node = keyword.value
            elif keyword.arg == "guidance":
                if guidance_node is not None:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=keyword.value.lineno,
                            col=keyword.value.col_offset,
                            code="WF901",
                            message="guidance must be supplied at most once",
                        )
                    )
                guidance_node = keyword.value
            elif keyword.arg in {"action", "work_items"}:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=keyword.value.lineno,
                        col=keyword.value.col_offset,
                        code="WF001",
                        message="self.do uses actions=[...] only; action= and work_items= are not part of the contract",
                    )
                )
            else:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=keyword.value.lineno,
                        col=keyword.value.col_offset,
                        code="WF001",
                        message="self.do accepts only actions= and guidance=",
                    )
                )

        if actions_node is None:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF001",
                    message="self.do actions must be a literal list or tuple of literal strings",
                )
            )
            return

        self._check_actions(actions_node)
        self._check_guidance(guidance_node)
        self._check_do_usage(node)

    def _check_guidance(self, node: ast.AST | None) -> None:
        if node is None:
            return
        if _literal_string(node) is not None or _is_literal_none(node):
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF901",
                message="guidance must be a literal string or None",
            )
        )

    def _check_actions(self, node: ast.AST) -> None:
        if not isinstance(node, (ast.List, ast.Tuple)):
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF001",
                    message="self.do actions must be a literal list or tuple of literal strings",
                )
            )
            return

        if not node.elts:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF001",
                    message="self.do actions must not be empty",
                )
            )
            return

        for item in node.elts:
            action = _literal_string(item)
            if action is None:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=item.lineno,
                        col=item.col_offset,
                        code="WF001",
                        message="self.do actions must contain only literal strings",
                    )
                )
                continue
            for category, term in disallowed_terms(action):
                if _is_allowed(self.lines, item.lineno, category, term):
                    continue
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=item.lineno,
                        col=item.col_offset,
                        code="WF101",
                        message=f"self.do action contains {category} control term {term!r}",
                        action=action,
                        category=category,
                        term=term,
                    )
                )

    def _check_do_usage(self, node: ast.Call) -> None:
        parent = getattr(node, "_workflow_parent", None)
        if isinstance(parent, ast.Expr):
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF201",
                message="self.do is side-effect-only; use self.evaluate(...) for returned facts or schemas",
            )
        )

    def _check_evaluate_call(self, node: ast.Call) -> None:
        subject_node: ast.AST | None = node.args[0] if node.args else None
        has_positional_subject = bool(node.args)
        guidance_node: ast.AST | None = node.args[1] if len(node.args) > 1 else None
        if len(node.args) > 2:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.args[2].lineno,
                    col=node.args[2].col_offset,
                    code="WF702",
                    message=(
                        "self.evaluate accepts one subject plus optional guidance; rely on lexical scope"
                    ),
                )
            )

        for keyword in node.keywords:
            if keyword.arg == "subject":
                if has_positional_subject:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=keyword.value.lineno,
                            col=keyword.value.col_offset,
                            code="WF702",
                            message=(
                                "self.evaluate accepts exactly one subject; "
                                "do not combine positional subject with subject="
                            ),
                        )
                    )
                subject_node = keyword.value
            elif keyword.arg == "guidance":
                if guidance_node is not None:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=keyword.value.lineno,
                            col=keyword.value.col_offset,
                            code="WF901",
                            message="guidance must be supplied at most once",
                        )
                    )
                guidance_node = keyword.value
            else:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=keyword.value.lineno,
                        col=keyword.value.col_offset,
                        code="WF702",
                        message=(
                            "self.evaluate accepts only subject= and guidance=; rely on lexical scope"
                        ),
                    )
                )

        self._check_guidance(guidance_node)
        parent = getattr(node, "_workflow_parent", None)
        if self._is_conditional_evaluate(node, parent):
            description = _literal_string(subject_node)
            if description is not None and description.strip():
                return
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF701",
                    message="conditional self.evaluate calls must use a literal declarative string subject",
                )
            )
            return

        if not isinstance(parent, ast.AnnAssign) or parent.value is not node:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF701",
                    message="self.evaluate return must be assigned with an explicit matching annotation",
                )
            )
            return

        annotation = _annotation_name(parent.annotation)
        description = _literal_string(subject_node)
        if description is not None:
            if description.strip() and _is_allowed_schema_type(parent.annotation, self.schema_classes):
                return
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF701",
                    message=(
                        "direct self.evaluate descriptions require bool, int, float, str, "
                        "Literal[...] or list[...] annotations"
                    ),
                )
            )
            return

        schema_name = _annotation_name(subject_node) if subject_node is not None else None
        if schema_name is None or schema_name not in self.schema_classes:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF701",
                    message=(
                        "self.evaluate first argument must be a declarative string or a WorkflowRecord schema "
                        "whose fields use allowed Value(...) descriptions"
                    ),
                )
            )
            return

        if annotation == schema_name:
            return

        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF701",
                message="self.evaluate assignment annotation must match its schema argument",
            )
        )

    def _is_conditional_evaluate(self, node: ast.Call, parent: ast.AST | None) -> bool:
        if isinstance(parent, (ast.If, ast.While)) and parent.test is node:
            return True
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            grandparent = getattr(parent, "_workflow_parent", None)
            return isinstance(grandparent, (ast.If, ast.While)) and grandparent.test is parent
        return False

    def _check_fill_call(self, node: ast.Call) -> None:
        record_node: ast.AST | None = node.args[0] if node.args else None
        guidance_node: ast.AST | None = node.args[1] if len(node.args) > 1 else None
        if len(node.args) > 2:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.args[2].lineno,
                    col=node.args[2].col_offset,
                    code="WF704",
                    message=(
                        "self.fill accepts one WorkflowRecord, WorkflowTool, "
                        "YAMLArgvTool or ArgvTool schema type plus optional guidance"
                    ),
                )
            )
        has_positional_record = bool(node.args)
        for keyword in node.keywords:
            if keyword.arg == "record_type":
                if has_positional_record:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=keyword.value.lineno,
                            col=keyword.value.col_offset,
                            code="WF704",
                            message="self.fill record type must be supplied at most once",
                        )
                    )
                record_node = keyword.value
            elif keyword.arg == "guidance":
                if guidance_node is not None:
                    self.findings.append(
                        Finding(
                            path=self.path,
                            line=keyword.value.lineno,
                            col=keyword.value.col_offset,
                            code="WF901",
                            message="guidance must be supplied at most once",
                        )
                    )
                guidance_node = keyword.value
            else:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=keyword.value.lineno,
                        col=keyword.value.col_offset,
                        code="WF704",
                        message="self.fill accepts only record_type= and guidance=",
                    )
                )

        if record_node is None:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF704",
                    message=(
                        "self.fill accepts exactly one WorkflowRecord, WorkflowTool, "
                        "YAMLArgvTool or ArgvTool schema type"
                    ),
                )
            )
            return

        self._check_guidance(guidance_node)
        parent = getattr(node, "_workflow_parent", None)
        if not isinstance(parent, ast.AnnAssign) or parent.value is not node:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF704",
                    message="self.fill return must be assigned with an explicit matching annotation",
                )
            )
            return

        schema_name = _annotation_name(record_node)
        annotation = _annotation_name(parent.annotation)
        if schema_name is not None and annotation == schema_name:
            return

        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF704",
                message="self.fill assignment annotation must match its schema argument",
            )
        )


def lint_source(source: str, *, path: str = "<string>") -> list[Finding]:
    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [
            Finding(
                path=path,
                line=exc.lineno or 1,
                col=exc.offset or 0,
                code="WF000",
                message=f"Python syntax error: {exc.msg}",
            )
        ]

    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            setattr(child, "_workflow_parent", parent)

    visitor = WorkflowVisitor(path, lines, _schema_fields(tree))
    visitor.visit(tree)
    return visitor.findings


def lint_file(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    if path.suffix != ".md":
        return lint_source(source, path=str(path))

    findings: list[Finding] = []
    for match in WORKFLOW_FENCE.finditer(source):
        line_offset = source.count("\n", 0, match.start("code"))
        findings.extend(
            lint_source("\n" * line_offset + match.group("code"), path=str(path))
        )
    return findings


def iter_python_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            if path.suffix in {".py", ".md"}:
                yield path
            continue
        if not path.is_dir():
            yield path
            continue
        for candidate in sorted(path.rglob("*.py")):
            if any(part in SKIP_DIRS for part in candidate.parts):
                continue
            yield candidate
        for candidate in sorted(path.rglob("*.md")):
            if any(part in SKIP_DIRS for part in candidate.parts):
                continue
            if "```python agentic-workflow" in candidate.read_text(encoding="utf-8"):
                yield candidate


def lint_paths(paths: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_python_files(paths):
        if not path.exists():
            findings.append(
                Finding(
                    path=str(path),
                    line=1,
                    col=0,
                    code="WF404",
                    message="path does not exist",
                )
            )
            continue
        findings.extend(lint_file(path))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint Agentic Team imperative workflow Python sources.")
    parser.add_argument("paths", nargs="+", type=Path, help="Python or tagged Markdown workflow sources to lint.")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    findings = lint_paths(args.paths)
    if args.json:
        print(json.dumps([finding.as_dict() for finding in findings], indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(finding.text(), file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
