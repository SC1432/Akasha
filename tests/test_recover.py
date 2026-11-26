"""Crash tests: a child process runs a real akashactl operation and dies (os._exit) mid-write."""

import hashlib
import json
import socket
import subprocess
import sys
import textwrap

import pytest

from conftest import ROOT, git, snapshot
from lib import recover as rec
from lib import vault as vault_mod

WRAPPER = ROOT / "bin" / "akashactl"

PAGE = (
    "---\ntype: concept\ntitle: Active recall\nstatus: seed\ncreated: 2026-11-25\nupdated: 2026-11-25\n"
    "tags: []\ngenerated: true\nsources: []\n---\nBody\n"
)


def crash(vault, operation, when):
    """Run capture/apply/undo in a child process that dies at `when`: 'before-commit' or 'after-add'."""
    plan = {"operation": "ingest", "log": "Crash test", "pages": [
        {"action": "create", "path": "wiki/concepts/active-recall.md", "content": PAGE},
        {"action": "update", "path": "wiki/concepts/spaced-repetition.md",
         "base_hash": hashlib.sha256((vault / "wiki/concepts/spaced-repetition.md").read_bytes()).hexdigest(),
         "content": PAGE.replace("Active recall", "Spaced repetition")},
    ]}
    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT / "scripts")!r})
        from lib import apply, capture, gitops, plan, schema, undo, vault
        def die(root, paths, *a, **k):
            if {when!r} == "after-add":
                gitops._git(root, "add", "--", *paths)
            os._exit(9)
        for mod in (apply, capture, undo):
            mod.gitops.commit_paths = die
        v = vault.open_vault({str(vault)!r})
        op = {operation!r}
        if op == "capture":
            capture.capture(v)
        elif op == "apply":
            s = schema.load()
            apply.apply_plan(plan.validate_plan({plan!r}, v, s), v, s)
        elif op == "undo":
            undo.undo(v)
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 9, result.stderr
    assert (vault / ".akasha/lock").is_file()


def run(*args, cwd=None):
    return subprocess.run([str(WRAPPER), *args], cwd=cwd, capture_output=True, text=True)


def clean_state(vault):
    return {k: v for k, v in snapshot(vault).items() if not k.startswith(".akasha/")}


@pytest.mark.parametrize("when", ["before-commit", "after-add"])
def test_recover_interrupted_apply(fixture_vault, when):
    before = clean_state(fixture_vault)
    crash(fixture_vault, "apply", when)
    assert (fixture_vault / "wiki/concepts/active-recall.md").exists()
    assert run("capture", cwd=fixture_vault).returncode == 2  # blocked by the stale lock
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert result.operation == "ingest"
    assert result.deleted == ["wiki/concepts/active-recall.md"]
    assert sorted(result.restored) == ["wiki/concepts/spaced-repetition.md", "wiki/index.md", "wiki/log.md"]
    assert clean_state(fixture_vault) == before
    assert git(fixture_vault, "status", "--porcelain") == ""
    assert not (fixture_vault / ".akasha/lock").exists()


@pytest.mark.parametrize("when", ["before-commit", "after-add"])
def test_recover_interrupted_capture_keeps_complete_raw_copies(fixture_vault, when):
    crash(fixture_vault, "capture", when)
    raw_files = sorted(p for p in (fixture_vault / ".raw").iterdir() if p.name != "manifest.json")
    assert len(raw_files) == 6
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert sorted(result.kept) == sorted(f".raw/{p.name}" for p in raw_files)
    assert result.deleted == [".raw/manifest.json"]
    assert not (fixture_vault / ".raw/manifest.json").exists()
    assert git(fixture_vault, "diff", "--cached", "--name-only") == ""
    second = run("capture", cwd=fixture_vault)
    assert second.returncode == 0, second.stderr
    assert "6 new, 1 duplicate" in second.stdout
    assert git(fixture_vault, "status", "--porcelain") == ""


def test_recover_interrupted_undo(fixture_vault):
    first = run("capture", cwd=fixture_vault)
    assert first.returncode == 0
    before = clean_state(fixture_vault)
    crash(fixture_vault, "undo", "before-commit")
    assert not (fixture_vault / ".raw/manifest.json").exists()
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert result.operation == "undo" and ".raw/manifest.json" in result.restored
    assert clean_state(fixture_vault) == before


def test_partial_raw_copy_deleted(fixture_vault):
    data = b"full content of a source"
    name = hashlib.sha256(data).hexdigest() + ".txt"
    (fixture_vault / ".raw").mkdir()
    (fixture_vault / ".raw" / name).write_bytes(data[:5])  # truncated by the crash
    (fixture_vault / ".akasha").mkdir()
    (fixture_vault / ".akasha/lock").write_text(json.dumps(
        {"operation": "capture", "pid": 999999, "host": socket.gethostname(), "paths": [f".raw/{name}"]}))
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert result.deleted == [f".raw/{name}"] and not (fixture_vault / ".raw" / name).exists()


def test_only_recorded_paths_touched(fixture_vault):
    crash(fixture_vault, "apply", "before-commit")
    (fixture_vault / "personal/journal.md").write_text("my unsaved edit\n")
    (fixture_vault / "wiki/concepts/mine.md").write_text("my own page\n")
    rec.recover(vault_mod.open_vault(fixture_vault))
    assert (fixture_vault / "personal/journal.md").read_text() == "my unsaved edit\n"
    assert (fixture_vault / "wiki/concepts/mine.md").read_text() == "my own page\n"


def test_dry_run_changes_nothing(fixture_vault):
    crash(fixture_vault, "apply", "after-add")
    before = snapshot(fixture_vault)
    staged = git(fixture_vault, "diff", "--cached", "--name-only")
    result = rec.recover(vault_mod.open_vault(fixture_vault), dry_run=True)
    assert result.deleted and result.restored
    assert snapshot(fixture_vault) == before
    assert git(fixture_vault, "diff", "--cached", "--name-only") == staged


def test_nothing_to_recover(fixture_vault):
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert not result.found
    out = run("recover", cwd=fixture_vault)
    assert out.returncode == 0 and "nothing to recover" in out.stdout


def test_lock_from_finished_write_just_cleared(fixture_vault):
    assert run("capture", cwd=fixture_vault).returncode == 0
    head = git(fixture_vault, "rev-parse", "HEAD")
    (fixture_vault / ".akasha").mkdir(exist_ok=True)
    paths = [".raw/manifest.json", "wiki/index.md"]
    (fixture_vault / ".akasha/lock").write_text(json.dumps(
        {"operation": "capture", "pid": 999999, "host": socket.gethostname(), "paths": paths}))
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert result.unchanged == sorted(paths) and not result.restored and not result.deleted
    assert git(fixture_vault, "rev-parse", "HEAD") == head
    assert not (fixture_vault / ".akasha/lock").exists()


def test_refuses_while_writer_still_running(fixture_vault):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (fixture_vault / ".akasha").mkdir()
        (fixture_vault / ".akasha/lock").write_text(json.dumps(
            {"operation": "ingest", "pid": sleeper.pid, "host": socket.gethostname(), "paths": []}))
        with pytest.raises(rec.RecoverError, match="still running"):
            rec.recover(vault_mod.open_vault(fixture_vault))
        assert (fixture_vault / ".akasha/lock").exists()
    finally:
        sleeper.kill()
        sleeper.wait()


def test_refuses_lock_from_another_computer(fixture_vault):
    (fixture_vault / ".akasha").mkdir()
    (fixture_vault / ".akasha/lock").write_text(json.dumps(
        {"operation": "ingest", "pid": 1, "host": "some-other-mac", "paths": []}))
    out = run("recover", cwd=fixture_vault)
    assert out.returncode == 1 and "another computer (some-other-mac)" in out.stderr


def test_refuses_when_git_index_lock_present(fixture_vault):
    crash(fixture_vault, "apply", "before-commit")
    (fixture_vault / ".git/index.lock").write_text("")
    with pytest.raises(rec.RecoverError, match="index.lock"):
        rec.recover(vault_mod.open_vault(fixture_vault))
    assert (fixture_vault / ".akasha/lock").exists()


def test_old_format_lock_only_cleared(fixture_vault):
    (fixture_vault / ".akasha").mkdir()
    (fixture_vault / ".akasha/lock").write_text("999999\n")
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert result.operation == "unknown" and any("no record" in n for n in result.notes)
    assert not (fixture_vault / ".akasha/lock").exists()


def test_unsafe_paths_in_lock_ignored(fixture_vault):
    (fixture_vault / ".akasha").mkdir()
    (fixture_vault / ".akasha/lock").write_text(json.dumps({
        "operation": "x", "pid": 999999, "host": socket.gethostname(),
        "paths": ["personal/journal.md", "../outside.md", "/etc/hosts", "akasha.json", "inbox/x"],
    }))
    before = clean_state(fixture_vault)
    result = rec.recover(vault_mod.open_vault(fixture_vault))
    assert not (result.restored or result.deleted or result.kept)
    assert clean_state(fixture_vault) == before


def test_lock_records_operation_and_paths(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    with vault_mod.write_lock(v, "ingest", ["wiki/b.md", "wiki/a.md", "wiki/a.md"]):
        record = json.loads((fixture_vault / ".akasha/lock").read_text())
    assert record["operation"] == "ingest" and record["paths"] == ["wiki/a.md", "wiki/b.md"]
    assert record["host"] == socket.gethostname() and isinstance(record["pid"], int)


def test_cli_recover_after_crash(fixture_vault):
    crash(fixture_vault, "apply", "before-commit")
    dry = run("recover", "--dry-run", cwd=fixture_vault)
    assert dry.returncode == 0 and "would recover interrupted ingest" in dry.stdout
    assert "delete wiki/concepts/active-recall.md" in dry.stdout and "would clear .akasha/lock" in dry.stdout
    real = run("recover", cwd=fixture_vault)
    assert real.returncode == 0 and "cleared .akasha/lock" in real.stdout
    assert run("capture", cwd=fixture_vault).returncode == 0


def test_stale_lock_error_points_to_recover(fixture_vault):
    (fixture_vault / ".akasha").mkdir()
    (fixture_vault / ".akasha/lock").write_text("{}")
    out = run("capture", cwd=fixture_vault)
    assert out.returncode == 2 and "akashactl recover --dry-run" in out.stderr
