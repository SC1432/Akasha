---
name: setup
description: Make a folder an Akasha vault or adopt an existing Obsidian vault in place.
disable-model-invocation: true
argument-hint: "[vault-folder]"
---

# Akasha setup

Set up the vault at `$ARGUMENTS` (if empty, use the current working directory). All writes go through `akashactl init`; do not create, move or edit any file in the vault yourself.

1. **Preview.** Run `akashactl init --vault "<folder>" --dry-run`. If it prints `setup refused`, show the reasons, explain what the user needs to change, and stop.
2. **Safety check.** If the folder already holds notes and this is the user's first time using Akasha on it, recommend trying setup on a copy of the vault first, and ask whether to continue on this folder.
3. **Personal folders.** Show the `folders found` list. Explain that personal folders hold the user's own writing: Akasha reads them but never writes to them. Ask which folders are personal. The options are any of the listed folders, the default (a new `personal/` folder), or none (`--no-personal`). Pass each chosen folder as its own `--personal "<name>"`.
4. **Large files.** Explain in one sentence that captured files larger than 20 MB are stored in `.raw/` but kept out of git, so the user's sync or backup must cover them. Ask whether 20 MB is fine. Pass `--raw-git-max-mb <n>` only if they want a different limit, or `0` for no limit.
5. **Confirm.** Run the dry run again with the chosen options and show its full output. Ask for an explicit yes before continuing.
6. **Apply.** Run the same command without `--dry-run`. Report the commit it made.
7. **Next steps.** If the output warned that existing notes stay untracked, tell the user they can version them with `git add -A && git commit -m "Existing notes"` from the vault folder, and that this is their choice. Then say that files dropped into `inbox/` are copied into `.raw/` by running `akashactl capture` in the vault folder.
