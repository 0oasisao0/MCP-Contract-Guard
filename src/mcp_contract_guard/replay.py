"""Replay saved data through local validators, never through tools or servers."""

import re
from itertools import islice
from typing import Any

from jsonschema.exceptions import ValidationError
from referencing.exceptions import Unresolvable

from .loading import prepare_schema
from .models import Finding, InputError, Report, pointer


def _errors(validator: Any, instance: Any) -> list[ValidationError]:
    try:
        # Bound report growth; validity only needs the first error. Multiple paths aid debugging.
        return list(islice(validator.iter_errors(instance), 20))
    except (Unresolvable, RecursionError, re.error, TypeError, ValueError, ArithmeticError):
        raise InputError(
            "Schema evaluation failed; check references, patterns, and recursion depth."
        ) from None


def replay(
    report: Report,
    before: dict[str, dict],
    after: dict[str, dict],
    cases: list[dict[str, Any]],
) -> None:
    cache = {}

    def validator(side: str, name: str, field: str) -> Any:
        key = (side, name, field)
        if key not in cache:
            tools = before if side == "before" else after
            cache[key] = prepare_schema(tools[name][field], input_schema=field == "inputSchema")
        return cache[key]

    for case in sorted(cases, key=lambda c: (c["tool"], c["id"])):
        name, case_id = case["tool"], case["id"]
        if name not in before:
            raise InputError("Fixture references a tool absent from the baseline snapshot.")
        if _errors(validator("before", name, "inputSchema"), case["arguments"]):
            raise InputError(
                "Baseline fixture arguments are invalid; fix the capture before comparing."
            )
        output_before = "not_provided"
        if "structuredContent" in case:
            output_before = "no_schema"
            if "outputSchema" in before[name]:
                if _errors(validator("before", name, "outputSchema"), case["structuredContent"]):
                    raise InputError(
                        "Baseline fixture structuredContent is invalid; fix the capture."
                    )
                output_before = "valid"
        result = {
            "id": case_id,
            "tool": name,
            "input": {"before": "valid", "after": "valid"},
            "output": {"before": output_before, "after": "not_provided"},
        }
        if name not in after:
            result["input"]["after"] = "missing_tool"
            result["output"]["after"] = "missing_tool"
            report.findings.append(
                Finding(
                    "breaking",
                    "fixture.tool_removed",
                    name,
                    "",
                    "A saved call targets a removed tool.",
                    case_id,
                )
            )
        else:
            errors = _errors(validator("after", name, "inputSchema"), case["arguments"])
            if errors:
                result["input"]["after"] = "invalid"
                for error in errors:
                    report.findings.append(
                        Finding(
                            "breaking",
                            "fixture.input_regression",
                            name,
                            "/arguments" + pointer(tuple(error.absolute_path)),
                            "Previously valid saved arguments fail candidate validation "
                            f"({error.validator}); values omitted.",
                            case_id,
                        )
                    )
            if "structuredContent" in case:
                result["output"]["after"] = "no_schema"
                if "outputSchema" in after[name]:
                    errors = _errors(
                        validator("after", name, "outputSchema"), case["structuredContent"]
                    )
                    result["output"]["after"] = "invalid" if errors else "valid"
                    for error in errors:
                        report.findings.append(
                            Finding(
                                "warning",
                                "fixture.output_mismatch",
                                name,
                                "/structuredContent" + pointer(tuple(error.absolute_path)),
                                "Saved output fails the candidate schema; "
                                "review the capture/server. "
                                "This alone does not prove a backward-compatibility regression "
                                f"({error.validator}); values omitted.",
                                case_id,
                            )
                        )
        report.fixtures.append(result)
