#!/usr/bin/env python3
"""Load and render modular agent-followed workflow sources."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Sequence


WORKFLOW_FENCE = re.compile(
    r"^```python agentic-workflow[ \t]*\n(?P<code>.*?)^```[ \t]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)


class WorkflowSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModuleSource:
    name: str
    path: Path
    code: str
    display_path: str


@dataclass(frozen=True)
class WorkflowDefinition:
    source_path: Path
    bundle_root: Path
    body: str
    block_start: int
    block_end: int
    kind: str
    agent_kind: str | None
    interface_module: str | None
    interface_symbol: str | None
    receiver_module: str | None
    receiver_symbol: str | None
    implementation_module: str
    implementation_symbol: str


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def split_frontmatter(text: str, *, path: Path) -> tuple[dict[str, str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise WorkflowSourceError(f"{path}: modular workflow source requires YAML frontmatter")

    end = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if end is None:
        raise WorkflowSourceError(f"{path}: unterminated YAML frontmatter")

    values: dict[str, str] = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if match and match.group(2):
            values[match.group(1)] = _unquote(match.group(2))
    return values, "".join(lines[end + 1 :])


def split_reference(value: str, *, field: str, path: Path) -> tuple[str, str]:
    module, separator, symbol = value.partition(":")
    if not separator or not module or not symbol:
        raise WorkflowSourceError(
            f"{path}: {field} must be a module:symbol reference, got {value!r}"
        )
    return module, symbol


def discover_bundle_root(source_path: Path) -> Path:
    source_path = source_path.resolve()
    for candidate in (source_path.parent, *source_path.parents):
        if (candidate / "package").is_dir():
            return candidate
    raise WorkflowSourceError(
        f"{source_path}: no workflow bundle root with a package/ directory was found"
    )


def parse_workflow_definition(
    source_path: Path,
    *,
    bundle_root: Path | None = None,
) -> WorkflowDefinition:
    source_path = source_path.resolve()
    frontmatter, body = split_frontmatter(
        source_path.read_text(encoding="utf-8"),
        path=source_path,
    )
    matches = list(WORKFLOW_FENCE.finditer(body))
    if len(matches) != 1:
        raise WorkflowSourceError(
            f"{source_path}: expected exactly one `python agentic-workflow` block, found {len(matches)}"
        )

    try:
        implementation_module = frontmatter["workflow_module"]
        implementation_symbol = frontmatter["workflow_entry"]
    except KeyError as exc:
        raise WorkflowSourceError(
            f"{source_path}: missing frontmatter key {exc.args[0]}"
        ) from exc

    interface = frontmatter.get("workflow_interface")
    receiver = frontmatter.get("workflow_receiver")
    if bool(interface) == bool(receiver):
        raise WorkflowSourceError(
            f"{source_path}: specify exactly one of workflow_interface or workflow_receiver"
        )
    if interface:
        kind = "agent"
        agent_kind = frontmatter.get("kind")
        interface_module, interface_symbol = split_reference(
            interface,
            field="workflow_interface",
            path=source_path,
        )
        receiver_module = receiver_symbol = None
    else:
        kind = "skill"
        agent_kind = None
        receiver_module, receiver_symbol = split_reference(
            receiver or "",
            field="workflow_receiver",
            path=source_path,
        )
        interface_module = interface_symbol = None
    block = matches[0]
    code = block.group("code")
    try:
        ast.parse(code, filename=str(source_path))
    except SyntaxError as exc:
        raise WorkflowSourceError(
            f"{source_path}:{exc.lineno}: invalid workflow Python: {exc.msg}"
        ) from exc

    return WorkflowDefinition(
        source_path=source_path,
        bundle_root=(bundle_root or discover_bundle_root(source_path)).resolve(),
        body=body,
        block_start=block.start(),
        block_end=block.end(),
        kind=kind,
        agent_kind=agent_kind,
        interface_module=interface_module,
        interface_symbol=interface_symbol,
        receiver_module=receiver_module,
        receiver_symbol=receiver_symbol,
        implementation_module=implementation_module,
        implementation_symbol=implementation_symbol,
    )


def _module_name(package_root: Path, path: Path) -> str:
    relative = path.relative_to(package_root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _markdown_module(path: Path) -> tuple[str, str] | None:
    try:
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"), path=path)
    except WorkflowSourceError:
        return None
    module = frontmatter.get("workflow_module")
    if not module:
        return None
    matches = list(WORKFLOW_FENCE.finditer(body))
    if len(matches) != 1:
        raise WorkflowSourceError(
            f"{path}: expected exactly one `python agentic-workflow` block, found {len(matches)}"
        )
    return module, matches[0].group("code")


def index_modules(
    bundle_root: Path,
    source_path: Path,
    *,
    package_roots: Sequence[Path] = (),
) -> dict[str, ModuleSource]:
    modules: dict[str, ModuleSource] = {}
    roots = [bundle_root / "package", *(Path(root).resolve() for root in package_roots)]
    seen_roots: set[Path] = set()
    for package_root in roots:
        package_root = package_root.resolve()
        if package_root in seen_roots or not package_root.is_dir():
            continue
        seen_roots.add(package_root)
        for path in sorted(package_root.rglob("*.py")):
            name = _module_name(package_root, path)
            if not name:
                continue
            existing = modules.get(name)
            if existing and existing.path != path.resolve():
                raise WorkflowSourceError(
                    f"workflow module {name!r} is provided by both {existing.path} and {path}"
                )
            modules[name] = ModuleSource(
                name,
                path.resolve(),
                path.read_text(encoding="utf-8"),
                f"{package_root.parent.name}/package/{path.relative_to(package_root)}",
            )

    markdown_paths = list((bundle_root / "agents").glob("*.md"))
    markdown_paths.extend((bundle_root / "skills").glob("*/SKILL.md"))
    if source_path not in markdown_paths:
        markdown_paths.append(source_path)
    for path in sorted(set(markdown_paths)):
        parsed = _markdown_module(path)
        if parsed is None:
            continue
        name, code = parsed
        existing = modules.get(name)
        if existing and existing.path != path.resolve():
            raise WorkflowSourceError(
                f"{path}: workflow module {name!r} is already provided by {existing.path}"
            )
        modules[name] = ModuleSource(
            name,
            path.resolve(),
            code,
            str(path.resolve().relative_to(bundle_root)),
        )
    return modules


def _resolve_relative_module(current: str, level: int, module: str | None) -> str:
    package = current.split(".")[:-1]
    keep = len(package) - (level - 1)
    if keep < 0:
        return ""
    prefix = package[:keep]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def module_dependencies(module: ModuleSource, available: set[str]) -> list[str]:
    try:
        tree = ast.parse(module.code, filename=str(module.path))
    except SyntaxError as exc:
        raise WorkflowSourceError(
            f"{module.path}:{exc.lineno}: invalid Python: {exc.msg}"
        ) from exc

    dependencies: set[str] = set()
    for node in ast.walk(tree):
        candidates: list[str] = []
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = (
                _resolve_relative_module(module.name, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            if base:
                candidates.append(base)
                candidates.extend(f"{base}.{alias.name}" for alias in node.names)
        for candidate in candidates:
            if candidate in available and candidate != module.name:
                dependencies.add(candidate)
    return sorted(dependencies)


def dependency_order(
    roots: Sequence[str],
    modules: dict[str, ModuleSource],
) -> list[ModuleSource]:
    missing = [root for root in roots if root not in modules]
    if missing:
        raise WorkflowSourceError(f"workflow modules not found: {', '.join(missing)}")

    available = set(modules)
    visited: set[str] = set()
    active: set[str] = set()
    ordered: list[ModuleSource] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in active:
            return
        active.add(name)
        for dependency in module_dependencies(modules[name], available):
            visit(dependency)
        active.remove(name)
        visited.add(name)
        ordered.append(modules[name])

    for root in roots:
        visit(root)
    return ordered


def _class_names(module: ModuleSource) -> set[str]:
    tree = ast.parse(module.code, filename=str(module.path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return None


def _class_base_names(module: ModuleSource, class_name: str) -> set[str]:
    tree = ast.parse(module.code, filename=str(module.path))
    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    if class_node is None:
        return set()
    return {name for base in class_node.bases if (name := _base_name(base)) is not None}


def _function(module: ModuleSource, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    tree = ast.parse(module.code, filename=str(module.path))
    return next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        prefix = _annotation_name(annotation.value)
        return f"{prefix}.{annotation.attr}" if prefix else annotation.attr
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return None


def workflow_roots(definition: WorkflowDefinition) -> list[str]:
    if definition.kind == "agent":
        assert definition.interface_module is not None
        return [definition.interface_module, definition.implementation_module]
    return [definition.implementation_module]


def workflow_modules(
    definition: WorkflowDefinition,
    modules: dict[str, ModuleSource],
) -> list[ModuleSource]:
    if definition.kind == "agent":
        return dependency_order(workflow_roots(definition), modules)
    return [modules[definition.implementation_module]]


def validate_definition(
    definition: WorkflowDefinition,
    modules: dict[str, ModuleSource],
) -> None:
    implementation = modules[definition.implementation_module]
    if definition.kind == "agent":
        assert definition.interface_module is not None
        assert definition.interface_symbol is not None
        interface = modules[definition.interface_module]
        if definition.interface_symbol not in _class_names(interface):
            raise WorkflowSourceError(
                f"{interface.path}: interface class {definition.interface_symbol!r} was not found"
            )
        required_base = {
            "main": "UserFacingWorkflow",
            "subagent": "SubagentWorkflow",
        }.get(definition.agent_kind or "")
        if required_base is None:
            raise WorkflowSourceError(
                f"{definition.source_path}: agent workflow kind must be main or subagent"
            )
        if required_base not in _class_base_names(interface, definition.interface_symbol):
            raise WorkflowSourceError(
                f"{interface.path}: {definition.agent_kind} agent interface "
                f"{definition.interface_symbol!r} must subclass {required_base}"
            )
        if definition.implementation_symbol not in _class_names(implementation):
            raise WorkflowSourceError(
                f"{implementation.path}: implementation class "
                f"{definition.implementation_symbol!r} was not found"
            )
        return

    assert definition.receiver_symbol is not None
    entry = _function(implementation, definition.implementation_symbol)
    if entry is None:
        raise WorkflowSourceError(
            f"{implementation.path}: skill function {definition.implementation_symbol!r} was not found"
        )
    positional = [*entry.args.posonlyargs, *entry.args.args]
    if not positional:
        raise WorkflowSourceError(
            f"{implementation.path}:{entry.lineno}: skill function must accept its workflow receiver"
        )
    annotation = _annotation_name(positional[0].annotation)
    if annotation not in {
        definition.receiver_symbol,
        f"{definition.receiver_module}.{definition.receiver_symbol}",
    }:
        raise WorkflowSourceError(
            f"{implementation.path}:{positional[0].lineno}: first skill parameter must be "
            f"annotated as {definition.receiver_symbol}, got {annotation or 'no annotation'}"
        )


def render_workflow(
    source_path: Path,
    *,
    bundle_root: Path | None = None,
    package_roots: Sequence[Path] = (),
    modules: dict[str, ModuleSource] | None = None,
) -> str:
    definition = parse_workflow_definition(source_path, bundle_root=bundle_root)
    if modules is None:
        modules = index_modules(
            definition.bundle_root,
            definition.source_path,
            package_roots=package_roots,
        )
    ordered = workflow_modules(definition, modules)
    validate_definition(definition, modules)

    if definition.kind == "agent":
        entry_description = (
            f"Follow `{definition.implementation_symbol}` as the implementation of "
            f"`{definition.interface_module}:{definition.interface_symbol}`."
        )
        dispatch_description = (
            "`operation.run()` starts a tool or subagent synchronously. "
            "`self.launch(operation)` starts a tool or subagent asynchronously and tracks it. "
            "`self.fire_and_forget(operation)` starts one asynchronously, discards the "
            "platform handle, and immediately continues with the next Python statement; "
            "never wait, poll, list, message, follow up with, or depend on that operation. "
            "A `SubagentWorkflow` starts a separate subagent that follows the contract "
            "named by its `agent_name` and receives its typed constructor fields. Preserve "
            "inherited history when supported; if a native named role cannot inherit "
            "history, explicitly direct the history-forked child to follow that named "
            "contract. Never execute its workflow body in the current agent context."
        )
    else:
        entry_description = (
            f"Follow `{definition.implementation_symbol}` in the current "
            f"`{definition.receiver_module}:{definition.receiver_symbol}` context."
        )
        dispatch_description = (
            "The skill extends the current workflow context; it does not launch another agent."
        )

    rendered: list[str] = [
        "## Imperative Workflow\n",
        (
            f"{entry_description} Ordinary Python ordering, scope, branches, loops, calls, "
            f"and return values are authoritative. {dispatch_description}\n"
        ),
    ]
    if definition.kind == "skill":
        rendered.append(
            "Before using an imported workflow symbol whose definition is not already in "
            "the active instructions, resolve its dotted module beneath a root in "
            "`$AR_WORKFLOW_PATH` (replace dots with `/` and append `.py`) and read that "
            "source file.\n"
        )
    rendered.append("### Workflow Modules\n")
    for module in ordered:
        rendered.extend(
            [
                f"#### `{module.name}`\n",
                f"Source: `{module.display_path}`\n",
                "```python\n",
                module.code.rstrip(),
                "\n```\n",
            ]
        )
    workflow_block = "\n".join(rendered).rstrip() + "\n"
    return (
        definition.body[: definition.block_start]
        + workflow_block
        + definition.body[definition.block_end :]
    )


class WorkflowRenderer:
    """Render related workflow sources while indexing their modules once."""

    def __init__(self, package_roots: Sequence[Path] = ()) -> None:
        self.package_roots = tuple(Path(root).resolve() for root in package_roots)
        self._modules: dict[Path, dict[str, ModuleSource]] = {}

    def render(self, source_path: Path) -> str:
        definition = parse_workflow_definition(source_path)
        modules = self._modules.get(definition.bundle_root)
        if modules is None:
            modules = index_modules(
                definition.bundle_root,
                definition.source_path,
                package_roots=self.package_roots,
            )
            self._modules[definition.bundle_root] = modules
        return render_workflow(
            source_path,
            bundle_root=definition.bundle_root,
            package_roots=self.package_roots,
            modules=modules,
        )


def manifest(
    source_path: Path,
    *,
    bundle_root: Path | None = None,
    package_roots: Sequence[Path] = (),
) -> dict[str, object]:
    definition = parse_workflow_definition(source_path, bundle_root=bundle_root)
    modules = index_modules(
        definition.bundle_root,
        definition.source_path,
        package_roots=package_roots,
    )
    ordered = workflow_modules(definition, modules)
    validate_definition(definition, modules)
    result: dict[str, object] = {
        "kind": definition.kind,
        "implementation": f"{definition.implementation_module}:{definition.implementation_symbol}",
        "modules": [
            {
                "name": module.name,
                "path": module.display_path,
            }
            for module in ordered
        ],
    }
    if definition.kind == "agent":
        result["interface"] = f"{definition.interface_module}:{definition.interface_symbol}"
    else:
        result["receiver"] = f"{definition.receiver_module}:{definition.receiver_symbol}"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("render", "manifest"))
    parser.add_argument("source", type=Path)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--package-root", type=Path, action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "render":
            sys.stdout.write(
                render_workflow(
                    args.source,
                    bundle_root=args.bundle_root,
                    package_roots=args.package_root,
                )
            )
        else:
            print(
                json.dumps(
                    manifest(
                        args.source,
                        bundle_root=args.bundle_root,
                        package_roots=args.package_root,
                    ),
                    indent=2,
                )
            )
    except (OSError, WorkflowSourceError) as exc:
        print(f"workflow-source: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
