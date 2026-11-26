"""Parse and emit the strict YAML frontmatter subset Akasha uses (see ADR-0004).

Supported: one flat mapping at the top of a note, between `---` lines, whose
values are strings (plain, "double" or 'single' quoted), integers, booleans,
null, or lists of those as block lists (`- item`) or flow lists (`[a, b]`).

Anything else raises FrontmatterError instead of being guessed at, so a note
with richer YAML is left alone rather than silently rewritten.
"""

from __future__ import annotations

import re

__all__ = ["FrontmatterError", "split", "parse", "dump", "render"]

DELIMITER = "---"
KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
INT_RE = re.compile(r"[-+]?(0|[1-9][0-9]*)")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Values YAML would read as floats, octal/hex/binary, infinities or sexagesimal numbers.
NUMBERISH_RES = [
    re.compile(r"[-+]?(\d[\d_]*(\.\d*)?|\.\d+)([eE][-+]?\d+)?"),
    re.compile(r"0[xXoObB][0-9a-fA-F_]+"),
    re.compile(r"[-+]?\.(inf|Inf|INF|nan|NaN|NAN)"),
    re.compile(r"[-+]?\d+(:[0-5]?\d)+(\.\d*)?"),
]
NULLS = {"null", "Null", "NULL", "~"}
TRUES = {"true", "True", "TRUE"}
FALSES = {"false", "False", "FALSE"}
YAML11_BOOLS = {"yes", "no", "on", "off"}
PLAIN_BAD_START = set("[]{}&*!|>%@`,?:#'\"")
CONTROL_EXTRA = set("\x7f\x85\u2028\u2029")
ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r", "0": "\0"}


class FrontmatterError(ValueError):
    """Frontmatter is malformed or outside the supported subset."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


def split(text: str) -> tuple[str | None, str]:
    """Return (frontmatter text or None, body). Line endings are normalised to \\n."""
    text = text.replace("\r\n", "\n").removeprefix("﻿")
    lines = text.split("\n")
    if lines[0] != DELIMITER:
        return None, text
    for i in range(1, len(lines)):
        if lines[i] == DELIMITER:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise FrontmatterError("frontmatter opened with '---' but never closed", 1)


def parse(text: str) -> tuple[dict, str]:
    """Parse a whole note. Returns (properties, body); ({}, text) if there is no frontmatter."""
    block, body = split(text)
    if block is None:
        return {}, body
    return _parse_block(block), body


def dump(data: dict) -> str:
    """Emit frontmatter, including both `---` lines and a trailing newline."""
    out = [DELIMITER]
    for key, value in data.items():
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise FrontmatterError(f"unsupported key {key!r}")
        if isinstance(value, list):
            if not value:
                out.append(f"{key}: []")
                continue
            out.append(f"{key}:")
            for item in value:
                out.append(f"  - {_format_scalar(item, key)}")
        else:
            out.append(f"{key}:" if value is None else f"{key}: {_format_scalar(value, key)}")
    out.append(DELIMITER)
    return "\n".join(out) + "\n"


def render(data: dict, body: str) -> str:
    """Rebuild a note from properties and body. No properties means no frontmatter block."""
    return dump(data) + body if data else body


# --- parsing -----------------------------------------------------------------


def _parse_block(block: str) -> dict:
    data: dict = {}
    list_key: str | None = None  # key whose block-list items may follow
    for index, raw in enumerate(block.split("\n")):
        line_no = index + 2  # line 1 is the opening '---'
        if "\t" in raw:
            raise FrontmatterError("tabs are not allowed in frontmatter", line_no)
        if any(ord(c) < 32 or c in CONTROL_EXTRA for c in raw):
            raise FrontmatterError("control characters must be written as escapes in a quoted string", line_no)
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "-" or stripped.startswith("- "):
            if list_key is None:
                raise FrontmatterError("list item without a key above it", line_no)
            item = stripped[1:].strip()
            if not item:
                raise FrontmatterError("empty list item", line_no)
            if data[list_key] is None:
                data[list_key] = []
            data[list_key].append(_parse_scalar(item, line_no))
            continue
        if raw[0] == " ":
            raise FrontmatterError("nested or continued values are not supported", line_no)
        key, sep, rest = raw.partition(":")
        if not sep or not KEY_RE.fullmatch(key):
            raise FrontmatterError(f"expected 'key: value', got {raw!r}", line_no)
        if rest and not rest.startswith(" "):
            raise FrontmatterError("a space is required after ':'", line_no)
        if key in data:
            raise FrontmatterError(f"duplicate key {key!r}", line_no)
        rest = rest.strip()
        if rest:
            data[key] = _parse_value(rest, line_no)
            list_key = None
        else:
            data[key] = None
            list_key = key
    return data


def _parse_value(text: str, line_no: int):
    if text.startswith("[["):
        raise FrontmatterError("unquoted [[link]] is a nested list in YAML; quote it", line_no)
    if text.startswith("["):
        return _parse_flow_list(text, line_no)
    return _parse_scalar(text, line_no)


def _parse_flow_list(text: str, line_no: int) -> list:
    if not text.endswith("]"):
        raise FrontmatterError("flow list must end with ']'", line_no)
    inner = text[1:-1].strip()
    if not inner:
        return []
    items, current, quote, i = [], "", None, 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            current += ch
            if ch == "\\" and quote == '"' and i + 1 < len(inner):
                current += inner[i + 1]
                i += 1
            elif ch == quote:
                if quote == "'" and inner[i + 1 : i + 2] == "'":
                    current += "'"
                    i += 1
                else:
                    quote = None
        elif ch in "\"'" and not current.strip():
            quote, current = ch, current + ch
        elif ch == ",":
            items.append(current)
            current = ""
        elif ch in "[]{}":
            raise FrontmatterError("nested lists or mappings are not supported", line_no)
        else:
            current += ch
        i += 1
    if quote:
        raise FrontmatterError("unterminated quoted string in list", line_no)
    items.append(current)
    result = []
    for item in items:
        item = item.strip()
        if not item:
            raise FrontmatterError("empty item in flow list", line_no)
        result.append(_parse_scalar(item, line_no))
    return result


def _parse_scalar(text: str, line_no: int):
    if text.startswith('"'):
        return _parse_double_quoted(text, line_no)
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise FrontmatterError("unterminated single-quoted string", line_no)
        inner = text[1:-1]
        if "'" in inner.replace("''", ""):
            raise FrontmatterError("stray quote in single-quoted string", line_no)
        return inner.replace("''", "'")
    if text in NULLS:
        return None
    if text in TRUES:
        return True
    if text in FALSES:
        return False
    if text.lower() in YAML11_BOOLS:
        raise FrontmatterError(f"{text!r} is a boolean in some YAML versions; quote it", line_no)
    if INT_RE.fullmatch(text):
        return int(text)
    if DATE_RE.fullmatch(text):
        return text
    if any(r.fullmatch(text) for r in NUMBERISH_RES):
        raise FrontmatterError(f"{text!r} would be read as a non-integer number; quote it", line_no)
    if text[0] in PLAIN_BAD_START or text in ("-", "=") or text.startswith("- "):
        raise FrontmatterError(f"value starting with {text[0]!r} must be quoted", line_no)
    if ": " in text or text.endswith(":") or " #" in text:
        raise FrontmatterError("value containing ': ', ' #' or a trailing ':' must be quoted", line_no)
    return text


def _parse_double_quoted(text: str, line_no: int) -> str:
    out, i = [], 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if i != len(text) - 1:
                raise FrontmatterError("text after closing quote", line_no)
            return "".join(out)
        if ch == "\\":
            nxt = text[i + 1 : i + 2]
            if nxt in ESCAPES:
                out.append(ESCAPES[nxt])
                i += 2
                continue
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2 : i + 6]):
                out.append(chr(int(text[i + 2 : i + 6], 16)))
                i += 6
                continue
            raise FrontmatterError(f"unsupported escape '\\{nxt}'", line_no)
        out.append(ch)
        i += 1
    raise FrontmatterError("unterminated double-quoted string", line_no)


# --- emitting ----------------------------------------------------------------


def _format_scalar(value, key: str) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise FrontmatterError(f"{key}: unsupported value type {type(value).__name__}")
    if _is_safe_plain(value):
        return value
    return '"' + "".join(_escape_char(c) for c in value) + '"'


def _is_safe_plain(value: str) -> bool:
    if not value or value != value.strip() or any(ord(c) < 32 or c in CONTROL_EXTRA for c in value):
        return False
    try:
        return _parse_scalar(value, 0) == value
    except FrontmatterError:
        return False


def _escape_char(c: str) -> str:
    for code, char in ESCAPES.items():
        if c == char and code != "/":
            return "\\" + code
    if ord(c) < 32 or c in CONTROL_EXTRA:
        return f"\\u{ord(c):04x}"
    return c
