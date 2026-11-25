# CLAUDE.md

This repo is both the Akasha plugin and the record of how it was built. Keep the record current.

## At the end of every working session

1. Create or append to `devlog/YYYY-MM-DD.md` (today's date) using `devlog/TEMPLATE.md`: what was done, what was learned, problems hit, next step.
2. Tick completed tasks in `docs/roadmap.md` and update the status line in `README.md` if a phase changed.
3. If an architectural decision was made or reversed, add an ADR in `docs/decisions/` (next number, template in `docs/decisions/0000-template.md`) and link it from the devlog entry.
4. Commit docs changes together with the code they describe.

## Conventions

- Python 3.11+, standard library first; tests with pytest against the fixture vault in `tests/`.
- Only `scripts/akashactl.py` may write to a vault. Skills and agents produce write plans.
- Never write to a vault's `personal/` or `.raw/` folders from plan code.
- Keep skill descriptions to one line; they cost context on every turn.
- Devlog entries are factual and short: no padding, include commands, errors and numbers.
