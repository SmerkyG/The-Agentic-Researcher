# External client contexts

Agentic Team can prepare a paired branch checkout for a CLI launched separately
from `agentic-team`, including a Codex desktop session connected to a remote
machine over SSH:

```bash
agentic-team -C ~/my-project-at run agent/research-main \
  --prepare-client --cli codex
```

Preparation still renders the selected main-agent instructions, skills, and
subagent definitions in the code worktree because each CLI discovers those at
fixed project-relative paths. Agentic Team locally excludes generated files
from Git. For directly connected clients whose shell does not inherit the
prepared `PATH`, the instruction file provides one generic
`agentic-team-client exec --client <cli> -- COMMAND [ARGS...]` template. The
agent substitutes whichever capability command it needs; the dispatcher
restores the complete prepared environment. Mutable runtime configuration does
**not** live in the code worktree.

Before preparation, `agentic-team checkout` places locally excluded bootstrap
guards in `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`. If someone opens the code
directory directly, those guards instruct the agent not to touch the project
and provide the required `agentic-team ... run ... --prepare-client` command.
The first AT run removes every bootstrap guard and atomically writes the
selected client's complete instruction document; start a new task afterward.

For each client, preparation writes:

```text
~/my-project-at/branches/agent/research-main/client/<cli>/
  context.json       # selected work, capabilities, paths, and runtime environment
  launch             # executable prepared CLI launcher
  ...                # external settings, hooks, plugins, or extensions as needed
```

It also updates `~/.config/agentic-team/client-contexts.json`. The generic
`agentic-team-client` dispatcher chooses the longest registered project path
matching the current working directory, so one user-global MCP or hook
registration can serve many projects and paired branches. An explicit
`AR_CLIENT_CONTEXT` takes precedence. Registry updates are locked and atomic.

## Client behavior

| Client | External integration |
| --- | --- |
| Codex | Registers the generic workflow MCP server with `codex mcp` and installs generic user-level compaction/steering hooks. The Codex desktop app can open the registered remote code directory directly. |
| Claude | The prepared launcher supplies the external settings file with `--settings` and the workflow MCP definition with `--mcp-config`. |
| Gemini | The prepared launcher restores `GEMINI_CLI_SYSTEM_SETTINGS_PATH`, which selects the external hooks and MCP settings. |
| OpenCode | The prepared launcher restores `OPENCODE_CONFIG` and `OPENCODE_CONFIG_DIR`, which select the external plugin and MCP configuration. |
| pi | The generic workflow MCP registration lives in the user's pi config; the prepared launcher adds the work-specific external compaction extension. |

For Claude, Gemini, OpenCode, and pi, run the printed `.../client/<cli>/launch`
path when starting outside the ordinary AT launcher. For Codex desktop, run
preparation on the remote host after installing/updating Agentic Team, connect
the app to the printed SSH host, and open the printed client working directory.
The global dispatcher resolves the correct work context from that directory.

Codex treats the generated user-level hooks as non-managed code. The first Codex
preparation after installation prints a `codex -C
<client-working-directory>` command. Run it on the remote host, enter `/hooks`
in the Codex TUI, and trust the Agentic Team hooks. Ordinary subsequent
preparations do not repeat this notice; Codex requires another review only when
Agentic Team changes a hook definition. Preparation does not automate this
security decision, and the desktop app does not currently expose the hook
review UI.

Re-run preparation whenever the selected agent, capabilities, work paths, or
Agentic Team installation changes. Normal `agentic-team` launches refresh the
same context automatically.
