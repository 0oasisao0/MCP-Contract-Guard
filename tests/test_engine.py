"""Directional rule tests use finite acceptance checks, not compatibility claims."""

import json
from copy import deepcopy

import pytest

from mcp_contract_guard.cli import main
from mcp_contract_guard.diffing import SchemaDiffer, _equal, compare_tools
from mcp_contract_guard.loading import (
    InputError,
    load_fixtures,
    load_snapshot,
    prepare_schema,
    read_json,
)
from mcp_contract_guard.models import Finding, Report, pointer
from mcp_contract_guard.replay import replay
from mcp_contract_guard.reporting import render_json, render_junit, render_text, write_report


def analyze(before, after, direction="input"):
    report = Report("compare")
    SchemaDiffer(report, "example", direction).compare(before, after, (direction + "Schema",))
    return report


def tools(input_schema=None, output_schema=None):
    tool = {"name": "example", "inputSchema": input_schema or {"type": "object"}}
    if output_schema is not None:
        tool["outputSchema"] = output_schema
    return {"example": tool}


# Every pair below is an explicit, independently checkable narrowing step.
NARROWINGS = [
    ({}, {"type": "string"}),
    ({"type": "number"}, {"type": "integer"}),
    ({"type": ["string", "null"]}, {"type": "string"}),
    ({"enum": ["a", "b"]}, {"enum": ["a"]}),
    ({}, {"enum": ["a"]}),
    ({"enum": ["a", "b"]}, {"const": "a"}),
    ({}, {"const": None}),
    ({"minimum": 0}, {"minimum": 1}),
    ({}, {"minimum": 1}),
    ({"maximum": 10}, {"maximum": 9}),
    ({}, {"maximum": 9}),
    ({"exclusiveMinimum": 0}, {"exclusiveMinimum": 1}),
    ({"exclusiveMaximum": 10}, {"exclusiveMaximum": 9}),
    ({"minLength": 0}, {"minLength": 1}),
    ({"maxLength": 10}, {"maxLength": 9}),
    ({"minItems": 0}, {"minItems": 1}),
    ({"maxItems": 10}, {"maxItems": 9}),
    ({"minProperties": 0}, {"minProperties": 1}),
    ({"maxProperties": 10}, {"maxProperties": 9}),
    ({"uniqueItems": False}, {"uniqueItems": True}),
    ({}, {"required": ["a"]}),
    ({"additionalProperties": True}, {"additionalProperties": False}),
    ({}, {"properties": {"a": {"type": "string"}}}),
    (
        {"properties": {"a": {"type": "string"}}},
        {"properties": {"a": {"type": "string", "minLength": 2}}},
    ),
    ({"properties": {"a": {}}, "additionalProperties": False}, {"additionalProperties": False}),
    ({"items": {}}, {"items": {"type": "string"}}),
    (True, False),
    ({}, False),
    ({"additionalProperties": {"type": "number"}}, {"additionalProperties": {"type": "integer"}}),
]


@pytest.mark.parametrize("before,after", NARROWINGS)
@pytest.mark.parametrize(
    "direction,reverse,breaking",
    [
        ("input", False, True),
        ("input", True, False),
        ("output", False, False),
        ("output", True, True),
    ],
)
def test_variance(before, after, direction, reverse, breaking):
    if reverse:
        before, after = after, before
    result = analyze(before, after, direction)
    assert result.failed() is breaking
    assert not any(f.severity == "warning" for f in result.findings)
    assert result.findings


@pytest.mark.parametrize(
    "before,after",
    [
        ({"type": ["string", "null"]}, {"type": ["null", "string"]}),
        ({"required": ["a", "b"]}, {"required": ["b", "a"]}),
        ({"enum": ["a", "b"]}, {"enum": ["b", "a"]}),
        ({"enum": [1]}, {"enum": [1.0]}),
        ({}, True),
        ({"type": "number"}, {"type": ["number", "integer"]}),
        ({"additionalProperties": True}, {}),
        ({"uniqueItems": False}, {}),
        ({}, {"$schema": "https://json-schema.org/draft/2020-12/schema"}),
    ],
)
def test_equivalent_edits_have_no_findings(before, after):
    assert analyze(before, after).findings == []


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("description", "new guidance"),
        ("default", "private-value"),
        ("examples", ["private"]),
        ("deprecated", True),
        ("title", "New"),
        ("readOnly", True),
        ("writeOnly", True),
        ("$comment", "internal"),
    ],
)
def test_schema_annotations_are_review_only_and_redacted(keyword, value):
    report = analyze({"type": "string"}, {"type": "string", keyword: value})
    assert not report.failed()
    assert report.failed("warning")
    assert report.findings[0].code == "schema.annotation_changed"
    assert "private" not in render_json(report, "warning")


@pytest.mark.parametrize(
    "schema",
    [
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        {"allOf": [{"type": "string"}]},
        {"oneOf": [{"type": "string"}, {"type": "number"}]},
        {"not": {"type": "null"}},
        {"pattern": "^a"},
        {"if": {"type": "string"}, "then": {"minLength": 2}},
        {"format": "email"},
        {"multipleOf": 2},
        {"unevaluatedProperties": False},
        {"dependentRequired": {"a": ["b"]}},
        {"prefixItems": [{"type": "string"}]},
        {"x-custom-constraint": 3},
        {"$defs": {"a": {"type": "string"}}, "$ref": "#/$defs/a"},
    ],
)
def test_complex_edits_require_review(schema):
    report = analyze({}, schema)
    assert not report.failed()
    assert report.failed("warning")
    assert report.findings[0].code == "schema.review_required"
    assert analyze(schema, deepcopy(schema)).findings == []


def test_annotations_inside_arrays_and_definitions():
    before = {"allOf": [{"type": "string"}], "$defs": {"a": {"type": "number"}}}
    after = deepcopy(before)
    after["allOf"][0]["description"] = "text"
    after["$defs"]["a"]["default"] = 5
    report = analyze(before, after)
    assert len(report.findings) == 2
    assert all(f.code == "schema.annotation_changed" for f in report.findings)


def test_boolean_not_equal_to_integer_even_nested():
    assert not _equal(True, 1)
    assert not _equal({"a": [True]}, {"a": [1]})
    report = analyze({"enum": [True]}, {"enum": [1]})
    assert report.failed()


def test_enum_and_const_intersection_is_reviewed():
    assert analyze({"const": 1, "enum": [1, 2]}, {"const": 1, "enum": [1]}).failed("warning")


def test_optional_property_addition_to_closed_object_is_safe_but_open_is_not():
    assert not analyze(
        {"additionalProperties": False},
        {"additionalProperties": False, "properties": {"limit": {"type": "integer"}}},
    ).failed()
    assert analyze({}, {"properties": {"limit": {"type": "integer"}}}).failed()


def test_tool_changes_and_output_schema_presence():
    report = compare_tools(tools(), {})
    assert report.findings[0].code == "tool.removed"
    assert compare_tools({}, tools()).findings[0].code == "tool.added"
    assert compare_tools(tools(output_schema={"type": "array"}), tools()).failed()
    assert not compare_tools(tools(), tools(output_schema={"type": "array"})).failed()
    before, after = tools(), tools()
    after["example"]["annotations"] = {"readOnlyHint": True}
    assert compare_tools(before, after).failed("warning")


def test_replay_witness_and_output_mismatch_have_distinct_severity():
    before = tools({"type": "object"}, {"type": "number"})
    after = tools({"type": "object", "required": ["query"]}, {"type": "integer"})
    report = compare_tools(before, after)
    replay(
        report,
        before,
        after,
        [{"id": "c1", "tool": "example", "arguments": {}, "structuredContent": 2.5}],
    )
    assert report.as_dict()["summary"]["input_regressions"] == 1
    assert report.as_dict()["summary"]["output_mismatches"] == 1
    assert any(
        f.severity == "breaking" and f.code == "fixture.input_regression" for f in report.findings
    )
    assert any(
        f.severity == "warning" and f.code == "fixture.output_mismatch" for f in report.findings
    )


@pytest.mark.parametrize("value", [None, False, 2, 2.5, "hello", [], [1, None], {"a": 1}])
def test_any_json_output_replay(value):
    baseline = tools(output_schema=True)
    report = Report("validate")
    replay(
        report,
        baseline,
        baseline,
        [{"id": "c", "tool": "example", "arguments": {}, "structuredContent": value}],
    )
    assert report.fixtures[0]["output"] == {"before": "valid", "after": "valid"}


def test_removed_tool_impact_and_no_output_schema():
    baseline = tools()
    cases = [{"id": "c", "tool": "example", "arguments": {}, "structuredContent": None}]
    report = compare_tools(baseline, {})
    replay(report, baseline, {}, cases)
    assert report.as_dict()["summary"]["input_regressions"] == 1
    assert report.fixtures[0]["output"]["before"] == "no_schema"
    report = Report("validate")
    replay(report, baseline, baseline, cases)
    assert report.fixtures[0]["output"]["after"] == "no_schema"


@pytest.mark.parametrize(
    "cases",
    [
        [{"id": "c", "tool": "missing", "arguments": {}}],
        [{"id": "c", "tool": "example", "arguments": {"query": 42}}],
        [{"id": "c", "tool": "example", "arguments": {}, "structuredContent": False}],
    ],
)
def test_baseline_invalid_cases_raise_input_error(cases):
    baseline = tools(
        {"type": "object", "properties": {"query": {"type": "string"}}}, {"type": "string"}
    )
    with pytest.raises(InputError, match="[Bb]aseline"):
        replay(Report("compare"), baseline, baseline, cases)


def test_recursive_schema_evaluation_is_controlled():
    baseline = tools({"$ref": "#"})
    with pytest.raises(InputError, match="evaluation failed"):
        replay(
            Report("validate"),
            baseline,
            baseline,
            [{"id": "c", "tool": "example", "arguments": {}}],
        )


def test_errors_are_capped_and_counts_are_per_case():
    props = {f"p{i}": {"type": "string"} for i in range(100)}
    baseline, candidate = tools(), tools({"type": "object", "properties": props})
    report = Report("compare")
    replay(
        report,
        baseline,
        candidate,
        [{"id": "c", "tool": "example", "arguments": {name: 1 for name in props}}],
    )
    assert len(report.findings) == 20
    assert report.as_dict()["summary"]["input_regressions"] == 1


def test_report_sorting_deduplication_and_xml_control_characters():
    report = Report("compare")
    f = Finding("warning", "code", "tool<&\x00", "/p", "message", "fixture<&\x1b")
    report.findings = [f, f]
    assert len(report.as_dict()["findings"]) == 1
    assert report.failed("none") is False
    text = render_text(report, "warning")
    assert "\x1b" not in text and "\\u001b" in text
    import xml.etree.ElementTree as ET

    xml = ET.fromstring(render_junit(report, "warning"))
    assert xml.attrib["failures"] == "1"
    assert xml.attrib["tests"] == "1"
    assert ET.fromstring(render_junit(Report("compare"), "breaking")).attrib["tests"] == "1"


def test_pointer_escaping():
    assert pointer(("a/b", "c~d", 0)) == "/a~1b/c~0d/0"


def test_writing_reports(tmp_path):
    target = tmp_path / "report.json"
    write_report(str(target), "first")
    write_report(str(target), "second")
    assert target.read_text() == "second"
    assert list(tmp_path.glob(".mcp-guard-*")) == []
    with pytest.raises(InputError, match="Cannot write"):
        write_report(str(tmp_path / "absent" / "result"), "data")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "bad"},
        {"$schema": "http://json-schema.org/draft-07/schema#"},
        {"$ref": "https://example.invalid/schema"},
        {"$ref": "#/$defs/absent"},
        {"$id": "https://example.invalid/local"},
        {"$dynamicRef": "#local"},
        {"$ref": "#/default", "default": {"type": "string"}},
        {"$ref": "#/default", "default": 42},
    ],
)
def test_invalid_or_unsupported_schema(schema):
    with pytest.raises(InputError):
        prepare_schema(schema)


def test_schema_walk_does_not_treat_data_as_schema():
    schema = {
        "const": {"$ref": "https://example.invalid/not-a-schema"},
        "examples": [{"$id": "https://example.invalid"}],
    }
    validator = prepare_schema(schema)
    assert validator.is_valid({"$ref": "https://example.invalid/not-a-schema"})


def test_local_anchor_and_fragment_reference():
    validator = prepare_schema({"$defs": {"x": {"$anchor": "x", "type": "string"}}, "$ref": "#x"})
    assert validator.is_valid("ok")
    assert not validator.is_valid(1)


def test_load_limits_and_nonfinite(tmp_path, monkeypatch):
    from mcp_contract_guard import loading

    path = tmp_path / "data.json"
    monkeypatch.setattr(loading, "MAX_BYTES", 10)
    path.write_text(" " * 11)
    with pytest.raises(InputError, match="limit"):
        read_json(path)
    monkeypatch.setattr(loading, "MAX_CASES", 1)
    with pytest.raises(InputError, match="limit"):
        load_fixtures({"cases": [{}, {}]})
    path.write_text("1e9999")
    with pytest.raises(InputError, match="non-finite"):
        read_json(path)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"tools": None},
        {"tools": [{}]},
        {"tools": [{"name": ""}]},
        {"tools": [{"name": "t"}]},
        {"result": [], "error": {}},
        {"tools": [{"name": "t", "inputSchema": {}, "title": 1}]},
        {"tools": [{"name": "t", "inputSchema": {}, "annotations": None}]},
        {"tools": [{"name": "t", "inputSchema": {}, "annotations": {"readOnlyHint": 1}}]},
        {"tools": [], "nextCursor": "next"},
        {"tools": [{"name": "t", "inputSchema": {}}, {"name": "t", "inputSchema": {}}]},
    ],
)
def test_invalid_snapshots(data):
    with pytest.raises(InputError):
        load_snapshot(data)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"cases": None},
        {"cases": [None]},
        {"cases": [{}]},
        {"cases": [{"id": "c", "tool": "t", "arguments": []}]},
        {"cases": [{"id": "c", "tool": "t", "arguments": {}, "extra": True}]},
        {"cases": [{"id": "c", "tool": "t", "arguments": {}}] * 2},
    ],
)
def test_invalid_fixtures(data):
    with pytest.raises(InputError):
        load_fixtures(data)


def test_cli_in_process_paths_and_errors(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({"tools": list(tools().values())}))
    candidate.write_text('{"tools": []}')
    assert main(["compare", str(baseline), str(candidate), "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"
    report = tmp_path / "report.json"
    junit = tmp_path / "report.xml"
    assert (
        main(
            [
                "validate",
                str(baseline),
                "--format",
                "json",
                "--output",
                str(report),
                "--junit",
                str(junit),
            ]
        )
        == 0
    )
    assert json.loads(report.read_text())["status"] == "pass"
    assert main(["validate", str(baseline), "--output", str(baseline)]) == 2
    assert main(["validate", str(tmp_path / "missing")]) == 2
    assert "Traceback" not in capsys.readouterr().err
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text('{"cases": [{"id":"c","tool":"example","arguments":{}}]}')
    assert main(["validate", str(baseline), "--fixtures", str(fixtures)]) == 0


def test_cli_generic_io_exception_is_sanitized(monkeypatch, capsys):
    from mcp_contract_guard import cli

    def fail(_):
        raise OSError("PRIVATE_PAYLOAD")

    monkeypatch.setattr(cli, "read_json", fail)
    assert main(["validate", "any.json"]) == 2
    assert "PRIVATE_PAYLOAD" not in capsys.readouterr().err
