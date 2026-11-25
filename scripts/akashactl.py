"""akashactl: the only process that writes to an Akasha vault.

Skills and agents produce write plans; this CLI validates and applies them.
Implemented so far: `capture` and `validate` (read-only). `apply`, `undo`,
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
import tomllib
from pathlib import Path

# Run with `python3 -I`, which does not add this directory to sys.path; add it explicitly.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import capture, frontmatter, gitops, schema, vault as vault_mod  # noqa: E402

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="akashactl", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"akashactl {plugin_version()}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("capture", help="hash inbox/ files into .raw/ and commit")
    p.add_argument("--vault", default=".", help="vault root (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="show what would be captured; write nothing")
    p.set_defaults(func=cmd_capture)

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
