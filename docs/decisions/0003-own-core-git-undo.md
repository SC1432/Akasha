# ADR-0003: Own small core with a single writer and git-based undo

**Date:** 2026-11-25
**Status:** accepted

## Context

claude-obsidian already implements inbox → raw → wiki with SHA-256 fingerprints, a write journal, source and claim ledgers, and transactional writes. Options were to use it as-is with a companion plugin, fork it, or rebuild the pattern.

## Decision

Rebuild the pattern in a small core:

- `.raw/` is create-only, files named by SHA-256.
- `akashactl.py` is the only writer; it validates plans against `schema/note-types.toml` (originally `.yaml`; changed by ADR-0004).
- Each update carries the `base_hash` of the page as read; a mismatch blocks the write.
- One git commit per operation; `akashactl undo` reverts the last Akasha commit.

## Alternatives considered

- **Companion plugin on top of claude-obsidian.** Fastest, inherits a mature engine, but couples my features to someone else's conventions.
- **Fork claude-obsidian.** Full engine, but a large codebase I didn't write and a manual merge on every upstream release.

## Consequences

- I understand and own every part; roughly a hundred lines replace the journal and fingerprint subsystem.
- No claim ledger in v1; provenance comes from source links and verbatim quotes. Revisit if contested claims become common.
- Credit claude-obsidian (MIT) for the pattern in the README.
