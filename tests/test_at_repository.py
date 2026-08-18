import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTIC_TEAM = REPO_ROOT / "agentic-team"
MIGRATE = REPO_ROOT / "scripts" / "migrate-at-workspace.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(AGENTIC_TEAM), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
    )


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_init_and_checkout_create_self_contained_paired_branch(tmp_path: Path) -> None:
    root = tmp_path / "project-at"

    initialized = run("init", str(root))

    assert initialized.returncode == 0, initialized.stderr
    assert git(root / "repo.git", "rev-parse", "--is-bare-repository") == "true"
    assert json.loads((root / ".agentic-team.json").read_text())["format_version"] == 2
    assert not (root / "project").exists()
    assert not (root / "branches" / "main").exists()
    exclude = root / "repo.git" / "info" / "exclude"
    exclude.write_text(
        exclude.read_text(encoding="utf-8")
        + "# BEGIN agentic-team generated files\n/.codex/agents/\n# END agentic-team generated files\n",
        encoding="utf-8",
    )

    checked_out = run("-C", str(root), "checkout", "main")

    assert checked_out.returncode == 0, checked_out.stderr
    code = root / "branches" / "main" / "code"
    state = root / "branches" / "main" / "records"
    assert git(code, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(state, "symbolic-ref", "--short", "HEAD") == "agentic/branch-records/main"
    assert git(root / "project-records", "symbolic-ref", "--short", "HEAD") == "agentic/project-records"
    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        text = (code / name).read_text(encoding="utf-8")
        assert "Unprepared Agentic Team Checkout" in text
        assert "Do not inspect, modify, build, test, or run this project" in text
        assert f"agentic-team -C {root} run main --prepare-client" in text
    assert git(code, "status", "--short", "--untracked-files=all") == ""
    assert "Next, run an agent with:" in checked_out.stdout
    assert "/.codex/agents/" in exclude.read_text(encoding="utf-8")


def test_run_never_creates_a_missing_checkout(tmp_path: Path) -> None:
    root = tmp_path / "project-at"
    assert run("init", str(root)).returncode == 0

    result = run("-C", str(root), "run", "agent/missing", "--main-agent", "general")

    assert result.returncode != 0
    assert "has no paired checkout" in result.stderr
    assert "agentic-team -C" in result.stderr
    assert not (root / "branches" / "agent" / "missing").exists()


def test_checkout_new_branch_inherits_state_through_creation_hook(tmp_path: Path) -> None:
    root = tmp_path / "project-at"
    assert run("init", str(root)).returncode == 0
    assert run("-C", str(root), "checkout", "main").returncode == 0
    code = root / "branches" / "main" / "code"
    state = root / "branches" / "main" / "records"
    (code / "README.md").write_text("# project\n")
    git(code, "add", "README.md")
    git(code, "commit", "-m", "initial code")
    (state / "condensed_report.md").write_text("# Parent finding\n")
    (state / "report_page1.md").write_text("# Parent report\n")
    (state / "TODO.md").write_text("- [ ] parent task\n")
    git(state, "add", "condensed_report.md", "report_page1.md", "TODO.md")
    git(state, "commit", "-m", "parent research state")

    created = run(
        "-C",
        str(root),
        "checkout",
        "-b",
        "agent/child",
        "main",
        "--capabilities",
        "research-coordinator",
    )

    assert created.returncode == 0, created.stderr
    child = root / "branches" / "agent" / "child" / "records"
    assert (child / "context" / "parent" / "condensed_report.md").read_text() == "# Parent finding\n"
    assert (child / "condensed_report.md").read_text().startswith("# Condensed Report: agent/child")
    manifest = (child / "context" / "manifest.yaml").read_text()
    assert "work_branch: main" in manifest
    assert "work_name" not in manifest


def test_clone_rejects_a_local_checkout_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)

    result = run("clone", str(source), str(tmp_path / "project-at"))

    assert result.returncode != 0
    assert "local repository imports are not supported" in result.stderr


def test_legacy_migration_tool_is_standalone_and_non_mutating(tmp_path: Path) -> None:
    project = tmp_path / "project"
    old = tmp_path / "legacy-at"
    new = tmp_path / "new-at"
    subprocess.run(["git", "init", "-b", "main", str(project)], check=True, capture_output=True, text=True)
    git(project, "config", "user.name", "Test User")
    git(project, "config", "user.email", "test@example.com")
    (project / "README.md").write_text("# project\n")
    git(project, "add", "README.md")
    git(project, "commit", "-m", "initial")
    (old / "legacy").mkdir(parents=True)
    (old / "project").symlink_to(project, target_is_directory=True)
    git(project, "worktree", "add", "-b", "agent/test", str(old / "legacy" / "code"), "main")

    migrated = subprocess.run(
        [str(MIGRATE), str(old), str(new)],
        capture_output=True,
        text=True,
    )

    assert migrated.returncode == 0, migrated.stderr
    assert (old / "project").is_symlink()
    assert git(new / "branches" / "agent" / "test" / "code", "branch", "--show-current") == "agent/test"
    assert git(new / "branches" / "agent" / "test" / "records", "branch", "--show-current") == "agentic/branch-records/agent/test"
    assert not (new / "project").exists()


def test_legacy_migration_removes_obsolete_work_branch_prefix(tmp_path: Path) -> None:
    project = tmp_path / "project"
    old = tmp_path / "legacy-at"
    new = tmp_path / "new-at"
    subprocess.run(
        ["git", "init", "-b", "benchmarks", str(project)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(project, "config", "user.name", "Test User")
    git(project, "config", "user.email", "test@example.com")
    (project / "README.md").write_text("# original benchmarks\n")
    git(project, "add", "README.md")
    git(project, "commit", "-m", "original benchmarks")
    (old / "benchmarks").mkdir(parents=True)
    (old / "project").symlink_to(project, target_is_directory=True)
    legacy_code = old / "benchmarks" / "code"
    legacy_state = old / "benchmarks" / "state"
    git(project, "worktree", "add", "-b", "work/benchmarks", str(legacy_code), "benchmarks")
    (legacy_code / "README.md").write_text("# newer AT benchmarks\n")
    git(legacy_code, "add", "README.md")
    git(legacy_code, "commit", "-m", "newer AT work")
    legacy_code_commit = git(legacy_code, "rev-parse", "HEAD")
    git(
        project,
        "worktree",
        "add",
        "--orphan",
        "-b",
        "agentic/work-state/work/benchmarks",
        str(legacy_state),
    )
    (legacy_state / "TODO.md").write_text("- [ ] continue benchmarks\n")
    git(legacy_state, "add", "TODO.md")
    git(legacy_state, "commit", "-m", "legacy benchmark state")

    migrated = subprocess.run(
        [str(MIGRATE), str(old), str(new)],
        capture_output=True,
        text=True,
    )

    assert migrated.returncode == 0, migrated.stderr
    code = new / "branches" / "benchmarks" / "code"
    state = new / "branches" / "benchmarks" / "records"
    assert git(code, "branch", "--show-current") == "benchmarks"
    assert git(code, "rev-parse", "HEAD") == legacy_code_commit
    assert git(state, "branch", "--show-current") == "agentic/branch-records/benchmarks"
    assert (state / "TODO.md").read_text() == "- [ ] continue benchmarks\n"
    assert not (new / "branches" / "work").exists()
    refs = git(new / "repo.git", "for-each-ref", "--format=%(refname:short)", "refs/heads")
    assert "work/benchmarks" not in refs.splitlines()
    assert "agentic/work-state/work/benchmarks" not in refs.splitlines()
