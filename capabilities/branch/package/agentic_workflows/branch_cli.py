"""Human-friendly command wrappers over native branch operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Callable, TypeVar

import yaml

from agentic_tools import (
    PythonTool,
    Record,
    record_data,
    record_from_data,
)
from agentic_workflows.branch import (
    BranchCommitCleanupTool,
    BranchCommitStatusTool,
    BranchCommitTool,
    BranchSnapshotTool,
    BranchWorktreeCreateTool,
    BranchWorktreeDropTool,
    BranchWorktreePublishTool,
)
from branch_tools.service import commit_snapshot_worker
from command_common import CommandError


ResultT = TypeVar("ResultT", bound=Record)


def _request() -> dict[str, object]:
    data = yaml.safe_load(sys.stdin.read()) or {}
    if not isinstance(data, dict):
        raise CommandError("request YAML must be a mapping")
    if "kind" in data:
        raise CommandError("omit request kind; select the command by running it directly")
    return data


def _tool(tool_type: type[PythonTool[ResultT]], data: dict[str, object]) -> PythonTool[ResultT]:
    return record_from_data(tool_type, data, reject_unknown=True)


def _execute(tool: PythonTool[ResultT]) -> ResultT:
    return tool.execute()


def _print(result: object, *, command: str, nested: str | None = None) -> None:
    data = record_data(result)
    if not isinstance(data, dict):
        raise TypeError("branch operation returned a non-object result")
    response = {"command": command, **data}
    if nested is not None:
        response[nested] = data
    print(json.dumps(response, sort_keys=True))


def _main(command_name: str, action: Callable[[], None]) -> int:
    try:
        action()
    except (CommandError, RuntimeError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"{command_name}: {error}", file=sys.stderr)
        return 1
    return 0


def snapshot_cli() -> int:
    parser = argparse.ArgumentParser(
        prog="branch-snapshot",
        description="Create an explicit-path snapshot for branch-commit. Reads YAML from stdin.",
        epilog="Fields: paths, commit_message, checks, project_dir, work_branch, check_timeout_seconds.",
    )
    parser.parse_args()

    def run() -> None:
        result = _execute(_tool(BranchSnapshotTool, _request()))
        _print(result, command="branch-snapshot")

    return _main("branch-snapshot", run)


def commit_cli() -> int:
    parser = argparse.ArgumentParser(
        prog="branch-commit",
        description="Commit a branch-snapshot from a temporary worktree. Reads YAML from stdin.",
        epilog="Fields: snapshot_dir, background.",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--snapshot-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()

    def run() -> None:
        if args.worker:
            if not args.snapshot_dir:
                raise CommandError("--snapshot-dir is required for worker mode")
            print(json.dumps(commit_snapshot_worker(args.snapshot_dir), sort_keys=True))
            return
        result = _execute(_tool(BranchCommitTool, _request()))
        _print(result, command="branch-commit", nested="commit_result")

    return _main("branch-commit", run)


def status_cli() -> int:
    parser = argparse.ArgumentParser(
        prog="branch-commit-status",
        description="Read branch-commit status for a snapshot. Reads YAML from stdin without an argument.",
        epilog="Field: snapshot_dir or status_path.",
    )
    parser.add_argument("status_target", nargs="?", help="Snapshot directory or status.yaml path.")
    args = parser.parse_args()

    def run() -> None:
        if args.status_target:
            data = {"snapshot_dir": args.status_target}
        else:
            request = _request()
            target = request.pop("status_path", None)
            if target is not None and "snapshot_dir" not in request:
                request["snapshot_dir"] = target
            data = request
        result = _execute(_tool(BranchCommitStatusTool, data))
        _print(result, command="branch-commit-status")

    return _main("branch-commit-status", run)


def cleanup_cli() -> int:
    parser = argparse.ArgumentParser(
        prog="branch-commit-cleanup",
        description="Clean branch snapshot metadata and temporary worktrees. Reads YAML from stdin.",
        epilog="Fields: snapshot_dir, snapshot_dirs, project_dir, states, older_than_days, dry_run.",
    )
    parser.parse_args()

    def run() -> None:
        result = _execute(_tool(BranchCommitCleanupTool, _request()))
        _print(result, command="branch-commit-cleanup")

    return _main("branch-commit-cleanup", run)


def temporary_worktree_cli() -> int:
    parser = argparse.ArgumentParser(
        prog="branch-temporary-worktree",
        description="Create, publish, or remove one temporary linked Git worktree.",
    )
    parser.add_argument("command", choices=["create", "publish", "drop"])
    args = parser.parse_args()

    def run() -> None:
        request = _request()
        request.pop("command", None)
        tool_type = {
            "create": BranchWorktreeCreateTool,
            "publish": BranchWorktreePublishTool,
            "drop": BranchWorktreeDropTool,
        }[args.command]
        result = _execute(_tool(tool_type, request))
        _print(result, command=f"branch-temporary-worktree {args.command}")

    return _main("branch-temporary-worktree", run)
