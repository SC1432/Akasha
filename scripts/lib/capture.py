"""inbox/ -> .raw/: hash each file, copy it create-only as .raw/<sha256><ext>, record it in the manifest.

The inbox is never modified. .raw/<hash> files are only ever created, never changed;
.raw/manifest.json is the one file in .raw/ that is rewritten (atomically) on each capture.
"""

from __future__ import annotations

import configparser
import datetime
import hashlib
import json
import plistlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops
from .vault import Vault, write_atomic

__all__ = ["CaptureError", "CaptureResult", "capture", "MANIFEST", "RAW", "INBOX"]

INBOX = "inbox"
RAW = ".raw"
MANIFEST = f"{RAW}/manifest.json"
URL_RE = re.compile(r"https?://\S+")
LINK_TEXT_MAX = 4096  # a "link file" is a tiny text file holding one URL

KINDS = {
    ".md": "text", ".markdown": "text", ".txt": "text",
    ".pdf": "pdf", ".epub": "epub",
    ".html": "html", ".htm": "html",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image", ".heic": "image",
    ".mp3": "audio", ".m4a": "audio", ".wav": "audio", ".ogg": "audio",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".url": "link", ".webloc": "link",
}


class CaptureError(Exception):
    pass


@dataclass
class CaptureResult:
    new: list[dict] = field(default_factory=list)  # manifest entries added
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (inbox path, hash)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (inbox path, reason)
    commit: str | None = None


def capture(vault: Vault, dry_run: bool = False, today: datetime.date | None = None) -> CaptureResult:
    inbox = vault.path(INBOX)
    raw = vault.path(RAW)
    result = CaptureResult()
    if not inbox.is_dir():
        return result
    if raw.is_symlink() or (raw.exists() and not raw.is_dir()):
        raise CaptureError(f"{RAW} must be a real directory")
    manifest = _load_manifest(vault)
    captured_on = (today or datetime.date.today()).isoformat()
    pending: dict[str, tuple[Path, dict]] = {}

    for path in sorted(inbox.rglob("*")):
        rel = path.relative_to(vault.root).as_posix()
        if any(part.startswith(".") for part in path.relative_to(inbox).parts):
            if path.is_file():
                result.skipped.append((rel, "hidden file"))
            continue
        if path.is_symlink():
            result.skipped.append((rel, "symlink"))
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if not data:
            result.skipped.append((rel, "empty file"))
            continue
        digest = hashlib.sha256(data).hexdigest()
        ext = path.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
            ext = ""
        stored = f"{digest}{ext}"
        dest = raw / stored

        known = manifest["files"].get(digest)
        if digest in pending or (known and vault.path(known["file"]).is_file()):
            result.duplicates.append((rel, digest))
            continue
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                raise CaptureError(f"{RAW}/{stored} exists but its content does not match its name")
            # File present but missing from the manifest (e.g. manifest restored): re-record it.

        entry = {
            "hash": digest,
            "file": f"{RAW}/{stored}",
            "name": path.name,
            "inbox_path": rel,
            "kind": KINDS.get(ext, "other"),
            "size": len(data),
            "captured": captured_on,
            "origin": None,
        }
        url = _link_target(ext, data)
        if url:
            entry.update(kind="link", origin=url, fetch="pending")
        pending[digest] = (dest, entry)
        result.new.append(entry)

    if dry_run or not pending:
        return result

    raw.mkdir(exist_ok=True)
    written = []
    for digest, (dest, entry) in pending.items():
        if not dest.exists():
            source = vault.root / entry["inbox_path"]
            with open(dest, "xb") as f:  # create-only: fails rather than overwrite
                f.write(source.read_bytes())
            if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                dest.unlink()
                raise CaptureError(f"{entry['inbox_path']} changed while being captured; run capture again")
        manifest["files"][digest] = entry
        written.append(entry["file"])
    write_atomic(vault.path(MANIFEST), (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())

    count = len(pending)
    body = "\n".join(f"- {e['inbox_path']} -> {e['file']}" for e in result.new)
    result.commit = gitops.commit_paths(
        vault.root, [*written, MANIFEST], f"akasha: capture {count} file{'s' * (count != 1)}", "capture", body
    )
    return result


def _load_manifest(vault: Vault) -> dict:
    path = vault.path(MANIFEST)
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CaptureError(f"{MANIFEST} is unreadable: {e}") from e
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
        raise CaptureError(f"{MANIFEST}: expected {{\"version\": 1, \"files\": {{...}}}}")
    return manifest


def _link_target(ext: str, data: bytes) -> str | None:
    """Return the URL if this file is just a link: a .url, a .webloc, or a text file holding one URL."""
    if len(data) > LINK_TEXT_MAX:
        return None
    try:
        if ext == ".webloc":
            url = plistlib.loads(data).get("URL")
        elif ext == ".url":
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(data.decode("utf-8-sig"))
            url = parser.get("InternetShortcut", "URL", fallback=None)
        elif ext in (".txt", ".md", ""):
            url = data.decode("utf-8-sig").strip()
        else:
            return None
    except (ValueError, UnicodeDecodeError, configparser.Error, plistlib.InvalidFileException):
        return None
    if isinstance(url, str) and URL_RE.fullmatch(url.strip()):
        return url.strip()
    return None
