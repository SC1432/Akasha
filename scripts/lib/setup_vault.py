"""akashactl init: make a folder an Akasha vault, or adopt an existing Obsidian vault in place.

Creates only new files (plus a marked block appended to .gitignore), runs `git init` if the
folder is not a repository yet, and commits just the files it created. Existing notes are
never moved, rewritten or committed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import gitops
from .apply import INDEX, INDEX_NOTE, LOG
from .vault import CONFIG, write_atomic

__all__ = ["InitError", "InitPlan", "plan_init", "run_init", "DEFAULT_RAW_GIT_MAX_MB"]

DEFAULT_RAW_GIT_MAX_MB = 20
MANAGED = ("inbox", "wiki", ".raw", ".akasha")
RESERVED_PAGES = (INDEX, LOG, "wiki/hot.md", "wiki/now.md")
GITIGNORE_HEADER = "# Akasha (managed by akashactl)"
GITIGNORE_LINES = [".akasha/", "inbox/*", "!inbox/.gitkeep"]
INBOX_KEEP = "inbox/.gitkeep"


class InitError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class InitPlan:
    root: Path
    exists: bool
    is_repo: bool
    obsidian: bool
    config: dict
    folders: list[tuple[str, int]] = field(default_factory=list)  # (top-level folder, .md count)
    loose_notes: int = 0
    create_dirs: list[str] = field(default_factory=list)
    create_files: dict[str, str] = field(default_factory=dict)
    gitignore_add: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        state = ["exists" if self.exists else "will be created"]
        if self.obsidian:
            state.append("Obsidian vault")
        state.append("git repository" if self.is_repo else "not a git repository")
        lines = [f"vault: {self.root} ({', '.join(state)})"]
        if self.folders or self.loose_notes:
            lines.append("folders found:")
            lines += [f"  {name}/  {count} note{'s' * (count != 1)}" for name, count in self.folders]
            if self.loose_notes:
                lines.append(f"  (top level)  {self.loose_notes} note{'s' * (self.loose_notes != 1)}")
        lines.append("actions:")
        if not self.is_repo:
            lines.append("  git init")
        lines += [f"  create folder {d}/" for d in self.create_dirs]
        lines += [f"  create {f}" for f in self.create_files if f != CONFIG]
        if self.gitignore_add:
            lines.append(f"  add to .gitignore: {', '.join(self.gitignore_add)}")
        lines.append(f"  write {CONFIG}: {json.dumps(self.config)}")
        lines.append("  commit only the files above" + ("" if self.is_repo else "; existing notes stay untracked"))
        if self.warnings:
            lines.append("warnings:")
            lines += [f"  {w}" for w in self.warnings]
        return lines


def plan_init(root: Path | str, personal: list[str] | None = None,
              raw_git_max_mb: float | None = DEFAULT_RAW_GIT_MAX_MB) -> InitPlan:
    """Inspect the folder and decide what init would do. Reads only; raises InitError on any problem."""
    root = Path(root).expanduser().resolve()
    errors: list[str] = []
    home = Path.home().resolve()
    if root == Path(root.anchor) or root == home or home.is_relative_to(root):
        raise InitError([f"{root} is your home folder or contains it; choose a dedicated vault folder"])
    if root.exists() and not root.is_dir():
        raise InitError([f"{root} exists and is not a folder"])
    exists = root.exists()
    if exists and (root / CONFIG).exists():
        raise InitError([f"{root} is already an Akasha vault ({CONFIG} exists); edit {CONFIG} to change settings"])

    is_repo = exists and gitops.is_repo_root(root)
    if not is_repo:
        ancestor = root if exists else next(p for p in root.parents if p.exists())
        toplevel = _git_toplevel(ancestor)
        if toplevel:
            errors.append(f"{root} is inside the git repository {toplevel}; the vault must be its own repository")

    default_personal = personal is None
    personal = ["personal"] if default_personal else personal
    clean_personal = []
    for folder in personal:
        name = folder.strip().rstrip("/")
        p = PurePosixPath(name)
        if not name or p.is_absolute() or "\\" in name or any(part in ("", ".", "..") for part in name.split("/")):
            errors.append(f"personal folder {folder!r} must be a plain relative folder name")
            continue
        if any(part.startswith(".") for part in p.parts):
            errors.append(f"personal folder {folder!r} must not be hidden")
            continue
        if p.parts[0] in MANAGED:
            errors.append(f"personal folder {folder!r} overlaps {p.parts[0]}/, which Akasha manages")
            continue
        if not default_personal and not (root / name).is_dir():
            errors.append(f"personal folder {name!r} does not exist in {root}")
            continue
        if name not in clean_personal:
            clean_personal.append(name)

    if raw_git_max_mb is not None and not (isinstance(raw_git_max_mb, (int, float)) and raw_git_max_mb > 0):
        errors.append("raw_git_max_mb must be a positive number (or 0 for no limit)")

    for page in RESERVED_PAGES:
        if (root / page).exists():
            errors.append(f"{page} already exists; Akasha maintains that file. Rename yours first")
    raw = root / ".raw"
    if raw.exists() and (not raw.is_dir() or any(raw.iterdir())):
        errors.append(".raw/ already exists and is not empty; Akasha needs it for its own source copies")
    for name in ("inbox", "wiki", ".akasha"):
        target = root / name
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            errors.append(f"{name} exists but is not a plain folder")
    if errors:
        raise InitError(errors)

    config = {"version": 1, "personal": clean_personal, "raw_git_max_mb": raw_git_max_mb}
    plan = InitPlan(root=root, exists=exists, is_repo=is_repo, obsidian=(root / ".obsidian").is_dir(), config=config)
    if exists:
        plan.folders, plan.loose_notes = _survey(root)

    for d in ["inbox", "wiki", *([clean_personal[0]] if default_personal else [])]:
        if not (root / d).exists():
            plan.create_dirs.append(d)
    plan.create_files = {
        INBOX_KEEP: "",
        INDEX: f"# Index\n\n{INDEX_NOTE}\n",
        LOG: "# Log\n",
        CONFIG: json.dumps(config, indent=2) + "\n",
    }
    if (root / INBOX_KEEP).exists():
        del plan.create_files[INBOX_KEEP]

    existing = set()
    if (root / ".gitignore").is_file():
        existing = {line.strip() for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines()}
    plan.gitignore_add = [line for line in GITIGNORE_LINES if line not in existing]

    inbox_files = [p for p in (root / "inbox").rglob("*") if p.is_file() and p.name != ".gitkeep"] if exists else []
    if inbox_files:
        plan.warnings.append(f"inbox/ already has {len(inbox_files)} files; /akasha:capture will copy them into .raw/")
    wiki_files = [p for p in (root / "wiki").rglob("*.md") if p.is_file()] if exists else []
    if wiki_files:
        plan.warnings.append(
            f"wiki/ already has {len(wiki_files)} notes; Akasha only rewrites pages it generated (generated: true)"
        )
    if exists and not is_repo and (plan.folders or plan.loose_notes):
        plan.warnings.append("existing notes will not be committed; to version them too: git add -A && git commit")
    return plan


def run_init(plan: InitPlan) -> str | None:
    """Carry out an InitPlan. Returns the setup commit hash."""
    root = plan.root
    root.mkdir(parents=True, exist_ok=True)
    if not plan.is_repo:
        subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    for d in plan.create_dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    written = []
    for rel, content in plan.create_files.items():
        if rel == CONFIG:
            continue
        with open(root / rel, "x", encoding="utf-8") as f:  # create-only
            f.write(content)
        written.append(rel)
    if plan.gitignore_add:
        gitignore = root / ".gitignore"
        old = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        block = "\n".join([GITIGNORE_HEADER, *plan.gitignore_add]) + "\n"
        sep = "" if not old else ("\n" if old.endswith("\n") else "\n\n")
        write_atomic(gitignore, (old + sep + block).encode("utf-8"))
        written.append(".gitignore")
    # akasha.json last: a crash before this point leaves a folder that is not yet a vault.
    with open(root / CONFIG, "x", encoding="utf-8") as f:
        f.write(plan.create_files[CONFIG])
    written.append(CONFIG)
    body = "\n".join(f"- {p}" for p in written)
    return gitops.commit_paths(root, written, "akasha: setup", "setup", body)


def _git_toplevel(path: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _survey(root: Path) -> tuple[list[tuple[str, int]], int]:
    folders = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir() or entry.is_symlink():
            continue
        folders.append((entry.name, sum(1 for p in entry.rglob("*.md") if p.is_file())))
    loose = sum(1 for p in root.glob("*.md") if p.is_file())
    return folders, loose
