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
    "ask_user",
    "cancel",
    "context",
    "do",
    "evaluate",
    "lock",
    "run_tool",
    "start_tool",
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


def _is_list_schema_type(node: ast.AST) -> bool:
    if not isinstance(node, ast.Subscript) or _call_name(node.value) not in {"list", "List"}:
        return False
    element_type = node.slice
    if isinstance(element_type, ast.Tuple):
        return False
    return _annotation_name(element_type) in ALLOWED_SCHEMA_SCALARS


def _is_allowed_schema_type(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if _annotation_name(node) in ALLOWED_SCHEMA_SCALARS:
        return True
    if _is_literal_schema_type(node):
        return True
    return _is_list_schema_type(node)


def _value_description(node: ast.Call) -> str | None:
    candidate: ast.AST | None = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "description":
            candidate = keyword.value
    return _literal_string(candidate)


def _is_schema_field(node: ast.AnnAssign) -> bool:
    if not _is_allowed_schema_type(node.annotation):
        return False
    if not _is_value_call(node.value) or not isinstance(node.value, ast.Call):
        return False
    description = _value_description(node.value)
    return bool(description and description.strip())


def _is_dataclass(node: ast.ClassDef) -> bool:
    return any(_call_name(decorator) == "dataclass" for decorator in node.decorator_list)


def _schema_fields(tree: ast.AST) -> dict[str, set[str]]:
    schemas: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_dataclass(node):
            continue
        fields = [
            item for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        ]
        if fields and all(_is_schema_field(field) for field in fields):
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

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_workflow_entrypoint(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._is_self_method_call(node):
            self._check_self_method_call(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "do":
            self._check_do_call(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "evaluate":
            self._check_evaluate_call(node)
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
        if node.name == "AgentWorkflow":
            return
        if not any(_call_name(base) == "AgentWorkflow" for base in node.bases):
            return
        call_methods = [
            item for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__call__"
        ]
        if call_methods:
            for item in call_methods:
                self._check_workflow_call_signature(item)
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF401",
                message="AgentWorkflow subclasses must define __call__ as their launch entrypoint",
            )
        )

    def _check_workflow_call_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        if args.posonlyargs or args.vararg or args.kwarg or args.kwonlyargs:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    code="WF402",
                    message=(
                        "AgentWorkflow __call__ signatures must use explicit typed "
                        "positional-or-keyword parameters only; do not use /, *, *args, or **kwargs"
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
                        message="AgentWorkflow __call__ parameters must have explicit type annotations",
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
                            "AgentWorkflow __call__ parameters must not use Any or dict; "
                            "use explicit scalar parameters or typed dataclass contracts"
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
                        "AgentWorkflow __call__ return types must not use Any or dict; "
                        "return None, a scalar, or a typed dataclass result"
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
                    "context_packet hides structured state in a string; use typed dataclass "
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
            if statement.name not in self.schema_classes or not _is_dataclass(statement):
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
                        "local schema dataclasses must be defined immediately before "
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
        if _is_evaluate_call(value):
            schema_node: ast.AST | None = value.args[0] if value.args else None
            for keyword in value.keywords:
                if keyword.arg == "subject":
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
        if not isinstance(node.func, ast.Attribute) or node.func.attr in ALLOWED_SELF_METHODS:
            return
        self.findings.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                code="WF501",
                message=(
                    f"self.{node.func.attr}(...) is not declared in the AgentWorkflow contract; "
                    "use a declared runtime primitive, a plain helper function, or a workflow object's __call__"
                ),
            )
        )

    def _check_do_call(self, node: ast.Call) -> None:
        actions_node: ast.AST | None = node.args[0] if node.args else None
        for keyword in node.keywords:
            if keyword.arg == "actions":
                actions_node = keyword.value
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
        self._check_do_usage(node)

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
        if len(node.args) > 1:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.args[1].lineno,
                    col=node.args[1].col_offset,
                    code="WF702",
                    message=(
                        "self.evaluate accepts exactly one subject; rely on lexical scope "
                        "or use self.context(...) only to narrow ambiguous inputs"
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
            else:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=keyword.value.lineno,
                        col=keyword.value.col_offset,
                        code="WF702",
                        message=(
                            "self.evaluate accepts only subject=; "
                            "rely on lexical scope or use self.context(...) only to narrow ambiguous inputs"
                        ),
                    )
                )

        parent = getattr(node, "_workflow_parent", None)
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
            if description.strip() and _is_allowed_schema_type(parent.annotation):
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
                        "self.evaluate first argument must be a declarative string or a dataclass schema "
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
    return lint_source(path.read_text(encoding="utf-8"), path=str(path))


def iter_python_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            if path.suffix == ".py":
                yield path
            continue
        if not path.is_dir():
            yield path
            continue
        for candidate in sorted(path.rglob("*.py")):
            if any(part in SKIP_DIRS for part in candidate.parts):
                continue
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
    parser.add_argument("paths", nargs="+", type=Path, help="Python files or directories to lint.")
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
