"""Git helpers. Every Akasha write is one commit carrying an Akasha-Operation trailer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

__all__ = ["GitError", "is_repo_root", "commit_paths", "OPERATION_TRAILER"]

OPERATION_TRAILER = "Akasha-Operation"
AUTHOR = ("Akasha", "akasha@localhost")


class GitError(Exception):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": AUTHOR[0],
        "GIT_AUTHOR_EMAIL": AUTHOR[1],
        "GIT_COMMITTER_NAME": AUTHOR[0],
        "GIT_COMMITTER_EMAIL": AUTHOR[1],
    }
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def is_repo_root(root: Path) -> bool:
    result = _git(root, "rev-parse", "--show-toplevel", check=False)
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve()


def commit_paths(root: Path, paths: list[str], subject: str, operation: str, body: str = "") -> str | None:
    """Stage and commit exactly these paths (other staged changes are left alone).

    Returns the commit hash, or None when the paths already match HEAD (e.g. a restored file).
    """
    if not paths:
        raise GitError("nothing to commit")
    _git(root, "add", "--", *paths)
    if _git(root, "diff", "--cached", "--quiet", "HEAD", "--", *paths, check=False).returncode == 0:
        return None
    message = subject + ("\n\n" + body.rstrip() if body else "") + f"\n\n{OPERATION_TRAILER}: {operation}\n"
    _git(root, "commit", "--quiet", "--no-verify", "-m", message, "--only", "--", *paths)
    return _git(root, "rev-parse", "HEAD").stdout.strip()
