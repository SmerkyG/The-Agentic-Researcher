#!/usr/bin/env python3
"""Migrate one legacy symlink-based AT workspace into repository format v2.

This tool is deliberately standalone and is not part of normal launcher
compatibility. It reads OLD_AT_DIR, creates a separate NEW_AT_DIR, and never
modifies the old workspace or its project checkout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class MigrationError(RuntimeError):
    pass


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise MigrationError(f"{' '.join(command)} failed: {detail}")
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], check=check)


def current_branch(worktree: Path) -> str:
    result = git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        raise MigrationError(f"worktree has no named branch: {worktree}")
    return branch


def require_clean(worktree: Path) -> None:
    result = git(worktree, "status", "--porcelain", "--untracked-files=all")
    if result.stdout.strip():
        details = "\n".join(f"  {line}" for line in result.stdout.rstrip().splitlines())
        raise MigrationError(f"worktree has uncommitted changes: {worktree}\n{details}")


def local_branch_exists(repo: Path, branch: str) -> bool:
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def add_existing_worktree(repo: Path, destination: Path, branch: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise MigrationError(f"destination path already exists: {destination}")
    git(repo, "worktree", "add", str(destination), branch)


def add_orphan_worktree(repo: Path, destination: Path, branch: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--orphan", "-b", branch, str(destination))


def migrated_branch_name(source_branch: str) -> str:
    if source_branch.startswith("work/"):
        branch = source_branch.removeprefix("work/")
        if not branch:
            raise MigrationError("legacy code branch 'work/' has no branch name to migrate")
        return branch
    return source_branch


def discover_legacy_works(
    old_root: Path,
) -> dict[str, tuple[str, Path, Path | None, str | None]]:
    works: dict[str, tuple[str, Path, Path | None, str | None]] = {}
    ignored = {"artifacts", "project-state", ".runtime", "work", "repo.git"}
    for child in sorted(old_root.iterdir()):
        if child.name in ignored or not child.is_dir():
            continue
        code = child / "code"
        if not (code.exists() or code.is_symlink()):
            continue
        resolved_code = code.resolve()
        source_branch = current_branch(resolved_code)
        branch = migrated_branch_name(source_branch)
        if branch in works:
            raise MigrationError(
                f"legacy work directories map to the same migrated branch '{branch}': "
                f"{works[branch][1]} and {code}"
            )
        state = child / "state"
        resolved_state = state.resolve() if state.exists() else None
        state_branch = current_branch(resolved_state) if resolved_state is not None else None
        works[branch] = (source_branch, resolved_code, resolved_state, state_branch)
    if not works:
        raise MigrationError(f"no legacy WORK_NAME/code directories found under {old_root}")
    return works


def migrate_branch_ref(repo: Path, source: str, target: str, *, description: str) -> None:
    if not local_branch_exists(repo, source):
        raise MigrationError(f"{description} branch '{source}' has no committed ref")
    source_commit = git(repo, "rev-parse", f"refs/heads/{source}^{{commit}}").stdout.strip()
    if source != target and local_branch_exists(repo, target):
        target_commit = git(repo, "rev-parse", f"refs/heads/{target}^{{commit}}").stdout.strip()
        if target_commit != source_commit:
            is_ancestor = git(
                repo,
                "merge-base",
                "--is-ancestor",
                target_commit,
                source_commit,
                check=False,
            ).returncode == 0
            if not is_ancestor:
                raise MigrationError(
                    f"cannot translate legacy {description} branch '{source}' to '{target}': "
                    "the existing target has divergent commits"
                )
    git(repo, "update-ref", f"refs/heads/{target}", source_commit)


def migrate(old_root: Path, new_root: Path) -> None:
    old_root = old_root.expanduser().resolve()
    new_root = new_root.expanduser().resolve()
    if (old_root / ".agentic-team.json").exists():
        raise MigrationError(f"source already uses repository format v2: {old_root}")
    project_link = old_root / "project"
    if not (project_link.exists() or project_link.is_symlink()):
        raise MigrationError(f"legacy workspace has no project link: {project_link}")
    project = project_link.resolve()
    if git(project, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise MigrationError(f"legacy project link is not a Git checkout: {project}")
    if new_root == old_root or old_root in new_root.parents:
        raise MigrationError("NEW_AT_DIR must be separate from and outside OLD_AT_DIR")
    if new_root.exists() and any(new_root.iterdir()):
        raise MigrationError(f"destination is not empty: {new_root}")

    guards = list((old_root / ".runtime" / "branch-guards").glob("*/*.guard"))
    if guards:
        raise MigrationError(
            "legacy workspace has branch guard files; stop all AT sessions and clear stale guards before migration"
        )

    works = discover_legacy_works(old_root)
    persistent_worktrees = {project}
    project_records = old_root / "project-state"
    if project_records.exists():
        persistent_worktrees.add(project_records.resolve())
    for _, code, state, _ in works.values():
        persistent_worktrees.add(code)
        if state is not None:
            persistent_worktrees.add(state)
    for worktree in sorted(persistent_worktrees):
        require_clean(worktree)

    new_root.mkdir(parents=True, exist_ok=True)
    repo = new_root / "repo.git"
    run(["git", "clone", "--bare", "--no-local", str(project), str(repo)])

    upstream = git(project, "remote", "get-url", "origin", check=False).stdout.strip() or None
    if upstream:
        git(repo, "remote", "set-url", "origin", upstream)
        git(repo, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    else:
        git(repo, "remote", "remove", "origin", check=False)

    (new_root / "branches").mkdir()
    (new_root / ".runtime").mkdir()
    (new_root / "artifacts" / "project").mkdir(parents=True)
    (new_root / ".agentic-team.json").write_text(
        json.dumps(
            {"format_version": 2, "repository": "repo.git", "upstream": upstream},
            indent=2,
        )
        + "\n"
    )

    project_records_branch = "agentic/project-records"
    legacy_project_branch = (
        current_branch(project_records.resolve())
        if project_records.exists()
        else "agentic/project-state"
    )
    if local_branch_exists(repo, legacy_project_branch):
        migrate_branch_ref(
            repo,
            legacy_project_branch,
            project_records_branch,
            description="project records",
        )
        add_existing_worktree(repo, new_root / "project-records", project_records_branch)
    else:
        add_orphan_worktree(repo, new_root / "project-records", project_records_branch)

    obsolete_refs: set[str] = set()
    retained_refs: set[str] = set()
    for branch, (source_branch, _, _, source_state_branch) in sorted(works.items()):
        migrate_branch_ref(repo, source_branch, branch, description="code")
        retained_refs.add(branch)
        if source_branch != branch:
            obsolete_refs.add(source_branch)
        base = new_root / "branches" / Path(branch)
        add_existing_worktree(repo, base / "code", branch)
        twin = f"agentic/branch-records/{branch}"
        retained_refs.add(twin)
        conventional_source_twin = f"agentic/work-state/{source_branch}"
        source_twin = source_state_branch or (
            conventional_source_twin if local_branch_exists(repo, conventional_source_twin) else None
        )
        if source_twin is not None:
            migrate_branch_ref(repo, source_twin, twin, description="branch records")
            if source_twin != twin:
                obsolete_refs.add(source_twin)
            add_existing_worktree(repo, base / "records", twin)
        else:
            add_orphan_worktree(repo, base / "records", twin)

    if legacy_project_branch != project_records_branch:
        obsolete_refs.add(legacy_project_branch)

    for branch in sorted(obsolete_refs - retained_refs):
        git(repo, "update-ref", "-d", f"refs/heads/{branch}")

    old_artifacts = old_root / "artifacts" / "project"
    if old_artifacts.is_dir():
        shutil.copytree(
            old_artifacts,
            new_root / "artifacts" / "project",
            dirs_exist_ok=True,
            symlinks=True,
        )

    print(f"Migrated legacy AT workspace: {old_root}")
    print(f"New Agentic Team repository: {new_root}")
    print(f"Bare repository: {repo}")
    translated = [
        (source_branch, branch)
        for branch, (source_branch, _, _, _) in sorted(works.items())
        if source_branch != branch
    ]
    if translated:
        print("")
        print("Translated legacy branches:")
        for source_branch, branch in translated:
            print(f"  {source_branch} -> {branch}")
    print("")
    print("The old workspace was not modified.")
    print("Client contexts and runtime files were intentionally not copied.")
    print("Re-run 'agentic-team ... run BRANCH --prepare-client' for external clients.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_at_dir", help="Legacy AT workspace containing project and WORK_NAME/code paths.")
    parser.add_argument("new_at_dir", help="Empty destination for repository format v2.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        migrate(Path(args.old_at_dir), Path(args.new_at_dir))
    except MigrationError as error:
        print(f"migrate-at-workspace: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
