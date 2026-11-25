"""Load and validate a write plan. Nothing here writes; apply.py does that after validation passes.

A plan is JSON:
    {"operation": "ingest",
     "pages": [{"action": "create", "path": "wiki/...md", "content": "..."},
               {"action": "update", "path": "wiki/...md", "base_hash": "<sha256>", "content": "..."}],
     "log": "One line describing the change"}
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import frontmatter
from . import schema as schema_mod
from .vault import Vault

__all__ = ["PlanError", "Plan", "PageChange", "load_plan", "validate_plan", "sha256_file", "RESERVED", "WIKI"]

WIKI = "wiki"
RESERVED = {f"{WIKI}/index.md", f"{WIKI}/log.md", f"{WIKI}/hot.md", f"{WIKI}/now.md"}
RESERVED_OPERATIONS = {"capture", "undo"}
OPERATION_RE = re.compile(r"[a-z][a-z0-9-]{0,39}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
MAX_PAGE_BYTES = 1_000_000
MAX_LOG_CHARS = 300
LINK_RE = re.compile(r"!?\[\[([^\]\|#\n]*)(?:#[^\]\|\n]*)?(?:\|[^\]\n]*)?\]\]")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
SKIP_DIRS = {".git", ".raw", ".akasha", ".obsidian", ".trash"}


class PlanError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class PageChange:
    action: str  # "create" or "update"
    path: str
    content: str
    old_content: str | None = None


@dataclass
class Plan:
    operation: str
    log: str
    pages: list[PageChange]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanError([f"plan is not valid JSON: {e}"]) from e
    if not isinstance(data, dict):
        raise PlanError(["plan must be a JSON object"])
    return data


def validate_plan(data: dict, vault: Vault, note_schema: dict) -> Plan:
    """Check everything before any write. Raises PlanError listing every problem found."""
    errors: list[str] = []
    extra = set(data) - {"operation", "pages", "log"}
    if extra:
        errors.append(f"unknown plan keys: {', '.join(sorted(extra))}")
    operation = data.get("operation")
    if not isinstance(operation, str) or not OPERATION_RE.fullmatch(operation):
        errors.append("operation must be a short lowercase name like 'ingest'")
    elif operation in RESERVED_OPERATIONS:
        errors.append(f"operation {operation!r} is reserved for akashactl")
    log = data.get("log")
    if not isinstance(log, str) or not log.strip():
        errors.append("log must be a non-empty string")
        log = ""
    log = " ".join(log.split())
    if len(log) > MAX_LOG_CHARS:
        errors.append(f"log must be at most {MAX_LOG_CHARS} characters")
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        errors.append("pages must be a non-empty list")
        pages = []

    changes: list[PageChange] = []
    seen: dict[str, str] = {}
    for i, page in enumerate(pages):
        label = f"pages[{i}]"
        if not isinstance(page, dict):
            errors.append(f"{label}: must be an object")
            continue
        path = page.get("path")
        if isinstance(path, str):
            label = path
        change = _check_page(page, label, vault, note_schema, errors)
        if change is None:
            continue
        key = change.path.lower()
        if key in seen:
            errors.append(f"{label}: appears twice in the plan (as {seen[key]!r})")
            continue
        seen[key] = change.path
        changes.append(change)

    if not errors:
        errors.extend(_check_links(changes, vault))
    if errors:
        raise PlanError(errors)
    return Plan(operation=operation, log=log, pages=changes)


def _check_page(page: dict, label: str, vault: Vault, note_schema: dict, errors: list[str]) -> PageChange | None:
    before = len(errors)
    action = page.get("action")
    allowed = {"action", "path", "content"} | ({"base_hash"} if action == "update" else set())
    extra = set(page) - allowed
    if action not in ("create", "update"):
        errors.append(f"{label}: action must be 'create' or 'update'")
    elif extra:
        errors.append(f"{label}: unknown keys {', '.join(sorted(extra))}")
    path = page.get("path")
    content = page.get("content")
    if not isinstance(path, str):
        errors.append(f"{label}: path must be a string")
        return None
    path_errors = _check_path(path, vault)
    errors.extend(f"{label}: {e}" for e in path_errors)
    if not isinstance(content, str):
        errors.append(f"{label}: content must be a string")
        return None
    if len(content.encode("utf-8")) > MAX_PAGE_BYTES:
        errors.append(f"{label}: content is larger than {MAX_PAGE_BYTES} bytes")
    if not content.startswith("---\n"):
        errors.append(f"{label}: content must start with frontmatter ('---' on the first line)")
    else:
        try:
            meta, _ = frontmatter.parse(content)
        except frontmatter.FrontmatterError as e:
            errors.append(f"{label}: frontmatter {e}")
        else:
            errors.extend(f"{label}: {e}" for e in schema_mod.validate(meta, path, note_schema))
    if path_errors or action not in ("create", "update"):
        return None

    full = vault.root / path
    old_content = None
    if action == "create":
        if _exists_any_case(full):
            errors.append(f"{label}: create, but a file with this name already exists")
    else:
        base_hash = page.get("base_hash")
        if not isinstance(base_hash, str) or not HASH_RE.fullmatch(base_hash):
            errors.append(f"{label}: update needs base_hash, the sha256 of the page as read")
        elif not full.is_file() or full.name not in {p.name for p in full.parent.iterdir()}:
            errors.append(f"{label}: update, but the page does not exist")
        else:
            current = full.read_bytes()
            if hashlib.sha256(current).hexdigest() != base_hash:
                errors.append(f"{label}: page changed since it was read (base_hash mismatch); re-read and re-plan")
            else:
                old_content = current.decode("utf-8", errors="replace")
                try:
                    old_meta, _ = frontmatter.parse(old_content)
                except frontmatter.FrontmatterError:
                    old_meta = {}
                if old_meta.get("generated") is not True:
                    errors.append(f"{label}: existing page is not generated: true; Akasha only rewrites its own pages")
    if len(errors) > before:
        return None
    return PageChange(action=action, path=path, content=content, old_content=old_content)


def _check_path(path: str, vault: Vault) -> list[str]:
    p = PurePosixPath(path)
    if "\\" in path or p.is_absolute() or path != p.as_posix():
        return ["path must be a plain relative path with '/' separators"]
    if any(part in ("", ".", "..") for part in path.split("/")):
        return ["path must not contain '.', '..' or empty parts"]
    if any(part.startswith(".") for part in p.parts):
        return ["path must not contain hidden files or folders"]
    if p.parts[0] != WIKI or len(p.parts) < 2:
        return [f"writes are only allowed under {WIKI}/"]
    if p.suffix != ".md":
        return ["only .md pages can be written"]
    if path.lower() in RESERVED:
        return [f"{path} is maintained by akashactl and cannot be written by a plan"]
    for folder in vault.personal:
        prefix = PurePosixPath(folder.strip("/"))
        if p.parts[: len(prefix.parts)] == prefix.parts or str(p).lower().startswith(str(prefix).lower() + "/"):
            return [f"{folder} is personal and read-only to Akasha"]
    current = vault.root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            return [f"{current.relative_to(vault.root).as_posix()} is a symlink; refusing to write through it"]
        if not current.exists():
            break
        if current != vault.root / path and not current.is_dir():
            return [f"{current.relative_to(vault.root).as_posix()} is a file, not a folder"]
    return []


def _exists_any_case(full: Path) -> bool:
    if full.exists():
        return True
    if not full.parent.is_dir():
        return False
    return any(p.name.lower() == full.name.lower() for p in full.parent.iterdir())


def vault_files(vault: Vault) -> list[str]:
    """Every file Obsidian would see (hidden and runtime folders skipped), as vault-relative paths."""
    found = []
    stack = [vault.root]
    while stack:
        folder = stack.pop()
        for entry in folder.iterdir():
            if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                continue
            if entry.is_dir() and not entry.is_symlink():
                stack.append(entry)
            elif entry.is_file():
                found.append(entry.relative_to(vault.root).as_posix())
    return found


def link_targets(content: str) -> list[str]:
    stripped = INLINE_CODE_RE.sub("", FENCE_RE.sub("", content))
    return [m.group(1).strip() for m in LINK_RE.finditer(stripped)]


def resolves(target: str, files_lower: set[str], names_lower: set[str]) -> bool:
    """Obsidian-style resolution: by vault path (full or trailing part) or by file name, ignoring case."""
    if not target:
        return True  # [[#heading]] links to the same page
    t = target.lower().lstrip("/")
    candidates = [t] if PurePosixPath(t).suffix else [t + ".md", t]
    for c in candidates:
        if "/" in c:
            if c in files_lower or any(f.endswith("/" + c) for f in files_lower):
                return True
        elif c in names_lower:
            return True
    return False


def _check_links(changes: list[PageChange], vault: Vault) -> list[str]:
    files = {f.lower() for f in vault_files(vault)} | {c.path.lower() for c in changes}
    names = {PurePosixPath(f).name for f in files}
    errors = []
    for change in changes:
        missing = sorted({t for t in link_targets(change.content) if not resolves(t, files, names)})
        if missing:
            errors.append(f"{change.path}: links to pages that don't exist: {', '.join(missing)}")
    return errors
