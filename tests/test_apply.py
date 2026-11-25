import datetime
import hashlib
import json
import subprocess

import pytest

from conftest import ROOT, git, snapshot
from lib import apply as apply_mod
from lib import capture as cap
from lib import frontmatter, schema
from lib import plan as plan_mod
from lib import undo as undo_mod
from lib import vault as vault_mod

WRAPPER = ROOT / "bin" / "akashactl"
NOW = datetime.datetime(2026, 11, 25, 14, 3)


def run(*args, cwd=None, stdin=None):
    return subprocess.run([str(WRAPPER), *args], cwd=cwd, capture_output=True, text=True, input=stdin)


def page(body="Body.\n", **meta):
    data = {
        "type": "concept",
        "title": "Active recall",
        "status": "seed",
        "created": "2026-11-25",
        "updated": "2026-11-25",
        "tags": ["learning"],
        "generated": True,
        "sources": ["[[spaced-repetition-video]]"],
    }
    data.update(meta)
    return frontmatter.render({k: v for k, v in data.items() if v is not None}, body)


def create(path="wiki/concepts/active-recall.md", content=None):
    return {"action": "create", "path": path, "content": content if content is not None else page()}


def update(vault, path="wiki/concepts/spaced-repetition.md", content=None, base_hash=None):
    full = vault / path
    return {
        "action": "update",
        "path": path,
        "base_hash": base_hash or hashlib.sha256(full.read_bytes()).hexdigest(),
        "content": content if content is not None else page(title="Spaced repetition", status="developing"),
    }


def make_plan(*pages, operation="ingest", log="Test change"):
    return {"operation": operation, "log": log, "pages": list(pages)}


@pytest.fixture
def ctx(fixture_vault):
    return fixture_vault, vault_mod.open_vault(fixture_vault), schema.load()


def check(ctx, data):
    _, v, s = ctx
    return plan_mod.validate_plan(data, v, s)


def do_apply(ctx, data, dry_run=False):
    _, v, s = ctx
    return apply_mod.apply_plan(check(ctx, data), v, s, dry_run=dry_run, now=NOW)


def rejected(ctx, data):
    with pytest.raises(plan_mod.PlanError) as exc:
        check(ctx, data)
    return "\n".join(exc.value.errors)


# --- the four Phase 1 roadmap tests -------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "personal/journal.md",
        "inbox/x.md",
        ".raw/x.md",
        "akasha.json",
        "x.md",
        "wiki/../personal/journal.md",
        "/etc/passwd",
        "wiki\\concepts\\x.md",
        "wiki/.obsidian/x.md",
        "wiki/concepts/x.txt",
        "wiki//concepts/x.md",
        "./wiki/concepts/x.md",
    ],
)
def test_writes_outside_wiki_refused(ctx, path):
    vault = ctx[0]
    before = snapshot(vault)
    errors = rejected(ctx, make_plan(create(path)))
    assert path in errors or "pages[0]" in errors
    assert snapshot(vault) == before


def test_personal_untouched_by_apply_and_undo(ctx):
    vault = ctx[0]
    before = snapshot(vault, "personal")
    do_apply(ctx, make_plan(create(), update(vault)))
    undo_mod.undo(ctx[1])
    assert snapshot(vault, "personal") == before


def test_personal_folder_inside_wiki_refused(fixture_vault):
    (fixture_vault / "akasha.json").write_text(json.dumps({"version": 1, "personal": ["personal", "wiki/private"]}))
    v = vault_mod.open_vault(fixture_vault)
    with pytest.raises(plan_mod.PlanError, match="personal and read-only"):
        plan_mod.validate_plan(make_plan(create("wiki/Private/x.md")), v, schema.load())


def test_changed_page_blocks_apply(ctx):
    vault = ctx[0]
    change = update(vault)
    (vault / "wiki/concepts/spaced-repetition.md").write_text(page(title="Spaced repetition", body="My edit\n"))
    before = snapshot(vault)
    errors = rejected(ctx, make_plan(create(), change))
    assert "base_hash mismatch" in errors
    assert snapshot(vault) == before  # the valid create in the same plan was not written either


def test_undo_restores(ctx):
    vault = ctx[0]
    before = snapshot(vault)
    head = git(vault, "rev-parse", "HEAD")
    do_apply(ctx, make_plan(create(), update(vault)))
    assert snapshot(vault) != before
    result = undo_mod.undo(ctx[1])
    assert snapshot(vault) == before
    assert result.deleted == ["wiki/concepts/active-recall.md"]
    assert git(vault, "diff", "--stat", head.strip(), "HEAD") == ""


# --- apply --------------------------------------------------------------------


def test_apply_writes_pages_index_log_and_one_commit(ctx):
    vault = ctx[0]
    result = do_apply(ctx, make_plan(create(), update(vault), log="Added active recall"))
    assert (vault / "wiki/concepts/active-recall.md").read_text() == page()
    assert "status: developing" in (vault / "wiki/concepts/spaced-repetition.md").read_text()
    index = (vault / "wiki/index.md").read_text()
    assert "## Concepts" in index and "## Sources" in index
    assert index.index("[[wiki/concepts/active-recall|Active recall]]") < index.index(
        "[[wiki/concepts/spaced-repetition|Spaced repetition]]"
    )
    log = (vault / "wiki/log.md").read_text()
    assert log.startswith("# Log\n\n## 2026-11-25 14:03 · ingest\n\nAdded active recall\n\n")
    assert "- created [[wiki/concepts/active-recall]]" in log
    assert "- updated [[wiki/concepts/spaced-repetition]]" in log
    assert git(vault, "rev-list", "--count", "HEAD").strip() == "2"
    message = git(vault, "log", "-1", "--format=%B")
    assert message.startswith("akasha: ingest: Added active recall")
    assert "Akasha-Operation: ingest" in message
    assert sorted(git(vault, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        ["wiki/concepts/active-recall.md", "wiki/concepts/spaced-repetition.md", "wiki/index.md", "wiki/log.md"]
    )
    assert result.commit == git(vault, "rev-parse", "HEAD").strip()
    assert git(vault, "status", "--porcelain") == ""


def test_log_is_newest_first(ctx):
    vault = ctx[0]
    do_apply(ctx, make_plan(create(), log="First"))
    do_apply(ctx, make_plan(create("wiki/concepts/blurting.md", page(title="Blurting")), log="Second"))
    log = (vault / "wiki/log.md").read_text()
    assert log.index("Second") < log.index("First")


def test_log_created_when_missing(ctx):
    vault = ctx[0]
    (vault / "wiki/log.md").unlink()
    do_apply(ctx, make_plan(create()))
    assert (vault / "wiki/log.md").read_text().startswith("# Log\n\n## ")


def test_dry_run_writes_nothing(ctx):
    vault = ctx[0]
    before = snapshot(vault)
    head = git(vault, "rev-parse", "HEAD")
    result = do_apply(ctx, make_plan(create(), update(vault)), dry_run=True)
    assert result.commit is None
    assert snapshot(vault) == before
    assert git(vault, "rev-parse", "HEAD") == head
    lines = result.summary_lines()
    assert "create wiki/concepts/active-recall.md (13 lines)" in lines
    assert any(line.startswith("update wiki/concepts/spaced-repetition.md (+") for line in lines)
    assert any(line.startswith("update wiki/log.md") for line in lines)


def test_dry_run_diff(ctx):
    result = do_apply(ctx, make_plan(update(ctx[0])), dry_run=True)
    diff = "\n".join(result.summary_lines(diff=True))
    assert "--- a/wiki/concepts/spaced-repetition.md" in diff
    assert "-status: seed" in diff and "+status: developing" in diff


def test_failed_write_rolls_back(ctx, monkeypatch):
    vault = ctx[0]
    before = snapshot(vault)

    def boom(*a, **k):
        raise vault_mod.gitops.GitError("simulated failure")

    monkeypatch.setattr(apply_mod.gitops, "commit_paths", boom)
    with pytest.raises(vault_mod.gitops.GitError):
        do_apply(ctx, make_plan(create(), update(vault)))
    assert snapshot(vault) == before
    assert not (vault / ".akasha/lock").exists()


def test_lock_blocks_concurrent_write(ctx):
    vault = ctx[0]
    (vault / ".akasha").mkdir()
    (vault / ".akasha/lock").write_text("123\n")
    with pytest.raises(vault_mod.VaultError, match="lock"):
        do_apply(ctx, make_plan(create()))
    assert not (vault / "wiki/concepts/active-recall.md").exists()


# --- plan validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "data, message",
    [
        ({"operation": "ingest", "log": "x", "pages": [], "extra": 1}, "unknown plan keys"),
        ({"operation": "Ingest!", "log": "x", "pages": [{}]}, "operation must be"),
        ({"operation": "undo", "log": "x", "pages": [{}]}, "reserved"),
        ({"operation": "ingest", "log": " ", "pages": [{}]}, "log must be"),
        ({"operation": "ingest", "log": "x" * 301, "pages": [{}]}, "at most 300"),
        ({"operation": "ingest", "log": "x", "pages": []}, "non-empty list"),
        ({"operation": "ingest", "log": "x", "pages": ["nope"]}, "must be an object"),
        ({"operation": "ingest", "log": "x", "pages": [{"action": "delete", "path": "wiki/a.md", "content": ""}]},
         "action must be"),
    ],
)
def test_malformed_plans(ctx, data, message):
    assert message in rejected(ctx, data)


def test_all_errors_reported_together(ctx):
    errors = rejected(ctx, make_plan(create("personal/a.md"), create(content=page(status="nope"))))
    assert "personal/a.md" in errors and "status 'nope'" in errors


@pytest.mark.parametrize("name", ["index", "log", "hot", "now", "Index"])
def test_reserved_pages_refused(ctx, name):
    assert "maintained by akashactl" in rejected(ctx, make_plan(create(f"wiki/{name}.md")))


def test_schema_enforced(ctx):
    errors = rejected(ctx, make_plan(create(content=page(sources=None, created="yesterday"))))
    assert "missing required field 'sources'" in errors and "'created'" in errors


def test_wrong_folder_for_type(ctx):
    assert "belong directly in wiki/concepts/" in rejected(ctx, make_plan(create("wiki/entities/active-recall.md")))


def test_content_must_have_frontmatter(ctx):
    assert "must start with frontmatter" in rejected(ctx, make_plan(create(content="# No frontmatter\n")))


def test_unparseable_frontmatter(ctx):
    content = page().replace("status: seed", "status:\n  nested: 1")
    assert "frontmatter line" in rejected(ctx, make_plan(create(content=content)))


def test_create_existing_refused_any_case(ctx):
    assert "already exists" in rejected(ctx, make_plan(create("wiki/concepts/spaced-repetition.md")))
    assert "already exists" in rejected(ctx, make_plan(create("wiki/concepts/Spaced-Repetition.md")))


def test_duplicate_paths_in_plan(ctx):
    errors = rejected(ctx, make_plan(create(), create("wiki/concepts/Active-Recall.md")))
    assert "appears twice" in errors


def test_update_missing_page(ctx):
    data = make_plan({**update(ctx[0]), "path": "wiki/concepts/nope.md"})
    assert "does not exist" in rejected(ctx, data)


def test_update_needs_valid_base_hash(ctx):
    change = update(ctx[0])
    del change["base_hash"]
    assert "needs base_hash" in rejected(ctx, make_plan(change))


def test_update_refuses_non_generated_page(ctx):
    vault = ctx[0]
    path = vault / "wiki/concepts/spaced-repetition.md"
    path.write_text(path.read_text().replace("generated: true", "generated: false"))
    git(vault, "commit", "--quiet", "-am", "my page now")
    assert "only rewrites its own pages" in rejected(ctx, make_plan(update(vault)))


def test_symlinked_folder_refused(ctx, tmp_path):
    vault = ctx[0]
    (tmp_path / "outside").mkdir()
    (vault / "wiki/entities").symlink_to(tmp_path / "outside")
    content = page(type="entity", title="Feynman")
    assert "symlink" in rejected(ctx, make_plan(create("wiki/entities/feynman.md", content)))
    assert list((tmp_path / "outside").iterdir()) == []


def test_broken_links_refused(ctx):
    content = page(body="See [[nowhere]] and ![[missing.png]] and [[spaced-repetition#Intro|alias]].\n")
    errors = rejected(ctx, make_plan(create(content=content)))
    assert "nowhere" in errors and "missing.png" in errors and "spaced-repetition" not in errors.split(":")[-1]


def test_links_resolve_by_name_path_case_and_within_plan(ctx):
    body = (
        "[[Spaced-Repetition]] [[concepts/spaced-repetition]] [[wiki/sources/spaced-repetition-video.md]] "
        "[[blurting]] [[#Heading]] `[[in code]]`\n\n```\n[[in fence]]\n```\n"
    )
    plan = make_plan(create(content=page(body=body)), create("wiki/concepts/blurting.md", page(title="Blurting")))
    assert len(check(ctx, plan).pages) == 2


def test_links_in_frontmatter_checked(ctx):
    assert "ghost" in rejected(ctx, make_plan(create(content=page(sources=["[[ghost]]"]))))


def test_index_ignores_hand_written_and_unparseable_pages(ctx):
    vault = ctx[0]
    (vault / "wiki/concepts/mine.md").write_text("---\ntype: concept\ntitle: Mine\n---\n")
    (vault / "wiki/concepts/weird.md").write_text("---\nx:\n  y: 1\n---\n")
    do_apply(ctx, make_plan(create()))
    index = (vault / "wiki/index.md").read_text()
    assert "Mine" not in index and "weird" not in index


# --- undo ---------------------------------------------------------------------


def test_undo_steps_back_through_operations(ctx):
    vault = ctx[0]
    v = ctx[1]
    original = snapshot(vault)
    do_apply(ctx, make_plan(create(), log="First"))
    after_first = snapshot(vault)
    do_apply(ctx, make_plan(create("wiki/concepts/blurting.md", page(title="Blurting")), log="Second"))
    assert "Second" in undo_mod.undo(v).subject
    assert snapshot(vault) == after_first
    assert "First" in undo_mod.undo(v).subject
    assert snapshot(vault) == original
    with pytest.raises(undo_mod.UndoError, match="nothing to undo"):
        undo_mod.undo(v)


def test_undo_commit_trailers(ctx):
    vault = ctx[0]
    applied = do_apply(ctx, make_plan(create(), log="First"))
    undone = undo_mod.undo(ctx[1])
    message = git(vault, "log", "-1", "--format=%B")
    assert message.startswith("akasha: undo: ingest: First")
    assert "Akasha-Operation: undo" in message
    assert f"Akasha-Reverts: {applied.commit}" in message
    assert undone.commit == git(vault, "rev-parse", "HEAD").strip()


def test_undo_refuses_if_file_edited_since(ctx):
    vault = ctx[0]
    do_apply(ctx, make_plan(create()))
    target = vault / "wiki/concepts/active-recall.md"
    target.write_text(target.read_text() + "\nMy addition\n")
    with pytest.raises(undo_mod.UndoError, match="active-recall.md"):
        undo_mod.undo(ctx[1])
    assert "My addition" in target.read_text()


def test_undo_refuses_if_file_committed_since(ctx):
    vault = ctx[0]
    do_apply(ctx, make_plan(create()))
    log = vault / "wiki/log.md"
    log.write_text(log.read_text() + "\nmanual note\n")
    git(vault, "-c", "user.name=Me", "-c", "user.email=me@example.com", "commit", "--quiet", "-am", "mine")
    with pytest.raises(undo_mod.UndoError, match="wiki/log.md"):
        undo_mod.undo(ctx[1])


def test_undo_skips_unrelated_user_commits(ctx):
    vault = ctx[0]
    do_apply(ctx, make_plan(create()))
    (vault / "personal/journal.md").write_text("new entry\n")
    git(vault, "-c", "user.name=Me", "-c", "user.email=me@example.com", "commit", "--quiet", "-am", "journal")
    undo_mod.undo(ctx[1])
    assert not (vault / "wiki/concepts/active-recall.md").exists()
    assert (vault / "personal/journal.md").read_text() == "new entry\n"


def test_undo_capture_removes_raw_files(ctx):
    vault = ctx[0]
    cap.capture(ctx[1])
    assert (vault / ".raw/manifest.json").exists()
    result = undo_mod.undo(ctx[1])
    assert ".raw/manifest.json" in result.deleted
    assert not any((vault / ".raw").iterdir()) if (vault / ".raw").exists() else True


def test_undo_dry_run(ctx):
    vault = ctx[0]
    do_apply(ctx, make_plan(create(), update(vault)))
    before = snapshot(vault)
    result = undo_mod.undo(ctx[1], dry_run=True)
    assert result.commit is None and snapshot(vault) == before
    assert sorted(result.restored) == ["wiki/concepts/spaced-repetition.md", "wiki/index.md", "wiki/log.md"]
    assert result.deleted == ["wiki/concepts/active-recall.md"]


def test_undo_without_akasha_commits(ctx):
    with pytest.raises(undo_mod.UndoError, match="nothing to undo"):
        undo_mod.undo(ctx[1])


# --- CLI ----------------------------------------------------------------------


def test_cli_apply_dry_run_then_apply_then_undo(fixture_vault, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(make_plan(create(), log="CLI test")))
    dry = run("apply", "--dry-run", str(plan_file), cwd=fixture_vault)
    assert dry.returncode == 0, dry.stderr
    assert dry.stdout.startswith("dry run, nothing written:")
    assert "create wiki/concepts/active-recall.md" in dry.stdout
    assert not (fixture_vault / "wiki/concepts/active-recall.md").exists()

    real = run("apply", "-", "--vault", str(fixture_vault), stdin=plan_file.read_text())
    assert real.returncode == 0, real.stderr
    assert "applied ingest:" in real.stdout and "commit " in real.stdout

    undo_dry = run("undo", "--dry-run", cwd=fixture_vault)
    assert undo_dry.returncode == 0 and "would undo" in undo_dry.stdout
    assert "delete wiki/concepts/active-recall.md" in undo_dry.stdout
    undone = run("undo", cwd=fixture_vault)
    assert undone.returncode == 0 and "undid" in undone.stdout
    again = run("undo", cwd=fixture_vault)
    assert again.returncode == 1 and "nothing to undo" in again.stderr


def test_cli_rejected_plan_lists_errors(fixture_vault, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(make_plan(create("personal/x.md"))))
    result = run("apply", str(plan_file), cwd=fixture_vault)
    assert result.returncode == 1
    assert "plan rejected, nothing written:" in result.stderr and "personal/x.md" in result.stderr


def test_cli_apply_bad_json(fixture_vault):
    result = run("apply", "-", cwd=fixture_vault, stdin="{not json")
    assert result.returncode == 1 and "not valid JSON" in result.stderr


def test_cli_hash_matches_base_hash(fixture_vault):
    result = run("hash", "wiki/concepts/spaced-repetition.md", cwd=fixture_vault)
    assert result.returncode == 0
    expected = hashlib.sha256((fixture_vault / "wiki/concepts/spaced-repetition.md").read_bytes()).hexdigest()
    assert result.stdout.split()[0] == expected
