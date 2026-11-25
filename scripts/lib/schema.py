"""Load schema/note-types.toml and validate a page's frontmatter against it (see ADR-0004)."""

from __future__ import annotations

import datetime
import re
import tomllib
from pathlib import Path, PurePosixPath

__all__ = ["SchemaError", "DEFAULT_PATH", "load", "validate"]

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "schema" / "note-types.toml"
KINDS = {"string", "int", "bool", "date", "list"}
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SchemaError(ValueError):
    """The schema file itself is invalid."""


def load(path: Path | str = DEFAULT_PATH) -> dict:
    """Read and sanity-check the schema. Raises SchemaError on a malformed schema."""
    with open(path, "rb") as f:
        try:
            schema = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise SchemaError(f"{path}: {e}") from e
    if schema.get("version") != 1:
        raise SchemaError("unsupported schema version; expected version = 1")
    fields = schema.get("fields", {})
    for name, kind in fields.items():
        if kind not in KINDS:
            raise SchemaError(f"field {name!r} has unknown kind {kind!r}")
    for name in schema.get("common", []):
        if name not in fields:
            raise SchemaError(f"common field {name!r} is not declared in [fields]")
    types = schema.get("types", {})
    if not types:
        raise SchemaError("no [types.*] tables defined")
    for tname, spec in types.items():
        folder = spec.get("folder", "")
        parts = PurePosixPath(folder).parts
        if not folder or PurePosixPath(folder).is_absolute() or ".." in parts or parts[0] != "wiki":
            raise SchemaError(f"type {tname!r}: folder must be a relative path under wiki/")
        if not spec.get("statuses"):
            raise SchemaError(f"type {tname!r}: statuses must be a non-empty list")
        for name in spec.get("required", []):
            if name not in fields:
                raise SchemaError(f"type {tname!r}: required field {name!r} is not declared in [fields]")
    return schema


def validate(meta: dict, rel_path: str, schema: dict) -> list[str]:
    """Return a list of problems with this page's frontmatter and location; empty means valid."""
    errors: list[str] = []
    tname = meta.get("type")
    spec = schema["types"].get(tname) if isinstance(tname, str) else None
    if spec is None:
        known = ", ".join(sorted(schema["types"]))
        return [f"type {tname!r} is not a known note type ({known})"]

    for name in [*schema.get("common", []), *spec.get("required", [])]:
        if name not in meta:
            errors.append(f"missing required field {name!r}")

    for name, value in meta.items():
        kind = schema["fields"].get(name)
        if kind is not None and name in meta and not _matches(kind, value):
            errors.append(f"field {name!r} should be {kind}, got {value!r}")

    if "status" in meta and meta["status"] not in spec["statuses"]:
        errors.append(f"status {meta['status']!r} not allowed for {tname} ({', '.join(spec['statuses'])})")
    if "generated" in meta and meta["generated"] is not True:
        errors.append("generated must be true on pages Akasha writes")

    errors.extend(_check_path(rel_path, tname, spec))
    return errors


def _matches(kind: str, value) -> bool:
    if kind == "string":
        return isinstance(value, str) and value != ""
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "date":
        if not isinstance(value, str) or not DATE_RE.fullmatch(value):
            return False
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if kind == "list":
        return isinstance(value, list) and all(isinstance(v, (str, int, bool)) for v in value)
    return False


def _check_path(rel_path: str, tname: str, spec: dict) -> list[str]:
    path = PurePosixPath(rel_path)
    if path.is_absolute() or ".." in path.parts:
        return [f"path {rel_path!r} must be relative to the vault and stay inside it"]
    if path.suffix != ".md":
        return [f"path {rel_path!r} must end in .md"]
    folder = PurePosixPath(spec["folder"])
    depth = 2 if spec.get("subfolder") else 1
    if path.parent.parts[: len(folder.parts)] != folder.parts or len(path.parts) != len(folder.parts) + depth:
        where = f"{folder}/<name>/" if depth == 2 else f"{folder}/"
        return [f"{tname} pages belong directly in {where}, not {rel_path!r}"]
    return []
