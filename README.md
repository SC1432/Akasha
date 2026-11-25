# Akasha

A Claude Code plugin that turns an Obsidian vault into a personal assistant: one agent that keeps a linked wiki of everything I capture, tracks what I'm working on, and turns school notes into study material.

It follows the inbox → raw → wiki pattern from [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), rebuilt smaller so every part is understood and owned.

> Status: **Phase 1 in progress**: `akashactl` (`init`, `capture`, `apply`, `undo`) and `/akasha:setup` are done; a trial on a copy of the real vault remains.

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
| `.claude-plugin/plugin.json` | Plugin manifest |
| `bin/akashactl` | Wrapper that puts `akashactl` on Claude's Bash PATH when the plugin is enabled |
| `scripts/akashactl.py` | The single writer: `init`, `capture`, `apply`, `undo`, plus read-only `validate` and `hash` |
| `skills/setup/` | `/akasha:setup`, the guided wrapper around `akashactl init` |
| `schema/note-types.toml` | Note types: folder, required fields, statuses |
| `scripts/lib/` | Stdlib helpers: strict frontmatter parser/emitter, schema loader and validator |
| `tests/` | pytest suite (`python3 -m pytest`); `tests/fixtures/vault/` is the sample vault the tests copy |

More skills, agents and hooks arrive from Phase 2 onwards. Requires Python 3.11+. Check a vault's generated pages with `bin/akashactl validate --vault <vault>`. No third-party packages are needed to run Akasha; pytest is the only development dependency.

## Core ideas

- **One agent, many skills.** Areas of life (wiki, projects, courses) are skills and data schemas, not separate agents.
- **Raw is sacred.** Every source is kept as an immutable, hash-named copy; every generated claim links back to it.
- **One writer.** Only `akashactl.py` writes to the vault; everything else proposes plans.
- **Git is the undo button.** One commit per operation.
- **My writing is untouchable.** `personal/` is read-only to the system.

## Documentation process

Every working session ends with a devlog entry (`devlog/YYYY-MM-DD.md`, template in `devlog/TEMPLATE.md`). Any decision that changes the architecture gets an ADR in `docs/decisions/`. The roadmap checklists are ticked as tasks land.
