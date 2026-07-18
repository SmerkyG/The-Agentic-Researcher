"""Direct Git inspection operations used by research workflows."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import ArgvTool, CommandResult, Value


class GitRecentLogTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("git", "log", "--oneline")
    count: int = 20

    def argv(self) -> list[str]:
        return [*self.argv_template, f"-{self.count}"]


class GitStatusShortTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("git", "status", "--short")


class GitStatusPathsTool(ArgvTool[CommandResult]):
    """Inspect whether any explicitly selected paths differ from HEAD."""

    argv_template: ClassVar[tuple[str, ...]] = (
        "git", "status", "--porcelain=v1", "--untracked-files=all",
    )
    paths: list[str] = Value("Explicit code paths to inspect")
    project_dir: str = "."

    def argv(self) -> list[str]:
        return [
            "git",
            "-C",
            self.project_dir,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *self.paths,
        ]
