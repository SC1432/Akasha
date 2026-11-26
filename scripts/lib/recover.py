"""Clean up after an akashactl write that was interrupted (crash, power loss, kill) before it committed.

The write lock (.akasha/lock) records the operation and the exact paths it was about to touch.
Recover puts each of those paths back to the last commit, deletes files the interrupted
operation created, unstages anything it staged, and clears the lock. Nothing outside the
recorded paths is touched. A complete .raw/ copy (content hash matches its name) is kept even
if uncommitted: it is a valid source copy, and the next capture records it again.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .gitops import _git
from .vault import LOCK, Vault, write_atomic

__all__ = ["RecoverError", "RecoverResult", "recover"]

RAW_BOOKKEEPING = {".raw/manifest.json", ".raw/.gitignore"}


class RecoverError(Exception):
    pass


@dataclass
class RecoverResult:
    found: bool = False
    operation: str = ""
    started: str = ""
    pid: int | None = None
    restored: list[str] = field(default_factory=list)  # put back to the last commit
    deleted: list[str] = field(default_factory=list)  # created by the interrupted write
    kept: list[str] = field(default_factory=list)  # complete raw copies, left for the next capture
    unchanged: list[str] = field(default_factory=list)  # already match the last commit
    notes: list[str] = field(default_factory=list)


def recover(vault: Vault, dry_run: bool = False) -> RecoverResult:
    lock = vault.root / LOCK
    result = RecoverResult()
    if not lock.is_file():
        return result
    result.found = True
    record = _read_record(lock, result)
    _check_not_running(record, result)

    git_lock = _git_index_lock(vault)
    if git_lock.exists():
        raise RecoverError(
            f"git's own lock {git_lock} exists, so git was also interrupted. "
            "If no git command is running, delete that file, then run recover again"
        )

    has_head = _git(vault.root, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
    paths = [p for p in record.get("paths", []) if _safe(p)]
    actions: list[tuple[str, str, bytes | None]] = []  # (kind, path, data)
    for path in paths:
        full = vault.root / path
        head_data = _head_bytes(vault, path) if has_head else None
        on_disk = full.read_bytes() if full.is_file() else None
        if head_data is not None:
            if on_disk == head_data and not _staged(vault, path, has_head):
                result.unchanged.append(path)
            else:
                actions.append(("restore", path, head_data))
                result.restored.append(path)
        elif on_disk is None:
            if _staged(vault, path, has_head):
                actions.append(("unstage", path, None))
                result.restored.append(path)
            else:
                result.unchanged.append(path)
        elif _is_complete_raw_copy(path, on_disk):
            actions.append(("keep", path, None))
            result.kept.append(path)
        else:
            actions.append(("delete", path, None))
            result.deleted.append(path)

    if dry_run:
        return result

    touched = [path for kind, path, _ in actions]
    if touched:
        if has_head:
            _git(vault.root, "reset", "--quiet", "--", *touched, check=False)
        else:
            _git(vault.root, "rm", "-r", "--cached", "--quiet", "--ignore-unmatch", "--", *touched, check=False)
    for kind, path, data in actions:
        full = vault.root / path
        if kind == "restore":
            full.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(full, data)
        elif kind == "delete":
            full.unlink(missing_ok=True)
    lock.unlink()
    return result


def _read_record(lock: Path, result: RecoverResult) -> dict:
    text = lock.read_text(encoding="utf-8", errors="replace")
    try:
        record = json.loads(text)
        if not isinstance(record, dict):
            raise ValueError
    except ValueError:
        record = {}
        result.notes.append(
            "the lock has no record of which files were being written (older akashactl); "
            "only the lock is cleared. Check `git status` for leftover changes"
        )
    result.operation = str(record.get("operation") or "unknown")
    result.started = str(record.get("started") or "")
    pid = record.get("pid")
    result.pid = pid if isinstance(pid, int) else None
    return record


def _check_not_running(record: dict, result: RecoverResult) -> None:
    host = record.get("host")
    if host and host != socket.gethostname():
        raise RecoverError(
            f"the lock was taken on another computer ({host}); run recover there, "
            f"or delete {LOCK} yourself if you're sure nothing is writing"
        )
    if result.pid is not None and _alive(result.pid):
        raise RecoverError(
            f"the {result.operation} that holds the lock is still running (pid {result.pid}); wait for it to finish"
        )


def _alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe(path: object) -> bool:
    if not isinstance(path, str) or not path:
        return False
    p = PurePosixPath(path)
    return not p.is_absolute() and ".." not in p.parts and p.parts[0] in ("wiki", ".raw")


def _is_complete_raw_copy(path: str, data: bytes) -> bool:
    p = PurePosixPath(path)
    if p.parts[0] != ".raw" or path in RAW_BOOKKEEPING or len(p.parts) != 2:
        return False
    stem = p.name.split(".", 1)[0]
    return hashlib.sha256(data).hexdigest() == stem


def _head_bytes(vault: Vault, path: str) -> bytes | None:
    result = subprocess.run(["git", "-C", str(vault.root), "show", f"HEAD:{path}"], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def _staged(vault: Vault, path: str, has_head: bool) -> bool:
    if has_head:
        return _git(vault.root, "diff", "--cached", "--quiet", "HEAD", "--", path, check=False).returncode != 0
    return bool(_git(vault.root, "ls-files", "--cached", "--", path, check=False).stdout.strip())


def _git_index_lock(vault: Vault) -> Path:
    rel = _git(vault.root, "rev-parse", "--git-path", "index.lock").stdout.strip()
    return vault.root / rel
