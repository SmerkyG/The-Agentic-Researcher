# Agentic Team

### FORKED from The Agentic Researcher, with added features: notes-system for coordinated learning across projects and teams, native (non-sandboxed) mode, AMD GPU detection, gpu backend plugins, skills (instead of commands), and subagent role support.

**A Practical Guide to AI-Assisted Research in Mathematics and Machine Learning**

<p align="center">
  <img src="assets/main_figure.png" alt="The Agentic Researcher running parallel GPU training jobs inside a sandboxed container" width="700">
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2603.15914"><strong>Paper</strong></a> &middot;
  <a href="https://maxzimmer.org/the-agentic-researcher/"><strong>Project Page</strong></a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#workflow">Workflow</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="#citation">Citation</a>
</p>

<p align="center">
  <a href="https://maxzimmer.org">Max Zimmer</a> &middot;
  <a href="https://pelleriti.org">Nico Pelleriti</a> &middot;
  <a href="https://christopheroux.de">Christophe Roux</a> &middot;
  <a href="https://pokutta.com">Sebastian Pokutta</a>
  <br>
  <a href="https://iol.zib.de">IOL Lab</a> &middot; Zuse Institute Berlin & TU Berlin
</p>

---

The Agentic Researcher launches AI coding agents with structured research instructions, GPU workflow guidance, and optional filesystem isolation. The default path uses **sandboxed containers**; an opt-in native runtime runs the selected CLI directly on the host without containers or bind mounts.

Supports [Claude Code](https://github.com/anthropics/claude-code), [OpenCode](https://opencode.ai), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Codex CLI](https://github.com/openai/codex), and [pi](https://github.com/badlogic/pi-mono).

## Prerequisites

- **Docker** (default), **Podman**, or **Apptainer** (Linux only) for sandboxed mode, or a host-installed CLI tool for native mode
- An API key or OAuth login for your chosen CLI tool (see [supported tools](#supported-cli-tools))
- GPU drivers installed on the host if you want GPU passthrough
- Project dependencies managed with [uv](https://docs.astral.sh/uv/) (recommended) — the agent runs `uv sync` inside the sandbox

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/ZIB-IOL/The-Agentic-Researcher.git
cd The-Agentic-Researcher

# 2. Install
./scripts/install.sh

# 3a. Build container for Docker (default)
agentic-researcher --build

# 3b. Build container for Podman
agentic-researcher --podman --build

# 3c. Build container for Apptainer (Linux only)
agentic-researcher --apptainer --build

# 3d. Or use native mode on a project (no container build)
agentic-researcher --native --project-id my-project-2026 ~/my-project
```

Docker is the default runtime when available. If Docker is not installed or not on `PATH`, but Podman is, the launcher and install script automatically fall back to Podman for OCI builds. Podman uses the same OCI image and launch flow as Docker, but runs through the `podman` CLI instead. When building with Podman, the build script requests Docker image format (`podman build --format docker`) so Dockerfile `SHELL` directives keep working and Podman avoids noisy OCI-format warnings. By default the launcher stores state under `~/.cache/agentic-researcher` and launches Claude Code. Claude uses OAuth by default; other CLIs handle auth inside the tool, with standard API key env vars passed through if set.

## Configuration

Run `agentic-researcher --setup` to create a configuration file at `${XDG_CONFIG_HOME:-$HOME/.config}/agentic-researcher/config.sh`. The setup wizard lets you configure:

- **Runtime** — Docker, Podman, Apptainer, or native host execution
- **CLI tool** — Claude Code, OpenCode, Gemini CLI, Codex CLI, or pi
- **Authentication** — OAuth login or API key (with configurable env var name)
- **Custom API endpoint** — point Claude at an Anthropic-compatible proxy or gateway
- **State/cache directory** (`AR_STATE_ROOT`) — where caches, container `/tmp`, and tool state are stored. Defaults to `~/.cache/agentic-researcher`. On HPC systems with Apptainer, set this to a path with sufficient space (e.g. on a scratch filesystem) to avoid hitting the default 64 MB overlay limit
- **Extra environment variables** (`AR_EXTRA_ENV`) — pipe-separated `KEY=VALUE` pairs forwarded into the container (e.g. `HF_TOKEN=hf_...|WANDB_API_KEY=...`)
- **Network proxy** — HTTP/HTTPS proxy settings for use inside the container
- **Extra bind directories** — additional host paths to mount into the sandbox
- **GPU backend** — auto, none, cluster-run, or remote-run
- **Optional skills** (`AR_OPTIONAL_SKILLS`) — comma-separated selectable skills from `optional-skills/`
- **Project id** (`AR_PROJECT_ID` or `--project-id`) — required stable id for project notes and experiment logs

You can re-run `--setup` at any time to update your configuration.

## Usage

```bash
# Sandbox current directory with Claude Code (default)
agentic-researcher --project-id my-project-2026

# Sandbox a specific project directory
agentic-researcher --project-id my-project-2026 ~/my-project

# Use a different CLI tool
agentic-researcher --project-id my-project-2026 --tool gemini

# Run without containers or bind mounts
agentic-researcher --project-id my-project-2026 --native --tool codex

# Auto-approve all tool calls
agentic-researcher --project-id my-project-2026 --yolo
```

Native mode runs in your real host environment and does not provide Agentic Researcher filesystem isolation. Install the selected CLI tool on `PATH` before launching native mode.

### Project Git and Agentic Notes State

Agentic Researcher uses your normal project Git repository for code work and a separate Git-backed state branch for learned project notes and experiment logs. The agent's project worktree stays on your normal code branch; AR never switches it to the state branch.

Use AR from an ordinary project worktree. If you want project notes and experiment logs to be shared, the project Git repo should have a remote. Every launch must provide a stable project id, either with `--project-id`, `AR_PROJECT_ID`, or config:

```bash
agentic-researcher --setup AR_ROLE_ID=gpu-kernel-engineer
agentic-researcher --setup AR_ORG_NOTES_REPO=git@github.com:ORG/org-agentic-notes.git
agentic-researcher --project-id my-project-2026 .
```

On launch, AR creates or updates a cached checkout at `$AR_STATE_ROOT/projects/$AR_PROJECT_ID/agentic-state/` and uses the project `agentic/state` branch for:

```text
.agentic/notes/general.md
.agentic/experiment-log/COUNTER.yaml
.agentic/experiment-log/SUMMARY.md
.agentic/experiment-log/experiments/
```

When AR creates `agentic/state` for the first time, it creates an orphan branch with an empty starting fileset and commits only the `.agentic/` state files. It does not copy the current code tree, branch contents, datasets, or generated files into `agentic/state`. If `agentic/state` already exists on the remote, AR checks out and updates that existing state branch instead of recreating it.

If the project has no Git remote, AR still works, but the project state checkout is local to that AR installation and cannot be shared or pushed.

Multiple projects are supported within one AR installation. Each project gets a separate cache directory keyed by `AR_PROJECT_ID`. The project id is required; AR does not infer it from the directory name. For multi-worktree or multi-agent projects, pass the same `--project-id` or set the same `AR_PROJECT_ID` in every launch so all agents share the same notes and experiment log.

Multiple top-level agents can work in separate Git worktrees of the same project repo. Their code branches stay independent, while note and experiment-log operations are serialized through the shared cached `agentic/state` checkout. Subagents rendered by a top-level launch use the same project id and state checkout as their parent agent.

`report.tex` and `TODO.md` remain normal files in the project worktree. AR does not lock them, so they should be treated as branch-local narrative and checklist files rather than a shared multi-agent queue or canonical experiment index. The shared cross-agent experiment history is the locked experiment log on `agentic/state`.

See [docs/dynamic-notes.md](docs/dynamic-notes.md) for the notes repo layout, role notes, note-updater flow, and experiment log format.

### Multi-Node Dispatch (Slurm + Apptainer)

For multi-node Slurm allocations, the `--multi-node` flag starts a dispatcher that lets the agent run experiments on remote nodes via the `remote-run` command inside the container:

```bash
get_gpu 2 2                          # Allocate 2 nodes × 2 GPUs
agentic-researcher --project-id my-project-2026 --multi-node
agentic-researcher --project-id my-project-2026 --multi-node --test
```

Off by default. Requires Apptainer runtime and an active multi-node Slurm allocation. Single-node workflows are unaffected.

### GPU Backend Skills

Agentic Researcher can render project skills for GPU placement backends. In native mode, `AR_GPU_BACKEND=auto` uses `cluster-run` when it is available on `PATH`; otherwise no external GPU backend is configured.

Skill definitions start from neutral Agentic Researcher sources. Always-on skills live in `skills/`; selectable skills live in `optional-skills/`. Both are rendered into the selected CLI's project discovery path: `.claude/skills` for Claude, `.gemini/skills` for Gemini, `.opencode/skills` for OpenCode, and `.agents/skills` for Codex/pi. If a selected skill has `INSTRUCTIONS.md`, that file is also injected into the workspace instruction file.

Subagent definitions start from neutral Markdown files in `agents/` and are rendered into the selected CLI's project agent path: `.claude/agents` for Claude, `.gemini/agents` for Gemini, `.opencode/agents` for OpenCode, and `.codex/agents` for Codex. Add `codex_reasoning_effort: low|medium|high` to an agent's frontmatter to render Codex `model_reasoning_effort` for that subagent.

```bash
agentic-researcher --project-id my-project-2026 --native --gpu-backend cluster-run
agentic-researcher --project-id my-project-2026 --optional-skill cluster-run
cluster-run status
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

The existing `--multi-node` flow selects the `remote-run` backend for Apptainer plus Slurm allocations.

To add lab- or site-specific backends, create an optional skill under `optional-skills/` and enable it with `--optional-skill`. See [docs/extending-ar.md](docs/extending-ar.md) for the optional skill layout, custom GPU backend checklist, and when launcher changes are needed.

## Supported CLI Tools

| Tool | Instruction file | Provider | Flag |
|------|-----------------|----------|------|
| [Claude Code](https://github.com/anthropics/claude-code) | `CLAUDE.md` | Anthropic | `--tool claude` (default) |
| [OpenCode](https://opencode.ai) | `AGENTS.md` | Any (LiteLLM) | `--tool opencode` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Google | `--tool gemini` |
| [Codex CLI](https://github.com/openai/codex) | `AGENTS.md` | OpenAI | `--tool codex` |
| [pi](https://github.com/badlogic/pi-mono) | `AGENTS.md` | Any | `--tool pi` |

At launch, AR also renders a project-local compaction hook for the selected CLI. After context compaction, the hook uses `$AR_NOTES_CLI` to pull the org notes and project `agentic/state` checkouts under local locks, rematerializes the instruction file rendered for that exact invocation (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`), tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary, asks it to read the refreshed instruction file, and then resumes the task it was already doing. In container mode the AR runtime is mounted read-only at `/opt/agentic-researcher`, while `AR_STATE_ROOT` is mounted read-write so the org checkout and project state branch can be updated. Claude and Codex use compact-session hooks, Gemini uses `PreCompress` plus a one-shot `BeforeModel` refresh, OpenCode uses a compaction plugin, and pi uses a launch-specific extension.

## Workflow

### Starting a New Project

1. **Launch** the sandbox from your project directory: e.g., `agentic-researcher --project-id my-project-2026 --yolo`
2. **Ask the agent to use the `setup_research_plan` skill.** This starts an interactive dialogue that asks about your research goal, evaluation metrics, constraints, and compute budget.
3. The agent fills in the **Project Instructions** section of the instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`) and creates branch-local research files such as `report.tex` and `TODO.md`.

### Resuming a Session

When you relaunch the sandbox on a project that already has filled-in instructions, using the `setup_research_plan` skill will automatically detect the existing state, read the shared experiment summary when available, consult branch-local `report.tex` and `TODO.md`, and summarize where the project left off before continuing.

## Architecture

### Sandbox

| Layer | Details |
|-------|---------|
| **Filesystem isolation** | The agent can write `/workspace` and the mounted `AR_STATE_ROOT`; the AR runtime is mounted read-only at `/opt/agentic-researcher`; extra directories from `AR_EXTRA_BIND_DIRS` are mounted under `/workspace/.mount/<basename>` |
| **Namespace isolation** | Apptainer `--compat` enables user/mount namespaces |
| **Path traversal protection** | Symlinks resolved; system directories blocked |

`--yolo` auto-approves tool calls but does **not** weaken filesystem isolation.

Native mode intentionally disables Agentic Researcher filesystem isolation: the selected CLI runs directly in the project directory with your host `HOME`, `PATH`, and credentials.

### Research Agent Instructions

The framework ships `INSTRUCTIONS.md` as a canonical template containing universal research commandments (e.g., never manipulate evaluation, one variable per experiment, record everything) and domain-specific modules for mathematical and compute-intensive research. At launch it is copied into the workspace under the filename required by the selected tool. The `setup_research_plan` skill then fills in the project-specific section through an interactive dialogue.

## Citation

If you use this framework, please cite our paper:

```bibtex
@misc{zimmer2026agenticresearcherpracticalguide,
  title         = {The Agentic Researcher: A Practical Guide to AI-Assisted Research
                   in Mathematics and Machine Learning},
  author        = {Max Zimmer and Nico Pelleriti and Christophe Roux and Sebastian Pokutta},
  year          = {2026},
  eprint        = {2603.15914},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/2603.15914}
}
```

## License

This project is licensed under the [MIT License](LICENSE).

## Disclaimer

The sandboxing provided by this framework is designed to limit the agent's filesystem access, but it comes with **no guarantee of security**. The authors assume no responsibility for any damage, data loss, or unintended behavior resulting from the use of this software. Use at your own risk.
