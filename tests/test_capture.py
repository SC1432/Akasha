import hashlib
import json
import subprocess

import pytest

from conftest import ROOT, git, snapshot
from lib import capture as cap
from lib import vault as vault_mod

WRAPPER = ROOT / "bin" / "akashactl"


def run(*args, cwd=None):
    return subprocess.run([str(WRAPPER), *args], cwd=cwd, capture_output=True, text=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(vault):
    return json.loads((vault / ".raw" / "manifest.json").read_text())


def test_capture_stores_hash_named_copies(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    result = cap.capture(v)
    article = fixture_vault / "inbox" / "spaced-repetition-article.md"
    stored = fixture_vault / ".raw" / f"{sha(article)}.md"
    assert stored.read_bytes() == article.read_bytes()
    png = fixture_vault / "inbox" / "carousel-slide.PNG"
    assert (fixture_vault / ".raw" / f"{sha(png)}.png").is_file()
    assert len(result.new) == 6
    raw_files = sorted(p.name for p in (fixture_vault / ".raw").iterdir())
    assert len(raw_files) == 7 and "manifest.json" in raw_files


def test_manifest_entries(fixture_vault):
    cap.capture(vault_mod.open_vault(fixture_vault), today=__import__("datetime").date(2026, 11, 25))
    files = manifest(fixture_vault)["files"]
    by_name = {e["name"]: e for e in files.values()}
    article = by_name["copy-of-article.md"] if "copy-of-article.md" in by_name else by_name["spaced-repetition-article.md"]
    assert article["kind"] == "text" and article["origin"] is None and "fetch" not in article
    assert article["captured"] == "2026-11-25"
    assert by_name["reel-caption.txt"]["inbox_path"] == "inbox/reels/reel-caption.txt"
    assert by_name["carousel-slide.PNG"]["kind"] == "image"
    for name, url in [
        ("video-link.txt", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("feynman.url", "https://example.com/feynman-technique"),
        ("leitner.webloc", "https://example.com/leitner-system"),
    ]:
        assert by_name[name]["kind"] == "link"
        assert by_name[name]["origin"] == url
        assert by_name[name]["fetch"] == "pending"
    for digest, entry in files.items():
        assert entry["hash"] == digest
        assert sha(fixture_vault / entry["file"]) == digest


def test_duplicates_and_skips(fixture_vault):
    result = cap.capture(vault_mod.open_vault(fixture_vault))
    assert [rel for rel, _ in result.duplicates] == ["inbox/spaced-repetition-article.md"]
    assert dict(result.skipped) == {"inbox/.DS_Store": "hidden file", "inbox/empty.txt": "empty file"}


def test_second_run_is_all_duplicates_and_no_commit(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    cap.capture(v)
    head = git(fixture_vault, "rev-parse", "HEAD")
    before = snapshot(fixture_vault, ".raw")
    result = cap.capture(v)
    assert result.new == [] and len(result.duplicates) == 7 and result.commit is None
    assert git(fixture_vault, "rev-parse", "HEAD") == head
    assert snapshot(fixture_vault, ".raw") == before


def test_new_file_later_is_added(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    cap.capture(v)
    (fixture_vault / "inbox" / "later.md").write_text("A later note\n")
    result = cap.capture(v)
    assert [e["name"] for e in result.new] == ["later.md"]
    assert len(manifest(fixture_vault)["files"]) == 7


def test_inbox_personal_and_wiki_untouched(fixture_vault):
    before = {k: v for k, v in snapshot(fixture_vault).items() if not k.startswith(".raw/")}
    cap.capture(vault_mod.open_vault(fixture_vault))
    after = {k: v for k, v in snapshot(fixture_vault).items() if not k.startswith(".raw/")}
    assert after == before


def test_one_commit_with_only_raw_paths(fixture_vault):
    result = cap.capture(vault_mod.open_vault(fixture_vault))
    assert git(fixture_vault, "rev-list", "--count", "HEAD").strip() == "2"
    changed = git(fixture_vault, "show", "--name-only", "--format=", "HEAD").split()
    assert changed and all(p.startswith(".raw/") for p in changed)
    message = git(fixture_vault, "log", "-1", "--format=%B")
    assert message.startswith("akasha: capture 6 files")
    assert "Akasha-Operation: capture" in message
    assert git(fixture_vault, "log", "-1", "--format=%an").strip() == "Akasha"
    assert result.commit == git(fixture_vault, "rev-parse", "HEAD").strip()
    assert git(fixture_vault, "status", "--porcelain") == ""


def test_users_staged_changes_left_out_of_commit(fixture_vault):
    (fixture_vault / "personal" / "journal.md").write_text("edited by me\n")
    git(fixture_vault, "add", "personal/journal.md")
    cap.capture(vault_mod.open_vault(fixture_vault))
    changed = git(fixture_vault, "show", "--name-only", "--format=", "HEAD").split()
    assert "personal/journal.md" not in changed
    assert git(fixture_vault, "diff", "--cached", "--name-only").split() == ["personal/journal.md"]


def test_dry_run_writes_nothing(fixture_vault):
    before = snapshot(fixture_vault)
    head = git(fixture_vault, "rev-parse", "HEAD")
    result = cap.capture(vault_mod.open_vault(fixture_vault), dry_run=True)
    assert len(result.new) == 6 and result.commit is None
    assert snapshot(fixture_vault) == before
    assert git(fixture_vault, "rev-parse", "HEAD") == head


def test_existing_raw_file_is_never_overwritten(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    cap.capture(v)
    article = fixture_vault / "inbox" / "spaced-repetition-article.md"
    stored = fixture_vault / ".raw" / f"{sha(article)}.md"
    stored.write_text("tampered")
    entry_files = manifest(fixture_vault)["files"]
    del entry_files[sha(article)]
    (fixture_vault / ".raw" / "manifest.json").write_text(json.dumps({"version": 1, "files": entry_files}))
    with pytest.raises(cap.CaptureError, match="does not match its name"):
        cap.capture(v)
    assert stored.read_text() == "tampered"


def test_raw_file_without_manifest_entry_is_rerecorded(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    cap.capture(v)
    (fixture_vault / ".raw" / "manifest.json").unlink()
    git(fixture_vault, "commit", "--quiet", "-am", "lose manifest")
    result = cap.capture(v)
    assert len(result.new) == 6
    assert len(manifest(fixture_vault)["files"]) == 6


def test_missing_raw_file_is_restored(fixture_vault):
    v = vault_mod.open_vault(fixture_vault)
    cap.capture(v)
    article = fixture_vault / "inbox" / "copy-of-article.md"
    stored = fixture_vault / ".raw" / f"{sha(article)}.md"
    stored.unlink()
    result = cap.capture(v)
    assert len(result.new) == 1 and stored.read_bytes() == article.read_bytes()
    assert result.commit is None  # restored bytes match HEAD, so there is nothing new to commit
    assert git(fixture_vault, "status", "--porcelain") == ""


def test_symlinks_skipped(fixture_vault, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private key")
    (fixture_vault / "inbox" / "sneaky.txt").symlink_to(secret)
    result = cap.capture(vault_mod.open_vault(fixture_vault))
    assert ("inbox/sneaky.txt", "symlink") in result.skipped
    assert all(e["name"] != "sneaky.txt" for e in result.new)


def test_raw_symlink_refused(fixture_vault, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (fixture_vault / ".raw").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(cap.CaptureError, match="real directory"):
        cap.capture(vault_mod.open_vault(fixture_vault))


def test_corrupt_manifest_refused(fixture_vault):
    (fixture_vault / ".raw").mkdir()
    (fixture_vault / ".raw" / "manifest.json").write_text("{not json")
    with pytest.raises(cap.CaptureError, match="unreadable"):
        cap.capture(vault_mod.open_vault(fixture_vault))


def test_no_inbox_is_a_no_op(fixture_vault):
    import shutil

    shutil.rmtree(fixture_vault / "inbox")
    result = cap.capture(vault_mod.open_vault(fixture_vault))
    assert result.new == [] and result.commit is None


@pytest.mark.parametrize(
    "ext, data, expected",
    [
        (".txt", b"https://a.example/x\n", "https://a.example/x"),
        (".txt", b"see https://a.example/x", None),
        (".txt", b"https://a.example/x https://b.example", None),
        (".md", b"\xef\xbb\xbfhttp://a.example", "http://a.example"),
        (".url", b"[InternetShortcut]\nURL=https://a.example\n", "https://a.example"),
        (".url", b"garbage", None),
        (".webloc", b"not a plist", None),
        (".pdf", b"https://a.example", None),
        (".txt", b"ftp://a.example", None),
        (".txt", b"\xff\xfe", None),
    ],
)
def test_link_detection(ext, data, expected):
    assert cap._link_target(ext, data) == expected


def test_open_vault_requires_config_and_git(tmp_path):
    with pytest.raises(vault_mod.VaultError, match="akasha.json"):
        vault_mod.open_vault(tmp_path)
    (tmp_path / "akasha.json").write_text('{"version": 1, "personal": ["personal"]}')
    with pytest.raises(vault_mod.VaultError, match="git"):
        vault_mod.open_vault(tmp_path)
    (tmp_path / "akasha.json").write_text('{"version": 2}')
    with pytest.raises(vault_mod.VaultError, match="version"):
        vault_mod.open_vault(tmp_path)


def test_open_vault_refuses_subfolder_of_repo(fixture_vault):
    sub = fixture_vault / "wiki"
    (sub / "akasha.json").write_text('{"version": 1}')
    with pytest.raises(vault_mod.VaultError, match="root of a git repository"):
        vault_mod.open_vault(sub)


def test_cli_capture_and_dry_run(fixture_vault):
    dry = run("capture", "--dry-run", cwd=fixture_vault)
    assert dry.returncode == 0, dry.stderr
    assert "6 new, 1 duplicate, 2 skipped; dry run, nothing written" in dry.stdout
    assert not (fixture_vault / ".raw").exists()
    real = run("capture", "--vault", str(fixture_vault))
    assert real.returncode == 0, real.stderr
    assert "captured: inbox/feynman.url -> .raw/" in real.stdout
    assert "(link, fetch pending: https://example.com/feynman-technique)" in real.stdout
    assert "6 new, 1 duplicate, 2 skipped; commit " in real.stdout


def test_cli_capture_outside_vault(tmp_path):
    result = run("capture", "--vault", str(tmp_path))
    assert result.returncode == 2 and "run /akasha:setup first" in result.stderr


def test_fixture_vault_validates_clean(fixture_vault):
    result = run("validate", "--vault", str(fixture_vault))
    assert result.returncode == 0, result.stdout
    assert "2 checked, 0 with problems" in result.stdout


def test_capture_in_repo_with_no_commits(tmp_path):
    import shutil

    from conftest import FIXTURE_VAULT

    vault = tmp_path / "fresh"
    shutil.copytree(FIXTURE_VAULT, vault)
    git(vault, "init", "--quiet")
    result = cap.capture(vault_mod.open_vault(vault))
    assert len(result.new) == 6 and result.commit
    assert git(vault, "rev-list", "--count", "HEAD").strip() == "1"
