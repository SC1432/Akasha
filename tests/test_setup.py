import json
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, git, snapshot
from lib import apply as apply_mod
from lib import capture as cap
from lib import frontmatter, schema
from lib import plan as plan_mod
from lib import setup_vault as sv
from lib import undo as undo_mod
from lib import vault as vault_mod

WRAPPER = ROOT / "bin" / "akashactl"
SETUP_FILES = [".gitignore", "akasha.json", "inbox/.gitkeep", "wiki/index.md", "wiki/log.md"]


def run(*args, cwd=None):
    return subprocess.run([str(WRAPPER), *args], cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def obsidian_vault(tmp_path):
    """An existing Obsidian vault that is not yet a git repo."""
    v = tmp_path / "Vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Courses" / "COMP4800").mkdir(parents=True)
    (v / "Courses" / "COMP4800" / "week1.md").write_text("# Week 1\n")
    (v / "Research").mkdir()
    (v / "Research" / "honours.md").write_text("# Honours\n")
    (v / "Daily.md").write_text("# Today\n")
    return v


def refused(*args, **kwargs):
    with pytest.raises(sv.InitError) as exc:
        sv.plan_init(*args, **kwargs)
    return "\n".join(exc.value.errors)


def committed_files(v):
    return sorted(git(v, "show", "--name-only", "--format=", "HEAD").split())


# --- preview -------------------------------------------------------------------


def test_dry_run_plan_writes_nothing(obsidian_vault):
    before = snapshot(obsidian_vault)
    plan = sv.plan_init(obsidian_vault)
    assert snapshot(obsidian_vault) == before
    assert not (obsidian_vault / ".git").exists()
    text = "\n".join(plan.describe())
    assert "Obsidian vault, not a git repository" in text
    assert "Courses/  1 note\n" in text + "\n" and "Research/  1 note" in text and "(top level)  1 note" in text
    assert "git init" in text and "create folder personal/" in text
    assert "existing notes will not be committed" in text


def test_cli_dry_run(obsidian_vault):
    result = run("init", "--dry-run", "--personal", "Courses", cwd=obsidian_vault)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("dry run, nothing written.")
    assert '"personal": ["Courses"]' in result.stdout
    assert not (obsidian_vault / "akasha.json").exists()


# --- adopting and creating -----------------------------------------------------


def test_adopt_obsidian_vault(obsidian_vault):
    notes_before = snapshot(obsidian_vault)
    commit = sv.run_init(sv.plan_init(obsidian_vault, ["Courses", "Research/"]))
    v = vault_mod.open_vault(obsidian_vault)
    assert v.personal == ["Courses", "Research"]
    assert v.raw_git_max_bytes == sv.DEFAULT_RAW_GIT_MAX_MB * 1024 * 1024 == 5 * 1024 * 1024
    assert committed_files(obsidian_vault) == SETUP_FILES
    assert commit == git(obsidian_vault, "rev-parse", "HEAD").strip()
    assert "Akasha-Operation: setup" in git(obsidian_vault, "log", "-1", "--format=%B")
    for rel, data in notes_before.items():
        assert (obsidian_vault / rel).read_bytes() == data
    untracked = git(obsidian_vault, "status", "--porcelain").split("\n")
    assert "?? Courses/" in untracked and "?? Daily.md" in untracked
    assert not (obsidian_vault / "personal").exists()


def test_new_vault_folder(tmp_path):
    target = tmp_path / "brand" / "new"
    sv.run_init(sv.plan_init(target))
    v = vault_mod.open_vault(target)
    assert v.personal == ["personal"] and (target / "personal").is_dir()
    assert (target / "wiki/index.md").read_text() == apply_mod.render_index(v, schema.load())
    assert (target / "wiki/log.md").read_text() == "# Log\n"
    assert git(target, "status", "--porcelain") == ""


def test_no_personal_and_no_size_limit(tmp_path):
    sv.run_init(sv.plan_init(tmp_path / "v", [], None))
    v = vault_mod.open_vault(tmp_path / "v")
    assert v.personal == [] and v.raw_git_max_bytes is None
    assert not (tmp_path / "v" / "personal").exists()


def test_adopt_existing_repo_keeps_staged_changes_and_gitignore(obsidian_vault):
    git(obsidian_vault, "init", "--quiet")
    (obsidian_vault / ".gitignore").write_text(".DS_Store\n.akasha/")  # no trailing newline, one line present
    git(obsidian_vault, "add", ".gitignore", "Daily.md")
    git(obsidian_vault, "-c", "user.name=Me", "-c", "user.email=me@example.com", "commit", "--quiet", "-m", "mine")
    (obsidian_vault / "Research" / "honours.md").write_text("# Honours, edited\n")
    git(obsidian_vault, "add", "Research/honours.md")
    plan = sv.plan_init(obsidian_vault, ["Research"])
    assert plan.is_repo and plan.gitignore_add == ["inbox/*", "!inbox/.gitkeep"]
    sv.run_init(plan)
    assert (obsidian_vault / ".gitignore").read_text() == (
        ".DS_Store\n.akasha/\n\n# Akasha (managed by akashactl)\ninbox/*\n!inbox/.gitkeep\n"
    )
    assert "Research/honours.md" not in committed_files(obsidian_vault)
    assert git(obsidian_vault, "diff", "--cached", "--name-only").split() == ["Research/honours.md"]


def test_inbox_contents_ignored_by_git(tmp_path):
    sv.run_init(sv.plan_init(tmp_path / "v"))
    (tmp_path / "v" / "inbox" / "drop.txt").write_text("x")
    assert git(tmp_path / "v", "status", "--porcelain") == ""


def test_warnings_for_existing_inbox_and_wiki(obsidian_vault):
    (obsidian_vault / "inbox").mkdir()
    (obsidian_vault / "inbox" / "saved.txt").write_text("x")
    (obsidian_vault / "wiki").mkdir()
    (obsidian_vault / "wiki" / "mine.md").write_text("# Mine\n")
    warnings = "\n".join(sv.plan_init(obsidian_vault).warnings)
    assert "inbox/ already has 1 files" in warnings and "wiki/ already has 1 notes" in warnings


def test_existing_inbox_gitkeep_not_recreated(tmp_path):
    (tmp_path / "v" / "inbox").mkdir(parents=True)
    (tmp_path / "v" / "inbox" / ".gitkeep").write_text("")
    plan = sv.plan_init(tmp_path / "v")
    assert "inbox/.gitkeep" not in plan.create_files
    sv.run_init(plan)
    assert vault_mod.open_vault(tmp_path / "v")


# --- refusals ------------------------------------------------------------------


def test_refuses_home_and_its_ancestors():
    assert "home folder" in refused(Path.home())
    assert "home folder" in refused(Path.home().parent)
    assert "home folder" in refused("/")


def test_refuses_file(tmp_path):
    (tmp_path / "f").write_text("x")
    assert "not a folder" in refused(tmp_path / "f")


def test_refuses_already_set_up(fixture_vault):
    assert "already an Akasha vault" in refused(fixture_vault)


def test_refuses_inside_another_repo(fixture_vault):
    assert "inside the git repository" in refused(fixture_vault / "wiki" / "sub")
    (fixture_vault / "notes").mkdir()
    assert "inside the git repository" in refused(fixture_vault / "notes")


@pytest.mark.parametrize("page", ["wiki/index.md", "wiki/log.md", "wiki/hot.md", "wiki/now.md"])
def test_refuses_to_overwrite_reserved_pages(obsidian_vault, page):
    (obsidian_vault / page).parent.mkdir(exist_ok=True)
    (obsidian_vault / page).write_text("mine\n")
    assert "Rename yours first" in refused(obsidian_vault)


def test_refuses_non_empty_raw(obsidian_vault):
    (obsidian_vault / ".raw").mkdir()
    (obsidian_vault / ".raw" / "x").write_text("x")
    assert ".raw/ already exists" in refused(obsidian_vault)


def test_refuses_symlinked_managed_folder(obsidian_vault, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (obsidian_vault / "wiki").symlink_to(tmp_path / "elsewhere")
    assert "wiki exists but is not a plain folder" in refused(obsidian_vault)


@pytest.mark.parametrize(
    "folder, message",
    [
        ("Nope", "does not exist"),
        ("", "plain relative folder"),
        ("/etc", "plain relative folder"),
        ("../outside", "plain relative folder"),
        ("Courses\\COMP4800", "plain relative folder"),
        ("Courses/", None),
        (".obsidian", "must not be hidden"),
        ("wiki", "overlaps wiki/"),
        ("inbox/x", "overlaps inbox/"),
    ],
)
def test_refuses_bad_personal_folders(obsidian_vault, folder, message):
    if message is None:  # a trailing slash is fine
        assert sv.plan_init(obsidian_vault, [folder]).config["personal"] == ["Courses"]
        return
    assert message in refused(obsidian_vault, [folder])


def test_all_refusal_reasons_reported_together(obsidian_vault):
    (obsidian_vault / "wiki").mkdir()
    (obsidian_vault / "wiki" / "index.md").write_text("x")
    errors = refused(obsidian_vault, ["Nope"], -1)
    assert "does not exist" in errors and "raw_git_max_mb" in errors and "index.md" in errors


def test_cli_refusal(obsidian_vault):
    result = run("init", "--personal", "Nope", cwd=obsidian_vault)
    assert result.returncode == 1 and "setup refused, nothing written" in result.stderr
    assert not (obsidian_vault / ".git").exists()


def test_cli_init_then_open(obsidian_vault):
    result = run("init", "--personal", "Courses", "--raw-git-max-mb", "0", cwd=obsidian_vault)
    assert result.returncode == 0, result.stderr
    assert "done; commit " in result.stdout
    assert vault_mod.open_vault(obsidian_vault).raw_git_max_bytes is None


# --- undo stops at setup -------------------------------------------------------


def test_undo_stops_at_setup(obsidian_vault):
    sv.run_init(sv.plan_init(obsidian_vault, ["Courses"]))
    v = vault_mod.open_vault(obsidian_vault)
    with pytest.raises(undo_mod.UndoError, match="setup"):
        undo_mod.undo(v)
    content = frontmatter.render(
        {"type": "concept", "title": "X", "status": "seed", "created": "2026-11-25", "updated": "2026-11-25",
         "tags": [], "generated": True, "sources": []},
        "Body\n",
    )
    s = schema.load()
    plan = plan_mod.validate_plan(
        {"operation": "ingest", "log": "x", "pages": [{"action": "create", "path": "wiki/concepts/x.md",
                                                       "content": content}]}, v, s)
    apply_mod.apply_plan(plan, v, s)
    undo_mod.undo(v)
    assert not (obsidian_vault / "wiki/concepts/x.md").exists()
    with pytest.raises(undo_mod.UndoError, match="setup"):
        undo_mod.undo(v)
    assert (obsidian_vault / "akasha.json").exists()


# --- capture size limit --------------------------------------------------------


def set_limit(vault, mb):
    cfg = json.loads((vault / "akasha.json").read_text())
    cfg["raw_git_max_mb"] = mb
    (vault / "akasha.json").write_text(json.dumps(cfg))
    git(vault, "-c", "user.name=Me", "-c", "user.email=me@example.com", "commit", "--quiet", "-am", "limit")


def test_large_raw_files_kept_out_of_git(fixture_vault):
    set_limit(fixture_vault, 0.0001)  # ~104 bytes: the article (>104 B) is large, the links are small
    (fixture_vault / "inbox" / "big.bin").write_bytes(b"x" * 5000)
    result = cap.capture(vault_mod.open_vault(fixture_vault))
    entries = {e["name"]: e for e in result.new}
    big = entries["big.bin"]
    assert big["in_git"] is False and (fixture_vault / big["file"]).is_file()
    assert "in_git" not in entries["video-link.txt"]
    ignore = (fixture_vault / ".raw/.gitignore").read_text().splitlines()
    assert "/" + Path(big["file"]).name in ignore
    changed = committed_files(fixture_vault)
    assert big["file"] not in changed and entries["video-link.txt"]["file"] in changed
    assert ".raw/.gitignore" in changed and ".raw/manifest.json" in changed
    assert git(fixture_vault, "status", "--porcelain", "--", ".raw") == ""


def test_large_file_duplicate_and_second_capture(fixture_vault):
    set_limit(fixture_vault, 0.0001)
    v = vault_mod.open_vault(fixture_vault)
    cap.capture(v)
    lines_before = (fixture_vault / ".raw/.gitignore").read_text()
    (fixture_vault / "inbox" / "big2.bin").write_bytes(b"y" * 5000)
    result = cap.capture(v)
    assert [e["name"] for e in result.new] == ["big2.bin"]
    after = (fixture_vault / ".raw/.gitignore").read_text()
    assert after.startswith(lines_before) and after.count("\n") == lines_before.count("\n") + 1


def test_no_limit_without_config_key(fixture_vault):
    assert vault_mod.open_vault(fixture_vault).raw_git_max_bytes is None
    cap.capture(vault_mod.open_vault(fixture_vault))
    assert not (fixture_vault / ".raw/.gitignore").exists()


@pytest.mark.parametrize("value", [0, -5, "20", True])
def test_bad_limit_in_config_refused(fixture_vault, value):
    cfg = json.loads((fixture_vault / "akasha.json").read_text())
    cfg["raw_git_max_mb"] = value
    (fixture_vault / "akasha.json").write_text(json.dumps(cfg))
    with pytest.raises(vault_mod.VaultError, match="raw_git_max_mb"):
        vault_mod.open_vault(fixture_vault)


# --- the skill -----------------------------------------------------------------


def test_setup_skill_frontmatter():
    text = (ROOT / "skills" / "setup" / "SKILL.md").read_text()
    meta, body = frontmatter.parse(text)
    assert meta["name"] == "setup"
    assert meta["disable-model-invocation"] is True
    assert "\n" not in meta["description"] and len(meta["description"]) <= 120
    assert "akashactl init" in body and "--dry-run" in body
