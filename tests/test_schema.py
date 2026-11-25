import pytest

from lib import schema as schema_mod
from lib.schema import SchemaError, load, validate


@pytest.fixture(scope="module")
def schema():
    return load()


def concept(**overrides):
    meta = {
        "type": "concept",
        "title": "Spaced repetition",
        "status": "seed",
        "created": "2026-11-25",
        "updated": "2026-11-25",
        "tags": ["learning"],
        "generated": True,
        "sources": ["[[spaced-repetition-video]]"],
    }
    meta.update(overrides)
    return meta


def test_repo_schema_loads(schema):
    assert set(schema["types"]) == {"source", "concept", "entity", "question", "course", "project"}


def test_valid_concept(schema):
    assert validate(concept(), "wiki/concepts/spaced-repetition.md", schema) == []


def test_unknown_type(schema):
    errors = validate(concept(type="recipe"), "wiki/concepts/x.md", schema)
    assert len(errors) == 1 and "not a known note type" in errors[0]


def test_missing_required_fields(schema):
    meta = concept()
    del meta["sources"], meta["tags"]
    errors = validate(meta, "wiki/concepts/x.md", schema)
    assert any("'sources'" in e for e in errors)
    assert any("'tags'" in e for e in errors)


@pytest.mark.parametrize(
    "field, value",
    [
        ("created", "25-11-2026"),
        ("created", "2026-02-30"),
        ("tags", "learning"),
        ("generated", "true"),
        ("title", ""),
        ("title", 5),
    ],
)
def test_wrong_field_kinds(schema, field, value):
    errors = validate(concept(**{field: value}), "wiki/concepts/x.md", schema)
    assert any(f"'{field}'" in e for e in errors)


def test_bad_status(schema):
    errors = validate(concept(status="done"), "wiki/concepts/x.md", schema)
    assert any("status" in e for e in errors)


def test_generated_must_be_true(schema):
    errors = validate(concept(generated=False), "wiki/concepts/x.md", schema)
    assert any("generated must be true" in e for e in errors)


@pytest.mark.parametrize(
    "path",
    [
        "wiki/sources/x.md",
        "wiki/concepts/sub/x.md",
        "personal/x.md",
        "wiki/concepts/x.txt",
        "/wiki/concepts/x.md",
        "wiki/concepts/../../personal/x.md",
    ],
)
def test_wrong_location(schema, path):
    assert validate(concept(), path, schema) != []


def test_course_needs_code_subfolder(schema):
    meta = concept(type="course", status="current", course="COMP 4800", built_from=["personal/comp4800/w1.md"])
    del meta["sources"]
    assert validate(meta, "wiki/courses/comp4800/summary.md", schema) == []
    assert validate(meta, "wiki/courses/summary.md", schema) != []


def test_unknown_extra_fields_allowed(schema):
    assert validate(concept(rating=5), "wiki/concepts/x.md", schema) == []


@pytest.mark.parametrize(
    "toml, message",
    [
        ("version = 2", "version"),
        ('version = 1\n[fields]\na = "float"', "unknown kind"),
        ('version = 1\ncommon = ["a"]', "not declared"),
        ("version = 1", "no [types"),
        ('version = 1\n[types.x]\nfolder = "personal"\nstatuses = ["a"]', "under wiki/"),
        ('version = 1\n[types.x]\nfolder = "wiki/../personal"\nstatuses = ["a"]', "under wiki/"),
        ('version = 1\n[types.x]\nfolder = "wiki/x"\nstatuses = []', "statuses"),
        ('version = 1\n[types.x]\nfolder = "wiki/x"\nstatuses = ["a"]\nrequired = ["z"]', "not declared"),
        ("version = ", "note-types"),
    ],
)
def test_bad_schema_rejected(tmp_path, toml, message):
    path = tmp_path / "note-types.toml"
    path.write_text(toml)
    with pytest.raises(SchemaError, match=message.replace("[", r"\[")):
        load(path)


def test_default_path_points_at_repo_schema():
    assert schema_mod.DEFAULT_PATH.name == "note-types.toml"
    assert schema_mod.DEFAULT_PATH.exists()
