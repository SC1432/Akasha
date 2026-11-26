# ADR-0004: TOML schema and a stdlib parser for a strict frontmatter subset

**Date:** 2026-11-25
**Status:** accepted

## Context

The design named `schema/note-types.yaml`, and Obsidian stores note properties as YAML frontmatter. The conventions say Python standard library first, and Python has no stdlib YAML parser. Two separate things need parsing:

1. The schema file, which lives in the plugin repo, is edited by hand and only read by `akashactl`.
2. The frontmatter of every vault note, which Obsidian requires to be YAML and which `akashactl` must both read and write.

## Decision

- The schema is `schema/note-types.toml`, read with `tomllib` (stdlib since Python 3.11).
- Frontmatter is handled by `scripts/lib/frontmatter.py`, a small parser and emitter for a strict YAML subset: one flat mapping whose values are strings, integers, booleans, null, or lists of those, written as block lists (`- item`) or flow lists (`[a, b]`). Strings may be plain, double-quoted or single-quoted.
- Anything outside the subset raises `FrontmatterError` with a line number instead of being guessed at: nested mappings, multi-line strings, anchors, tags, tabs, duplicate keys, floats, YAML 1.1 booleans (`yes`, `no`, `on`, `off`), and plain values YAML would misread (containing `: ` or ` #`, or starting with `[[`).
- The emitter writes only that subset and quotes any string that would otherwise parse as another type, so `parse(dump(x)) == x`. Dates are kept as `YYYY-MM-DD` strings; the schema checks their format.

## Alternatives considered

- **PyYAML as the one dependency.** Reads any YAML, but every machine and scheduled `claude -p` job then needs a package installed, and PyYAML uses YAML 1.1 rules (`no` becomes `false`, `3.10` becomes `3.1`), which would silently change values on rewrite.
- **JSON for the schema.** Stdlib, but no comments and fragile to hand-edit.
- **Markdown for the schema.** No standard data structure, so it would need a parser for an invented format, with silent failures on typos.

## Consequences

- Akasha runs with no third-party packages; only pytest for development.
- Hand-written notes with richer YAML are refused rather than rewritten. That is acceptable because Akasha only rewrites its own `generated: true` pages; `lint` (Phase 5) should report refused frontmatter so it stays visible.
- The schema can be read but not written by stdlib (`tomllib` has no writer). The schema is hand-edited, so this costs nothing.
- If Obsidian or a future feature needs nested properties, revisit this ADR before widening the parser.
