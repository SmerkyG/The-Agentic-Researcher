"""Package-native lifecycle hooks for research work-state creation."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import yaml


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _work_name(branch: str) -> str:
    return branch.rstrip("/").rsplit("/", 1)[-1] or "parent"


def _report_page_key(name: str) -> tuple[int, str]:
    suffix = Path(name).stem.removeprefix("report_page")
    try:
        return int(suffix), name
    except ValueError:
        return 10**9, name


def _selected_files(repo: Path) -> list[str]:
    if not _git(repo, "rev-parse", "--verify", "HEAD"):
        return []
    tracked = _git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    names = [
        name
        for name in tracked
        if name in {"condensed_report.md", "TODO.md"}
        or (name.startswith("report_page") and name.endswith(".md"))
        or name.startswith("images/")
    ]
    preferred = [name for name in ("condensed_report.md",) if name in names]
    preferred.extend(
        sorted(
            (name for name in names if name.startswith("report_page") and name.endswith(".md")),
            key=_report_page_key,
        )
    )
    preferred.extend(name for name in ("TODO.md",) if name in names)
    preferred.extend(name for name in names if name not in preferred)
    return preferred


def _read_references(parent_state: Path) -> list[dict[str, object]]:
    path = parent_state / "context" / "manifest.yaml"
    if not path.exists():
        return []
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict) or not isinstance(value.get("references"), list):
        return []
    references: list[dict[str, object]] = []
    for entry in value["references"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("files", []), list):
            continue
        references.append(
            {
                "work_name": str(entry.get("work_name") or "unknown"),
                "work_branch": str(entry.get("work_branch") or ""),
                "state_branch": str(entry.get("state_branch") or ""),
                "state_commit": str(entry.get("state_commit") or ""),
                "files": [str(item) for item in entry.get("files", [])],
            }
        )
    return references


def _merge_references(references: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[tuple[str, str, str], dict[str, object]] = {}
    for entry in references:
        key = (
            str(entry.get("work_branch") or ""),
            str(entry.get("state_branch") or ""),
            str(entry.get("state_commit") or ""),
        )
        if not any(key):
            continue
        target = merged.setdefault(
            key,
            {
                "work_name": str(entry.get("work_name") or "unknown"),
                "work_branch": key[0],
                "state_branch": key[1],
                "state_commit": key[2],
                "files": [],
            },
        )
        files = target["files"]
        assert isinstance(files, list)
        for file_name in entry.get("files", []):
            value = str(file_name)
            if value and value not in files:
                files.append(value)
    return list(merged.values())


def _copy_if_missing(source: Path, target: Path) -> None:
    if source.is_file() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def create_work() -> None:
    parent_state = Path(_required("AT_CREATE_SOURCE_STATE_DIR"))
    new_state = Path(_required("AT_CREATE_NEW_STATE_DIR"))
    work_name = _required("AT_CREATE_WORK_NAME")
    parent_branch = _required("AT_CREATE_SOURCE_BRANCH")
    new_branch = _required("AT_CREATE_NEW_BRANCH")

    parent_context = new_state / "context" / "parent"
    parent_context.mkdir(parents=True, exist_ok=True)
    (new_state / "images").mkdir(parents=True, exist_ok=True)
    _copy_if_missing(parent_state / "condensed_report.md", parent_context / "condensed_report.md")
    reports = sorted(parent_state.glob("report_page*.md"), key=lambda path: _report_page_key(path.name))
    if reports:
        _copy_if_missing(reports[-1], parent_context / reports[-1].name)
    _copy_if_missing(parent_state / "TODO.md", parent_context / "TODO.md")

    state_branch = _git(parent_state, "branch", "--show-current")
    state_commit = _git(parent_state, "rev-parse", "--verify", "HEAD")
    references = _read_references(parent_state)
    parent_files = _selected_files(parent_state)
    if state_commit and parent_files:
        references.append(
            {
                "work_name": _work_name(parent_branch),
                "work_branch": parent_branch,
                "state_branch": state_branch,
                "state_commit": state_commit,
                "files": parent_files,
            }
        )
    manifest = {
        "version": 1,
        "created_from": {
            "work_name": _work_name(parent_branch),
            "work_branch": parent_branch,
            "state_branch": state_branch,
            "state_commit": state_commit,
        },
        "references": _merge_references(references),
    }
    context_dir = new_state / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    readme = [
        "# Inherited Context",
        "",
        f"This work was created from `{parent_branch}` into `{new_branch}`.",
        "",
        "The immediate parent's lightweight records are copied locally when present:",
        "",
        "- `context/parent/condensed_report.md`",
        "- the latest `context/parent/report_pageN.md`",
        "- `context/parent/TODO.md`",
        "",
        "All inherited condensed-report/report-page/TODO/image references are flattened in `context/manifest.yaml`.",
        "Read a referenced file with:",
        "",
        "```bash",
        'git -C "$AR_WORK_STATE_DIR" show <state_commit>:<path>',
        "```",
    ]
    if manifest["references"]:
        readme.extend(["", "## References", ""])
        for entry in manifest["references"]:
            readme.append(
                f"- `{entry['work_name']}` (`{entry['work_branch']}`) "
                f"state `{entry['state_branch']}` at `{entry['state_commit']}`"
            )
            for file_name in entry["files"]:
                readme.append(f"  - `{file_name}`")
    (context_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    condensed_report = new_state / "condensed_report.md"
    if not condensed_report.exists():
        condensed_report.write_text(
            f"# Condensed Report: {work_name}\n\n"
            f"Created from `{parent_branch}` into `{new_branch}`.\n\n"
            "Keep this condensed report to about one page. Rewrite it as the work evolves so it "
            "summarizes the current best findings, important negative results, open risks, and "
            "next direction without accumulating a long chronology.\n",
            encoding="utf-8",
        )
    report = new_state / "report_page1.md"
    if not report.exists():
        report.write_text(
            f"# Research Log: {work_name}\n\n"
            f"Created from `{parent_branch}` into `{new_branch}`.\n\n"
            "## Inherited Context\n\nRead `context/README.md` first. The immediate parent's "
            "`condensed_report.md`, latest numbered report page, and `TODO.md` are copied under "
            "`context/parent/` when present; larger artifacts such as older report pages and images "
            "are referenced by commit in `context/manifest.yaml`.\n\n"
            f"Use numbered report pages for new analysis, derivations, figures, verification notes, "
            f"and selected result tables for `{new_branch}`. The research finalizer starts the next "
            "numbered page when the latest page already has 300 lines.\n",
            encoding="utf-8",
        )
    todo = new_state / "TODO.md"
    if not todo.exists():
        todo.write_text(
            "# TODO\n\n- [ ] Read inherited context from `context/README.md`\n"
            f"- [ ] Define the first experiment for `{work_name}`\n",
            encoding="utf-8",
        )
    print(f"Referenced inherited context in {context_dir / 'manifest.yaml'}")
