# ADR-0005: Apply and undo semantics

**Date:** 2026-11-25
**Status:** accepted (refines ADR-0003)

## Context

ADR-0003 fixed the shape: a single writer, a `base_hash` per update, one commit per operation, and undo as a `git revert` of the last Akasha commit. Building `apply` and `undo` raised details it left open: how `index.md` is maintained, which existing pages a plan may overwrite, what undo does when I've edited a file since, and what a second undo means.

## Decision

- **Validate everything, then write everything.** `apply` checks the whole plan before any write and reports every problem at once. The checks are: path allow-list, schema, `base_hash`, links resolve, and create targets not existing (case-insensitively, because macOS filesystems are case-insensitive). A failure during writing rolls the files back.
- **Plans only rewrite Akasha's own pages.** An `update` is refused unless the existing page has `generated: true`. `wiki/index.md`, `log.md`, `hot.md` and `now.md` are reserved: only `akashactl` writes them, and plans can't.
- **`index.md` is regenerated** on every apply from the frontmatter of all `generated: true` typed pages, grouped by type (`label` in the schema). It links by vault path (`[[wiki/concepts/x|Title]]`) so pages with the same file name, like each course's `summary.md`, never collide.
- **`log.md` gets one entry per operation**, newest first, inserted after the `# Log` heading.
- **Undo restores files rather than running `git revert`.** It picks the newest Akasha commit (one with an `Akasha-Operation` trailer) that is neither an undo nor already undone, and restores each file it touched to its state in that commit's parent, or deletes the file if the operation created it. All of this becomes a new commit with `Akasha-Operation: undo` and `Akasha-Reverts: <sha>`, so running undo again steps further back. If any of those files has changed since the operation (in a later commit, the index or the working tree), undo refuses and names the files.
- **One write lock.** `capture`, `apply` and `undo` hold `.akasha/lock` (created with `O_EXCL`) while writing.

## Alternatives considered

- **Literal `git revert`.** It merges against later changes, which can silently combine my edits with the revert or stop mid-way in a conflict state inside the vault. Because the restore runs only when nothing changed since, it produces the same result as a clean revert, and refuses in exactly the cases where `git revert` would have to guess.
- **Appending to `index.md` from plan-supplied entries.** This drifts when pages are renamed or undone, and needs every skill to get the entry format right. Regenerating it is deterministic and makes undo trivially correct.
- **Allowing updates to any page under `wiki/`.** This would let a bad or injected plan rewrite hand-written notes that happen to live in `wiki/`.

## Consequences

- Edits I make by hand to `index.md` are overwritten on the next apply (the file says so in a comment).
- Undoing a `capture` deletes the `.raw/` files it created. This is the one path that removes raw files, and it only runs when I ask for it.
- A stale `.akasha/lock` after a crash blocks writes until I delete it; the error message says so.
- Undo can't step past an operation whose files I've since edited. The fix is to commit or revert my edit first, which keeps undo from ever destroying my work.
