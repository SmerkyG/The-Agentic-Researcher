# External client contexts

Agentic Team can prepare a work entry for a CLI that is launched separately
from `agentic-team`, including a Codex desktop session connected to a remote
machine over SSH:

```bash
agentic-team --prepare-client --cli codex ~/my-project-at research-main
```

Preparation still renders the selected main-agent instructions, skills, and
subagent definitions in the code worktree because each CLI discovers those at
fixed project-relative paths. Agentic Team locally excludes generated files
from Git. Mutable runtime configuration does **not** live there.

For each client, preparation writes:

```text
~/my-project-at/research-main/client/<cli>/
  context.json       # selected work, capabilities, paths, and runtime environment
  launch             # executable prepared CLI launcher
  ...                # external settings, hooks, plugins, or extensions as needed
```

It also updates `~/.config/agentic-team/client-contexts.json`. The generic
`agentic-team-client` dispatcher chooses the longest registered project path
matching the current working directory, so one user-global MCP or hook
registration can serve many projects and work entries. An explicit
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
the app to that host, and open `~/my-project-at/research-main/code`. The global
dispatcher resolves the correct work context from that directory.

Re-run preparation whenever the selected agent, capabilities, work paths, or
Agentic Team installation changes. Normal `agentic-team` launches refresh the
same context automatically.
