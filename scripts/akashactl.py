"""akashactl: the only process that writes to an Akasha vault.

Skills and agents produce write plans; this CLI validates and applies them.
Implemented: `init`, `capture`, `apply`, `undo`, and the read-only `validate` and `hash`.
`brief` and `lint` arrive per docs/roadmap.md.
"""

import sys

if sys.version_info < (3, 11):
    sys.exit(
        f"akashactl needs Python 3.11 or newer (found {sys.version.split()[0]}). "
        "On macOS, install it with Homebrew: brew install python"
    )

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

# Run with `python3 -I`, which does not add this directory to sys.path; add it explicitly.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import apply as apply_mod  # noqa: E402
from lib import capture, frontmatter, gitops, plan as plan_mod, schema, setup_vault, undo as undo_mod  # noqa: E402
from lib import vault as vault_mod  # noqa: E402

PLUGIN_ROOT = SCRIPTS_DIR.parent


def plugin_version() -> str:
    manifest = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["version"]


def cmd_validate(args: argparse.Namespace) -> int:
    """Check generated pages' frontmatter and location against the schema. Never writes."""
    vault = Path(args.vault).resolve()
    if not vault.is_dir():
        print(f"error: vault {vault} is not a directory", file=sys.stderr)
        return 2
    try:
        note_schema = schema.load(args.schema) if args.schema else schema.load()
    except (OSError, schema.SchemaError) as e:
        print(f"error: schema: {e}", file=sys.stderr)
        return 2

    if args.paths:
        targets, explicit = [Path(p) for p in args.paths], True
    else:
        targets, explicit = sorted((vault / "wiki").rglob("*.md")), False

    problems = checked = skipped = 0
    for target in targets:
        full = (target if target.is_absolute() else Path.cwd() / target).resolve()
        if not full.is_relative_to(vault):
            print(f"{target}: outside the vault {vault}")
            problems += 1
            continue
        rel = full.relative_to(vault).as_posix()
        try:
            meta, _ = frontmatter.parse(full.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            print(f"{rel}: cannot read: {e}")
            problems += 1
            continue
        except frontmatter.FrontmatterError as e:
            print(f"{rel}: frontmatter: {e}")
            problems += 1
            continue
        if not explicit and meta.get("generated") is not True:
            skipped += 1
            continue
        checked += 1
        errors = schema.validate(meta, rel, note_schema)
        for err in errors:
            print(f"{rel}: {err}")
        problems += bool(errors)

    print(f"{checked} checked, {problems} with problems, {skipped} skipped (not generated)")
    return 1 if problems else 0


def cmd_init(args: argparse.Namespace) -> int:
    """Make a folder an Akasha vault (or adopt an existing one). --dry-run previews and writes nothing."""
    personal = [] if args.no_personal else args.personal
    limit = None if args.raw_git_max_mb == 0 else args.raw_git_max_mb
    try:
        plan = setup_vault.plan_init(args.vault, personal, limit)
    except setup_vault.InitError as e:
        print("setup refused, nothing written:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("dry run, nothing written." if args.dry_run else "setting up:")
    for line in plan.describe():
        print(line)
    if args.dry_run:
        return 0
    try:
        commit = setup_vault.run_init(plan)
    except (gitops.GitError, OSError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"done; commit {commit[:12]}" if commit else "done")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    """Hash inbox files into .raw/ (create-only) and commit. The inbox is left as it is."""
    try:
        vault = vault_mod.open_vault(args.vault)
        result = capture.capture(vault, dry_run=args.dry_run)
    except (vault_mod.VaultError, capture.CaptureError, gitops.GitError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    prefix = "would capture" if args.dry_run else "captured"
    for entry in result.new:
        extra = f" (link, fetch pending: {entry['origin']})" if entry.get("fetch") else ""
        print(f"{prefix}: {entry['inbox_path']} -> {entry['file']}{extra}")
    for rel, digest in result.duplicates:
        print(f"duplicate: {rel} (already {digest[:12]})")
    for rel, reason in result.skipped:
        print(f"skipped: {rel} ({reason})")
    summary = f"{len(result.new)} new, {len(result.duplicates)} duplicate, {len(result.skipped)} skipped"
    if result.commit:
        summary += f"; commit {result.commit[:12]}"
    elif args.dry_run:
        summary += "; dry run, nothing written"
    print(summary)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Validate a write plan, then write it as one commit (or only show it with --dry-run)."""
    try:
        vault = vault_mod.open_vault(args.vault)
        note_schema = schema.load()
        text = sys.stdin.read() if args.plan == "-" else Path(args.plan).read_text(encoding="utf-8")
        plan = plan_mod.validate_plan(plan_mod.load_plan(text), vault, note_schema)
        result = apply_mod.apply_plan(plan, vault, note_schema, dry_run=args.dry_run)
    except plan_mod.PlanError as e:
        print("plan rejected, nothing written:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except (vault_mod.VaultError, apply_mod.ApplyError, schema.SchemaError, gitops.GitError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print("dry run, nothing written:" if args.dry_run else f"applied {plan.operation}:")
    for line in result.summary_lines(diff=args.diff):
        print(f"  {line}" if not args.diff else line)
    print("log entry:")
    for line in result.log_entry.rstrip("\n").splitlines():
        print(f"  {line}")
    if result.commit:
        print(f"commit {result.commit[:12]}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """Restore the files of the last Akasha operation that hasn't been undone, as a new commit."""
    try:
        vault = vault_mod.open_vault(args.vault)
        result = undo_mod.undo(vault, dry_run=args.dry_run)
    except undo_mod.UndoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (vault_mod.VaultError, gitops.GitError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    verb = "would undo" if args.dry_run else "undid"
    print(f"{verb} {result.target[:12]} {result.subject}")
    for path in result.restored:
        print(f"  restore {path}")
    for path in result.deleted:
        print(f"  delete {path}")
    if result.commit:
        print(f"commit {result.commit[:12]}")
    return 0


def cmd_hash(args: argparse.Namespace) -> int:
    """Print the sha256 of each file, for use as base_hash in an update."""
    status = 0
    for path in args.paths:
        try:
            print(f"{plan_mod.sha256_file(Path(path))}  {path}")
        except OSError as e:
            print(f"error: {path}: {e}", file=sys.stderr)
            status = 2
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="akashactl", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"akashactl {plugin_version()}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("init", help="make a folder an Akasha vault, or adopt an existing vault")
    p.add_argument("--vault", default=".", help="vault folder (default: current directory)")
    p.add_argument("--personal", action="append", metavar="FOLDER",
                   help="folder of your own notes, read-only to Akasha (repeatable; default: personal/)")
    p.add_argument("--no-personal", action="store_true", help="no personal folders")
    p.add_argument("--raw-git-max-mb", type=float, default=setup_vault.DEFAULT_RAW_GIT_MAX_MB, metavar="MB",
                   help=f"keep captured files larger than this out of git (default {setup_vault.DEFAULT_RAW_GIT_MAX_MB}; 0 = no limit)")
    p.add_argument("--dry-run", action="store_true", help="show what setup would do; write nothing")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("capture", help="hash inbox/ files into .raw/ and commit")
    p.add_argument("--vault", default=".", help="vault root (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="show what would be captured; write nothing")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("apply", help="validate a write plan and apply it as one commit")
    p.add_argument("plan", help="plan JSON file, or - for stdin")
    p.add_argument("--vault", default=".", help="vault root (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="validate and show the changes; write nothing")
    p.add_argument("--diff", action="store_true", help="also print a unified diff of every file")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("undo", help="revert the last Akasha operation that hasn't been undone")
    p.add_argument("--vault", default=".", help="vault root (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="show what would be restored; write nothing")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("hash", help="print sha256 of files (the base_hash for an update)")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_hash)

    p = sub.add_parser("validate", help="check generated pages against the schema (read-only)")
    p.add_argument("paths", nargs="*", help="pages to check; default: every generated page in wiki/")
    p.add_argument("--vault", default=".", help="vault root (default: current directory)")
    p.add_argument("--schema", help="schema file (default: the plugin's schema/note-types.toml)")
    p.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
