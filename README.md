# Akasha

A Claude Code plugin that turns an Obsidian vault into a personal assistant: one agent that keeps a linked wiki of everything I capture, tracks what I'm working on, and turns school notes into study material.

It follows the inbox → raw → wiki pattern from [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), rebuilt smaller so every part is understood and owned.

> Status: **Phase 1 in progress** (schema and frontmatter parser done; writer next).

The name comes from *akasha* (Sanskrit ākāśa, "aether" or "sky"), the root of the Akashic records: the idea of a complete record of everything ever thought or learned.

## Repository layout

| Path | What it holds |
| --- | --- |
| `docs/context.md` | Handoff context for Claude Code: preferences, decisions, state, next steps |
| `docs/design.md` | What the tool does, how it is built, how to use it |
| `docs/roadmap.md` | Seven phases, their gates and task checklists |
| `docs/decisions/` | Architecture decision records (ADRs), one per decision |
| `devlog/` | Dated build log, one file per working session |
| `CLAUDE.md` | Rules for Claude Code sessions in this repo, including keeping the devlog current |
| `schema/note-types.toml` | Note types: folder, required fields, statuses |
| `scripts/lib/` | Stdlib helpers: strict frontmatter parser/emitter, schema loader and validator |
| `tests/` | pytest suite (`python3 -m pytest`) |

The rest of the plugin (`.claude-plugin/`, `skills/`, `agents/`, `hooks/`, `scripts/akashactl.py`) arrives during Phase 1. No third-party packages are needed to run Akasha; pytest is the only development dependency.

## Core ideas

- **One agent, many skills.** Areas of life (wiki, projects, courses) are skills and data schemas, not separate agents.
- **Raw is sacred.** Every source is kept as an immutable, hash-named copy; every generated claim links back to it.
- **One writer.** Only `akashactl.py` writes to the vault; everything else proposes plans.
- **Git is the undo button.** One commit per operation.
- **My writing is untouchable.** `personal/` is read-only to the system.

## Documentation process

Every working session ends with a devlog entry (`devlog/YYYY-MM-DD.md`, template in `devlog/TEMPLATE.md`). Any decision that changes the architecture gets an ADR in `docs/decisions/`. The roadmap checklists are ticked as tasks land.
