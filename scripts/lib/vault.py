"""Locate and check an Akasha vault: akasha.json plus a git repository."""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import gitops

__all__ = ["VaultError", "Vault", "open_vault", "write_atomic", "write_lock", "LOCK"]

CONFIG = "akasha.json"
LOCK = ".akasha/lock"


class VaultError(Exception):
    """The folder is not a usable Akasha vault."""


@dataclass(frozen=True)
class Vault:
    root: Path
    config: dict

    @property
    def personal(self) -> list[str]:
        return list(self.config.get("personal", []))

    @property
    def raw_git_max_bytes(self) -> int | None:
        """Raw files larger than this are kept out of git (None: no limit)."""
        limit = self.config.get("raw_git_max_mb")
        return None if limit is None else int(limit * 1024 * 1024)

    def path(self, rel: str) -> Path:
        return self.root / rel


def open_vault(root: Path | str) -> Vault:
    root = Path(root).resolve()
    if not root.is_dir():
        raise VaultError(f"{root} is not a directory")
    config_path = root / CONFIG
    if not config_path.is_file():
        raise VaultError(f"{root} has no {CONFIG}; run /akasha:setup first")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise VaultError(f"{config_path}: {e}") from e
    if not isinstance(config, dict) or config.get("version") != 1:
        raise VaultError(f"{config_path}: expected an object with \"version\": 1")
    personal = config.get("personal", [])
    if not isinstance(personal, list) or not all(isinstance(p, str) and p for p in personal):
        raise VaultError(f"{config_path}: \"personal\" must be a list of folder names")
    limit = config.get("raw_git_max_mb")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit <= 0):
        raise VaultError(f"{config_path}: \"raw_git_max_mb\" must be a positive number or null")
    dotgit = root / ".git"
    if dotgit.is_file():
        pointer = dotgit.read_text(encoding="utf-8", errors="replace").strip()
        target = pointer.removeprefix("gitdir:").strip()
        if pointer.startswith("gitdir:") and not (root / target).exists():
            raise VaultError(
                f"this vault's git history is kept at {target}, which doesn't exist on this computer; "
                "Akasha can only write to the vault on the computer that holds its history"
            )
    if not gitops.is_repo_root(root):
        raise VaultError(f"{root} is not the root of a git repository; run /akasha:setup first")
    return Vault(root=root, config=config)


def write_atomic(path: Path, data: bytes) -> None:
    """Replace path with data so readers never see a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def write_lock(vault: Vault, operation: str = "", paths: list[str] | tuple[str, ...] = ()):
    """Hold .akasha/lock for the duration of a write so two akashactl writes never interleave.

    The lock records which files the write is about to touch, so `akashactl recover` can put
    exactly those back if the process dies before committing.
    """
    lock = vault.root / LOCK
    if lock.parent.is_symlink():
        raise VaultError(".akasha is a symlink; refusing to use it")
    lock.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise VaultError(
            f"{LOCK} exists: another akashactl write is running, or one was interrupted. "
            "Run `akashactl recover --dry-run` to see what it was doing and clean up."
        ) from None
    record = {
        "operation": operation,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "paths": sorted(set(paths)),
    }
    with os.fdopen(fd, "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
