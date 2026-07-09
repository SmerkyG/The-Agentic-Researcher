# Imperative Research Workflows

This directory contains an experimental rewrite of the current
`research-coordinator` role and research subagents using
`docs/imperative-workflow-specs.md`.

The live agent definitions in `agents/*.md` are unchanged. Treat
`research_roles.py` as a reviewable prototype for the code-shaped workflow
contract: ordering, branching, waiting, and failure behavior are Python control
flow; `self.do([...])` takes a literal actions list of atomic plain-language work
items. Related model-facing work is grouped by putting multiple strings in that
same list when one structured result depends on several related substeps.
`self.fill(SchemaType, ...)` is used when an `Annotated` dataclass schema fully
describes the requested structured output without a separate action string.
