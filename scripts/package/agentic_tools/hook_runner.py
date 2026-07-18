"""Load capability lifecycle hooks declared as importable Python functions."""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import os
from pathlib import Path
import sys
import tomllib
from typing import Iterator, Mapping


def hook_reference(capability_root: str | Path, hook_name: str) -> str | None:
    root = Path(capability_root).expanduser().resolve()
    manifest = root / "capability.toml"
    if not manifest.is_file():
        return None
    document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{manifest}: hooks must be a TOML table")
    value = hooks.get(hook_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{manifest}: hooks.{hook_name} must be a module:function reference")
    return value


@contextmanager
def _environment(values: Mapping[str, str] | None) -> Iterator[None]:
    if values is None:
        yield
        return
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def execute_hook(
    capability_root: str | Path,
    hook_name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    root = Path(capability_root).expanduser().resolve()
    reference = hook_reference(root, hook_name)
    if reference is None:
        return 0
    package_root = root / "package"
    if package_root.is_dir() and str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    module_name, separator, function_name = reference.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError(f"invalid hook reference: {reference!r}")
    function: object = importlib.import_module(module_name)
    for component in function_name.split("."):
        function = getattr(function, component)
    if not callable(function):
        raise TypeError(f"capability hook is not callable: {reference}")
    with _environment(environment):
        result = function()
    return int(result) if isinstance(result, int) else 0


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: agentic-hook CAPABILITY_ROOT HOOK_NAME", file=sys.stderr)
        return 2
    try:
        return execute_hook(sys.argv[1], sys.argv[2])
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"agentic-hook: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
