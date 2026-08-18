import json
import os
import shutil
import stat
import subprocess
import sys
import time
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import yaml
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTIC_NOTES_INTERNAL = REPO_ROOT / "capabilities" / "agentic-notes" / "lib" / "agentic-notes-internal"
AGENTIC_NOTES_STATE = REPO_ROOT / "capabilities" / "agentic-notes" / "package" / "agentic_notes" / "state.py"
AGENTIC_NOTES = REPO_ROOT / "capabilities" / "agentic-notes" / "bin" / "agentic-notes"
EXPERIMENT_LOG = REPO_ROOT / "capabilities" / "experiment-log" / "bin" / "experiment-log"
FINALIZATION = REPO_ROOT / "capabilities" / "research-coordinator" / "bin" / "research-coordinator-finalization"
BRANCH_SNAPSHOT = REPO_ROOT / "capabilities" / "branch" / "bin" / "branch-snapshot"
TEMPORARY_WORKTREE = REPO_ROOT / "capabilities" / "branch" / "bin" / "branch-temporary-worktree"
AGENTIC_TEAM = REPO_ROOT / "agentic-team"
AGENTIC_WORKSPACE = REPO_ROOT / "scripts" / "bin" / "agentic-workspace"
IMPERATIVE_PACKAGE = REPO_ROOT / "capabilities" / "imperative-workflows" / "package"
RESEARCH_PACKAGE = REPO_ROOT / "capabilities" / "research-coordinator" / "package"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "package"))
sys.path.insert(0, str(IMPERATIVE_PACKAGE))
sys.path.insert(0, str(RESEARCH_PACKAGE))

from agentic_workflows.execution import OperationExecutor  # noqa: E402
from agentic_workflows.research.research_state import (  # noqa: E402
    ResearchStateInitializeTool,
)
from agentic_workflows.research.report import ReportAppendResult, ReportAppendTool  # noqa: E402


def test_builtin_subagents_have_one_contract_template() -> None:
    for agent_path in sorted((REPO_ROOT / "agents").glob("*.md")):
        text = agent_path.read_text(encoding="utf-8")
        if "kind: subagent" not in text:
            continue
        if "workflow:" in text:
            assert "```python agentic-workflow" not in text, agent_path.name
            continue
        assert "## Subagent Contract" in text, agent_path.name
        contract = text.split("## Subagent Contract", 1)[1]
        if "\n## " in contract:
            contract = contract.split("\n## ", 1)[0]
        assert "Use when:" in contract, agent_path.name
        assert "Request template:" in contract, agent_path.name
        assert contract.count("```yaml") == 1, agent_path.name
        assert "\nkind:" not in contract, agent_path.name
        assert "Request kind:" not in contract, agent_path.name


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd or REPO_ROOT,
        env=env,
        input=input,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(command)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo, check=check)


def append_report(
    branch_records_dir: Path | str,
    content: str,
    *,
    max_lines: int = 300,
) -> ReportAppendResult:
    with OperationExecutor() as executor:
        return executor.run(
            ReportAppendTool(
                branch_records_dir=str(branch_records_dir),
                content=content,
                max_lines=max_lines,
            )
        )


def test_research_report_append_uses_latest_numbered_page(tmp_path: Path) -> None:
    state = tmp_path / "work-state"
    state.mkdir()

    first = append_report(state, "## First result\n\nEvidence.")
    assert first.page_number == 1
    assert first.created is True
    assert (state / "report_page1.md").read_text(encoding="utf-8") == "## First result\n\nEvidence.\n"

    second = append_report(state, "## Second result")
    assert second.page_number == 1
    assert second.created is False
    assert (state / "report_page1.md").read_text(encoding="utf-8").endswith("\n\n## Second result\n")


def test_research_report_append_starts_page_after_line_limit(tmp_path: Path) -> None:
    state = tmp_path / "work-state"
    state.mkdir()
    (state / "report_page1.md").write_text("\n".join(f"line {index}" for index in range(300)) + "\n", encoding="utf-8")

    response = append_report(state, "## New page")

    assert response.page_number == 2
    assert response.created is True
    assert (state / "report_page2.md").read_text(encoding="utf-8") == "## New page\n"


def test_temporary_worktree_publishes_without_overwriting_newer_visible_edits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run(["git", "init", str(repo)])
    configure_git(repo)
    (repo / "report.md").write_text("# Report\n", encoding="utf-8")
    (repo / "TODO.md").write_text("- [ ] baseline\n", encoding="utf-8")
    git(repo, "add", "report.md", "TODO.md")
    git(repo, "commit", "-m", "initial")
    private = tmp_path / "private"

    created = json.loads(
        run(
            [str(TEMPORARY_WORKTREE), "create"],
            input=yaml.safe_dump({"source_worktree": str(repo), "worktree": str(private)}),
        ).stdout
    )
    (private / "report.md").write_text("# Report\n\nResult.\n", encoding="utf-8")
    (private / "TODO.md").write_text("- [x] baseline\n", encoding="utf-8")
    (repo / "TODO.md").write_text("- [ ] newer visible work\n", encoding="utf-8")

    published = json.loads(
        run(
            [str(TEMPORARY_WORKTREE), "publish"],
            input=yaml.safe_dump({**created, "message": "record result"}),
        ).stdout
    )
    assert published["changed"] is True
    assert "Result." in (repo / "report.md").read_text(encoding="utf-8")
    assert git(repo, "show", "HEAD:TODO.md").stdout == "- [x] baseline\n"
    assert (repo / "TODO.md").read_text(encoding="utf-8") == "- [ ] newer visible work\n"

    run(
        [str(TEMPORARY_WORKTREE), "drop"],
        input=yaml.safe_dump({"source_worktree": str(repo), "worktree": str(private)}),
    )
    assert not private.exists()


def test_temporary_worktree_rejects_a_moved_target_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run(["git", "init", str(repo)])
    configure_git(repo)
    (repo / "value.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "value.txt")
    git(repo, "commit", "-m", "initial")
    private = tmp_path / "private"
    created = json.loads(
        run(
            [str(TEMPORARY_WORKTREE), "create"],
            input=yaml.safe_dump({"source_worktree": str(repo), "worktree": str(private)}),
        ).stdout
    )
    (private / "value.txt").write_text("private\n", encoding="utf-8")
    (repo / "other.txt").write_text("other\n", encoding="utf-8")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-m", "advance branch")

    result = run(
        [str(TEMPORARY_WORKTREE), "publish"],
        input=yaml.safe_dump({**created, "message": "private change"}),
        check=False,
    )
    assert result.returncode != 0
    assert "target branch moved" in result.stderr
    assert (private / "value.txt").read_text(encoding="utf-8") == "private\n"


def test_temporary_worktree_drop_refuses_unregistered_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run(["git", "init", str(repo)])
    configure_git(repo)
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    ordinary_directory = tmp_path / "ordinary"
    ordinary_directory.mkdir()
    (ordinary_directory / "keep.txt").write_text("keep\n", encoding="utf-8")

    result = run(
        [str(TEMPORARY_WORKTREE), "drop"],
        input=yaml.safe_dump({"source_worktree": str(repo), "worktree": str(ordinary_directory)}),
        check=False,
    )
    assert result.returncode != 0
    assert "refusing to remove unregistered worktree path" in result.stderr
    assert (ordinary_directory / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_finalization_stages_assets_and_publishes_state_for_committed_code(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = tmp_path / "work-state"
    run(["git", "init", str(project)])
    run(["git", "init", str(state)])
    configure_git(project)
    configure_git(state)
    (project / "result.py").write_text("value = 0\n", encoding="utf-8")
    (state / "report_page1.md").write_text("# Research Log\n", encoding="utf-8")
    (state / "condensed_report.md").write_text("# Condensed\n", encoding="utf-8")
    (state / "TODO.md").write_text("- [ ] baseline\n", encoding="utf-8")
    git(project, "add", "result.py")
    git(project, "commit", "-m", "initial code")
    git(state, "add", "report_page1.md", "condensed_report.md", "TODO.md")
    git(state, "commit", "-m", "initial state")
    code_branch = git(project, "branch", "--show-current").stdout.strip()

    (project / "result.py").write_text("value = 1\n", encoding="utf-8")
    git(project, "add", "result.py")
    git(project, "commit", "-m", "research: record result")
    code_commit = git(project, "rev-parse", "HEAD").stdout.strip()
    image = state / "images" / "result.png"
    image.parent.mkdir()
    image.write_bytes(b"png")
    env = {
        **os.environ,
        "AR_PROJECT_DIR": str(project),
        "AR_BRANCH_RECORDS_DIR": str(state),
        "AR_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "AR_WORK_BRANCH": code_branch,
    }
    captured = json.loads(
        run(
            [str(FINALIZATION), "capture"],
            cwd=project,
            env=env,
            input=yaml.safe_dump({"report_assets": ["images/result.png"]}),
        ).stdout
    )
    root = Path(captured["root"])
    assert captured["code_commit"] == code_commit
    assert not (root / "records").exists()
    (project / "result.py").write_text("value = 2\n", encoding="utf-8")
    ready = json.loads(
        run(
            [str(FINALIZATION), "ready"],
            env=env,
            input=yaml.safe_dump({"root": str(root)}),
        ).stdout
    )
    assert ready["state"] == "active"
    private_state = Path(ready["records_dir"])
    assert (private_state / "images" / "result.png").read_bytes() == b"png"
    append_report(private_state, "## Completed result\n\nEvidence.")
    (private_state / "condensed_report.md").write_text("# Condensed\n\nCurrent result.\n", encoding="utf-8")
    (private_state / "TODO.md").write_text("- [x] baseline\n", encoding="utf-8")
    (state / "TODO.md").write_text("- [ ] newer live work\n", encoding="utf-8")

    committed = json.loads(
        run(
            [str(FINALIZATION), "commit"],
            env=env,
            input=yaml.safe_dump({"root": str(root)}),
        ).stdout
    )
    assert committed["state"] == "committed"
    assert committed["records_changed"] is True
    assert git(project, "show", "HEAD:result.py").stdout == "value = 1\n"
    assert (project / "result.py").read_text(encoding="utf-8") == "value = 2\n"
    assert "Completed result" in (state / "report_page1.md").read_text(encoding="utf-8")
    assert (state / "condensed_report.md").read_text(encoding="utf-8").endswith("Current result.\n")
    assert git(state, "show", "HEAD:TODO.md").stdout == "- [x] baseline\n"
    assert (state / "TODO.md").read_text(encoding="utf-8") == "- [ ] newer live work\n"
    assert git(state, "status", "--short").stdout == " M TODO.md\n"

    finished = json.loads(
        run(
            [str(FINALIZATION), "finish"],
            env=env,
            input=yaml.safe_dump({"root": str(root), "state": "complete"}),
        ).stdout
    )
    assert finished["state"] == "complete"
    assert not private_state.exists()
    assert not (root / "assets").exists()
    status = json.loads(
        run(
            [str(FINALIZATION), "status"],
            env=env,
            input=yaml.safe_dump({"root": str(root)}),
        ).stdout
    )
    assert status["state"] == "complete"

    repeated = json.loads(
        run(
            [str(FINALIZATION), "finish"],
            env=env,
            input=yaml.safe_dump({"root": str(root), "state": "complete"}),
        ).stdout
    )
    assert repeated["state"] == "complete"


def test_finalization_reconcile_completes_logged_committed_ticket(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = tmp_path / "work-state"
    run(["git", "init", str(project)])
    run(["git", "init", str(state)])
    configure_git(project)
    configure_git(state)
    (project / "result.py").write_text("value = 1\n", encoding="utf-8")
    (state / "report_page1.md").write_text("# Research Log\n", encoding="utf-8")
    git(project, "add", "result.py")
    git(project, "commit", "-m", "initial code")
    git(state, "add", "report_page1.md")
    git(state, "commit", "-m", "initial state")
    code_branch = git(project, "branch", "--show-current").stdout.strip()
    code_commit = git(project, "rev-parse", "HEAD").stdout.strip()
    env = {
        **os.environ,
        "AR_PROJECT_DIR": str(project),
        "AR_BRANCH_RECORDS_DIR": str(state),
        "AR_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "AR_WORK_BRANCH": code_branch,
    }

    captured = json.loads(
        run([str(FINALIZATION), "capture"], env=env, input="{}\n").stdout
    )
    root = Path(captured["root"])
    ready = json.loads(
        run(
            [str(FINALIZATION), "ready"],
            env=env,
            input=yaml.safe_dump({"root": str(root)}),
        ).stdout
    )
    append_report(ready["records_dir"], "## Result")
    run(
        [str(FINALIZATION), "commit"],
        env=env,
        input=yaml.safe_dump({"root": str(root)}),
    )

    experiment = state / "experiment-log" / "experiments" / "E0001_result.yaml"
    experiment.parent.mkdir(parents=True)
    experiment.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "E0001_result",
                "work_branch": code_branch,
                "created_at": "9999-01-01T00:00:00Z",
                "code": {"branch": code_branch, "commit": code_commit},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    git(state, "add", "experiment-log/experiments/E0001_result.yaml")
    git(state, "commit", "-m", "experiment: log result")

    reconciled = json.loads(
        run(
            [str(FINALIZATION), "reconcile"],
            env=env,
            input=yaml.safe_dump(
                {"project_dir": str(project), "work_branch": code_branch}
            ),
        ).stdout
    )
    assert [ticket["id"] for ticket in reconciled["recovered"]] == [captured["id"]]
    assert reconciled["unresolved"] == []
    assert not Path(ready["records_dir"]).exists()
    status = json.loads(
        run(
            [str(FINALIZATION), "status"],
            env=env,
            input=yaml.safe_dump({"root": str(root)}),
        ).stdout
    )
    assert status["state"] == "complete"


def test_later_finalization_refreshes_after_earlier_completion(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = tmp_path / "work-state"
    run(["git", "init", str(project)])
    run(["git", "init", str(state)])
    configure_git(project)
    configure_git(state)
    (project / "README.md").write_text("project\n", encoding="utf-8")
    (state / "report_page1.md").write_text("# Research Log\n", encoding="utf-8")
    git(project, "add", "README.md")
    git(project, "commit", "-m", "initial code")
    git(state, "add", "report_page1.md")
    git(state, "commit", "-m", "initial state")
    code_branch = git(project, "branch", "--show-current").stdout.strip()
    env = {
        **os.environ,
        "AR_PROJECT_DIR": str(project),
        "AR_BRANCH_RECORDS_DIR": str(state),
        "AR_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "AR_WORK_BRANCH": code_branch,
    }

    first = json.loads(run([str(FINALIZATION), "capture"], env=env, input="{}\n").stdout)
    time.sleep(0.001)
    second = json.loads(run([str(FINALIZATION), "capture"], env=env, input="{}\n").stdout)
    first_ready = json.loads(
        run([str(FINALIZATION), "ready"], env=env, input=yaml.safe_dump({"root": first["root"]})).stdout
    )
    append_report(first_ready["records_dir"], "## First")
    run([str(FINALIZATION), "commit"], env=env, input=yaml.safe_dump({"root": first["root"]}))
    run(
        [str(FINALIZATION), "finish"],
        env=env,
        input=yaml.safe_dump({"root": first["root"], "state": "complete"}),
    )

    second_ready = json.loads(
        run([str(FINALIZATION), "ready"], env=env, input=yaml.safe_dump({"root": second["root"]})).stdout
    )
    second_report = Path(second_ready["records_dir"]) / "report_page1.md"
    assert "## First" in second_report.read_text(encoding="utf-8")


def test_initialize_research_state_creates_numbered_records(tmp_path: Path) -> None:
    state = tmp_path / "work-state"
    run(["git", "init", str(state)])
    configure_git(state)
    (state / ".seed").write_text("seed\n", encoding="utf-8")
    git(state, "add", ".seed")
    git(state, "commit", "-m", "initial state")
    with OperationExecutor() as executor:
        response = executor.run(
            ResearchStateInitializeTool(
                plan="# Research Plan\n\nMeasure the baseline.",
                branch_records_dir=str(state),
                work_branch="research-main",
                agent_name="research-coordinator",
            )
        )

    assert response.created == [
        "agent-notes/research-coordinator/always-injected.md",
        "condensed_report.md",
        "report_page1.md",
        "TODO.md",
    ]
    assert (state / "report_page1.md").exists()
    assert not (state / "report.md").exists()
    assert (state / "condensed_report.md").exists()
    assert (state / "TODO.md").read_text(encoding="utf-8").endswith(
        "- [ ] Run baseline evaluation\n"
    )
    assert git(state, "status", "--short").stdout == ""


def configure_git(repo: Path) -> None:
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")


def write_pre_push_hook(repo: Path, content: str) -> Path:
    hook_dir = repo / ".git-hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    git(repo, "config", "extensions.worktreeConfig", "true")
    git(repo, "config", "--worktree", "core.hooksPath", str(hook_dir))
    hook = hook_dir / "pre-push"
    hook.write_text(content, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return hook


def init_bare_remote(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    bare = tmp_path / f"{name}.git"
    work = tmp_path / f"{name}-seed"
    run(["git", "init", "--bare", str(bare)])
    run(["git", "clone", str(bare), str(work)])
    configure_git(work)
    git(work, "checkout", "-b", "main")
    for rel, content in files.items():
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(work, "add", *files.keys())
    git(work, "commit", "-m", "seed")
    git(work, "push", "-u", "origin", "main")
    run(["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"])
    return bare


def clone_project(tmp_path: Path, remote: Path, name: str = "project") -> Path:
    project = tmp_path / name
    run(["git", "clone", str(remote), str(project)])
    configure_git(project)
    git(project, "checkout", "-b", "kernel-search")
    return project


def base_env(tmp_path: Path, org_remote: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = (
        f"{REPO_ROOT / 'scripts' / 'bin'}:"
        f"{REPO_ROOT / 'capabilities' / 'agentic-notes' / 'bin'}:"
        f"{REPO_ROOT / 'capabilities' / 'experiment-log' / 'bin'}:"
        f"{env['PATH']}"
    )
    env.update(
        {
            "AR_STATE_ROOT": str(tmp_path / "state"),
            "AR_WORKSPACE_ROOT": str(tmp_path / "project-at"),
            "AR_MAIN_AGENT": "research-coordinator",
            "AR_WORK_BRANCH": "kernel-search",
            "AR_USER_ID": "alice",
            "AR_PROJECT_RECORDS_BRANCH": "agentic/project-records",
            "AR_CAPABILITIES": "agentic-notes,experiment-log",
            "AR_NOTES_GIT_NAME": "Agentic Test",
            "AR_NOTES_GIT_EMAIL": "agentic-test@example.com",
            "AR_NOTES_AUTO_REFRESH": "false",
            "UV_CACHE_DIR": str(REPO_ROOT / ".pytest_cache" / "uv" / "cache"),
            "UV_PYTHON_INSTALL_DIR": str(REPO_ROOT / ".pytest_cache" / "uv" / "python"),
            "UV_TOOL_DIR": str(REPO_ROOT / ".pytest_cache" / "uv" / "tools"),
        }
    )
    if org_remote is not None:
        env["AR_ORG_NOTES_REPO"] = str(org_remote)
    return env


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def make_request(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / f"request-{len(list(tmp_path.glob('request-*.yaml')))}.yaml"
    write_yaml(path, data)
    return path


def state_checkout(env: dict[str, str], workspace_name: str = "project") -> Path:
    return workspace_root(env, workspace_name) / "project-records"


def workspace_root(env: dict[str, str], workspace_name: str = "project") -> Path:
    configured = env.get("AR_WORKSPACE_ROOT")
    if configured:
        return Path(configured)
    return Path(env["AR_STATE_ROOT"]).parent / f"{workspace_name}-at"


def work_state_checkout(
    env: dict[str, str],
    workspace_name: str = "project",
    work_branch: str = "kernel-search",
) -> Path:
    return workspace_root(env, workspace_name) / "branches" / Path(work_branch) / "records"


def work_log(env: dict[str, str], workspace_name: str = "project", work_branch: str = "kernel-search") -> Path:
    return work_state_checkout(env, workspace_name, work_branch) / "experiment-log"


def branch_records_dir(env: dict[str, str], workspace_name: str = "project", work_branch: str = "kernel-search") -> Path:
    return work_state_checkout(env, workspace_name, work_branch)


def at_launch_args(
    project: Path,
    env: dict[str, str],
    source_ref: str = "kernel-search",
) -> list[str]:
    root = workspace_root(env)
    repo = root / "repo.git"
    if not repo.exists():
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--bare", "--no-local", str(project), str(repo)],
            check=True,
            capture_output=True,
            text=True,
        )
        (root / "branches").mkdir(exist_ok=True)
        (root / "artifacts" / "project").mkdir(parents=True, exist_ok=True)
        (root / ".runtime").mkdir(exist_ok=True)
        (root / ".agentic-team.json").write_text(
            '{"format_version": 2, "repository": "repo.git", "upstream": null}\n'
        )
    code = root / "branches" / Path(source_ref) / "code"
    if not code.exists():
        subprocess.run(
            [str(REPO_ROOT / "scripts/bin/agentic-workspace"), "-C", str(root), "checkout", source_ref],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    return ["run", str(code)]


def assert_linked_worktree(path: Path) -> None:
    assert (path / ".git").is_file(), f"{path} should be a linked Git worktree"


def local_experiment_id(ref: str) -> str:
    return ref.split("::", 1)[1] if "::" in ref else ref


def operation_result(output: str, field: str) -> str:
    return str(json.loads(output)[field])


def org_checkout(env: dict[str, str]) -> Path:
    return Path(env["AR_STATE_ROOT"]) / "repos" / "org-agentic-notes"


def seed_org_remote(tmp_path: Path) -> Path:
    return init_bare_remote(
        tmp_path,
        "org-notes",
        {
            "agent-notes/all-agents/always-injected.md": "# Org Notes\n\nOrg body.\n",
            "agent-notes/all-agents/triton.md": "# Triton\n\nTopic hints: triton, launch checks\n\nUse Triton-specific launch checks.\n",
            "agent-notes/all-agents/pytorch.md": "# PyTorch\n\nTopic hints: pytorch, launch checks\n\nUse PyTorch-specific launch checks.\n",
            "agent-notes/gpu-kernel-engineer/always-injected.md": "# Agent Type Notes\n\nAgent Type body.\n",
            "agent-notes/gpu-kernel-engineer/kernel-optimization.md": "# Kernel Optimization\n\nTopic hints: occupancy, kernels\n\nUse occupancy checks.\n",
        },
    )


def seed_project_remote(tmp_path: Path) -> Path:
    return init_bare_remote(tmp_path, "project", {"README.md": "# Project\n"})


def test_render_section_injects_always_injected_notes_and_lists_on_demand_notes(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)
    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "list-notes",
            "--scope",
            "work",
            "--project-dir",
            str(project),
            "--agent-type",
            "all-agents",
            "--work-branch",
            "kernel-search",
        ],
        env=env,
    )
    state = state_checkout(env)
    assert_linked_worktree(state)
    (state / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Project Notes\n\nProject body.\n", encoding="utf-8"
    )
    (state / "agent-notes" / "all-agents" / "evaluation.md").write_text(
        "# Evaluation\n\nTopic hints: eval command, fixed split\n\nUse the fixed evaluation command.\n", encoding="utf-8"
    )
    project_agent = state / "agent-notes" / "gpu-kernel-engineer"
    project_agent.mkdir(parents=True, exist_ok=True)
    (project_agent / "always-injected.md").write_text(
        "# Project GPU Agent Type Notes\n\nProject agent type body.\n",
        encoding="utf-8",
    )
    (project_agent / "benchmarking.md").write_text(
        "# Project Benchmarking\n\nTopic hints: benchmark scripts\n\nUse project benchmark scripts.\n", encoding="utf-8"
    )
    git(
        state,
        "add",
        "agent-notes/all-agents/always-injected.md",
        "agent-notes/all-agents/evaluation.md",
        "agent-notes/gpu-kernel-engineer/always-injected.md",
        "agent-notes/gpu-kernel-engineer/benchmarking.md",
    )
    git(state, "commit", "-m", "seed project state")
    git(state, "push")

    text = run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "render-section",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
        ],
        env=env,
    ).stdout

    assert "Org body." in text
    assert "Agent Type body." in text
    assert "Project body." in text
    assert "Project agent type body." in text
    assert "Source:" not in text
    assert "Directory:" not in text
    assert "(none)" not in text
    assert "### Available On-Demand Note Topics" in text
    assert "--agent-type gpu-kernel-engineer NOTE_TOPIC" in text
    assert "- `triton` - triton, launch checks" in text
    assert "- `pytorch` - pytorch, launch checks" in text
    assert "- `kernel-optimization` - occupancy, kernels" in text
    assert "- `evaluation` - eval command, fixed split" in text
    assert "- `benchmarking` - benchmark scripts" in text
    assert "- `always-injected`" not in text

    rendered_note = run(
        [
            str(AGENTIC_NOTES),
            "read-note",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
            "benchmarking",
        ],
        env=env,
    ).stdout
    assert "# Agentic Note: benchmarking" in rendered_note
    assert "## Project: gpu-kernel-engineer" in rendered_note
    assert "Use project benchmark scripts." in rendered_note
    assert "# Project Benchmarking" not in rendered_note
    assert "Source:" not in rendered_note


def test_render_section_skips_title_only_placeholder_notes(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)
    text = run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "render-section",
            "--project-dir",
            str(project),
            "--agent-type",
            "research-coordinator",
        ],
        env=env,
    ).stdout

    assert "### Always-Injected Notes" not in text
    assert "Project All Agents Notes" not in text
    assert "### Available On-Demand Note Topics" not in text


def test_render_sections_batches_multiple_agent_note_sections(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)
    output_dir = tmp_path / "rendered-notes"

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "render-sections",
            "--project-dir",
            str(project),
            "--output-dir",
            str(output_dir),
            "--agent-type",
            "gpu-kernel-engineer",
            "--agent-type",
            "research-coordinator",
        ],
        env=env,
    )

    gpu_text = (output_dir / "gpu-kernel-engineer.md").read_text(encoding="utf-8")
    coordinator_text = (output_dir / "research-coordinator.md").read_text(encoding="utf-8")
    assert "Org body." in gpu_text
    assert "Agent Type body." in gpu_text
    assert "#### Organization: gpu-kernel-engineer" in gpu_text
    assert "Org body." in coordinator_text
    assert "Organization: research-coordinator" not in coordinator_text


def test_read_note_combines_all_scoped_note_parts(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)

    org = org_checkout(env)
    configure_git(org)
    (org / "agent-notes" / "gpu-kernel-engineer" / "triton.md").write_text(
        "# Org GPU Triton\n\nOrg agent type body.\n",
        encoding="utf-8",
    )
    git(org, "add", "agent-notes/gpu-kernel-engineer/triton.md")
    git(org, "commit", "-m", "seed org agent triton")

    state = state_checkout(env)
    (state / "agent-notes" / "all-agents" / "triton.md").write_text(
        "# Project Triton\n\nProject all agents body.\n",
        encoding="utf-8",
    )
    project_agent = state / "agent-notes" / "gpu-kernel-engineer"
    project_agent.mkdir(parents=True, exist_ok=True)
    (project_agent / "triton.md").write_text(
        "# Project GPU Triton\n\nProject agent type body.\n",
        encoding="utf-8",
    )
    git(
        state,
        "add",
        "agent-notes/all-agents/triton.md",
        "agent-notes/gpu-kernel-engineer/triton.md",
    )
    git(state, "commit", "-m", "seed project triton")

    result = run(
        [
            str(AGENTIC_NOTES),
            "read-note",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
            "triton",
        ],
        env=env,
    )

    rendered = result.stdout
    expected_order = [
        "## Organization: all agents",
        "Use Triton-specific launch checks.",
        "## Organization: gpu-kernel-engineer",
        "Org agent type body.",
        "## Project: all agents",
        "Project all agents body.",
        "## Project: gpu-kernel-engineer",
        "Project agent type body.",
    ]
    positions = [rendered.index(item) for item in expected_order]
    assert positions == sorted(positions)
    assert "Org agent type body." in rendered
    assert "Project all agents body." in rendered
    assert "Project agent type body." in rendered
    assert "# Triton" not in rendered
    assert "# Org GPU Triton" not in rendered
    assert "# Project Triton" not in rendered
    assert "# Project GPU Triton" not in rendered
    assert "Source:" not in rendered
    assert "Directory:" not in rendered


def test_refresh_loop_pulls_org_notes_while_heartbeat_is_active(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)

    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    heartbeat = heartbeat_dir / "agent.heartbeat"
    heartbeat.touch()
    proc = subprocess.Popen(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "refresh-loop",
            "--project-dir",
            str(project),
            "--heartbeat-dir",
            str(heartbeat_dir),
            "--interval-seconds",
            "1",
            "--stale-seconds",
            "3",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        snapshot = workspace_root(env) / ".runtime" / "agentic-notes" / "steering" / "research-coordinator.snapshot.json"
        deadline = time.time() + 8
        while time.time() < deadline:
            heartbeat.touch()
            if snapshot.exists():
                break
            time.sleep(0.25)
        else:
            stdout, stderr = proc.communicate(timeout=1)
            raise AssertionError(f"refresh loop did not establish steering baseline\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")

        org_update = tmp_path / "org-update"
        run(["git", "clone", str(org_remote), str(org_update)])
        configure_git(org_update)
        (org_update / "agent-notes" / "all-agents" / "always-injected.md").write_text(
            "# Org Notes\n\nPulled by refresh loop.\n",
            encoding="utf-8",
        )
        git(org_update, "add", "agent-notes/all-agents/always-injected.md")
        git(org_update, "commit", "-m", "update org notes")
        git(org_update, "push")

        note_path = org_checkout(env) / "agent-notes" / "all-agents" / "always-injected.md"
        deadline = time.time() + 8
        while time.time() < deadline:
            heartbeat.touch()
            if "Pulled by refresh loop." in note_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.25)
        else:
            stdout, stderr = proc.communicate(timeout=1)
            raise AssertionError(f"refresh loop did not pull org update\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        steering = run(
            [
                str(AGENTIC_NOTES_INTERNAL),
                "steering-message",
                "--project-dir",
                str(project),
                "--agent-type",
                "research-coordinator",
            ],
            env=env,
        )
        assert "Agentic Notes changed" in steering.stdout
        assert "`always-injected`" in steering.stdout
        assert "read-note" in steering.stdout
        drained = run(
            [
                str(AGENTIC_NOTES_INTERNAL),
                "steering-message",
                "--project-dir",
                str(project),
                "--agent-type",
                "research-coordinator",
            ],
            env=env,
        )
        assert drained.stdout == ""
    finally:
        heartbeat.unlink(missing_ok=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)


def test_replace_project_agent_note_updates_shared_state_and_capability_rendering(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    note_file = tmp_path / "research-coordinator-note.md"
    note_file.write_text(
        "# Research Coordinator Project Instructions\n\n"
        "**Goal:** Draft a sparse transformer paper.\n\n"
        "**Primary Metric:**\n"
        "- Name: validation loss\n"
        "- Direction: lower is better\n"
        "- Eval command: `uv run python eval.py`\n"
        "- Baseline: 1.23\n",
        encoding="utf-8",
    )

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "project",
            "--agent-type",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(note_file),
        ],
        env=env,
    )

    state = state_checkout(env)
    stored = (
        state / "agent-notes" / "research-coordinator" / "always-injected.md"
    ).read_text(encoding="utf-8")
    rendered = run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "render-section",
            "--project-dir",
            str(project),
            "--agent-type",
            "research-coordinator",
        ],
        env=env,
    ).stdout
    listed = run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "list-notes",
            "--scope",
            "project",
            "--agent-type",
            "research-coordinator",
            "--project-dir",
            str(project),
        ],
        env=env,
    )
    assert stored.startswith("# Research Coordinator Project Instructions")
    assert not (state / "AGENTS.md").exists()
    assert "**Goal:** Draft a sparse transformer paper." in rendered
    assert "validation loss" in stored
    assert "#### Project: research-coordinator" in rendered
    assert "Directory:" in listed.stdout


@pytest.mark.skip(reason="legacy project-local compaction hook layout was removed by repository format v2")
def test_compaction_refresh_pulls_notes_and_rematerializes_instructions(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)
    state = state_checkout(env)
    (state / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Project Notes\n\nOld project body.\n", encoding="utf-8"
    )
    git(state, "add", "agent-notes/all-agents/always-injected.md")
    git(state, "commit", "-m", "seed old project note")
    git(state, "push")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
    )
    assert launch.returncode == 0
    assert "Old project body." in (project / "AGENTS.md").read_text(encoding="utf-8")
    hook = project / ".codex" / "hooks" / "agentic-team-compaction.py"
    assert hook.exists()

    org_update = tmp_path / "org-update"
    run(["git", "clone", str(org_remote), str(org_update)])
    configure_git(org_update)
    (org_update / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Org Notes\n\nFresh org body.\n", encoding="utf-8"
    )
    git(org_update, "add", "agent-notes/all-agents/always-injected.md")
    git(org_update, "commit", "-m", "fresh org note")
    git(org_update, "push")

    state_update = tmp_path / "state-update"
    run(["git", "clone", str(project_remote), str(state_update)])
    configure_git(state_update)
    git(state_update, "fetch", "origin", "agentic/project-records")
    git(state_update, "checkout", "-B", "agentic/project-records", "origin/agentic/project-records")
    (state_update / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Project Notes\n\nFresh project body.\n", encoding="utf-8"
    )
    git(state_update, "add", "agent-notes/all-agents/always-injected.md")
    git(state_update, "commit", "-m", "fresh project note")
    git(state_update, "push", "origin", "agentic/project-records")

    result = run(
        [
            sys.executable,
            str(hook),
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"SessionStart"}',
    )

    payload = json.loads(result.stdout)
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "Agentic Team refreshed post-compaction instructions." in payload["systemMessage"]
    assert "just experienced context compaction" in payload["hookSpecificOutput"]["additionalContext"]
    assert "Fresh org body." in text
    assert "Fresh project body." in text
    assert "Old project body." not in text

    post_compact_result = run(
        [
            sys.executable,
            str(hook),
            "post-compact",
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"PostCompact"}',
    )
    post_compact_payload = json.loads(post_compact_result.stdout)
    assert "just experienced context compaction" in post_compact_payload["systemMessage"]
    assert "hookSpecificOutput" not in post_compact_payload
    assert not (hook.parent / ".agentic-team-compaction.pending").exists()

    inject_result = run(
        [
            sys.executable,
            str(hook),
            "inject-pending",
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"UserPromptSubmit"}',
    )
    inject_payload = json.loads(inject_result.stdout)
    assert inject_payload == {}
    assert not (hook.parent / ".agentic-team-compaction.pending").exists()

    stale_marker = hook.parent / ".agentic-team-compaction.pending"
    stale_marker.write_text(
        json.dumps({"message": "stale compaction text"}) + "\n",
        encoding="utf-8",
    )
    stale_inject_result = run(
        [
            sys.executable,
            str(hook),
            "inject-pending",
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"UserPromptSubmit"}',
    )
    assert json.loads(stale_inject_result.stdout) == {}
    assert not stale_marker.exists()

    legacy_user_prompt_result = run(
        [
            sys.executable,
            str(hook),
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"UserPromptSubmit"}',
    )
    assert json.loads(legacy_user_prompt_result.stdout) == {}


def test_note_updater_creates_new_org_note_and_commits(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "git"},
            "summary": "Prefer named staging.",
            "lesson": "Stage files by explicit path instead of using git add all.",
            "source": {"user_id": "alice", "agent_type": "gpu-kernel-engineer"},
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    checkout = org_checkout(env)
    assert "Stage files by explicit path" in (checkout / "agent-notes" / "all-agents" / "git.md").read_text()
    assert "notes: update agent-notes/all-agents/git.md" in git(checkout, "log", "-1", "--pretty=%s").stdout


def test_note_update_stores_lesson_without_summary_or_rationale_boilerplate(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    request = {
        "target": {"scope": "org", "agent_type": "all-agents", "note_name": "gpu-runtime"},
        "summary": "ROCm runtime mismatch",
        "lesson": "Check PyTorch device visibility before launching local ROCm GPU jobs.",
        "rationale": "rocm-smi listed devices but the active uv environment reported zero torch devices on 2026-07-01",
        "project_dir": str(project),
    }

    result = run(
        [str(AGENTIC_NOTES), "update-note"],
        input=yaml.safe_dump(request, sort_keys=False),
        env=env,
    )
    response = json.loads(result.stdout)
    assert response["scope"] == "org"
    assert response["changed"] is True

    checkout = org_checkout(env)
    text = (checkout / "agent-notes" / "all-agents" / "gpu-runtime.md").read_text()
    assert "Topic hints: ROCm runtime mismatch" in text
    assert "- Check PyTorch device visibility before launching local ROCm GPU jobs." in text
    assert "ROCm runtime mismatch:" not in text
    assert "rocm-smi listed devices" not in text


def test_rewrite_note_replaces_one_note_through_agent_command(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    update_request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "gpu-runtime"},
            "summary": "PyTorch device visibility",
            "lesson": "Check PyTorch device visibility before launching local GPU jobs.",
        },
    )
    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(update_request), "--project-dir", str(project)], env=env)
    rewrite_request = {
        "target": {"scope": "org", "agent_type": "all-agents", "note_name": "gpu-runtime"},
        "content": "# Gpu Runtime\n\n## Lessons\n\n- Check PyTorch device visibility before local ROCm or CUDA jobs.\n",
    }

    result = run(
        [
            str(AGENTIC_NOTES),
            "rewrite-note",
        ],
        input=yaml.safe_dump(rewrite_request, sort_keys=False),
        env=env,
    )

    response = json.loads(result.stdout)
    assert response["scope"] == "org"
    assert response["changed"] is True
    checkout = org_checkout(env)
    text = (checkout / "agent-notes" / "all-agents" / "gpu-runtime.md").read_text()
    assert "before local ROCm or CUDA jobs" in text
    assert "before launching local GPU jobs" not in text
    assert "notes: replace agent-notes/all-agents/gpu-runtime.md" in git(checkout, "log", "-1", "--pretty=%s").stdout


def test_note_updater_does_not_duplicate_existing_agent_type_bullet(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    checkout = org_checkout(env)
    note = checkout / "agent-notes" / "gpu-kernel-engineer" / "triton.md"
    note.write_text("# Triton\n\n## Lessons\n\n- Keep BLOCK power-of-two.\n", encoding="utf-8")
    git(checkout, "add", str(note.relative_to(checkout)))
    git(checkout, "commit", "-m", "seed agent type triton note")
    git(checkout, "push")
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "gpu-kernel-engineer", "note_name": "triton"},
            "summary": "Power-of-two blocks.",
            "lesson": "Keep BLOCK power-of-two.",
            "source": {"user_id": "alice", "agent_type": "gpu-kernel-engineer"},
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    text = note.read_text(encoding="utf-8")
    assert text.count("Keep BLOCK power-of-two.") == 1


def test_note_updater_updates_project_note_on_agentic_state_branch(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {
                "scope": "project",
                "agent_type": "all-agents",
                "note_name": "evaluation",
            },
            "summary": "Use fixed eval split.",
            "lesson": "Keep the evaluation split unchanged across experiments.",
            "source": {"user_id": "alice"},
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    inspect = tmp_path / "inspect-state"
    run(["git", "clone", "-b", "agentic/project-records", str(project_remote), str(inspect)])
    assert "evaluation split unchanged" in (
        inspect / "agent-notes" / "all-agents" / "evaluation.md"
    ).read_text()


def test_project_state_initialization_creates_required_layout(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)

    state = state_checkout(env)
    always_injected = state / "agent-notes" / "all-agents" / "always-injected.md"
    assert always_injected.exists()
    assert always_injected.read_text(encoding="utf-8") == ""
    assert not (state / "work-state").exists()
    assert not (state / "experiment-log").exists()
    assert not (state / "README.md").exists()
    head_with_parents = git(state, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert len(head_with_parents) == 1


def test_work_state_files_render_plan_and_stay_off_code_branch(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])
    plan = tmp_path / "plan.md"
    condensed_report = tmp_path / "condensed_report.md"
    report = tmp_path / "report_page1.md"
    todo = tmp_path / "TODO.md"
    figure = tmp_path / "baseline.png"
    plan.write_text(
        "# Research Plan: kernel-search\n\n"
        "**Goal:** Find a faster sparse attention kernel.\n\n"
        "**Current Next Steps:**\n"
        "- Run the baseline benchmark.\n",
        encoding="utf-8",
    )
    report.write_text(
        "# Research Log\n\nBaseline pending.\n",
        encoding="utf-8",
    )
    condensed_report.write_text(
        "# Condensed Report\n\nBaseline pending.\n",
        encoding="utf-8",
    )
    todo.write_text("- [ ] Run baseline benchmark\n", encoding="utf-8")
    figure.write_bytes(b"not-a-real-png")

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "work",
            "--work-branch",
            "kernel-search",
            "--agent-type",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(plan),
        ],
        env=env,
    )
    work_state = branch_records_dir(env)
    (work_state / "condensed_report.md").write_text(condensed_report.read_text(encoding="utf-8"), encoding="utf-8")
    (work_state / "report_page1.md").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    (work_state / "TODO.md").write_text(todo.read_text(encoding="utf-8"), encoding="utf-8")
    (work_state / "images").mkdir()
    (work_state / "images" / "baseline.png").write_bytes(figure.read_bytes())
    git(work_state, "add", "condensed_report.md", "report_page1.md", "TODO.md", "images/")
    git(work_state, "commit", "-m", "work-state: update research records")
    git(work_state, "push")

    stored_plan = work_state / "agent-notes" / "research-coordinator" / "always-injected.md"
    assert stored_plan.read_text(encoding="utf-8") == plan.read_text(encoding="utf-8")
    assert (work_state / "condensed_report.md").read_text(encoding="utf-8") == condensed_report.read_text(encoding="utf-8")
    assert (work_state / "report_page1.md").read_text(encoding="utf-8") == report.read_text(encoding="utf-8")
    assert (work_state / "TODO.md").read_text(encoding="utf-8") == todo.read_text(encoding="utf-8")
    assert (work_state / "images" / "baseline.png").read_bytes() == figure.read_bytes()
    assert not (project / "condensed_report.md").exists()
    assert not (project / "report_page1.md").exists()
    assert not (project / "TODO.md").exists()
    assert not (project / "images" / "baseline.png").exists()

    run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "research-coordinator",
            *launch_args,
        ],
        env=env,
    )
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agentic Records" in instruction_text
    assert "agentic/branch-records/kernel-search" in instruction_text
    assert 'BRANCH_RECORDS_DIR="${AR_BRANCH_RECORDS_DIR:?}"' in instruction_text
    assert "## Callback-Managed Imperative Workflow" in instruction_text
    assert "Call the `start_workflow` tool" in instruction_text
    assert (
        "agentic_workflows.research.research_coordinator:ResearchCoordinator"
        in instruction_text
    )
    assert "Do not invoke `imperative-workflows-callback` through a shell" in instruction_text
    assert "### Workflow Modules" not in instruction_text
    assert "class ResearchCoordinator" not in instruction_text
    normalized_instructions = " ".join(instruction_text.split())
    assert "persistent worker owns Python ordering" in normalized_instructions
    assert "only `ask_user`, `complete`, `failed`, or `cancelled` is a terminal event" in normalized_instructions
    assert "run `--help`" in instruction_text
    assert "subagent_admission" in instruction_text
    assert "research-coordinator-finalization" not in instruction_text
    assert "research-coordinator-report-append" not in instruction_text
    finalizer_text = (code / ".codex" / "agents" / "research-finalizer.toml").read_text(encoding="utf-8")
    assert "## Callback-Managed Imperative Workflow" in finalizer_text
    assert "Call the `start_workflow` tool" in finalizer_text
    assert (
        "agentic_workflows.research.research_finalizer:ResearchFinalizer"
        in finalizer_text
    )
    assert "$BRANCH_RECORDS_DIR/images/" in instruction_text
    assert (
        "do not skip report-ready PNG/PDF figures merely because they are binary files"
        in " ".join(instruction_text.split())
    )
    assert "**Goal:** Find a faster sparse attention kernel." in instruction_text
    assert "#### Work branch: kernel-search / research-coordinator" in instruction_text
    assert "No work-branch always-injected guidance" not in instruction_text
    assert "--name research-plan" not in instruction_text

    rendered_plan = run(
        [
            str(AGENTIC_NOTES),
            "read-note",
            "--project-dir",
            str(project),
            "--agent-type",
            "research-coordinator",
            "always-injected",
        ],
        env=env,
    ).stdout
    assert "## Work branch: kernel-search / research-coordinator" in rendered_plan
    assert "**Goal:** Find a faster sparse attention kernel." in rendered_plan

    legacy_notes_command = "at" "-notes"
    assert not (REPO_ROOT / "capabilities" / "agentic-notes" / "bin" / legacy_notes_command).exists()

    missing_summary = run(
        [
            str(EXPERIMENT_LOG),
            "summary",
            "--project-dir",
            str(project),
            "--work-branch",
            "kernel-search",
        ],
        env=env,
        check=False,
    )
    assert missing_summary.returncode == 1
    assert "experiment summary does not exist" in missing_summary.stderr


def test_agentic_notes_state_ensure_does_not_commit_dirty_work_records(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)], env=env)
    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "list-notes",
            "--scope",
            "work",
            "--project-dir",
            str(project),
            "--agent-type",
            "all-agents",
            "--work-branch",
            "kernel-search",
        ],
        env=env,
    )
    state = branch_records_dir(env)
    assert state.exists()
    base_head = git(state, "rev-parse", "HEAD").stdout.strip()
    (state / "report_page1.md").write_text("# Research Log\n\nUncommitted result.\n", encoding="utf-8")

    run([str(AGENTIC_NOTES_INTERNAL), "refresh", "--project-dir", str(project)], env=env)

    assert git(state, "rev-parse", "HEAD").stdout.strip() == base_head
    assert git(state, "status", "--short").stdout == "?? report_page1.md\n"


@pytest.mark.skip(reason="legacy named-work layout was removed by repository format v2")
def test_named_work_creates_at_layout_and_references_research_context(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env["AR_CAPABILITIES"] = "agentic-notes,experiment-log,research-coordinator"

    plan = tmp_path / "plan.md"
    plan.write_text("# Parent Plan\n\nExplore existing bounds.\n", encoding="utf-8")
    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "work",
            "--work-branch",
            "kernel-search",
            "--agent-type",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(plan),
        ],
        env=env,
    )
    parent_state = branch_records_dir(env)
    assert_linked_worktree(parent_state)
    parent_all_notes = parent_state / "agent-notes" / "all-agents"
    parent_research_notes = parent_state / "agent-notes" / "research-coordinator"
    parent_all_notes.mkdir(parents=True, exist_ok=True)
    parent_research_notes.mkdir(parents=True, exist_ok=True)
    (parent_all_notes / "routing-constraints.md").write_text(
        "# Routing Constraints\n\nTopic hints: routing, constraints\n\nUse the parent routing constraint.\n",
        encoding="utf-8",
    )
    (parent_research_notes / "experiment-scaling.md").write_text(
        "# Experiment Scaling\n\nTopic hints: scaling, experiments\n\nUse the parent scaling note.\n",
        encoding="utf-8",
    )
    (parent_state / "condensed_report.md").write_text("# Condensed Report\n\nBest parent finding.\n", encoding="utf-8")
    (parent_state / "report_page1.md").write_text("# Parent Page 1\n\nOld result.\n", encoding="utf-8")
    (parent_state / "report_page2.md").write_text("# Parent Page 2\n\nUseful result.\n", encoding="utf-8")
    (parent_state / "TODO.md").write_text("- [ ] Parent todo\n", encoding="utf-8")
    (parent_state / "images").mkdir(exist_ok=True)
    (parent_state / "images" / "parent.png").write_bytes(b"png")
    (parent_state / "context").mkdir(exist_ok=True)
    write_yaml(
        parent_state / "context" / "manifest.yaml",
        {
            "version": 1,
            "references": [
                {
                    "work_branch": "agent/ancestor",
                    "records_branch": "agentic/branch-records/agent/ancestor",
                    "records_commit": "abc123",
                    "files": ["report_page3.md", "images/ancestor.png"],
                }
            ],
        },
    )
    git(
        parent_state,
        "add",
        "condensed_report.md",
        "report_page1.md",
        "report_page2.md",
        "TODO.md",
        "images/",
        "context/manifest.yaml",
        "agent-notes/all-agents/routing-constraints.md",
        "agent-notes/research-coordinator/experiment-scaling.md",
    )
    git(parent_state, "commit", "-m", "work-state: add parent research records")
    git(parent_state, "push")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    root = workspace_root(env)
    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            str(root),
            "kdtree-bounds",
            "--from",
            "kernel-search",
            "--project-dir",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0
    code_dir = root / "kdtree-bounds" / "code"
    state_dir = root / "branches" / "kdtree-bounds" / "records"
    assert code_dir.exists()
    assert state_dir.exists()
    assert (root / "project").is_symlink()
    assert_linked_worktree(root / "project-records")
    assert_linked_worktree(state_dir)
    assert git(code_dir, "branch", "--show-current").stdout.strip() == "agent/alice/kdtree-bounds"
    assert (
        state_dir / "agent-notes" / "research-coordinator" / "always-injected.md"
    ).read_text(encoding="utf-8") == plan.read_text(encoding="utf-8")
    assert "parent routing constraint" in (
        state_dir / "agent-notes" / "all-agents" / "routing-constraints.md"
    ).read_text(encoding="utf-8")
    assert "parent scaling note" in (
        state_dir / "agent-notes" / "research-coordinator" / "experiment-scaling.md"
    ).read_text(encoding="utf-8")
    report_text = (state_dir / "report_page1.md").read_text(encoding="utf-8")
    assert report_text.startswith("# Research Log: kdtree-bounds")
    assert "Created from `kernel-search` into `agent/alice/kdtree-bounds`" in report_text
    condensed_text = (state_dir / "condensed_report.md").read_text(encoding="utf-8")
    assert condensed_text.startswith("# Condensed Report: kdtree-bounds")
    assert "Keep this condensed report to about one page" in condensed_text
    assert (state_dir / "context" / "parent" / "condensed_report.md").read_text(encoding="utf-8").startswith("# Condensed Report")
    assert (state_dir / "context" / "parent" / "report_page2.md").read_text(encoding="utf-8").startswith("# Parent Page 2")
    assert (state_dir / "context" / "parent" / "TODO.md").exists()
    assert not (state_dir / "context" / "parent" / "report_page1.md").exists()
    assert not (state_dir / "context" / "parent" / "images" / "parent.png").exists()
    manifest = yaml.safe_load((state_dir / "context" / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["created_from"]["work_branch"] == "kernel-search"
    assert [entry["work_branch"] for entry in manifest["references"]] == ["agent/ancestor", "kernel-search"]
    assert manifest["references"][0]["files"] == ["report_page3.md", "images/ancestor.png"]
    assert manifest["references"][1]["records_branch"] == "agentic/branch-records/kernel-search"
    assert manifest["references"][1]["files"] == [
        "condensed_report.md",
        "report_page1.md",
        "report_page2.md",
        "TODO.md",
        "images/parent.png",
    ]
    readme_text = (state_dir / "context" / "README.md").read_text(encoding="utf-8")
    assert "condensed_report.md" in readme_text
    assert "report_page1.md" in readme_text
    assert "report_page2.md" in readme_text
    assert "images/parent.png" in readme_text
    assert (root / "project-records").exists()
    assert (
        git(project, "ls-remote", "--exit-code", "--heads", "origin", "agent/alice/kdtree-bounds", check=False).returncode
        == 2
    )
    assert (
        git(
            project,
            "ls-remote",
            "--exit-code",
            "--heads",
            "origin",
            "agentic/branch-records/agent/alice/kdtree-bounds",
            check=False,
        ).returncode
        == 2
    )


@pytest.mark.skip(reason="legacy named-work branch synthesis was removed by repository format v2")
def test_named_work_from_agent_branch_uses_sibling_branch_name(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env["AR_CAPABILITIES"] = "none"
    root = workspace_root(env)
    source_code = root / "dan-agent" / "code"
    source_code.parent.mkdir(parents=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "project").symlink_to(project, target_is_directory=True)
    git(project, "worktree", "add", "-b", "agent/dan-agent", str(source_code), "kernel-search")
    configure_git(source_code)

    result = run(
        [
            str(AGENTIC_WORKSPACE),
            "ensure-work",
            "dan-agent2",
            "--workspace-root",
            str(root),
            "--from",
            "dan-agent",
            "--capabilities",
            "none",
        ],
        env=env,
    )

    assert result.returncode == 0
    code_dir = root / "dan-agent2" / "code"
    assert git(code_dir, "branch", "--show-current").stdout.strip() == "agent/dan-agent2"


@pytest.mark.skip(reason="legacy named-work branch synthesis was removed by repository format v2")
def test_named_work_does_not_suffix_when_requested_branch_exists_remotely(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env["AR_CAPABILITIES"] = "none"
    root = workspace_root(env)
    source_code = root / "dan-agent" / "code"
    source_code.parent.mkdir(parents=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "project").symlink_to(project, target_is_directory=True)
    git(project, "worktree", "add", "-b", "agent/dan-agent", str(source_code), "kernel-search")
    configure_git(source_code)
    git(project, "branch", "agent/dan-agent2", "kernel-search")
    git(project, "push", "origin", "agent/dan-agent2")
    git(project, "branch", "-D", "agent/dan-agent2")

    result = run(
        [
            str(AGENTIC_WORKSPACE),
            "ensure-work",
            "dan-agent2",
            "--workspace-root",
            str(root),
            "--from",
            "dan-agent",
            "--capabilities",
            "none",
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "agent/dan-agent2" in result.stderr
    assert "origin/agent/dan-agent2" in result.stderr
    assert "dan-agent2-2" not in result.stderr
    assert not (root / "dan-agent2" / "code").exists()


def test_project_state_uses_directory_name_when_no_remote_exists(tmp_path: Path) -> None:
    project = tmp_path / "project-without-remote"
    project.mkdir()
    env = base_env(tmp_path)

    result = run(
        [str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)],
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert (workspace_root(env) / "project-records").exists()


def test_project_state_uses_checkout_name_even_with_git_remote(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    result = run(
        [str(AGENTIC_NOTES_INTERNAL), "ensure-project-records", "--project-dir", str(project)],
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert_linked_worktree(workspace_root(env, "project") / "project-records")
    assert (
        workspace_root(env, "project")
        / "project-records"
        / "agent-notes"
        / "all-agents"
        / "always-injected.md"
    ).exists()


def test_launcher_branch_guard_blocks_same_branch_but_not_other_branches(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    git(project, "branch", "paper-draft", "kernel-search")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env.pop("AR_WORK_BRANCH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"

    guard_dir = workspace_root(env) / ".runtime" / "branch-guards" / "kernel-search"
    guard_dir.mkdir(parents=True)
    (guard_dir / "session-one.guard").write_text(
        "\n".join(
            [
                "session_id=session-one",
                "main_agent=research-coordinator",
                "pid=12345",
                "host=test-host",
                f"workspace={project}",
                "started_at=2026-06-30T00:00:00Z",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    blocked = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
        check=False,
    )
    other = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env, "paper-draft"),
        ],
        env=env,
    )

    assert blocked.returncode == 1
    assert "already has an active local agent session" in blocked.stderr
    assert other.returncode == 0
    assert "Work branch:   paper-draft" in other.stdout


def test_remote_repo_spec_detects_scp_style_remotes() -> None:
    loader = SourceFileLoader("ar_notes_remote_spec_test", str(AGENTIC_NOTES_STATE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    at_notes = importlib.util.module_from_spec(spec)
    loader.exec_module(at_notes)

    assert at_notes.is_remote_repo_spec("dan-git@localhost:org-agentic-state.git")
    assert at_notes.is_remote_repo_spec("git@github.com:SmerkyG/abctest.git")
    assert not at_notes.is_remote_repo_spec("/tmp/abctest.git")


def test_init_org_notes_treats_scp_style_repo_as_remote(tmp_path: Path) -> None:
    loader = SourceFileLoader("ar_notes_scp_org_remote_test", str(AGENTIC_NOTES_STATE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    at_notes = importlib.util.module_from_spec(spec)
    loader.exec_module(at_notes)

    remote = "dan-git@localhost:org-agentic-state.git"
    checkout_calls = []

    def fail_local_repo(repo: Path, branch: str) -> Path:
        raise AssertionError(f"scp-style remote was treated as a local path: {repo}")

    def fake_checkout(repo_url: str | None = None) -> None:
        checkout_calls.append(repo_url)
        return None

    at_notes.ensure_local_git_repo = fail_local_repo
    at_notes.ensure_org_checkout = fake_checkout
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        at_notes.init_org_notes(SimpleNamespace(repo=remote))
    finally:
        os.chdir(old_cwd)

    assert checkout_calls == [remote]
    assert not (tmp_path / remote).exists()


def test_init_org_notes_creates_empty_always_injected_placeholder(tmp_path: Path) -> None:
    org_repo = tmp_path / "org-notes"
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_repo)], env=env)

    note = org_repo / "agent-notes" / "all-agents" / "always-injected.md"
    assert note.exists()
    assert note.read_text(encoding="utf-8") == ""


def test_update_org_note_locks_only_org_state(tmp_path: Path) -> None:
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "git"},
            "summary": "Lock test.",
            "lesson": "Lock test.",
        },
    )
    previous = {
        "AR_STATE_ROOT": os.environ.get("AR_STATE_ROOT"),
        "AR_ORG_NOTES_REPO": os.environ.get("AR_ORG_NOTES_REPO"),
    }
    os.environ["AR_STATE_ROOT"] = str(tmp_path / "state")
    os.environ["AR_ORG_NOTES_REPO"] = str(tmp_path / "org.git")
    try:
        loader = SourceFileLoader("ar_notes_lock_test", str(AGENTIC_NOTES_STATE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        at_notes = importlib.util.module_from_spec(spec)
        loader.exec_module(at_notes)
        locks = at_notes.lock_paths_for_args(
            SimpleNamespace(
                command="update-note",
                request=str(request),
                project_dir=str(tmp_path / "project"),
            )
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    lock_names = {path.name for path in locks}
    assert lock_names == {"org-agentic-notes.lock"}


def experiment_request(tmp_path: Path, short_description: str, key_result: str = "passed") -> Path:
    return make_request(
        tmp_path,
        {
            "short_description": short_description,
            "title": short_description,
            "description": "Test experiment.",
            "code": {"branch": "test", "commit": "9f4d2a8c7b0e"},
            "command": "uv run pytest",
            "status": "completed",
            "success": False,
            "key_result": key_result,
            "metrics": [{"name": "tests_passed", "value": "1"}],
            "artifacts": [],
            "notes": None,
        },
    )


def test_experiment_log_rejects_payloads_outside_the_tool_schema(tmp_path: Path) -> None:
    cases = [
        (lambda data: data.pop("title"), "missing required ExperimentLogAppendTool fields: title"),
        (lambda data: data.__setitem__("success", "false"), "expected bool, got str"),
        (lambda data: data.__setitem__("status", "successful"), "expected one of"),
        (lambda data: data.__setitem__("metrics", {"tests_passed": 1}), "expected an array, got dict"),
        (lambda data: data.__setitem__("artifacts", {}), "expected an array, got dict"),
        (lambda data: data.__setitem__("mystery", True), "unexpected ExperimentLogAppendTool fields: mystery"),
        (lambda data: data["code"].__setitem__("repo", "local"), "unexpected ExperimentCode fields: repo"),
        (
            lambda data: (data.__setitem__("success", True), data.__setitem__("status", "failed")),
            "success=true requires status=completed",
        ),
        (
            lambda data: (data.__setitem__("success", True), data["code"].__setitem__("commit", None)),
            "success=true requires code.commit",
        ),
    ]

    for mutate, expected in cases:
        data = yaml.safe_load(experiment_request(tmp_path, "Invalid request").read_text())
        mutate(data)
        request = make_request(tmp_path, data)
        result = run(
            [str(EXPERIMENT_LOG), "append", "--request", str(request), "--project-dir", str(tmp_path)],
            check=False,
        )
        assert result.returncode == 1
        assert expected in result.stderr


def summary_rows(summary: str) -> list[str]:
    return [line for line in summary.splitlines() if line.startswith("| [")]


def test_experiment_logger_creates_counter_ids_and_appends_summary(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    first = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Triton power-of-two shape test")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    first = operation_result(first, "experiment_id")
    second = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Attention odd seq benchmark")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    second = operation_result(second, "experiment_id")

    log_dir = work_log(env)
    first_id = local_experiment_id(first)
    second_id = local_experiment_id(second)
    assert first == "kernel-search::E0001_triton-power-of-two-shape-test"
    assert second == "kernel-search::E0002_attention-odd-seq-benchmark"
    assert (log_dir / "experiments" / f"{first_id}.yaml").exists()
    assert (log_dir / "experiments" / f"{second_id}.yaml").exists()
    counter = yaml.safe_load((log_dir / "COUNTER.yaml").read_text())
    assert counter["next_experiment_number"] == 3
    assert "next_correction_number" not in counter
    summary = run(
        [
            str(EXPERIMENT_LOG),
            "summary",
            "--project-dir",
            str(project),
            "--work-branch",
            "kernel-search",
        ],
        env=env,
    ).stdout
    assert len(summary_rows(summary)) == 2
    assert first_id in summary
    assert second_id in summary


def test_successful_experiment_creates_local_success_tag(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    commit = git(project, "rev-parse", "HEAD").stdout.strip()
    request = make_request(
        tmp_path,
        {
            "short_description": "Successful run",
            "title": "Successful run",
            "description": "Test experiment.",
            "code": {"branch": "kernel-search", "commit": commit},
            "command": "uv run pytest",
            "status": "completed",
            "success": True,
            "key_result": "new best result",
            "metrics": [{"name": "tests_passed", "value": "1"}],
            "artifacts": [],
            "notes": None,
        },
    )

    experiment_ref = operation_result(run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip(), "experiment_id")

    experiment_id = local_experiment_id(experiment_ref)
    tag_name = f"exp/kernel-search/{experiment_id}-success"
    assert git(project, "rev-list", "-n", "1", tag_name).stdout.strip() == commit
    experiment_doc = yaml.safe_load((work_log(env) / "experiments" / f"{experiment_id}.yaml").read_text())
    assert experiment_doc["success"] is True


def test_summary_is_append_only_and_existing_experiment_files_are_unchanged(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    first = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "First run")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    first = operation_result(first, "experiment_id")
    log_dir = work_log(env)
    first_id = local_experiment_id(first)
    first_file = log_dir / "experiments" / f"{first_id}.yaml"
    first_content = first_file.read_text(encoding="utf-8")
    hidden = log_dir / "experiments" / "E9999_hidden.yaml"
    hidden.write_text("kind: experiment_result\nexperiment_id: E9999_hidden\n", encoding="utf-8")
    state = work_state_checkout(env)
    git(state, "add", str(hidden.relative_to(state)))
    git(state, "commit", "-m", "add hidden experiment")
    git(state, "push")

    second = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Second run")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    second = operation_result(second, "experiment_id")

    summary = (log_dir / "SUMMARY.md").read_text()
    assert first_file.read_text(encoding="utf-8") == first_content
    assert local_experiment_id(second) in summary
    assert "E9999_hidden" not in summary


def test_push_conflict_retries_with_next_counter_number(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project_one = clone_project(tmp_path, project_remote, "project-one")
    project_two = clone_project(tmp_path, project_remote, "project-two")
    env_one = base_env(tmp_path / "one")
    env_two = base_env(tmp_path / "two")
    env_one["AR_WORKSPACE_ROOT"] = str(tmp_path / "one" / "conflict-project-at")
    env_two["AR_WORKSPACE_ROOT"] = str(tmp_path / "two" / "conflict-project-at")

    run([str(EXPERIMENT_LOG), "summary", "--project-dir", str(project_one), "--work-branch", "kernel-search"], env=env_one, check=False)
    run([str(EXPERIMENT_LOG), "summary", "--project-dir", str(project_two), "--work-branch", "kernel-search"], env=env_two, check=False)
    state_two = work_state_checkout(env_two)
    waiting = tmp_path / "waiting"
    allow = tmp_path / "allow"
    write_pre_push_hook(
        state_two,
        "#!/bin/sh\n"
        f"touch '{waiting}'\n"
        f"while [ ! -f '{allow}' ]; do sleep 0.05; done\n",
    )

    proc_two = subprocess.Popen(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Conflict loser")),
            "--project-dir",
            str(project_two),
        ],
        cwd=REPO_ROOT,
        env=env_two,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(100):
        if waiting.exists():
            break
        time.sleep(0.05)
    assert waiting.exists()
    winner = operation_result(run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Conflict winner")),
            "--project-dir",
            str(project_one),
        ],
        env=env_one,
    ).stdout.strip(), "experiment_id")
    allow.touch()
    stdout, stderr = proc_two.communicate(timeout=30)
    assert proc_two.returncode == 0, stderr
    loser = operation_result(stdout.strip(), "experiment_id")
    assert winner.startswith("kernel-search::E0001_")
    assert loser.startswith("kernel-search::E0002_")


def test_same_installation_multiple_actor_worktrees_serialize_project_log_updates(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project_one = clone_project(tmp_path, project_remote, "actor-one")
    project_two = clone_project(tmp_path, project_remote, "actor-two")
    env = base_env(tmp_path)
    env["AR_WORKSPACE_ROOT"] = str(tmp_path / "shared-worktree-project-at")

    run([str(EXPERIMENT_LOG), "summary", "--project-dir", str(project_one), "--work-branch", "kernel-search"], env=env, check=False)
    state = work_state_checkout(env)
    waiting = tmp_path / "same-install-waiting"
    allow = tmp_path / "same-install-allow"
    write_pre_push_hook(
        state,
        "#!/bin/sh\n"
        f"touch '{waiting}'\n"
        f"while [ ! -f '{allow}' ]; do sleep 0.05; done\n",
    )

    proc_one = subprocess.Popen(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Shared state first")),
            "--project-dir",
            str(project_one),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(100):
        if waiting.exists():
            break
        time.sleep(0.05)
    assert waiting.exists()

    proc_two = subprocess.Popen(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Shared state second")),
            "--project-dir",
            str(project_two),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    allow.touch()
    stdout_one, stderr_one = proc_one.communicate(timeout=30)
    stdout_two, stderr_two = proc_two.communicate(timeout=30)
    assert proc_one.returncode == 0, stderr_one
    assert proc_two.returncode == 0, stderr_two
    assert operation_result(stdout_one.strip(), "experiment_id").startswith("kernel-search::E0001_")
    assert operation_result(stdout_two.strip(), "experiment_id").startswith("kernel-search::E0002_")
    summary = (work_log(env) / "SUMMARY.md").read_text()
    assert len(summary_rows(summary)) == 2


def test_correction_logging_appends_to_experiment_file_and_summary_row(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    experiment_id = operation_result(run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Needs correction")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip(), "experiment_id")
    correction_request = make_request(
        tmp_path,
        {
            "experiment_id": experiment_id,
            "summary": "Metric was computed on the wrong split.",
            "correction": "Use the fixed validation split.",
        },
    )

    correction_id = operation_result(run(
        [
            str(EXPERIMENT_LOG),
            "correct",
            "--request",
            str(correction_request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip(), "correction_id")
    second_request = make_request(
        tmp_path,
        {
            "experiment_id": experiment_id,
            "summary": "Artifact path was stale.",
            "correction": "Use the artifact path from the rerun.",
        },
    )
    second_correction_id = operation_result(run(
        [
            str(EXPERIMENT_LOG),
            "correct",
            "--request",
            str(second_request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip(), "correction_id")

    log_dir = work_log(env)
    local_id = local_experiment_id(experiment_id)
    experiment_path = log_dir / "experiments" / f"{local_id}.yaml"
    experiment_doc = yaml.safe_load(experiment_path.read_text())
    assert correction_id == "kernel-search::E0001_R001"
    assert second_correction_id == "kernel-search::E0001_R002"
    assert [entry["correction_id"] for entry in experiment_doc["corrections"]] == [
        "E0001_R001",
        "E0001_R002",
    ]
    assert experiment_doc["corrections"][0]["correction"] == "Use the fixed validation split."
    assert not (log_dir / "corrections").exists()
    summary = (log_dir / "SUMMARY.md").read_text()
    assert "E0001_R001" in summary
    assert "E0001_R002" in summary
    assert f"experiments/{local_id}.yaml" in summary


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_launcher_uses_unoccupied_agent_branch(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env.pop("AR_WORK_BRANCH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Work branch:   kernel-search" in result.stdout
    code = workspace_root(env) / "branches" / "kernel-search" / "code"
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "Unprepared Agentic Team Checkout" not in instruction_text
    assert instruction_text.startswith("# Global Instructions")
    assert not (code / "CLAUDE.md").exists()
    assert not (code / "GEMINI.md").exists()
    assert "## Agent Branch" not in instruction_text
    assert "Active branch: `kernel-search`." not in instruction_text
    assert "No conflicting local branch guard was detected at launch." not in instruction_text
    assert "The user explicitly accepted the launcher branch warning" not in instruction_text
    assert "kernel-search/exp/<experiment-name>" not in instruction_text


def test_launcher_render_only_rewrites_managed_instruction_and_normalizes_whitespace(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    launch_args = at_launch_args(project, env)
    code = workspace_root(env) / "branches" / "kernel-search" / "code"
    (code / "AGENTS.md").write_text(
        "# Research Agent Instructions\n\n"
        "stale generated base\n"
        "\n\n\n\n\n"
        "<!-- AGENTIC-TEAM-MAIN-AGENT-START name=research-coordinator -->\n"
        "old generated main agent\n"
        "<!-- AGENTIC-TEAM-MAIN-AGENT-END -->\n",
        encoding="utf-8",
    )

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0
    assert f"Rendered instruction file: {code / 'AGENTS.md'}" in result.stdout
    text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Global Instructions")
    assert "# Research Agent Instructions" not in text.splitlines()[0]
    assert "stale generated base" not in text
    assert "old generated main agent" not in text
    assert "\n\n\n\n" not in text
    assert "## Agentic Notes" in text
    assert "## Agent Branch" not in text
    assert "<!-- AGENTIC-TEAM-MAIN-AGENT-START" not in text
    assert "<!-- AGENTIC-TEAM-MODULE-START" not in text
    assert "<!-- AGENTIC-TEAM-PROVIDER-START" not in text
    assert "<!-- AGENTIC-TEAM-NOTES-START" not in text
    assert "<!-- AGENTIC-TEAM-TOPIC-START" not in text
    assert "<!-- AGENTIC-TEAM-SUBAGENTS-START" not in text
    assert text.count("<!--") == 0
    assert (code / ".codex" / "agents" / "research-finalizer.toml").exists()
    status = git(code, "status", "--short", "--untracked-files=all", "AGENTS.md", ".codex", ".agents")
    assert status.stdout == ""
    exclude_text = (workspace_root(env) / "repo.git" / "info" / "exclude").read_text(encoding="utf-8")
    assert "# BEGIN agentic-team generated files" in exclude_text
    assert "/AGENTS.md" in exclude_text
    assert "/.codex/agents/" in exclude_text
    assert "/.agents/skills/" in exclude_text


def test_launcher_passive_startup_does_not_push_agentic_state_branches(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *at_launch_args(project, env),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    remote_refs = run(
        ["git", "ls-remote", "--heads", str(project_remote), "agentic/*"]
    ).stdout
    assert remote_refs == ""

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    remote_refs = run(
        ["git", "ls-remote", "--heads", str(project_remote), "agentic/*"]
    ).stdout
    assert remote_refs == ""


def test_main_agent_required_capabilities_are_added_to_empty_selection(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agentic Notes" in text
    assert "## Agentic Records" in text
    assert "## Experiment Log" in text
    assert (code / ".codex" / "agents" / "research-finalizer.toml").exists()


def test_launcher_requires_an_explicit_main_agent(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env.pop("AR_MAIN_AGENT")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "empty-config")
    launch_args = at_launch_args(project, env)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "No main agent selected" in result.stderr
    assert "--main-agent NAME" in result.stderr


def test_systems_developer_required_capabilities_do_not_add_experiment_log(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "systems-developer",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agentic Notes" in text
    assert "## Experiment Log" not in text
    assert (code / ".codex" / "agents" / "code-reviewer.toml").exists()
    assert (code / ".codex" / "agents" / "note-updater.toml").exists()
    assert not (code / ".codex" / "agents" / "research-finalizer.toml").exists()


@pytest.mark.skip(reason="v2 permits any explicitly materialized paired branch")
def test_launcher_refuses_main_branch_without_permission_in_noninteractive_mode(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    git(project, "switch", "main")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env.pop("AR_WORK_BRANCH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            str(project),
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "has no paired checkout" in result.stderr
    assert "Current branch: main" in result.stdout
    assert "agentic-team" in result.stdout
    assert "--project-dir" in result.stdout


def test_launcher_notes_integration_keeps_builtin_skill_rendering(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])
    stale_skill = code / ".agents" / "skills" / "experiment_log" / "SKILL.md"
    stale_skill.parent.mkdir(parents=True)
    stale_skill.write_text(
        "<!-- Generated by agentic-team. Edit the source skill to change this file. -->\n",
        encoding="utf-8",
    )

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0
    research_skill = code / ".agents" / "skills" / "do_research" / "SKILL.md"
    assert research_skill.exists()
    research_skill_text = research_skill.read_text(encoding="utf-8")
    assert "name: do_research" in research_skill_text
    assert "## Callback-Managed Skill" in research_skill_text
    assert "Call the `start_workflow` tool" in research_skill_text
    assert (
        "agentic_workflows.research.research_coordinator:ResearchCoordinator"
        in research_skill_text
    )
    assert "def do_research" not in research_skill_text
    assert "workflow_receiver:" not in research_skill_text
    assert "```python agentic-workflow" not in research_skill_text
    assert not (code / ".agents" / "skills" / "note_usage" / "SKILL.md").exists()
    assert not (code / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    assert (code / ".codex" / "agents" / "code-reviewer.toml").exists()
    assert (code / ".codex" / "agents" / "note-updater.toml").exists()
    assert (code / ".codex" / "agents" / "research-finalizer.toml").exists()
    assert not (code / ".codex" / "agents" / "branch-committer.toml").exists()
    assert not (code / ".codex" / "agents" / "branch-commit-status.toml").exists()
    assert not (code / ".codex" / "agents" / "research-coordinator.toml").exists()
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- AGENTIC-TEAM-MAIN-AGENT-START" not in instruction_text
    assert "<!-- AGENTIC-TEAM-SUBAGENTS-START" not in instruction_text
    assert "## Available Subagents" in instruction_text
    assert "Standing user request" in instruction_text
    assert "If the subagent spawn fails, try to spawn it one more time" in instruction_text
    assert "On Codex, these definitions are project-scoped custom agents under `.codex/agents/`" in instruction_text
    assert "Do not search `.agents` for subagent definitions" in instruction_text
    assert "- `research-finalizer`:" in instruction_text
    assert "- `branch-committer`:" not in instruction_text
    assert "- `branch-commit-status`:" not in instruction_text
    assert "Request: `" not in instruction_text
    assert "Contract: `" in instruction_text
    assert "# Research Coordinator" in instruction_text
    assert "## Agentic Notes" in instruction_text
    assert "## Agent Branch" not in instruction_text
    assert "<!-- AGENTIC-TEAM-PROVIDER-START" not in instruction_text
    assert instruction_text.count("<!--") == 0
    assert "Org body." in instruction_text


def test_launcher_renders_builtin_systems_developer_main_agent(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "systems-developer",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0
    assert not (code / ".codex" / "agents" / "systems-developer.toml").exists()
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- AGENTIC-TEAM-MAIN-AGENT-START" not in instruction_text
    assert "# Systems Developer Instructions" in instruction_text
    assert "This is not a research experiment workflow." not in instruction_text


def test_launcher_renders_org_agents_and_overrides_builtin_agents(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-agent-extensions",
        {
            "agent-notes/all-agents/always-injected.md": "# Org Notes\n\nOrg body.\n",
            "capabilities/org-agents/capability.toml": (
                'description = "Organization agent extensions."\n'
                'requires = ["agentic-notes"]\n'
            ),
            "capabilities/org-agents/agents/experiment-runner.md": (
                "---\n"
                "name: experiment-runner\n"
                "kind: subagent\n"
                "description: Org-specific experiment runner.\n"
                "codex_reasoning_effort: low\n"
                "---\n\n"
                "You are the org-specific experiment runner.\n"
            ),
            "capabilities/org-agents/agents/data-curator.md": (
                "---\n"
                "name: data-curator\n"
                "kind: subagent\n"
                "description: Inspect datasets and splits.\n"
                "codex_reasoning_effort: medium\n"
                "---\n\n"
                "You are the org data curator.\n"
            ),
            "agent-notes/data-curator/always-injected.md": (
                "# Data Curator Agent Type\n\nUse the org dataset checklist.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] += ",org-agents"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
    )

    experiment_runner = code / ".codex" / "agents" / "experiment-runner.toml"
    data_curator = code / ".codex" / "agents" / "data-curator.toml"
    assert experiment_runner.exists()
    assert data_curator.exists()
    experiment_text = experiment_runner.read_text(encoding="utf-8")
    data_curator_text = data_curator.read_text(encoding="utf-8")
    assert "Org-specific experiment runner" in experiment_text
    assert "You are the org-specific experiment runner." in experiment_text
    assert 'model_reasoning_effort = "low"' in experiment_text
    assert "Run one clearly scoped experiment at a time." not in experiment_text
    assert "You are the org data curator." in data_curator_text
    assert "Use the org dataset checklist." in data_curator_text


def test_launcher_renders_org_main_agent_override_without_subagent(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-main-agents",
        {
            "capabilities/research-coordinator/capability.toml": (
                'description = "Organization research coordinator."\n'
                'requires = ["agentic-notes"]\n'
            ),
            "capabilities/research-coordinator/agents/research-coordinator.md": (
                "---\n"
                "name: research-coordinator\n"
                "kind: main\n"
                "description: Org research coordinator.\n"
                "codex_reasoning_effort: high\n"
                "---\n\n"
                "# Org Research Coordinator\n\n"
                "Use the org-specific research playbook.\n"
            ),
            "agent-notes/research-coordinator/always-injected.md": (
                "# Coordinator Agent Type Notes\n\nUse the org coordinator note.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Org Research Coordinator" in instruction_text
    assert "Use the org-specific research playbook." in instruction_text
    assert "# Research Coordinator Instructions" not in instruction_text
    assert "Use the org coordinator note." in instruction_text
    assert not (code / ".codex" / "agents" / "research-coordinator.toml").exists()


def test_launcher_renders_modular_main_agent_and_subagent(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-modular-agents",
        {
            "capabilities/demo/capability.toml": (
                'description = "Demo modular agents."\n'
                'requires = ["imperative-workflows"]\n'
            ),
            "capabilities/demo/package/demo/__init__.py": "",
            "capabilities/demo/package/demo/contract.py": (
                "class WorkflowRecord:\n"
                "    pass\n\n"
                "class AgentWorkflow(WorkflowRecord):\n"
                "    pass\n\n"
                "class SubagentWorkflow(AgentWorkflow):\n"
                "    pass\n\n"
                "class UserFacingWorkflow(AgentWorkflow):\n"
                "    pass\n\n"
                "def Value(description: str):\n"
                "    return None\n"
            ),
            "capabilities/demo/package/demo/main.py": (
                "from demo.contract import UserFacingWorkflow\n\n"
                "class ModularMain(UserFacingWorkflow):\n"
                "    pass\n"
            ),
            "capabilities/demo/package/demo/helper.py": (
                "from demo.contract import SubagentWorkflow, Value\n\n"
                "class ModularHelper(SubagentWorkflow):\n"
                "    summary: str = Value(\"helper request summary\")\n"
            ),
            "capabilities/demo/agents/modular-main.md": (
                "---\n"
                "name: modular-main\n"
                "kind: main\n"
                "description: Modular main agent.\n"
                "renderer: imperative-workflows\n"
                "workflow_interface: demo.main:ModularMain\n"
                "workflow_module: demo.workflows.main\n"
                "workflow_entry: ModularMainWorkflow\n"
                "---\n\n"
                "# Modular Main\n\n"
                "```python agentic-workflow\n"
                "from demo.helper import ModularHelper\n"
                "from demo.main import ModularMain\n\n"
                "class ModularMainWorkflow(ModularMain):\n"
                "    def workflow(self) -> None:\n"
                "        ModularHelper(summary=\"inspect state\").run()\n"
                "```\n"
            ),
            "capabilities/demo/agents/modular-helper.md": (
                "---\n"
                "name: modular-helper\n"
                "kind: subagent\n"
                "description: Modular helper agent.\n"
                "codex_reasoning_effort: low\n"
                "renderer: imperative-workflows\n"
                "workflow_interface: demo.helper:ModularHelper\n"
                "workflow_module: demo.workflows.helper\n"
                "workflow_entry: ModularHelperWorkflow\n"
                "---\n\n"
                "# Modular Helper\n\n"
                "```python agentic-workflow\n"
                "from demo.helper import ModularHelper\n\n"
                "class ModularHelperWorkflow(ModularHelper):\n"
                "    def workflow(self) -> None:\n"
                "        self.do([\"inspect requested state\"])\n"
                "```\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "modular-main",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    helper_text = (code / ".codex" / "agents" / "modular-helper.toml").read_text(
        encoding="utf-8"
    )
    assert "Call the `start_workflow` tool" in instruction_text
    assert "demo.workflows.main:ModularMainWorkflow" in instruction_text
    assert "## Callback-Managed Imperative Workflow" in instruction_text
    assert "class ModularHelperWorkflow" not in instruction_text
    assert "Call the `start_workflow` tool" in helper_text
    assert "demo.workflows.helper:ModularHelperWorkflow" in helper_text
    assert "class ModularHelperWorkflow" not in helper_text
    assert "workflow_interface:" not in instruction_text
    assert "workflow_module:" not in helper_text
    assert "```python agentic-workflow" not in instruction_text


def test_project_capability_can_provide_and_activate_main_agent(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    capability = project / ".agentic-team" / "capabilities" / "project-agent"
    (capability / "agents").mkdir(parents=True)
    (capability / "capability.toml").write_text(
        'description = "Project agent provider."\n'
        'requires = ["agentic-notes"]\n',
        encoding="utf-8",
    )
    (capability / "INSTRUCTIONS.md").write_text(
        "# Project Provider Instructions\n",
        encoding="utf-8",
    )
    (capability / "agents" / "project-main.md").write_text(
        "---\n"
        "name: project-main\n"
        "kind: main\n"
        "description: Project-local main agent.\n"
        "---\n\n"
        "# Project Main Agent\n\n"
        "Use the project-local workflow.\n",
        encoding="utf-8",
    )
    git(project, "add", ".agentic-team/capabilities/project-agent")
    git(project, "commit", "-m", "add project agent capability")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "project-main",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Project Main Agent" in instruction_text
    assert "# Project Provider Instructions" in instruction_text
    assert "## Agentic Notes" in instruction_text


def test_project_capability_replaces_builtin_provider_with_same_name(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    capability = project / ".agentic-team" / "capabilities" / "research-coordinator"
    (capability / "agents").mkdir(parents=True)
    (capability / "capability.toml").write_text(
        'description = "Project research provider."\n'
        'requires = ["agentic-notes"]\n',
        encoding="utf-8",
    )
    (capability / "agents" / "research-coordinator.md").write_text(
        "---\n"
        "name: research-coordinator\n"
        "kind: main\n"
        "description: Project research coordinator.\n"
        "---\n\n"
        "# Project Research Coordinator\n",
        encoding="utf-8",
    )
    git(project, "add", ".agentic-team/capabilities/research-coordinator")
    git(project, "commit", "-m", "override research coordinator")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"
    launch_args = at_launch_args(project, env)
    code = Path(launch_args[1])

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            *launch_args,
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    instruction_text = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Project Research Coordinator" in instruction_text
    assert "class ResearchCoordinator" not in instruction_text
    assert not (code / ".agents" / "skills" / "do_research" / "SKILL.md").exists()


def test_main_agent_branch_ownership_frontmatter_is_removed(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-main-agent-branch-ownership",
        {
            "capabilities/readonly-reporter/capability.toml": (
                'description = "Removed readonly reporter."\n'
                'requires = []\n'
            ),
            "capabilities/readonly-reporter/agents/readonly-reporter.md": (
                "---\n"
                "name: readonly-reporter\n"
                "kind: main\n"
                "description: Old readonly reporter.\n"
                "branch_ownership: readonly\n"
                "---\n\n"
                "# Readonly Reporter\n\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)
    launch_args = at_launch_args(project, env)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "readonly-reporter",
            *launch_args,
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "uses removed branch_ownership metadata" in result.stderr


def test_multiple_main_agents_use_separate_worktrees_and_project_agent_notes(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-paper-agent",
        {
            "capabilities/research-paper-author/capability.toml": (
                'description = "Research paper author."\n'
                'requires = ["agentic-notes"]\n'
            ),
            "capabilities/research-paper-author/agents/research-paper-author.md": (
                "---\n"
                "name: research-paper-author\n"
                "kind: main\n"
                "description: Draft papers from verified evidence.\n"
                "codex_reasoning_effort: high\n"
                "---\n\n"
                "# Research Paper Author Instructions\n\n"
                "Write from verified experiment logs and project agent-type notes.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    coordinator = clone_project(tmp_path, project_remote, name="project-coordinator")
    paper = tmp_path / "project-paper"
    run(["git", "-C", str(coordinator), "worktree", "add", "-b", "paper-draft", str(paper), "HEAD"])
    configure_git(paper)

    env = base_env(tmp_path, org_remote)
    env["AR_WORKSPACE_ROOT"] = str(tmp_path / "project-at")
    coordinator_args = at_launch_args(coordinator, env)
    coordinator_code = Path(coordinator_args[1])
    root = workspace_root(env)
    run([str(AGENTIC_WORKSPACE), "-C", str(root), "checkout", "paper-draft"], env=env)
    paper_code = root / "branches" / "paper-draft" / "code"
    paper_args = ["run", str(paper_code)]
    coordinator_note = tmp_path / "coordinator-note.md"
    coordinator_note.write_text(
        "# Research Coordinator Project Instructions\n\n"
        "Coordinator goal: run verified experiments.\n",
        encoding="utf-8",
    )
    paper_note = tmp_path / "paper-note.md"
    paper_note.write_text(
        "# Research Paper Author Project Instructions\n\n"
        "Paper goal: write the manuscript from verified evidence.\n",
        encoding="utf-8",
    )
    for agent_type, note in (
        ("research-coordinator", coordinator_note),
        ("research-paper-author", paper_note),
    ):
        run(
            [
                str(AGENTIC_NOTES_INTERNAL),
                "replace-note",
                "--project-dir",
                str(coordinator),
                "--scope",
                "project",
                "--agent-type",
                agent_type,
                "--note-name",
                "always-injected",
                "--note-file",
                str(note),
            ],
            env=env,
        )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    coordinator_launch = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "research-coordinator",
            *coordinator_args,
        ],
        env=env,
    )
    paper_launch = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "research-paper-author",
            *paper_args,
        ],
        env=env,
    )

    assert coordinator_launch.returncode == 0, coordinator_launch.stderr
    assert paper_launch.returncode == 0, paper_launch.stderr
    coordinator_text = (coordinator_code / "AGENTS.md").read_text(encoding="utf-8")
    paper_text = (paper_code / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Research Coordinator" in coordinator_text
    assert "# Research Paper Author Instructions" not in coordinator_text
    assert "# Research Paper Author Instructions" in paper_text
    assert "# Research Coordinator Instructions" not in paper_text
    assert "Coordinator goal: run verified experiments." in coordinator_text
    assert "Paper goal: write the manuscript" not in coordinator_text
    assert "Paper goal: write the manuscript from verified evidence." in paper_text
    assert "Coordinator goal: run verified experiments." not in paper_text
    state = state_checkout(env)
    assert (state / "agent-notes" / "research-coordinator" / "always-injected.md").exists()
    assert (state / "agent-notes" / "research-paper-author" / "always-injected.md").exists()
    assert not (state / "AGENTS.md").exists()
