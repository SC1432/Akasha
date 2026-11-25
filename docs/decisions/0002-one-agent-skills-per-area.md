# ADR-0002: One main agent, skills per area, subagents by task shape

**Date:** 2026-11-25
**Status:** accepted

## Context

The first idea was an orchestrator agent with a subagent per life area (knowledge base, project tracker, future areas). Subagents run in isolated context and return summaries.

## Decision

One main agent sees the whole vault. Each area is a skill plus a note type in the schema. Subagents are used only where the task's shape calls for isolation:

- `source-reader`: reads untrusted captured content with no write, shell or web tools.
- `reviewer`: checks drafts and summaries against raw sources with fresh context.

## Alternatives considered

- **Subagent per area.** Rejected: cross-area questions ("what have I saved that helps with this project?") need handoffs that lose detail; each spawn adds cost and latency; every new area needs new routing logic.

## Consequences

- Adding an area = schema entry + template + skill, no routing changes.
- All areas share one link graph, so concepts from courses, captures and projects meet on the same pages.
- Prompt-injection risk from captured content is contained by the `source-reader` boundary plus `brainctl` validation.
