"""Directional risk rules, not a general JSON Schema subsumption prover."""

import json
from decimal import Decimal
from typing import Any

from .loading import ARRAY_SCHEMAS, MAP_SCHEMAS, SINGLE_SCHEMAS
from .models import Finding, Report, pointer

ANNOTATIONS = {
    "title",
    "description",
    "default",
    "examples",
    "$comment",
    "deprecated",
    "readOnly",
    "writeOnly",
}
SUPPORTED = {
    "type",
    "enum",
    "const",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
    "uniqueItems",
    "$schema",
}
LOWER_BOUNDS = {"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"}
UPPER_BOUNDS = {"maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"}
ALL_TYPES = {"null", "boolean", "object", "array", "string", "integer", "fractional"}


def _json_key(value: Any) -> str:
    def decimal_key(number):
        if isinstance(number, Decimal):
            return (
                int(number)
                if number == number.to_integral_value()
                else {"decimal": format(number, "f").rstrip("0").rstrip(".")}
            )
        raise TypeError("Unsupported non-JSON schema value")

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=decimal_key
    )


def _semantic(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key in ANNOTATIONS or key == "$schema":
            continue
        if key in MAP_SCHEMAS and isinstance(value, dict):
            value = {name: _semantic(child) for name, child in value.items()}
        elif key in SINGLE_SCHEMAS:
            value = _semantic(value)
        elif key in ARRAY_SCHEMAS and isinstance(value, list):
            value = [_semantic(child) for child in value]
        elif key in {"required", "enum", "type"} and isinstance(value, list):
            value = sorted(value, key=_json_key)
        result[key] = value
    return result


def _metadata(schema: Any, path: tuple = ()) -> dict[tuple, Any]:
    result = {}
    if not isinstance(schema, dict):
        return result
    for key, value in schema.items():
        if key in ANNOTATIONS:
            result[path + (key,)] = value
        elif key in MAP_SCHEMAS and isinstance(value, dict):
            for name, child in value.items():
                result.update(_metadata(child, path + (key, name)))
        elif key in SINGLE_SCHEMAS:
            result.update(_metadata(value, path + (key,)))
        elif key in ARRAY_SCHEMAS and isinstance(value, list):
            for index, child in enumerate(value):
                result.update(_metadata(child, path + (key, index)))
    return result


def _equal(a: Any, b: Any) -> bool:
    # JSON booleans must not compare equal to integers, unlike Python's equality.
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b, strict=False))
    return a == b


def _contains(values: list[Any], value: Any) -> bool:
    return any(_equal(v, value) for v in values)


def _types(schema: dict) -> set[str]:
    types = schema.get("type")
    if types is None:
        return ALL_TYPES.copy()
    result = {types} if isinstance(types, str) else set(types)
    if "number" in result:
        result.remove("number")
        result |= {"integer", "fractional"}
    return result


class SchemaDiffer:
    def __init__(self, report: Report, tool: str, direction: str):
        self.report, self.tool, self.direction = report, tool, direction

    def emit(self, severity: str, code: str, path: tuple, message: str) -> None:
        self.report.findings.append(Finding(severity, code, self.tool, pointer(path), message))

    def relation(self, narrowed: bool, widened: bool, path: tuple, subject: str) -> None:
        if not narrowed and not widened:
            return
        risk = narrowed if self.direction == "input" else widened
        if risk:
            message = (
                f"{subject}: accepted inputs may narrow. Review existing callers."
                if self.direction == "input"
                else f"{subject}: possible outputs may widen beyond the previous guarantee."
            )
            self.emit("breaking", f"{self.direction}.schema_risk", path, message)
        else:
            self.emit(
                "info",
                f"{self.direction}.schema_relaxed",
                path,
                f"{subject}: change is in the compatible direction for this rule.",
            )

    def compare(self, before: Any, after: Any, path: tuple) -> None:
        old_metadata, new_metadata = _metadata(before), _metadata(after)
        missing = object()
        for key in sorted(old_metadata.keys() | new_metadata.keys(), key=str):
            if not _equal(old_metadata.get(key, missing), new_metadata.get(key, missing)):
                self.emit(
                    "warning",
                    "schema.annotation_changed",
                    path + key,
                    "Schema guidance changed; review agent behavior and defaults.",
                )
        self._compare(_semantic(before), _semantic(after), path)

    def _compare(self, before: Any, after: Any, path: tuple) -> None:
        if _equal(before, after):
            return
        if before is True:
            before = {}
        if after is True:
            after = {}
        if _equal(before, after):
            return
        if before is False or after is False:
            self.relation(after is False, before is False, path, "Boolean schema changed")
            return
        unsupported = (set(before) | set(after)) - SUPPORTED
        if unsupported:
            self.emit(
                "warning",
                "schema.review_required",
                path,
                "Schema uses constraints outside the directional diff subset; review this edit.",
            )
            return
        self.relation(
            bool(_types(before) - _types(after)),
            bool(_types(after) - _types(before)),
            path + ("type",),
            "Allowed types changed",
        )
        old_values = [before["const"]] if "const" in before else before.get("enum")
        new_values = [after["const"]] if "const" in after else after.get("enum")
        if old_values is not None or new_values is not None:
            # enum and const together can interact; do not pretend to simplify intersections.
            if ("const" in before and "enum" in before) or ("const" in after and "enum" in after):
                self.emit(
                    "warning",
                    "schema.review_required",
                    path,
                    "Combined const and enum constraints require review.",
                )
            else:
                narrowed = new_values is not None and (
                    old_values is None or any(not _contains(new_values, v) for v in old_values)
                )
                widened = old_values is not None and (
                    new_values is None or any(not _contains(old_values, v) for v in new_values)
                )
                self.relation(narrowed, widened, path + ("enum",), "Allowed values changed")
        for keyword in sorted(LOWER_BOUNDS | UPPER_BOUNDS):
            old, new = before.get(keyword), after.get(keyword)
            if old == new:
                continue
            tighter = new is not None and (
                old is None or (new > old if keyword in LOWER_BOUNDS else new < old)
            )
            looser = old is not None and (
                new is None or (new < old if keyword in LOWER_BOUNDS else new > old)
            )
            self.relation(tighter, looser, path + (keyword,), "A validation bound changed")
        old_unique, new_unique = before.get("uniqueItems", False), after.get("uniqueItems", False)
        self.relation(
            not old_unique and new_unique,
            old_unique and not new_unique,
            path + ("uniqueItems",),
            "Array uniqueness changed",
        )
        old_required, new_required = set(before.get("required", [])), set(after.get("required", []))
        for name in sorted(old_required ^ new_required):
            self.relation(
                name in new_required,
                name in old_required,
                path + ("required", name),
                "Required property changed",
            )
        old_props, new_props = before.get("properties", {}), after.get("properties", {})
        old_extra, new_extra = (
            before.get("additionalProperties", True),
            after.get("additionalProperties", True),
        )
        # Treat each named property using its effective old/new extra-property schema.
        for name in sorted(old_props.keys() | new_props.keys()):
            self._compare(
                old_props.get(name, old_extra),
                new_props.get(name, new_extra),
                path + ("properties", name),
            )
        self._compare(old_extra, new_extra, path + ("additionalProperties",))
        if "items" in before or "items" in after:
            self._compare(before.get("items", True), after.get("items", True), path + ("items",))


def compare_tools(before: dict[str, dict], after: dict[str, dict]) -> Report:
    report = Report("compare")
    for name in sorted(before.keys() - after.keys()):
        report.findings.append(Finding("breaking", "tool.removed", name, "", "Tool was removed."))
    for name in sorted(after.keys() - before.keys()):
        report.findings.append(Finding("info", "tool.added", name, "", "Tool was added."))
    for name in sorted(before.keys() & after.keys()):
        old, new = before[name], after[name]
        missing = object()
        for key in sorted((old.keys() | new.keys()) - {"name", "inputSchema", "outputSchema"}):
            if not _equal(old.get(key, missing), new.get(key, missing)):
                report.findings.append(
                    Finding(
                        "warning",
                        "tool.metadata_changed",
                        name,
                        pointer((key,)),
                        "Tool metadata changed; review behavior. "
                        "Annotations are not security guarantees.",
                    )
                )
        SchemaDiffer(report, name, "input").compare(
            old["inputSchema"], new["inputSchema"], ("inputSchema",)
        )
        if "outputSchema" in old and "outputSchema" not in new:
            report.findings.append(
                Finding(
                    "breaking",
                    "output.schema_removed",
                    name,
                    "/outputSchema",
                    "The declared structured-output guarantee was removed.",
                )
            )
        elif "outputSchema" not in old and "outputSchema" in new:
            report.findings.append(
                Finding(
                    "info",
                    "output.schema_added",
                    name,
                    "/outputSchema",
                    "A structured-output schema was added; review runtime compliance.",
                )
            )
        elif "outputSchema" in old:
            SchemaDiffer(report, name, "output").compare(
                old["outputSchema"], new["outputSchema"], ("outputSchema",)
            )
    return report
