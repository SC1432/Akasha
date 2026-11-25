import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_VAULT = ROOT / "tests" / "fixtures" / "vault"

sys.path.insert(0, str(ROOT / "scripts"))


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def snapshot(root, sub=""):
    """Map of relative path -> bytes for every file under root/sub, ignoring .git."""
    base = Path(root) / sub
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in base.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


@pytest.fixture
def fixture_vault(tmp_path):
    """A fresh copy of tests/fixtures/vault as a git repo with one commit, plus a .DS_Store in the inbox."""
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vault)
    (vault / "inbox" / ".DS_Store").write_bytes(b"junk")
    git(vault, "init", "--quiet", "--initial-branch=main")
    git(vault, "-c", "user.name=Me", "-c", "user.email=me@example.com", "add", "-A")
    git(vault, "-c", "user.name=Me", "-c", "user.email=me@example.com", "commit", "--quiet", "-m", "initial")
    return vault
