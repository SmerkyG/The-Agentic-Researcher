---
name: "update_base"
description: "Update the project instruction file from the latest base template."
---

You need to update the project's instruction file with the latest base template while keeping the project-specific content intact.

## Steps

1. **Locate** the latest base template. Prefer the first readable path from:
   - `$AR_INSTRUCTIONS_TEMPLATE`
   - `/workspace/INSTRUCTIONS.md` or `./INSTRUCTIONS.md` when the current workspace is the Agentic Researcher source checkout
   - legacy mounted paths `/claude-home/INSTRUCTIONS.md.template` or `/claude-home/.claude/INSTRUCTIONS.md.template`
2. If no template is readable, stop and tell the user to relaunch with a current Agentic Researcher launcher or set `AR_INSTRUCTIONS_TEMPLATE` to the rendered base template path.
3. **Detect** which instruction file exists in the workspace (check `CLAUDE.md`, `GEMINI.md`, `AGENTS.md` in order). Use the first one found as `$INSTRUCTION_FILE`.
4. **Read** the current project file at `/workspace/$INSTRUCTION_FILE`.
5. **Extract** from the current file: everything starting from `## 8. Project Instructions` (inclusive) to the end of the file. This is the project-specific content that must be preserved exactly as-is, including managed Agentic Notes or skill instruction sections appended after it.
6. **Combine**: take the template content up to (but NOT including) `## 8. Project Instructions`, then append the extracted project-specific content from step 5.
7. **Write** the combined result to `/workspace/$INSTRUCTION_FILE`.
8. **Show** the user a brief summary of what changed (e.g., "Updated base sections 0-7 from template, preserved your Project Instructions").
9. **Commit** with message: `chore: update instruction file base template`.
