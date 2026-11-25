"""Locate and check an Akasha vault: akasha.json plus a git repository."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import gitops

__all__ = ["VaultError", "Vault", "open_vault", "write_atomic"]

CONFIG = "akasha.json"


class VaultError(Exception):
    """The folder is not a usable Akasha vault."""


@dataclass(frozen=True)
class Vault:
    root: Path
    config: dict

    @property
    def personal(self) -> list[str]:
        return list(self.config.get("personal", []))

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
