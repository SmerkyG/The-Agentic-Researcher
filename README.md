# Agentic Team

### FORKED from The Agentic Researcher, with added features: notes-system for coordinated learning across projects and teams, native (non-sandboxed) mode, AMD GPU detection, gpu backend plugins, skills (instead of commands), and subagent role support.

**A Practical Guide to AI-Assisted Research in Mathematics and Machine Learning**

<p align="center">
  <img src="assets/main_figure.png" alt="The Agentic Researcher running parallel GPU training jobs inside a sandboxed container" width="700">
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2603.15914"><strong>Paper</strong></a> &middot;
  <a href="https://maxzimmer.org/the-agentic-researcher/"><strong>Project Page</strong></a> &middot;
  <a href="#installation">Installation</a> &middot;
  <a href="#workflow">Workflow</a> &middot;
  <a href="#org-notes">Org Notes</a> &middot;
  <a href="#runtimes">Runtimes</a> &middot;
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

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/ZIB-IOL/The-Agentic-Researcher.git
cd The-Agentic-Researcher

# 2. Install
./scripts/install.sh
```

The installer adds the `agentic-researcher` launcher and creates optional local configuration when requested.

Optional: configure a shared org notes repo if you want organization-wide notes, role-specific notes, or org-provided agents to follow this AR installation across projects. Create the local config first if it does not already exist:

```bash
agentic-researcher --setup
agentic-researcher --setup AR_ORG_NOTES_REPO=git@github.com:ORG/org-agentic-notes.git
agentic-researcher --setup AR_MAIN_AGENT=research-paper-author
```

`AR_MAIN_AGENT` defaults to `research-coordinator`. Only change it when the AR install or org notes repo provides another `kind: main` agent. Org notes are optional. Without them, AR still maintains project notes and the shared experiment log on the project's `agentic/state` branch. See [Org Notes](#org-notes) for the repo layout and when to use it.

## Workflow

### Starting a New Project

1. **Start from a normal project Git checkout.** The checkout should usually have an `origin` remote so AR can derive the project identity from the repo name automatically.
2. **Run AR from that checkout:** `cd ~/my-project && agentic-researcher .`. For auto-approved Claude permissions, add `--yolo`.
3. **For a new research effort, ask the default `research-coordinator` main agent to use the `setup_research_plan` skill.** This starts an interactive dialogue about your research goal, evaluation metrics, constraints, and compute budget.
4. The agent fills in the **Project Instructions** section of the instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`) and creates branch-local research files such as `report.tex` and `TODO.md`.

If the project has no Git remote, pass `--project-id` or set `AR_PROJECT_ID` so repeated launches use the same notes and experiment-log state.

### Resuming a Session

Relaunch AR from the same project Git checkout or another worktree with the same resolved project identity. The rendered instructions tell the agent to read the project instructions, shared experiment summary, branch-local `report.tex`, and `TODO.md` before continuing. Use `setup_research_plan` on resume only when you want a structured recap or to revise the project plan.

## Runtimes

The default runtime is Docker when available. If Docker is not installed or not on `PATH`, but Podman is, the launcher and install script automatically fall back to Podman for OCI launches and builds.

In container mode, AR builds the missing container image automatically on first launch. Use `container/build.sh --runtime docker|podman|apptainer` only when you want to prebuild or rebuild manually. Podman uses the same OCI image and launch flow as Docker, but runs through the `podman` CLI instead. When building with Podman, the build script requests Docker image format (`podman build --format docker`) so Dockerfile `SHELL` directives keep working and Podman avoids noisy OCI-format warnings.

Apptainer is supported on Linux and is the runtime used for the multi-node Slurm flow. Native mode skips containers entirely and runs the selected CLI directly in your host environment:

```bash
agentic-researcher --runtime native --tool codex ~/my-project
```

Native mode does not provide Agentic Researcher filesystem isolation. Install the selected CLI tool on `PATH` before launching native mode.

## Configuration

Run `agentic-researcher --setup` to create a configuration file at `${XDG_CONFIG_HOME:-$HOME/.config}/agentic-researcher/config.sh`. The setup wizard lets you configure:

- **Runtime** — Docker, Podman, Apptainer, or native host execution
- **CLI tool** — Claude Code, OpenCode, Gemini CLI, Codex CLI, or pi
- **Authentication** — OAuth login or API key (with configurable env var name)
- **Custom API endpoint** — point Claude at an Anthropic-compatible proxy or gateway
- **Org notes repo** (`AR_ORG_NOTES_REPO`) — optional shared Git repo for organization-wide and role-specific notes
- **Main agent** (`AR_MAIN_AGENT`) — top-level agent definition to render into the workspace instruction file. Defaults to `research-coordinator`
- **State/cache directory** (`AR_STATE_ROOT`) — where caches, container `/tmp`, and tool state are stored. Defaults to `~/.cache/agentic-researcher`. On HPC systems with Apptainer, set this to a path with sufficient space (e.g. on a scratch filesystem) to avoid hitting the default 64 MB overlay limit
- **Extra environment variables** (`AR_EXTRA_ENV`) — pipe-separated `KEY=VALUE` pairs forwarded into the container (e.g. `HF_TOKEN=hf_...|WANDB_API_KEY=...`)
- **Network proxy** — HTTP/HTTPS proxy settings for use inside the container
- **Extra bind directories** — additional host paths to mount into the sandbox
- **GPU backend** — auto, none, cluster-run, or remote-run
- **Auto-build** (`AR_AUTO_BUILD`) — whether missing container images should be built automatically on first launch
- **Optional skills** (`AR_OPTIONAL_SKILLS`) — comma-separated selectable skills from `optional-skills/`
- **Project identity override** (`AR_PROJECT_ID` or `--project-id`) — optional stable id for projects without a Git remote, forks that should share state, or other custom grouping

You can re-run `--setup` at any time to update your configuration.

## Usage

```bash
# Sandbox current directory with Claude Code (default)
agentic-researcher

# Sandbox a specific project directory
agentic-researcher ~/my-project

# Use a different CLI tool
agentic-researcher --tool gemini

# Run without containers or bind mounts
agentic-researcher --runtime native --tool codex

# Auto-approve all tool calls
agentic-researcher --yolo

# Override the inferred project identity when needed
agentic-researcher --project-id my-project-2026 ~/my-project
```

### Project Git and Agentic Notes State

Agentic Researcher uses your normal project Git repository for code work and a separate Git-backed state branch for learned project notes and experiment logs. The agent's project worktree stays on your normal code branch; AR never switches it to the state branch.

Use AR from an ordinary project worktree. If the project Git repo has an `origin` remote, AR derives the project identity from the remote repo name by default. For example, `https://github.com/SmerkyG/abctest` resolves to project id `abctest`. You can override that identity with `--project-id`, `AR_PROJECT_ID`, or config when the project has no remote, when two unrelated repos share the same repo name, or when you want a custom grouping:

```bash
agentic-researcher .
```

Organization-wide and role-specific notes are optional; configure `AR_ORG_NOTES_REPO` only when you want that shared layer.

On launch, AR creates or updates a cached checkout at `$AR_STATE_ROOT/projects/<project-id>/agentic-state/` and uses the project `agentic/state` branch for:

```text
.agentic/notes/always-injected.md
.agentic/experiment-log/COUNTER.yaml
.agentic/experiment-log/SUMMARY.md
.agentic/experiment-log/experiments/
```

When AR creates `agentic/state` for the first time, it creates an orphan branch with an empty starting fileset and commits only the `.agentic/` state files. It does not copy the current code tree, branch contents, datasets, or generated files into `agentic/state`. If `agentic/state` already exists on the remote, AR checks out and updates that existing state branch instead of recreating it.

If the project has no Git remote, pass `--project-id` or set `AR_PROJECT_ID`. The project state checkout is then local to that AR installation and cannot be shared or pushed unless the project later gets a remote.

Multiple projects are supported within one AR installation. Each project gets a separate cache directory keyed by the resolved project id. AR does not infer project identity from the directory name. For multi-worktree or multi-agent projects, use worktrees whose `origin` remotes have the same repo name, or pass the same `--project-id` or set the same `AR_PROJECT_ID` in every launch so all agents share the same notes and experiment log.

Multiple top-level agents can work in separate Git worktrees of the same project repo. Their code branches stay independent, while note and experiment-log operations are serialized through the shared cached `agentic/state` checkout. Subagents rendered by a top-level launch use the same project id and state checkout as their parent agent.

`report.tex` and `TODO.md` remain normal files in the project worktree. AR does not lock them, so they should be treated as branch-local narrative and checklist files rather than a shared multi-agent queue or canonical experiment index. The shared cross-agent experiment history is the locked experiment log on `agentic/state`.

See [docs/dynamic-notes.md](docs/dynamic-notes.md) for the notes repo layout, role notes, note-updater flow, experiment-logger flow, and experiment log format.

### Multi-Node Dispatch (Slurm + Apptainer)

For multi-node Slurm allocations, the `--multi-node` flag starts a dispatcher that lets the agent run experiments on remote nodes via the `remote-run` command inside the container:

```bash
get_gpu 2 2                          # Allocate 2 nodes × 2 GPUs
agentic-researcher --runtime apptainer --multi-node
agentic-researcher --runtime apptainer --multi-node --test
```

Off by default. Requires Apptainer runtime and an active multi-node Slurm allocation. Single-node workflows are unaffected.

### GPU Backend Skills

Agentic Researcher can render project skills for GPU placement backends. In native mode, `AR_GPU_BACKEND=auto` uses `cluster-run` when it is available on `PATH`; otherwise no external GPU backend is configured.

Skill definitions start from neutral Agentic Researcher sources. Always-on skills live in `skills/`; selectable skills live in `optional-skills/`. Both are rendered into the selected CLI's project discovery path: `.claude/skills` for Claude, `.gemini/skills` for Gemini, `.opencode/skills` for OpenCode, and `.agents/skills` for Codex/pi. If a selected skill has `INSTRUCTIONS.md`, that file is also injected into the workspace instruction file.

Agent definitions start from neutral Markdown files in AR's built-in `agents/` directory and optional org repo `agents/` directory. A definition with `kind: main` can be selected with `AR_MAIN_AGENT` and is inserted into the top-level instruction file. A definition with `kind: subagent` is rendered into the selected CLI's project agent path: `.claude/agents` for Claude, `.gemini/agents` for Gemini, `.opencode/agents` for OpenCode, and `.codex/agents` for Codex. Org repo agents render after built-ins, so org agents win on name conflict. Add `codex_reasoning_effort: low|medium|high` to an agent's frontmatter to render Codex `model_reasoning_effort` for that agent where supported. To add agents and roles, see [docs/extending-ar.md](docs/extending-ar.md#agents-and-roles).

```bash
agentic-researcher --runtime native --gpu-backend cluster-run
agentic-researcher --optional-skill cluster-run
cluster-run status
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

The existing `--multi-node` flow selects the `remote-run` backend for Apptainer plus Slurm allocations.

To add lab- or site-specific backends, create an optional skill under `optional-skills/` and enable it with `--optional-skill`. See [docs/extending-ar.md](docs/extending-ar.md) for the optional skill layout, custom GPU backend checklist, and when launcher changes are needed.

## Org Notes

An org notes repo is optional shared memory for guidance and learned lessons that should follow agents across multiple projects or AR installations. Use it for lab-wide conventions, shared infrastructure notes, package gotchas, benchmark rules, role-specific habits, or org-provided main agents and subagents. An empty org notes repo is a valid starting point when you want AR to accumulate organization-wide and role-specific notes over time. It just will not inject or list org/role guidance until notes have been added.

For immediate useful guidance, seed the repo from the example layout in [examples/org-notes/](examples/org-notes/):

```text
agents/
  data-curator.md          # kind: subagent rendered for every install
  research-paper-author.md # kind: main selectable with AR_MAIN_AGENT
notes/
  always-injected.md      # short organization-wide guidance injected every time
  git.md                  # on-demand topic note listed for relevant work
roles/
  research-coordinator/
    notes/
      always-injected.md  # injected for the default main agent
  gpu-kernel-engineer/
    notes/
      always-injected.md  # injected for that role id
```

Put only short, high-value guidance in `always-injected.md`. Put longer or situational details in topic notes such as `notes/git.md`, `notes/slurm.md`, `notes/pytorch.md`, or `roles/gpu-kernel-engineer/notes/benchmarking.md`; AR lists those notes so agents can read them only when relevant.

Org-provided agents in `agents/*.md` use the same neutral Markdown format as AR's built-in agents. They are rendered after built-ins, so an org agent with the same `name` as a built-in agent wins. `AR_MAIN_AGENT` selects both the top-level main-agent definition and the role-specific notes for that top-level agent. Subagents use their own `name` as the role id for role notes.

See [docs/dynamic-notes.md](docs/dynamic-notes.md) for the full notes layout and [docs/extending-ar.md](docs/extending-ar.md#agents-and-roles) for the agent format.

## Supported CLI Tools

| Tool | Instruction file | Provider | Flag |
|------|-----------------|----------|------|
| [Claude Code](https://github.com/anthropics/claude-code) | `CLAUDE.md` | Anthropic | `--tool claude` (default) |
| [OpenCode](https://opencode.ai) | `AGENTS.md` | Any (LiteLLM) | `--tool opencode` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Google | `--tool gemini` |
| [Codex CLI](https://github.com/openai/codex) | `AGENTS.md` | OpenAI | `--tool codex` |
| [pi](https://github.com/badlogic/pi-mono) | `AGENTS.md` | Any | `--tool pi` |

At launch, AR also renders a project-local compaction hook for the selected CLI. After context compaction, the hook uses `$AR_NOTES_CLI` to pull the org notes and project `agentic/state` checkouts under local locks, rematerializes the instruction file rendered for that exact invocation (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`), tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary, asks it to read the refreshed instruction file, and then resumes the task it was already doing. In container mode the AR runtime is mounted read-only at `/opt/agentic-researcher`, while `AR_STATE_ROOT` is mounted read-write so the org checkout and project state branch can be updated. Claude and Codex use compact-session hooks, Gemini uses `PreCompress` plus a one-shot `BeforeModel` refresh, OpenCode uses a compaction plugin, and pi uses a launch-specific extension.

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
