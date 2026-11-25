# Project context (handoff from claude.ai planning sessions)

This file carries the context from the planning conversations (2026-11-24 to 2026-11-25) that produced this repo, so work can continue in Claude Code without re-deriving it. `CLAUDE.md` imports it. Update it when the facts below change; record history in `devlog/` and decisions in `docs/decisions/`, not here.

## Who I'm working with

- **Cheneral** (GitHub `SC1432`), fourth-year Computer Science student at Brandon University, Manitoba. Timezone America/Winnipeg.
- Machine: 2020 M1 MacBook Air, 8 GB RAM, macOS, Homebrew, `gh` installed. Keep local processes light (no large local models; Whisper `base`/`small` at most).
- Already keeps an **Obsidian vault** with coursework, honours research notes and personal items. Akasha will eventually adopt it.
- Comfortable with Python, git and the terminal; wants to understand and own every part of the system, so explain non-obvious choices briefly in commits and devlog entries.

## How Cheneral wants me to work

- **Warn before anything destructive.** Before stopping, removing, recreating, overwriting or changing ports on anything that exists, say so explicitly and get a yes. This includes `git push --force`, deleting files in the real vault, and history rewrites.
- **One plan, then a checkpoint for big calls.** Decide the approach before answering; give one linear plan, no mid-answer pivots. For destructive actions, new architecture or infrastructure, spending money, or genuinely ambiguous asks: present the plan with tradeoffs and wait. Below that threshold: just do it, end to end.
- **Finish the whole ask.** Do every item in a list. "Done" means committed, pushed and visible, not just written. Partial work gets flagged as partial; never present a stub as finished.
- **Disagree directly.** If an idea or instruction is wrong, say so and why. Add real risks or a better approach briefly after the main answer, not as a detour.
- **Code blocks are copy-paste only.** No commentary inside them.
- **Style:** no filler ("Great question!"), don't restate the prompt, stay on topic, minimal disclaimers, no generic advice, depth over breadth, don't invent facts. Prose over heavy bullet lists in written explanations.
- **Capture decisions.** When a session produces real decisions, record them (devlog + ADR per `CLAUDE.md`).

## What Akasha is

A **Claude Code plugin** that turns an Obsidian vault into a personal assistant ("second brain"). The originating problem: useful Instagram posts/reels (and other resources) get saved or DM'd to self and never revisited, because saving is one tap and retrieval is effort. Akasha makes capture cheap and has Claude extract, organize, link and resurface the content.

Scope, in build order: knowledge wiki from captured sources → project tracker with a session brief → course summaries with active-recall questions from school notes → vault health/lint → packaging → phone capture (Instagram, YouTube, web) and scheduled jobs. Later areas are added through the extension contract (schema entry + template + skill).

Name: from *akasha* (Sanskrit ākāśa, "aether/sky"), root of the Akashic records. Chosen 2026-11-25 over Muninn, Mimir, Hippo, Memex, Loci and others. Command prefix `/akasha:`, writer `scripts/akashactl.py`, vault settings `akasha.json`, runtime state `.akasha/`.

Full design: `docs/design.md`. Roadmap with task checklists: `docs/roadmap.md`. Decisions: `docs/decisions/`.

## Decisions already made (do not reopen without a reason)

1. **Claude Code plugin, not an Agent SDK app** (ADR-0001). Unattended work later runs as scheduled `claude -p` jobs via launchd. The vault and `akashactl` are runtime-independent, so an SDK move later loses nothing.
2. **One main agent; areas are skills + note types; subagents only by task shape** (ADR-0002). Cheneral originally proposed one subagent per life area; rejected because cross-area questions need lossy handoffs, each spawn adds cost/latency, and routing grows with every area. Subagents: `source-reader` (reads untrusted captured content, no write/shell/web tools, returns a draft) and `reviewer` (checks drafts against raw sources with fresh context).
3. **Own small core, not a fork of claude-obsidian** (ADR-0003). Pattern borrowed from [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) (MIT): inbox → hash-named immutable `.raw/` → `wiki/`, index/log/hot cache, single writer. Replaced its journal/fingerprint/ledger subsystem with: `base_hash` check per updated page + one git commit per operation + `akashactl undo` = `git revert` of the last Akasha commit. No claim ledger in v1. Credit claude-obsidian in the README.
4. **Single writer.** Only `akashactl.py` writes to a vault. Skills and agents produce JSON write plans; `akashactl apply` validates (path allow-list, schema, `base_hash`, links resolve), writes, updates `wiki/index.md` and `wiki/log.md`, refreshes `wiki/hot.md`, commits. Every apply supports `--dry-run`, and skills show the dry run before applying.
5. **`personal/` is read-only to Akasha; `.raw/` is create-only.** Generated pages carry `generated: true` in frontmatter.
6. **Security boundary for prompt injection** from captured content: only `source-reader` touches untrusted text; `akashactl` only accepts well-formed plans into allowed folders; everything is dry-run then committed.
7. **Usage gates between phases.** No new area until the previous one has been used (Phase 3 gate: two weeks of daily use).
8. **Non-goals for v1:** standalone always-on app, embeddings search (keyword + links until a few hundred notes), multi-user, writes without a dry run.

## Facts verified during planning

- A Claude Code plugin is a directory with a manifest at `.claude-plugin/plugin.json` plus components: `skills/<name>/SKILL.md` (each also runs as `/<plugin>:<name>`), `agents/*.md`, `hooks/hooks.json`, `.mcp.json`. Source: https://code.claude.com/docs/en/plugins/overview
- During development, load without a marketplace: `claude --plugin-dir <path>`.
- Plugin manifest: only `name` is required; everything except `plugin.json` goes at the plugin root, not inside `.claude-plugin/`. Files in `bin/` are added to the Bash tool's PATH while the plugin is enabled, so skills call `akashactl` directly. `${CLAUDE_PLUGIN_ROOT}` is substituted inline in skill/agent Markdown and exported to hooks, but is **not** set in the Bash tool's environment. `${CLAUDE_PLUGIN_DATA}` persists across updates. Source: https://code.claude.com/docs/en/plugins-reference (read 2026-11-25).
- Skill frontmatter: `disable-model-invocation: true` makes a skill user-invoked only (`/name`); `user-invocable: false` is the opposite. `argument-hint`, `allowed-tools`, `$ARGUMENTS` / `$0` substitution. Source: https://code.claude.com/docs/en/skills.
- `claude plugin validate <dir>` checks the manifest and layout; `claude --plugin-dir <dir> plugin details akasha` shows the component inventory and always-on token cost. The `claude` CLI exists in cloud containers, so both run in CI-style tests. Publishing to the plugin directory requires a `LICENSE` file or `license` in `plugin.json` (Phase 6).
- Distribution: a repo with `.claude-plugin/marketplace.json`; install via `claude plugin marketplace add <owner>/<repo>` then `claude plugin install <plugin>@<marketplace>`.
- Every skill/agent Claude can invoke on its own costs context on every turn (name + description), so keep descriptions to one line and make rarely used skills user-invoked only.
- Cloud sessions (claude.ai/code) do not load local plugins; vault work happens in local Claude Code.
- claude-obsidian does no PDF/EPUB text extraction and needs a separate runner for web/YouTube; capture is a separate problem from organizing.

## Not yet verified (check docs before relying on them)

- That **SessionStart hook stdout is injected into the session context** (the session brief depends on it). Read the current hooks docs before building Phase 3.
- `marketplace.json` schema details (Phase 6).

## Schema and frontmatter formats (resolved, ADR-0004)

The schema is `schema/note-types.toml`, read with `tomllib`. Frontmatter goes through `scripts/lib/frontmatter.py`, a stdlib parser and emitter for a strict YAML subset (flat mapping; strings, ints, bools, null, lists of those). It raises `FrontmatterError` with a line number on anything else rather than guessing. `scripts/lib/schema.py` validates a page's frontmatter and path against the schema. Both were cross-checked against PyYAML: no mismatches over 20,000 random scalars and 12,174 accepted flow lists. PyYAML is not a dependency; it was only used for that check.

## Current state (2026-11-25)

- Repo: https://github.com/SC1432/Akasha (private, default branch `main`). Docs (`README.md`, `CLAUDE.md`, `docs/design.md`, `docs/roadmap.md`, `docs/decisions/0000–0005`, `devlog/`) plus `schema/note-types.toml`, `.claude-plugin/plugin.json`, `bin/akashactl`, `scripts/akashactl.py` (`capture`, `apply`, `undo`, read-only `validate` and `hash`), `scripts/lib/{frontmatter,schema,vault,gitops,capture,plan,apply,undo}.py`, `skills/` (empty), `tests/` with the fixture vault in `tests/fixtures/vault/` (232 passing, `python3 -m pytest`) and `pyproject.toml` (pytest config only, no runtime dependencies).
- A design doc also exists as a claude.ai artifact ("Akasha: Personal AI Assistant Plugin for Claude Code", https://claude.ai/artifact/UfVbKLAz7CaYgrhs3xSHZx). The repo's `docs/design.md` is now the source of truth; the artifact is not kept in sync.
- **Phase 1 in progress.** Done: ADR-0004 and its code; plugin scaffold; fixture vault; `akashactl capture`, `apply` (+ `--dry-run`/`--diff`), `undo` (ADR-0005). Next unchecked roadmap item: `/akasha:setup`, then the trial with `claude --plugin-dir` on a copy of the real vault (needs Cheneral's Mac).

## Open decisions (ask Cheneral when they block work)

- Adopt the existing Obsidian vault in place, or start a new vault and migrate gradually. Until decided, develop against the fixture vault in `tests/` and a **copy** of the real vault, never the original.
- Which existing vault folders count as `personal/` (coursework, honours research, personal items are candidates).
- Always-on host for Phase 7 (VPS, home-lab box, or Mac only) and vault sync (Obsidian Sync vs git + Syncthing).
- Anthropic API key vs Claude Code plan for headless jobs.

## Next steps

1. `/akasha:setup` per `docs/roadmap.md`: preview, adopt existing vault, pick `personal/` folders, write `akasha.json`, `git init`. Decide here how large media in `.raw/` is kept out of git (size threshold + `.gitignore`, or Git LFS).
2. Load with `claude --plugin-dir` against a copy of the real vault.
3. End the session per `CLAUDE.md`: devlog entry, tick roadmap, commit and push.

## Later-phase notes worth keeping

- Phone capture plan (Phase 7): Instagram share sheet → private Telegram bot → fetch (yt-dlp / instaloader for media and caption, Whisper for reel audio, Claude vision for carousel text) → text file into `inbox/`. Instagram actively blocks scrapers: use a throwaway account's cookies, never the main account, and build the screenshot fallback (bot asks for a screenshot when a fetch fails) from the start.
- YouTube: captions first (yt-dlp / youtube-transcript-api), Whisper only as fallback. Web: trafilatura or Obsidian Web Clipper. PDFs/EPUBs: pymupdf / ebooklib, chunked by chapter. Books: highlights and own reflections, not full text.
- Instagram "Download your information" export gives saved-post links for a one-time backlog import.
- Course summaries: `review.md` uses active-recall questions with answers hidden in Obsidian callouts; Cheneral studies with active recall, blurting, quizzing and spaced repetition.
