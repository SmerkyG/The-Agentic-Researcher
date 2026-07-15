# Agentic Team

**Sandboxed Agents That Learn From Their Mistakes Across Agents, Projects, and Teams**

<p align="center">(Forked and rewritten from original repo: The Agentic Researcher)</p>

<p align="center">
  <a href="#problem-statement">Problem Statement</a> &middot;
  <a href="#design-concepts">Design Concepts</a> &middot;
  <a href="#installation">Installation</a> &middot;
  <a href="#workflow">Workflow</a> &middot;
  <a href="#org-repo">Org Repo</a> &middot;
  <a href="#sandbox">Sandbox</a> &middot;
  <a href="#architecture">Architecture</a>
</p>

---

Agentic Team launches AI coding agents that learn from their mistakes and share those learnings with one another, with structured research instructions, workflow guidance, and optional filesystem isolation. The default path uses **sandboxed containers**; `--sandbox none` runs the selected CLI directly on the host without containers or bind mounts. It comes with task workflows for performing Math/ML Research and writing research papers, and supports adding your own new task workflows and custom state management capabilities.

LLM CLIs supported: [Claude Code](https://github.com/anthropics/claude-code), [OpenCode](https://opencode.ai), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Codex CLI](https://github.com/openai/codex), and [pi](https://github.com/badlogic/pi-mono). Sandboxing optionally supported via Docker, Podman, or Apptainer. Cluster job-queue support is provided through capability packages, with Slurm capabilities included.

## Problem Statement

Long-running agent teams have a memory problem: agents make mistakes, discover missing knowledge, learn local conventions, and uncover tool or infrastructure gotchas, but those lessons usually disappear with the session or context compaction. The next agent, project, or team repeats the same failure because the learning was not captured in a place other agents can use.

Agentic Team's solution is simple: agents take notes and store them in Git. These are kept in your project repo but separate from your normal code branches at project and work-branch scopes. Org-wide notes live in their own separate Git repo. All of these Git-backed notes are shared across agents, projects, installations, and teams through ordinary Git review and merge workflows. Notes apply to either `all-agents` or a specific agent-type.

There are two note modes. `always-injected.md` notes are short, high-value guidance injected into the agent's startup context. On-demand note topics are listed in the generated instructions but read only when relevant; agents read them through `agentic-notes read-note`, which dynamically combines the organization, project, and work-branch portions for `all-agents` plus the current agent type.

The storage layout is simple enough that you can add or edit note files directly if you wish. Working agents read notes through the rendered view rather than opening raw note storage files and are given commands for creating note updates.

## Design Concepts

Agentic Team is split into a small launcher, a shared Git-backed state substrate, and optional capabilities.

**Launcher.** The `agentic-team` command prepares the selected project worktree, materializes the invocation-specific instruction file (`AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`), renders the selected main agent and subagent definitions, runs enabled capability hooks, sets up PATH/env/binds, and then launches the selected LLM CLI in the selected sandbox. The launcher owns CLI and sandbox integration, instruction materialization, AT work entry prompts, and capability selection. It does not own the schemas for notes or experiment logs.

**Agentic State.** Agentic State is the shared storage substrate used by capabilities. It manages visible Git worktrees under `$AR_WORKSPACE_ROOT`, serializes local project/work updates with locks under `$AR_RUNTIME_ROOT`, and performs ordinary Git fetch/merge/commit/push operations. Organization scope lives in the optional org repo. Project scope lives on the project repo's orphan `agentic/project-state` branch. Work-branch scope lives on one orphan `agentic/work-state/<work-branch>` branch per work branch. Agentic State provides the storage mechanics; capabilities decide what files and schemas they store there.

**Capabilities.** Capabilities are selected packages that can add commands, instruction sections, launcher hooks, and stateful workflows. Built-in capabilities include:

- **Agentic Notes** (`agentic-notes`): owns `agent-notes/` layout at org, project, and work-branch scopes; renders `always-injected.md` content and on-demand note topic lists; provides the `agentic-notes` command with `read-note`, `update-note`, and `rewrite-note` subcommands.
- **Experiment Log** (`experiment-log`): owns `experiment-log/` files on the active work state branch; records experiment YAML files, `COUNTER.yaml`, and append-maintained `SUMMARY.md`; provides the `experiment-log` command with `append`, `correct`, and `summary` subcommands.

This separation is intentional: the launcher can stay mostly about launching and rendering, Agentic State can stay about Git-backed state mechanics, and each capability can evolve its own command surface and data model.

## Prerequisites

- You use **Git** for your projects
- **Docker** (default), **Podman**, or **Apptainer** (Linux only) for sandboxed mode, or a host-installed LLM CLI for `--sandbox none`
- An API key or OAuth login for your chosen CLI (see [supported CLIs](#supported-clis))
- GPU drivers installed on the host if you want GPU passthrough
- Project dependencies managed with [uv](https://docs.astral.sh/uv/) (recommended) — the agent runs `uv sync` inside the sandbox

## Installation

```bash
# 1. Install the launcher
./scripts/install.sh

# 2. Configure local defaults
agentic-team --setup
```

The installer adds the `agentic-team` launcher. The setup wizard creates local configuration, asks whether to use an org repo, and asks which main agent to use. Keep the default `research-coordinator` unless the Agentic Team install or org repo provides another `kind: main` agent. The org repo is optional. Without it, Agentic Team still maintains project state on the project's `agentic/project-state` branch and work-branch-local records on `agentic/work-state/<work-branch>` branches. Local code and state worktrees live under a visible sibling AT workspace such as `treeattention-at/`. See [Org Repo](#org-repo) for setup guidance.

## Workflow

### Starting the First Agent

1. **Start from the normal project checkout.** Pass the checkout directory you want AT to use as the project source. Agentic Team uses the checkout's current branch or ref as the starting point for the first AT work entry, and uses the checkout directory name for the default sibling AT workspace:

   ```bash
   agentic-team ~/my-project
   ```

2. **Create or choose the AT workspace when prompted.** Launching from the normal checkout always enters the AT setup flow because AT needs a separate workspace for code worktrees, state worktrees, artifacts, and runtime files. Accept the default sibling directory `../my-project-at` unless you want a different AT workspace root.
3. **Create a new AT work entry when prompted.** Enter a stable work name such as `research-main`. Agentic Team creates `<work-name>/code` and `<work-name>/state` under the AT workspace, backed by the corresponding code branch and work-state branch.
4. **Ask the launched agent to initialize the research workflow.** Your selected LLM CLI is now running in the AT worktree. For a new research effort, invoke the `do_research` skill. In Codex, type `$do_research` or select it from `/skills`. This starts the setup dialogue about the research goal, evaluation metrics, constraints, and compute budget.
5. Research workflows create a short rolling `condensed_report.md`, numbered report
   pages (`report_page1.md` is oldest and the highest number is current), a
   `TODO.md` checklist, report figures, and
   an experiment log under the AT workspace's `<work-name>/state/` directory.

### Resuming a Session

Relaunch Agentic Team by naming the AT workspace and work entry:

```bash
agentic-team ~/my-project-at research-main
```

### Running More Agents in Parallel

Each AT agent requires its own branch. To create and launch a new AT branch forked from an existing branch, use `--from`:

```bash
agentic-team ~/my-project-at kdtree-bounds --from research-main
```

If `--from` names only a Git ref such as `main` or `dev`, the new work starts the same way as your first agent would. If `--from` names an existing AT work entry (e.g. `research-main`), enabled capabilities inherit relevant state context for reference by the new agent. Use `--state clean` to skip inherited context when creating from an AT work entry.

## Sandbox

The default sandbox is Docker when available. If Docker is not installed or not on `PATH`, but Podman is, the launcher and install script automatically fall back to Podman for OCI launches and builds.

In container mode, Agentic Team builds the missing container image automatically on first launch. Use `container/build.sh --runtime docker|podman|apptainer` only when you want to prebuild or rebuild manually. Podman uses the same OCI image and launch flow as Docker, but runs through the `podman` CLI instead. When building with Podman, the build script requests Docker image format (`podman build --format docker`) so Dockerfile `SHELL` directives keep working and Podman avoids noisy OCI-format warnings.

Apptainer is supported on Linux and is the sandbox used for Slurm `remote-run` dispatch. `--sandbox none` skips containers entirely and runs the selected CLI directly in your host environment:

```bash
agentic-team --sandbox none --cli codex ~/my-project-at/research-main/code
```

`--sandbox none` does not provide Agentic Team filesystem isolation. Install the selected CLI on `PATH` before using it.

## Configuration

Run `agentic-team --setup` to create a configuration file at `${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team/config.sh`. The configuration file supports:

- **Sandbox** — Docker, Podman, Apptainer, or none host execution
- **CLI** — Claude Code, OpenCode, Gemini CLI, Codex CLI, or pi
- **Authentication** — OAuth login or API key (with configurable env var name)
- **Custom API endpoint** — point Claude at an Anthropic-compatible proxy or gateway
- **Org repo** (`AR_ORG_NOTES_REPO`) — optional shared Git repo for organization-wide notes, agents, and capabilities
- **Main agent** (`AR_MAIN_AGENT`) — top-level agent definition to render into the workspace instruction file. Defaults to `research-coordinator`
- **Work branch** (`AR_WORK_BRANCH` or `--work-branch`) — Git branch used by the top-level agent. Each top-level agent requires its own branch.
- **Git identity** (`AR_GIT_NAME`, `AR_GIT_EMAIL`) — repo-local fallback identity for Agentic Team-created commits when the project checkout does not already have `user.name` / `user.email`
- **AT workspace root** (`AR_WORKSPACE_ROOT`) — optional override for the visible workspace root that contains linked worktrees for `project-state/` plus `<work-name>/code` and `<work-name>/state`. By default it is a sibling named `<checkout-dir-name>-at`
- **Project runtime root** (`AR_RUNTIME_ROOT`) — optional override for hidden per-project runtime machinery. Defaults to `$AR_WORKSPACE_ROOT/.runtime`
- **Project artifacts directory** (`AR_ARTIFACTS_DIR`) — optional override for bulky shared project artifacts. Defaults to `$AR_WORKSPACE_ROOT/artifacts/project`
- **Global state/cache directory** (`AR_STATE_ROOT`) — where shared caches, container `/tmp`, CLI config state, and the optional org repo checkout are stored. Defaults to `~/.cache/agentic-team`. On HPC systems with Apptainer, set this to a path with sufficient space (e.g. on a scratch filesystem) to avoid hitting the default 64 MB overlay limit
- **Extra environment variables** (`AR_EXTRA_ENV`) — pipe-separated `KEY=VALUE` pairs forwarded into the container (e.g. `HF_TOKEN=hf_...|WANDB_API_KEY=...`)
- **Additional writable storage** (`AR_STORAGE_DIRS`) — a Bash array of `ENV_NAME=/absolute/host/path` entries. Matching names override built-in cache locations; new names are mounted into sandboxes at `/agent-storage/ENV_NAME` and exported to the agent
- **Network proxy** — HTTP/HTTPS proxy settings for use inside the container
- **Extra bind directories** — additional host paths to mount into the sandbox
- **Auto-build** (`AR_AUTO_BUILD`) — whether missing container images should be built automatically on first launch
- **Capabilities** (`AR_CAPABILITIES`) — comma-separated capability packages from `capabilities/`
- **Agentic Notes refresh** (`AR_NOTES_REFRESH_MODE`, `AR_NOTES_REFRESH_INTERVAL_SECONDS`) — defaults to periodic background refresh every 120 seconds while at least one agent for the project is running; set mode to `foreground` for synchronous launch refresh or `manual` to disable periodic refresh
- **Startup profiling** (`AR_PROFILE_STARTUP=true`) — print per-phase launcher setup timings to stderr before the selected CLI starts

For example, add arbitrary writable tool storage or relocate one built-in cache
in `config.sh`:

```bash
AR_STORAGE_DIRS=(
    "TRITON_CACHE_DIR=/scratch/local/$USER/triton"
    "MY_MODEL_CACHE=/shared/cache/models"
)
```

In native mode, each variable receives its host path directly. In a sandbox,
the launcher mounts each directory and sets the variable to
`/agent-storage/ENV_NAME`. Built-in UV paths retain their established `/uv-*`
destinations. Later entries replace earlier entries with the same variable name.

You can re-run `--setup` at any time to update your configuration.

## Usage

```bash
# Start from the normal project checkout; create an AT worktree if prompted
agentic-team ~/my-project

# Resume an existing AT effort
agentic-team ~/my-project-at/research-main/code

# Use a different CLI
agentic-team --cli gemini ~/my-project-at/research-main/code

# Run without containers or bind mounts
agentic-team --sandbox none --cli codex ~/my-project-at research-main

# Materialize AGENTS.md/CLAUDE.md/GEMINI.md and managed subagent files without launching a CLI
agentic-team --render-only --cli codex ~/my-project-at research-main

# Auto-approve all tool calls
agentic-team --yolo ~/my-project-at research-main

# Use a different top-level agent for this launch
agentic-team --main-agent research-paper-author ~/my-project-at paper

# Interactive Linux-focused systems/tooling development
agentic-team --main-agent systems-developer ~/my-project-at systems

# Create a parallel AT effort from an existing AT work entry
agentic-team ~/my-project-at kdtree-bounds --from research-main

# Create AT work noninteractively from a normal project checkout/ref
agentic-team ~/my-project-at research-main --from main --project-dir ~/my-project

# Launch an explicit nested code worktree path
agentic-team --worktree-path ~/my-project-at/research-main/code
```

### Required Workspace Layout

Agentic Team uses a fixed AT workspace layout. Keep your normal checkout on the branch you use as the human integration point, usually `main`; Agentic Team creates sibling AT workspace entries for agent work:

```text
my-project/                         # normal checkout, usually main
my-project-at/
  project -> ../my-project          # pointer back to the normal checkout
  artifacts/
    project/                        # shared bulky experiment artifacts
  project-state/                    # worktree for agentic/project-state
  research-main/
    code/                           # Git worktree for the derived code branch
    state/                          # worktree for the matching work-state branch
  kdtree-bounds/
    code/                           # another top-level agent worktree
    state/                          # matching work-state worktree
  .runtime/                         # hidden locks, snapshots, and temporary finalizer worktrees
```

The local `project-state/`, `<work-name>/code/`, and `<work-name>/state/` directories are linked Git worktrees of the project repo. The state worktrees use orphan state branches rather than normal code branches. They are intentionally visible so reports, TODOs, figures, notes, and experiment logs are easy to find. The hidden `.runtime/` directory is launcher-managed project machinery.

Bulky reusable experiment outputs go under the AT workspace's `artifacts/project/` directory by default and are exposed to agents as `$AR_ARTIFACTS_DIR`. Use unique run or experiment subdirectories there for new writes. Work-state report figures are different: keep report-ready PNG/PDF files under `<work-name>/state/images/` so report-page links remain self-contained and Git-backed.

### Project Git and Agentic State

Agentic Team uses your normal project Git repository for code work plus separate Git-backed state branches for agent-facing state. The original project checkout can stay on your normal human branch. AT code and state worktrees live under the visible AT workspace root, usually a sibling directory named `<checkout-dir-name>-at`.

Agentic Team derives the default AT workspace directory from the checkout directory name. For example, launching from `~/src/abctest-dev` defaults to `~/src/abctest-dev-at`, regardless of the Git remote name. To choose a different namespace, launch by naming the desired AT workspace directory, for example `agentic-team ~/shared-work-at research-main --from main --project-dir ~/my-project`.

The main state scopes are:

| Scope | Backing location |
|-------|------------------|
| Org | Optional org repo configured by `AR_ORG_NOTES_REPO` |
| Project | Project repo orphan branch `agentic/project-state` |
| Work branch | Project repo orphan branch `agentic/work-state/<work-branch>` |

State branches start as orphan branches with empty filesets. They contain only state files created by enabled capabilities, such as Agentic Notes, work-branch research records, and experiment logs. They do not contain `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or your code tree. Locally, those branches are linked worktrees at `PROJECT-at/project-state` and `PROJECT-at/<work-name>/state`.

Multiple top-level agents must work in separate AT workspace entries with separate work branches. Branch guard files are local-only under `$AR_RUNTIME_ROOT/branch-guards/`; Git remains the real conflict mechanism.

When the top-level agent has a coherent change set ready to commit, it uses `branch-snapshot` plus `branch-commit` directly so checks and commit creation happen from a temporary worktree. Snapshot metadata and temporary commit worktrees are retained locally for status checks and debugging; prune old completed or abandoned artifacts with `branch-commit-cleanup` after a dry run. When completed work-branch changes should land in a development branch such as `dev` or `main`, use the `branch-integrator` subagent.

For details, see:

- [docs/agentic-state.md](docs/agentic-state.md) for state scopes, orphan branches, cache locations, locks, refresh, and materialized instruction files
- [docs/agentic-notes.md](docs/agentic-notes.md) for `agent-notes/`, always-injected notes, on-demand notes, and note updates
- [docs/experiment-log.md](docs/experiment-log.md) for research experiment IDs, summaries, correction records, and logging flow

### Job Backend Capabilities

Capability packages can be used for job placement and execution backends, and Agentic Team comes with a SLURM capability called `remote-run`.

Capabilities can provide agents, Python workflow modules, and prompt skills under `agents/`, `package/`, and `skills/`. Enabled capability skills are rendered into the selected CLI's project discovery path: `.claude/skills` for Claude, `.gemini/skills` for Gemini, `.opencode/skills` for OpenCode, and `.agents/skills` for Codex/pi. Selecting a main agent automatically enables its providing capability and dependencies. The built-in `research-coordinator` capability provides that main agent, its research subagents, and the `do_research` and `retro` skills. Capability `INSTRUCTIONS.md` files are injected when that capability is enabled.

Agent definitions are neutral Markdown files supplied by capability `agents/` directories. A `kind: main` definition can be selected with `AR_MAIN_AGENT`; a `kind: subagent` definition is rendered into the selected CLI's project agent path. Built-in providers include `research-coordinator` for experiment-driven research and `systems-developer` for interactive Linux-focused development. The top-level instruction file gets a compact catalog of subagents from enabled capabilities. Project capabilities under `.agentic-team/capabilities/` override configured organization providers, which override built-ins with the same capability name. Add `codex_reasoning_effort: low|medium|high` to render Codex reasoning effort where supported. See [docs/extending-agentic-team.md](docs/extending-agentic-team.md#agents-and-agent-types).

```bash
agentic-team --capability cluster-run
cluster-run status
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

For multi-node Slurm allocations, enable the managed `remote-run` capability. It checks its own requirements, starts the host-side dispatcher, puts the `remote-run` command on the launched agent's PATH, and exposes the backend to the agent:

```bash
get_gpu 2 2                          # Allocate 2 nodes x 2 GPUs
agentic-team --sandbox apptainer --capability remote-run --test
agentic-team --sandbox apptainer --capability remote-run
remote-run --nodes
remote-run htc-gpuXXX --bg -- uv run python train.py --exp E005
```

To add lab- or site-specific backends, create a capability under `capabilities/` and enable it with `--capability`. See [docs/extending-agentic-team.md](docs/extending-agentic-team.md) for the capability layout, custom job backend checklist, and when launcher changes are needed.

## Org Repo

The org repo is optional. Use one when you want notes, custom agents, or custom capabilities to follow a team across multiple projects or Agentic Team installations.

`agentic-team --setup` asks for this repo and stores it as `AR_ORG_NOTES_REPO`. The value can be a Git URL or a local Git repo path. An empty org repo is a valid starting point: Agentic Team will not inject or list org guidance until notes have been added, but agents can add organization-wide notes later through the note-updater flow.

For a starter layout, copy or adapt [examples/org-notes/](examples/org-notes/):

```text
capabilities/
  research-paper/
    capability.toml
    agents/
      data-curator.md
      research-paper-author.md
  my-capability/
    skills/
      my-skill/
        SKILL.md           # optional prompt skill rendered when enabled
    bin/
      my-command           # executable placed on PATH when enabled
    lib/
      common.sh            # optional private support code for this capability
    hooks/
      instruction          # optional render/refresh hook executable
agent-notes/
  all-agents/
    always-injected.md    # short organization-wide guidance injected every time
    git.md                # on-demand topic note listed for relevant work
  research-coordinator/
    always-injected.md    # injected for the default main agent
  gpu-kernel-engineer/
    always-injected.md    # injected for that agent type
```

Put only short, high-value guidance in `always-injected.md`. Put longer or situational details in topic notes such as `agent-notes/all-agents/git.md`, `agent-notes/all-agents/slurm.md`, `agent-notes/all-agents/pytorch.md`, or `agent-notes/gpu-kernel-engineer/benchmarking.md`; Agentic Team lists those topics so agents can read the rendered note only when relevant.

Org-provided agents live inside `capabilities/<capability>/agents/`. A capability may also ship Python workflow modules under `package/`, skills under `skills/`, commands under `bin/`, private helpers under `lib/`, launcher hooks under `launcher/`, and instruction lifecycle hooks under `hooks/`. `capability.toml` declares transitive dependencies. Capabilities are selected explicitly or by selecting a main agent they provide. Project providers use the same structure under `.agentic-team/capabilities/` and take precedence over org and built-in providers.

See [docs/agentic-notes.md](docs/agentic-notes.md) for the notes layout and [docs/extending-agentic-team.md](docs/extending-agentic-team.md) for the agent and capability extension points.

## Supported CLIs

| CLI | Instruction file | Model/API | Flag |
|------|-----------------|----------|------|
| [Claude Code](https://github.com/anthropics/claude-code) | `CLAUDE.md` | Anthropic | `--cli claude` (default) |
| [OpenCode](https://opencode.ai) | `AGENTS.md` | Any (LiteLLM) | `--cli opencode` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Google | `--cli gemini` |
| [Codex CLI](https://github.com/openai/codex) | `AGENTS.md` | OpenAI | `--cli codex` |
| [pi](https://github.com/badlogic/pi-mono) | `AGENTS.md` | Any | `--cli pi` |

At launch, Agentic Team also renders a project-local compaction hook for the selected CLI. After context compaction, the hook runs the configured capabilities, refreshes shared Agentic State under local locks, rematerializes the capability sections in the instruction file rendered for that exact invocation (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`), tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary, asks it to read the refreshed instruction file, and then resumes the task it was already doing. In container mode the Agentic Team install is mounted read-only at `/opt/agentic-team`, while `AR_STATE_ROOT`, `AR_WORKSPACE_ROOT`, `AR_RUNTIME_ROOT`, and `AR_ARTIFACTS_DIR` are mounted read-write so the org checkout, project state branches, project runtime helpers, and shared project artifacts can be updated. Claude uses compact-session hooks, Codex uses `PostCompact`, Gemini uses `PreCompress` plus a one-shot `BeforeModel` refresh, OpenCode uses a compaction plugin, and pi uses a launch-specific extension.

## Architecture

### Sandbox

| Layer | Details |
|-------|---------|
| **Filesystem isolation** | The agent can write `/workspace`, the mounted `AR_STATE_ROOT`, the mounted `AR_WORKSPACE_ROOT`, and `$AR_RUNTIME_ROOT`; the Agentic Team install is mounted read-only at `/opt/agentic-team`; extra directories from `AR_EXTRA_BIND_DIRS` are mounted under `/workspace/.mount/<basename>` |
| **Namespace isolation** | Apptainer `--compat` enables user/mount namespaces |
| **Path traversal protection** | Symlinks resolved; system directories blocked |

`--yolo` auto-approves tool calls but does **not** weaken filesystem isolation.

`--sandbox none` intentionally disables Agentic Team filesystem isolation: the selected CLI runs directly in the project directory with your host `HOME`, `PATH`, and credentials.

### Research Agent Instructions

The framework ships `INSTRUCTIONS.md` as a shared base template and capability-owned agent definitions, instruction modules, and source renderers. Agent files can include a capability module with `<!-- AT_INSTRUCTION_MODULE: capability-name/module-name -->`; the launcher expands that directive when it materializes the selected CLI's instruction file or subagent definition.

### Agentic State

Agentic State is implemented as shared command-library code used by capabilities and launcher refresh paths. It owns state worktree locations, branch naming, local locks, and Git synchronization; capabilities own the files and schemas stored there. See [docs/agentic-state.md](docs/agentic-state.md) for scopes, orphan branches, cache locations, refresh behavior, and materialized instruction files.

### Capabilities

Capabilities own agent and tool implementations, skills, commands, launcher hooks, and stateful instruction sections. Built-in capabilities live in `capabilities/`:

- `agentic-notes` owns the `agent-notes/` data model, initializes and refreshes org/project/work-branch note state from its launcher hooks, renders Agentic Notes guidance plus dynamic always-injected and on-demand note listings, provides `agentic-notes read-note`, `agentic-notes update-note`, and `agentic-notes rewrite-note`, runs the background notes refresh loop, and emits lightweight steering notices when refreshed note topics change during a running session.
- `experiment-log` owns the active work-branch `experiment-log/` data model, renders active experiment-log guidance, and provides `experiment-log append`, `experiment-log correct`, and `experiment-log summary`. The experiment log is capability-owned and may be absent until the workflow records an experiment.
- `branch` provides snapshot commits plus generic `branch-temporary-worktree create`, `publish`, and `drop` operations shared by main-agent capabilities.
- `imperative-workflows` renders and validates Python-shaped agent and skill workflows.
- `research-coordinator` provides the research coordinator agent family and research-state workflow.

The default capability list is `agentic-notes,experiment-log` via `AR_CAPABILITIES`. After context compaction, the generated CLI hook runs `capability-refresh`, which delegates to `agentic-team --render-only --refresh-capabilities` so the launcher refreshes configured capabilities and rematerializes the instruction file for that exact invocation.

## Citation

Citation for the original Agentic Researcher paper:

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
