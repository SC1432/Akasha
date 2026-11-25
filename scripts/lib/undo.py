"""Undo the most recent Akasha operation that hasn't been undone, as a new commit.

Each file the operation touched is restored to its state in the commit's parent (or deleted
if the operation created it). If any of those files changed since the operation, in a later
commit, in the index or in the working tree, undo refuses rather than discard those edits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import gitops
from .gitops import OPERATION_TRAILER, GitError, _git
from .vault import Vault, write_atomic, write_lock

__all__ = ["UndoError", "UndoResult", "undo", "REVERTS_TRAILER"]

REVERTS_TRAILER = "Akasha-Reverts"


class UndoError(Exception):
    pass


@dataclass
class UndoResult:
    target: str = ""  # commit being undone
    subject: str = ""
    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    commit: str | None = None


def undo(vault: Vault, dry_run: bool = False) -> UndoResult:
    target, subject = _find_target(vault)
    result = UndoResult(target=target, subject=subject)
    parent = _parent(vault, target)
    paths = _git(vault.root, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "-z", target).stdout
    paths = [p for p in paths.split("\0") if p]

    changed_since = []
    for path in paths:
        at_target = _blob(vault, f"{target}:{path}")
        if _blob(vault, f"HEAD:{path}") != at_target or _blob(vault, f":{path}") != at_target:
            changed_since.append(path)
            continue
        on_disk = vault.root / path
        disk_blob = _git(vault.root, "hash-object", "--", path).stdout.strip() if on_disk.is_file() else None
        if disk_blob != at_target:
            changed_since.append(path)
    if changed_since:
        raise UndoError(
            f"cannot undo {target[:12]} ({subject}): these files changed since, and undo would discard that: "
            + ", ".join(changed_since)
        )

    for path in paths:
        (result.restored if parent and _blob(vault, f"{parent}:{path}") else result.deleted).append(path)
    if dry_run:
        return result

    with write_lock(vault):
        for path in result.restored:
            data = _git_bytes(vault, "show", f"{parent}:{path}")
            dest = vault.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(dest, data)
        for path in result.deleted:
            (vault.root / path).unlink(missing_ok=True)
        result.commit = gitops.commit_paths(
            vault.root, paths, f"akasha: undo: {subject.removeprefix('akasha: ')}", "undo", f"{REVERTS_TRAILER}: {target}"
        )
    return result


def _find_target(vault: Vault) -> tuple[str, str]:
    """Newest Akasha commit that is neither an undo nor already undone."""
    try:
        log = _git(vault.root, "log", "--format=%H%x00%s%x00%B%x1e", "HEAD").stdout
    except GitError as e:
        raise UndoError("nothing to undo: the vault has no commits") from e
    undone = set()
    for record in log.split("\x1e"):
        if not record.strip():
            continue
        sha, subject, body = record.strip("\n").split("\x00", 2)
        trailers = _trailers(body)
        operation = trailers.get(OPERATION_TRAILER)
        if operation is None:
            continue
        if operation == "setup" and sha not in undone:
            raise UndoError(
                "nothing to undo: the last Akasha operation is setup, which undo does not reverse "
                "(it could delete files that existed before). To stop using Akasha here, delete akasha.json."
            )
        if operation == "undo":
            if REVERTS_TRAILER in trailers:
                undone.add(trailers[REVERTS_TRAILER])
            continue
        if sha not in undone:
            return sha, subject
    raise UndoError("nothing to undo: no Akasha operations left in history")


def _trailers(body: str) -> dict[str, str]:
    found = {}
    for line in body.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key in (OPERATION_TRAILER, REVERTS_TRAILER):
            found[key] = value.strip()
    return found


def _parent(vault: Vault, sha: str) -> str | None:
    result = _git(vault.root, "rev-parse", "--verify", "--quiet", f"{sha}^", check=False)
    return result.stdout.strip() or None


def _blob(vault: Vault, spec: str) -> str | None:
    result = _git(vault.root, "rev-parse", "--verify", "--quiet", spec, check=False)
    return result.stdout.strip() or None


def _git_bytes(vault: Vault, *args: str) -> bytes:
    import subprocess

    return subprocess.run(["git", "-C", str(vault.root), *args], capture_output=True, check=True).stdout
