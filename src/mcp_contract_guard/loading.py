"""Strict file parsing and offline schema preparation."""

import json
import math
import re
from collections.abc import Iterator
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote_to_bytes

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

from .models import InputError, pointer
from .validation import GuardValidator

MAX_BYTES = 16 * 1024 * 1024
MAX_CASES = 10_000
DIALECT = "https://json-schema.org/draft/2020-12/schema"
MAP_SCHEMAS = {"$defs", "definitions", "properties", "patternProperties", "dependentSchemas"}
SINGLE_SCHEMAS = {
    "additionalProperties",
    "unevaluatedProperties",
    "propertyNames",
    "items",
    "contains",
    "unevaluatedItems",
    "not",
    "if",
    "then",
    "else",
    "contentSchema",
}
ARRAY_SCHEMAS = {"allOf", "anyOf", "oneOf", "prefixItems"}


def _deny_remote(uri: str) -> Any:
    raise NoSuchResource(ref=uri)


OFFLINE_REGISTRY: Registry = Registry(retrieve=_deny_remote)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("JSON contains a duplicate object key.")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise InputError("JSON contains a non-finite number.")


def _float(value: str) -> int | Decimal:
    probe = float(value)
    result = Decimal(value)
    if not math.isfinite(probe):
        raise InputError("JSON contains a non-finite or out-of-range number.")
    if probe == 0 and result != 0:
        raise InputError("JSON decimal magnitude is too small for the supported numeric profile.")
    # Avoid binary64 rounding inventing a baseline-valid/candidate-invalid witness.
    # Integral decimal literals become ints so JSON Schema's integer type works.
    return int(result) if result == result.to_integral_value() else result


def read_json(path: str | Path) -> Any:
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise InputError("Input file exceeds the 16 MiB limit.")
        return json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        # jsonschema/json decoders may embed whole payloads in errors: never forward them.
        raise InputError(
            "Cannot read input: use a readable file containing valid UTF-8 JSON."
        ) from None


def _schema_locations(
    schema: Any, path: tuple[str | int, ...] = ()
) -> Iterator[tuple[tuple[str | int, ...], Any]]:
    """Track locations, including booleans, without treating instance data as schemas."""
    if not isinstance(schema, (dict, bool)):
        return
    yield path, schema
    if isinstance(schema, bool):
        return
    for key, value in schema.items():
        if key in MAP_SCHEMAS and isinstance(value, dict):
            for name, child in value.items():
                yield from _schema_locations(child, path + (key, name))
        elif key in SINGLE_SCHEMAS:
            yield from _schema_locations(value, path + (key,))
        elif key in ARRAY_SCHEMAS and isinstance(value, list):
            for index, child in enumerate(value):
                yield from _schema_locations(child, path + (key, index))


def schema_nodes(schema: Any) -> Iterator[dict[str, Any]]:
    """Visit only object-valued schema positions, not const/default/examples payloads."""
    for _, node in _schema_locations(schema):
        if isinstance(node, dict):
            yield node


def _local_ref_path(
    schema: Any, ref: str, anchors: dict[str, tuple[str | int, ...]]
) -> tuple[str | int, ...]:
    """Validate RFC 6901 syntax before the resolver's permissive Python indexing."""
    fragment = ref[1:]
    if re.search(r"%(?![0-9A-Fa-f]{2})", fragment):
        raise InputError("Invalid percent escape in local schema reference.")
    fragment = unquote_to_bytes(fragment).decode("utf-8", errors="strict")
    if not fragment:
        return ()
    if not fragment.startswith("/"):
        if fragment not in anchors:
            raise InputError("Unresolved local schema anchor.")
        return anchors[fragment]
    target, path = schema, ()
    for token in fragment[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise InputError("Invalid JSON Pointer escape in local schema reference.")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(target, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise InputError("Invalid JSON Pointer array index in local schema reference.")
            index = int(token)
            if index >= len(target):
                raise InputError("Unresolved local schema reference.")
            target, path = target[index], path + (index,)
        elif isinstance(target, dict):
            if token not in target:
                raise InputError("Unresolved local schema reference.")
            target, path = target[token], path + (token,)
        else:
            raise InputError("Unresolved local schema reference.")
    return path


def prepare_schema(schema: Any, *, input_schema: bool = False) -> Draft202012Validator:
    if not isinstance(schema, (dict, bool)) or (input_schema and not isinstance(schema, dict)):
        raise InputError("A schema must be an object (output schemas may also be booleans).")
    try:
        Draft202012Validator.check_schema(schema)
        locations = dict(_schema_locations(schema))
        anchors = {}
        for path, node in locations.items():
            if not isinstance(node, dict):
                continue
            if "$schema" in node and node["$schema"] not in {DIALECT, DIALECT + "#"}:
                raise InputError("Only JSON Schema draft 2020-12 is supported.")
            # Nested resource IDs change scope; keep the offline subset explicit.
            if "$id" in node:
                raise InputError(
                    "Schema $id resources are unsupported; use fragment-only references."
                )
            for keyword in ("$ref", "$dynamicRef"):
                if keyword in node and not node[keyword].startswith("#"):
                    raise InputError(
                        "External schema references are disabled; use local fragments."
                    )
            if "$dynamicRef" in node:
                raise InputError("Dynamic schema references are unsupported.")
            for keyword in ("$anchor", "$dynamicAnchor"):
                if keyword in node:
                    if node[keyword] in anchors:
                        raise InputError("Local schema anchor names must be unique.")
                    anchors[node[keyword]] = path
        # Validate all references, even branches no fixture exercises. Rewriting
        # them to canonical pointers avoids permissive/variant URI parsing in
        # dependencies while preserving the already-validated local target.
        canonical_refs = {}
        for path, node in locations.items():
            if isinstance(node, dict) and "$ref" in node:
                target = _local_ref_path(schema, node["$ref"], anchors)
                if target not in locations:
                    raise InputError("A local schema reference targets a non-schema location.")
                canonical_refs[path] = "#" + quote(pointer(target), safe="/~")
        evaluated = deepcopy(schema)
        for path, node in _schema_locations(evaluated):
            if isinstance(node, dict):
                # The only allowed dialect is already checked above. Removing its
                # declaration prevents evolve() switching to a stock evaluator
                # and bypassing our exact decimal multipleOf implementation.
                node.pop("$schema", None)
                if path in canonical_refs:
                    node["$ref"] = canonical_refs[path]
        registry = OFFLINE_REGISTRY.with_resource(
            "", Resource.from_contents(evaluated, default_specification=DRAFT202012)
        )
        return GuardValidator(evaluated, registry=registry)
    except InputError:
        raise
    except (SchemaError, Unresolvable, RecursionError, TypeError, ValueError, KeyError):
        raise InputError("Invalid schema or unresolved local reference.") from None


def load_snapshot(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        raise InputError("Snapshot must be an object containing tools.")
    if "result" in data:
        if "error" in data or not isinstance(data["result"], dict):
            raise InputError("Snapshot must contain a successful tools/list result.")
        data = data["result"]
    if data.get("nextCursor") is not None:
        raise InputError("Snapshot is paginated; merge every page and remove nextCursor first.")
    if not isinstance(data.get("tools"), list):
        raise InputError("Snapshot must contain a tools array.")
    result = {}
    for tool in data["tools"]:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"]:
            raise InputError("Each tool requires a nonempty name.")
        if tool["name"] in result:
            raise InputError("Snapshot contains duplicate tool names.")
        if "inputSchema" not in tool:
            raise InputError("Each tool requires inputSchema.")
        for key in ("title", "description"):
            if key in tool and not isinstance(tool[key], str):
                raise InputError("Tool title and description must be strings.")
        if "annotations" in tool:
            annotations = tool["annotations"]
            if not isinstance(annotations, dict):
                raise InputError("Tool annotations must be an object.")
            for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                if key in annotations and not isinstance(annotations[key], bool):
                    raise InputError("Standard tool annotation hints must be booleans.")
        prepare_schema(tool["inputSchema"], input_schema=True)
        if "outputSchema" in tool:
            prepare_schema(tool["outputSchema"])
        result[tool["name"]] = tool
    return result


def load_fixtures(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise InputError("Fixtures must be an object containing a cases array.")
    if len(data["cases"]) > MAX_CASES:
        raise InputError("Fixture file exceeds the 10,000 case limit.")
    seen = set()
    for case in data["cases"]:
        if not isinstance(case, dict):
            raise InputError("Each fixture case must be an object.")
        for key in ("id", "tool"):
            if not isinstance(case.get(key), str) or not case[key]:
                raise InputError("Each fixture requires a nonempty id and tool.")
        if case["id"] in seen:
            raise InputError("Fixture case IDs must be unique.")
        seen.add(case["id"])
        if not isinstance(case.get("arguments"), dict):
            raise InputError("Each fixture requires an arguments object.")
        if set(case) - {"id", "tool", "arguments", "structuredContent"}:
            raise InputError(
                "Unknown fixture field; expected id, tool, arguments, structuredContent."
            )
    return data["cases"]
