# Global Instructions

You are operating in a Separated Workspace. The launcher may run you
in a sandboxed container or directly on the host with `--sandbox none`. Respect
the actual sandbox shown at session start.

Use the selected main-agent instructions below as the authority for your
agent-type-specific workflow. Use any injected project agent-type notes below as the
project-specific guidance for this agent type in this project.

## Global constraints

- **Startup**: if accessible, source the user's shell rc file at session start
  (`~/.bashrc`, `~/.zshrc`, or whichever exists) -- it may set HTTP proxies,
  PATH entries, aliases, or other environment configuration needed for git,
  curl, wget, etc.

### Accessible directories
| Path | Access | Contents |
|------|--------|----------|
| `/workspace` or the launch working directory | read-write | Your project |
| `/agent-home` | isolated, container mode only | Container home directory |
| launcher-provided writable dirs | read-write | Optional cache/data locations exposed by the launcher or environment |

In container mode, host paths outside mounted workspace/cache locations are
inaccessible. With `--sandbox none`, there is no Separated Workspace filesystem
isolation: avoid reading or modifying files outside the project unless the user
explicitly asks.

The main-agent instructions follow below:
