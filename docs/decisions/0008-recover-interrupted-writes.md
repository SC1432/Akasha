# ADR-0008: Recovering interrupted writes

**Date:** 2026-11-26
**Status:** accepted (extends ADR-0005)

## Context

`apply` rolls back when a write fails with an exception, but a crash, power loss or kill stops the process before it can roll back. That leaves some files written but not committed, possibly some staged, and a stale `.akasha/lock` that blocks every later write. Nothing is lost, because git holds the previous versions, but cleaning up by hand means knowing which uncommitted changes came from Akasha and which are mine. claude-obsidian solves this with a full transaction journal (`transaction recover`). ADR-0003 chose git instead of a journal and doesn't revisit that.

## Decision

- **The write lock records what the write is about to touch.** `capture`, `apply` and `undo` write a small record into `.akasha/lock` before writing anything, and fsync it: operation, pid, host, start time, and the exact vault paths. No file contents are copied; git already has the previous versions.
- **`akashactl recover [--dry-run]` acts only on that record.** For each recorded path it:
  - restores the last committed version if one exists;
  - deletes the file if the interrupted write created it;
  - unstages it if the crash came after `git add`.

  Then it clears the lock. Paths outside `wiki/` and `.raw/` in the record are ignored, so a tampered lock can't reach `personal/` or anything else.
- **Complete raw copies are kept.** An uncommitted `.raw/<hash>` whose content matches its hash is a valid source copy, and the next capture records it again. Only partial copies (hash mismatch) are deleted.
- **Recover refuses rather than guess** when:
  - the lock's process is still running on this computer;
  - the lock came from another computer (for example, synced through Google Drive);
  - git's own `index.lock` exists, so git was interrupted too. Recover reports it rather than deleting git's internals.
- **No automatic recovery.** A stale lock blocks writes with a message that points to `akashactl recover --dry-run`. I see what it will do and run it myself.

## Alternatives considered

- **A full journal of original file contents, as claude-obsidian does.** It duplicates what git already stores, and adds a second recovery mechanism to keep correct.
- **Restoring every uncommitted change in `wiki/` to HEAD.** It's simpler, but it would discard my own unsaved edits to wiki pages that the interrupted write never touched.
- **Recovering automatically on the next write.** It's convenient, but it silently discards partially written work. claude-obsidian takes the same stance: never steal a lock automatically.

## Consequences

- Recover can only be as precise as the lock record. A lock written by an older `akashactl` (plain pid) is just cleared, with a note to check `git status`.
- A crash between the commit and the lock removal leaves a lock whose paths all match HEAD. Recover reports them as `ok` and clears the lock.
- `setup` (`akashactl init`) doesn't take the lock, so a crash during setup is cleaned up by hand. Setup writes `akasha.json` last, so an interrupted setup doesn't leave a usable vault.
