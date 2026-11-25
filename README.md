# Brain (working name)

A Claude Code plugin that turns an Obsidian vault into a personal assistant: one agent that keeps a linked wiki of everything I capture, tracks what I'm working on, and turns school notes into study material.

It follows the inbox → raw → wiki pattern from [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), rebuilt smaller so every part is understood and owned.

> Status: **design complete, Phase 1 not started.** The name is still undecided (candidates: Muninn, Hippo, Mnemo, Loci, Memex).

## Repository layout

| Path | What it holds |
| --- | --- |
| `docs/design.md` | What the tool does, how it is built, how to use it |
| `docs/roadmap.md` | Seven phases, their gates and task checklists |
| `docs/decisions/` | Architecture decision records (ADRs), one per decision |
| `devlog/` | Dated build log, one file per working session |
| `CLAUDE.md` | Rules for Claude Code sessions in this repo, including keeping the devlog current |

Plugin code (`.claude-plugin/`, `skills/`, `agents/`, `hooks/`, `scripts/`, `schema/`, `tests/`) arrives in Phase 1.

## Core ideas

- **One agent, many skills.** Areas of life (wiki, projects, courses) are skills and data schemas, not separate agents.
- **Raw is sacred.** Every source is kept as an immutable, hash-named copy; every generated claim links back to it.
- **One writer.** Only `brainctl.py` writes to the vault; everything else proposes plans.
- **Git is the undo button.** One commit per operation.
- **My writing is untouchable.** `personal/` is read-only to the system.

## Documentation process

Every working session ends with a devlog entry (`devlog/YYYY-MM-DD.md`, template in `devlog/TEMPLATE.md`). Any decision that changes the architecture gets an ADR in `docs/decisions/`. The roadmap checklists are ticked as tasks land.
