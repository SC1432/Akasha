import pytest

from lib.frontmatter import FrontmatterError, dump, parse, render, split

OBSIDIAN_NOTE = """---
type: concept
title: Spaced repetition
status: seed
created: 2026-11-25
updated: 2026-11-25
tags:
  - learning
  - memory
sources:
  - "[[spaced-repetition-video]]"
aliases: [SRS, 'Leitner system']
generated: true
reviews: 3
due:
---
# Spaced repetition

Body text with: colons and # hashes is fine.
"""


def test_parses_obsidian_style_note():
    meta, body = parse(OBSIDIAN_NOTE)
    assert meta == {
        "type": "concept",
        "title": "Spaced repetition",
        "status": "seed",
        "created": "2026-11-25",
        "updated": "2026-11-25",
        "tags": ["learning", "memory"],
        "sources": ["[[spaced-repetition-video]]"],
        "aliases": ["SRS", "Leitner system"],
        "generated": True,
        "reviews": 3,
        "due": None,
    }
    assert body.startswith("# Spaced repetition\n")


def test_no_frontmatter_returns_whole_text():
    assert parse("# Just a note\n") == ({}, "# Just a note\n")
    assert split("text\n---\nmore") == (None, "text\n---\nmore")


def test_crlf_and_bom_normalised():
    meta, body = parse("\ufeff---\r\ntitle: A\r\n---\r\nbody\r\n")
    assert meta == {"title": "A"}
    assert body == "body\n"


def test_render_round_trips_body_exactly():
    meta, body = parse(OBSIDIAN_NOTE)
    assert parse(render(meta, body)) == (meta, body)


def test_render_without_properties_is_body_only():
    assert render({}, "body\n") == "body\n"


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "",
        "true",
        "no",
        "Yes",
        "123",
        "3.10",
        "0x1f",
        "1e5",
        "12:30",
        "null",
        "~",
        "a: b",
        "trailing:",
        "has #hash",
        "# leading hash",
        "- dash",
        "=",
        "[[link]]",
        "[not a list]",
        "{brace}",
        "*alias",
        "&anchor",
        "!tag",
        "|block",
        ">folded",
        "'single'",
        '"double"',
        "it's",
        'say "hi"',
        "back\\slash",
        "line\nbreak",
        "tab\there",
        " padded ",
        "émoji 🌌 ok",
        "2026-11-25",
        "\x01ctrl",
        "form\x0cfeed",
        "carriage\rreturn",
        "sep\u2028arator",
    ],
)
def test_strings_round_trip(value):
    data = {"v": value, "items": [value, value]}
    meta, body = parse(dump(data) + "body")
    assert meta == data
    assert body == "body"


def test_dump_types_and_order():
    text = dump({"b": 1, "a": True, "c": None, "d": [], "e": [1, False, None, "x"]})
    assert text == "---\nb: 1\na: true\nc:\nd: []\ne:\n  - 1\n  - false\n  - null\n  - x\n---\n"
    assert parse(text)[0] == {"b": 1, "a": True, "c": None, "d": [], "e": [1, False, None, "x"]}


def test_dump_quotes_ambiguous_strings():
    assert dump({"v": "yes"}) == '---\nv: "yes"\n---\n'
    assert dump({"v": "[[x]]"}) == '---\nv: "[[x]]"\n---\n'


@pytest.mark.parametrize(
    "data",
    [
        {"v": 1.5},
        {"v": {"nested": 1}},
        {"v": [[1]]},
        {"bad key": 1},
        {1: "x"},
    ],
)
def test_dump_refuses_unsupported(data):
    with pytest.raises(FrontmatterError):
        dump(data)


@pytest.mark.parametrize(
    "block, line",
    [
        ("parent:\n  child: 1", 3),
        ("text: |\n  multi\n  line", 2),
        ("text: >\n  folded", 2),
        ("a: &x 1", 2),
        ("a: *x", 2),
        ("a: !!str 1", 2),
        ("a: {b: 1}", 2),
        ("a: [b, [c]]", 2),
        ("a: [[link]]", 2),
        ("a: 1\na: 2", 3),
        ("a:\tb", 2),
        ("a: yes", 2),
        ("a: Off", 2),
        ("a: 3.10", 2),
        ("a: 0755", 2),
        ("a: .inf", 2),
        ("a: 1:30", 2),
        ("a: =", 2),
        ("a: x\x0cy", 2),
        ("a: x\ry", 2),
        ("a: b: c", 2),
        ("a: b # comment", 2),
        ('a: "x" trailing', 2),
        ('a: "unterminated', 2),
        ("a: 'it's'", 2),
        ('a: "bad \\q escape"', 2),
        ("a: [x, ]", 2),
        ("a: [x", 2),
        ("- orphan", 2),
        ("a:\n  -", 3),
        ("a:b", 2),
        ("bad key: 1", 2),
        ('"quoted": 1', 2),
        ("  indented: 1", 2),
        ("a:\n  - - nested", 3),
        ("a:\n  - k: v", 3),
    ],
)
def test_parse_refuses_outside_subset(block, line):
    with pytest.raises(FrontmatterError) as exc:
        parse(f"---\n{block}\n---\nbody")
    assert exc.value.line == line


def test_unterminated_frontmatter():
    with pytest.raises(FrontmatterError):
        parse("---\ntitle: x\nbody without closing line\n")


def test_comments_and_blank_lines_ignored():
    meta, _ = parse("---\n# a comment\n\ntitle: x\n---\n")
    assert meta == {"title": "x"}


def test_flow_list_with_quoted_commas():
    meta, _ = parse('---\na: ["x, y", \'z\'\'s\', 2, true]\n---\n')
    assert meta == {"a": ["x, y", "z's", 2, True]}


def test_list_items_at_column_zero():
    meta, _ = parse("---\ntags:\n- a\n- b\n---\n")
    assert meta == {"tags": ["a", "b"]}


def test_unicode_escape():
    meta, _ = parse('---\na: "\\u00e9\\n"\n---\n')
    assert meta == {"a": "é\n"}
