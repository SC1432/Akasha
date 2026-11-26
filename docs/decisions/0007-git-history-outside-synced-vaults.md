# ADR-0007: Git history outside cloud-synced vaults

**Date:** 2026-11-25
**Status:** accepted

## Context

My vault may live in Google Drive (or iCloud or Dropbox). Git is still needed, because it's what makes an operation that touches several files one undoable unit (ADR-0003, ADR-0005), and Drive's per-file version history can't do that. But a `.git` folder is thousands of small files that must change together, and sync clients copy them one at a time. That is a known way to corrupt a repository, especially with two machines or a sync still in progress.

## Decision

- **`akashactl init --git-dir PATH`** runs `git init --separate-git-dir PATH`. The history lives at `PATH`, and the vault holds only a one-line `.git` file pointing to it. Sync then copies one tiny file, never the repository's internals. The rest of Akasha needs no changes, because git resolves the `.git` file itself; capture, apply and undo are tested this way.
- **It only applies to a new repository.** For a vault that is already a git repository, init refuses `--git-dir`, because moving an existing repository is my decision. It also refuses a path that is relative, inside the vault, containing the vault, already non-empty, or inside a synced location itself.
- **Synced folders are detected by path:** `~/Library/CloudStorage/` (Google Drive for desktop, Dropbox, OneDrive) and `~/Library/Mobile Documents/` (iCloud). The dry run then warns and suggests `--git-dir ~/.akasha-git/<vault-name>`, and the setup skill explains the trade-off and asks.
- **A clear error on other computers.** If the `.git` file points to a folder that doesn't exist on this computer, as on a second computer that receives the vault through sync, `akashactl` says exactly that instead of "run setup".

## Alternatives considered

- **No git; rely on Drive's version history.** It's per file and time-limited (30 days or 100 versions), with no grouping by operation, so undoing an ingest would mean restoring each file by hand. Replacing git with my own snapshot journal is the subsystem ADR-0003 chose not to build.
- **Keep `.git` inside the vault and exclude it from sync.** Google Drive for desktop has no reliable per-folder exclude for a subfolder of a synced folder, and that setting would live outside the repository, where nothing can check it.
- **Always use a separate git folder.** For an unsynced vault it only adds a second place to back up, for no benefit.

## Consequences

- The history exists only on this computer. Time Machine covers `~/.akasha-git/` by default, but Drive doesn't, so losing the Mac without Time Machine loses undo history (not notes).
- Akasha can write to the vault only from the computer that holds the history. On another computer, reading in Obsidian works normally. This matters for the Phase 7 host decision: an always-on server that writes to the vault needs the history, which points towards git push/pull between machines rather than Drive.
- Detection is path-based and macOS-specific. A vault synced some other way (Syncthing, a custom folder) gets no warning; the skill still offers the option if I mention sync.
