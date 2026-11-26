import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
WRAPPER = ROOT / "bin" / "akashactl"


def run(*args, cwd=None):
    return subprocess.run([str(WRAPPER), *args], cwd=cwd, capture_output=True, text=True)


def test_manifest_fields():
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "akasha"
    assert data["description"] and len(data["description"]) <= 200


def test_manifest_version_matches_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert json.loads(MANIFEST.read_text())["version"] == pyproject["project"]["version"]


def test_only_manifest_inside_claude_plugin_dir():
    assert sorted(p.name for p in MANIFEST.parent.iterdir()) == ["plugin.json"]


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_claude_plugin_validate():
    # Not --strict: the one expected warning is that the repo's CLAUDE.md is not plugin context,
    # which is intended (it is for developing this repo). Any other warning fails the test.
    result = subprocess.run(["claude", "plugin", "validate", str(ROOT)], capture_output=True, text=True, timeout=120)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "Found 1 warning" in out and "CLAUDE.md at the plugin root is not loaded" in out, out


def test_wrapper_is_executable_and_reports_version():
    assert os.access(WRAPPER, os.X_OK)
    result = run("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"akashactl {json.loads(MANIFEST.read_text())['version']}"


def test_wrapper_ignores_shadowing_modules_in_cwd(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "__init__.py").write_text("raise SystemExit('planted module ran')")
    (tmp_path / "json.py").write_text("raise SystemExit('planted module ran')")
    result = run("--version", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "planted" not in result.stderr


GOOD = """---
type: concept
title: Spaced repetition
status: seed
created: 2026-11-25
updated: 2026-11-25
tags: [learning]
generated: true
sources:
  - "[[video]]"
---
Body
"""


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    (tmp_path / "personal").mkdir()
    (tmp_path / "wiki" / "concepts" / "spaced-repetition.md").write_text(GOOD)
    (tmp_path / "wiki" / "index.md").write_text("# Index\n")
    (tmp_path / "personal" / "diary.md").write_text("---\nmood: [[nested]]\n---\n")
    return tmp_path


def test_validate_clean_vault(vault):
    result = run("validate", "--vault", str(vault))
    assert result.returncode == 0, result.stdout
    assert "1 checked, 0 with problems, 1 skipped" in result.stdout


def test_validate_reports_bad_generated_page(vault):
    (vault / "wiki" / "concepts" / "bad.md").write_text(GOOD.replace("status: seed", "status: done"))
    result = run("validate", "--vault", str(vault))
    assert result.returncode == 1
    assert "wiki/concepts/bad.md: status 'done' not allowed" in result.stdout


def test_validate_reports_unparseable_frontmatter(vault):
    (vault / "wiki" / "concepts" / "weird.md").write_text("---\nparent:\n  child: 1\n---\n")
    result = run("validate", "--vault", str(vault))
    assert result.returncode == 1
    assert "wiki/concepts/weird.md: frontmatter: line 3" in result.stdout


def test_validate_explicit_path_outside_vault(vault, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.md"
    outside.write_text(GOOD)
    result = run("validate", "--vault", str(vault), str(outside))
    assert result.returncode == 1
    assert "outside the vault" in result.stdout


def test_validate_relative_paths_from_cwd(vault):
    result = run("validate", "wiki/concepts/spaced-repetition.md", cwd=vault)
    assert result.returncode == 0, result.stdout


def test_validate_never_writes(vault):
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    run("validate", "--vault", str(vault))
    after = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    assert before == after


def test_validate_missing_vault(tmp_path):
    result = run("validate", "--vault", str(tmp_path / "nope"))
    assert result.returncode == 2


def test_old_python_gets_clear_message():
    code = "import sys; sys.version_info = (3, 9, 0); sys.argv = ['akashactl']; exec(open(sys.argv_path).read())"
    script = ROOT / "scripts" / "akashactl.py"
    result = subprocess.run(
        [sys.executable, "-c", code.replace("sys.argv_path", repr(str(script)))], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "needs Python 3.11 or newer" in result.stderr
