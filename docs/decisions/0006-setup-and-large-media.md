# ADR-0006: Vault setup and large captured files

**Date:** 2026-11-25
**Status:** accepted

## Context

`/akasha:setup` must turn a folder into a vault, either a new one or my existing Obsidian vault adopted in place. It must not risk the notes already there. Separately, every captured file goes into `.raw/`, which is committed to git. Phase 7 brings reels and videos, and git keeps every version forever, so a few hundred reels would make the vault repository several gigabytes.

## Decision

- **Setup is `akashactl init`,** keeping the single-writer rule. The `setup` skill is user-invoked only (`disable-model-invocation: true`). It runs the dry run, asks which folders are personal and whether the size limit is fine, shows the final preview, and applies only after an explicit yes.
- **Init creates only new files.** It makes `akasha.json`, `inbox/.gitkeep`, `wiki/index.md` and `wiki/log.md`, plus a default `personal/` folder when none is named. The one exception to create-only is a marked block appended to `.gitignore`. It refuses:
  - my home folder or any folder containing it
  - a folder inside another git repository
  - an existing vault
  - existing `wiki/index.md`, `log.md`, `hot.md` or `now.md`
  - a non-empty `.raw/`
  - personal folders that are missing, absolute, hidden, or overlap folders Akasha manages
- **Existing notes are not committed.** If the folder wasn't a git repository, init runs `git init` and commits only its own files. Versioning existing notes is my choice; the skill tells me the command.
- **Setup can't be undone.** `undo` stops at the setup commit, because reversing it could delete a `.gitignore` that existed before. To stop using Akasha, delete `akasha.json`.
- **`inbox/` contents are git-ignored.** Inbox files are transient, and their permanent copies are in `.raw/`.
- **Size limit for git.** `akasha.json` has `raw_git_max_mb` (setup default 5; `null` means no limit). Capture still copies larger files into `.raw/` and records them in the manifest with `in_git: false`, but lists them in `.raw/.gitignore` instead of committing them. That file becomes the second rewritable bookkeeping file in `.raw/`, alongside `manifest.json`.

## Alternatives considered

- **Git LFS for large files.** It keeps everything versioned, but needs `git-lfs` installed, and GitHub's free LFS quota is 1 GB, with paid data packs beyond that.
- **Everything in git.** The simplest option and fully backed up, but the repository grows without bound once video arrives.
- **A baseline commit of all existing notes during setup.** It would give history from day one, but it would also commit my personal notes and large attachments without asking, and undo would then be able to delete them.

## Consequences

- Large raw files are backed up only by whatever syncs or backs up the vault folder (Google Drive, Time Machine, Syncthing, Obsidian Sync), not by git. The Phase 7 sync decision has to cover `.raw/`.
- Undoing a capture leaves large files on disk. A later capture re-records them, because their hash still matches.
- The default was lowered from 20 MB to 5 MB on the same day, before merge, to save disk space on the MacBook Air. Every committed raw file is stored twice on disk (the `.raw/` copy and git's compressed copy), and PDFs barely compress. At 5 MB, text captures, captions and transcripts stay fully versioned, while most PDFs, images and all video live only in `.raw/`. Raw files never change once captured, so losing git history for them costs little. Undo matters most for the wiki pages, and those are always committed.
- A vault set up before this ADR has no `raw_git_max_mb` key and keeps every raw file in git, which is how the test fixture vault behaves.
