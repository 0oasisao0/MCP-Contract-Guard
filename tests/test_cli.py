"""End-to-end tests of the public module CLI, not implementation helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-m", "mcp_contract_guard", *(str(arg) for arg in args)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def write_json(tmp_path: Path, name: str, data: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def tool(name: str = "lookup", **changes: object) -> dict:
    result = {
        "name": name,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    }
    result.update(changes)
    return result


def snapshots(tmp_path: Path, before: list[dict], after: list[dict]):
    return (
        write_json(tmp_path, "before.json", {"tools": before}),
        write_json(tmp_path, "after.json", {"tools": after}),
    )


def assert_clean_error(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.strip(), "Configuration errors should have a useful diagnostic"
    assert "Traceback" not in result.stdout + result.stderr


def test_module_help_is_available():
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "compare" in result.stdout
    assert "validate" in result.stdout


@pytest.mark.parametrize("args", [(), ("compare",), ("validate",), ("unknown",)])
def test_usage_errors_have_exit_two(args):
    assert_clean_error(run_cli(*args))


@pytest.mark.parametrize("wrapped", [False, True])
def test_validate_accepts_complete_plain_and_jsonrpc_snapshots(tmp_path, wrapped):
    snapshot = {"tools": [tool()], "nextCursor": None}
    if wrapped:
        snapshot = {"jsonrpc": "2.0", "id": 1, "result": snapshot}
    path = write_json(tmp_path, "snapshot.json", snapshot)
    result = run_cli("validate", path, "--format", "json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["mode"] == "validate"
    assert report["status"] == "pass"
    assert report["summary"]["breaking"] == 0
    assert report["findings"] == []
    assert not result.stderr


def test_unchanged_comparison_passes_with_json_report(tmp_path):
    before, after = snapshots(tmp_path, [tool()], [tool()])
    result = run_cli("compare", before, after, "--format", "json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "compare"
    assert report["status"] == "pass"
    assert report["findings"] == []
    assert not result.stderr


def test_added_tool_passes_default_threshold(tmp_path):
    before, after = snapshots(tmp_path, [tool()], [tool(), tool("new_tool")])
    result = run_cli("compare", before, after)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "threshold, expected", [(None, 1), ("breaking", 1), ("warning", 1), ("none", 0)]
)
def test_removed_tool_obeys_failure_threshold(tmp_path, threshold, expected):
    before, after = snapshots(tmp_path, [tool()], [])
    args = [] if threshold is None else ["--fail-on", threshold]
    result = run_cli("compare", before, after, "--format", "json", *args)
    assert result.returncode == expected, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["breaking"] >= 1
    assert any(f["tool"] == "lookup" and f["severity"] == "breaking" for f in report["findings"])
    assert report["status"] == ("fail" if expected else "pass")


@pytest.mark.parametrize(
    "threshold, expected", [(None, 0), ("breaking", 0), ("warning", 1), ("none", 0)]
)
@pytest.mark.parametrize(
    "field, old, new",
    [
        ("description", "Find an item", "Find the best item"),
        ("annotations", {"readOnlyHint": True}, {"readOnlyHint": False}),
    ],
)
def test_metadata_drift_is_warning_not_breaking(tmp_path, threshold, expected, field, old, new):
    before, after = snapshots(tmp_path, [tool(**{field: old})], [tool(**{field: new})])
    args = [] if threshold is None else ["--fail-on", threshold]
    result = run_cli("compare", before, after, "--format", "json", *args)
    assert result.returncode == expected, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["breaking"] == 0
    assert report["summary"]["warning"] >= 1
    assert report["status"] == ("fail" if expected else "pass")


def test_required_argument_addition_breaks_without_fixtures(tmp_path):
    candidate = tool()
    candidate["inputSchema"]["properties"]["limit"] = {"type": "integer"}
    candidate["inputSchema"]["required"].append("limit")
    before, after = snapshots(tmp_path, [tool()], [candidate])
    result = run_cli("compare", before, after)
    assert result.returncode == 1, result.stdout + result.stderr


def test_saved_input_regression_is_breaking(tmp_path):
    candidate = tool()
    candidate["inputSchema"]["properties"]["query"]["minLength"] = 5
    before, after = snapshots(tmp_path, [tool()], [candidate])
    fixture = write_json(
        tmp_path,
        "cases.json",
        {"cases": [{"id": "short-query", "tool": "lookup", "arguments": {"query": "hi"}}]},
    )
    result = run_cli("compare", before, after, "--fixtures", fixture, "--format", "json")
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["input_regressions"] == 1
    assert report["fixtures"][0]["id"] == "short-query"
    assert report["fixtures"][0]["input"] == {"before": "valid", "after": "invalid"}
    assert any(
        f.get("fixture") == "short-query" and f["severity"] == "breaking"
        for f in report["findings"]
    )


def test_saved_output_mismatch_is_warning_not_input_breakage(tmp_path):
    old = tool(
        outputSchema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 0}},
            "required": ["count"],
        }
    )
    new = tool(
        outputSchema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 10}},
            "required": ["count"],
        }
    )
    before, after = snapshots(tmp_path, [old], [new])
    fixture = write_json(
        tmp_path,
        "cases.json",
        {
            "cases": [
                {
                    "id": "saved-output",
                    "tool": "lookup",
                    "arguments": {"query": "hello"},
                    "structuredContent": {"count": 3},
                }
            ]
        },
    )
    result = run_cli("compare", before, after, "--fixtures", fixture, "--format", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["breaking"] == 0
    assert report["summary"]["output_mismatches"] == 1
    assert report["fixtures"][0]["id"] == "saved-output"
    assert report["fixtures"][0]["input"] == {"before": "valid", "after": "valid"}
    assert report["fixtures"][0]["output"] == {"before": "valid", "after": "invalid"}
    assert any(
        f.get("fixture") == "saved-output" and f["severity"] == "warning"
        for f in report["findings"]
    )
    strict = run_cli("compare", before, after, "--fixtures", fixture, "--fail-on", "warning")
    assert strict.returncode == 1, strict.stdout + strict.stderr


def test_report_determinism_and_no_input_paths(tmp_path):
    old = [tool("zeta"), tool("alpha", description="old")]
    new = [tool("alpha", description="new"), tool("beta")]
    before, after = snapshots(tmp_path, old, new)
    first = run_cli("compare", before, after, "--format", "json")
    second = run_cli("compare", before, after, "--format", "json")
    renamed_before = write_json(tmp_path, "renamed-before.json", {"tools": list(reversed(old))})
    renamed_after = write_json(tmp_path, "renamed-after.json", {"tools": list(reversed(new))})
    reordered = run_cli("compare", renamed_before, renamed_after, "--format", "json")
    assert first.returncode == second.returncode == reordered.returncode == 1
    assert first.stdout == second.stdout == reordered.stdout
    report = json.loads(first.stdout)
    assert str(tmp_path) not in first.stdout
    assert "timestamp" not in report
    assert "generated_at" not in report


def test_json_output_file_contains_report(tmp_path):
    before, after = snapshots(tmp_path, [tool()], [])
    output = tmp_path / "report.json"
    result = run_cli("compare", before, after, "--format", "json", "--output", output)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(report, dict)
    assert "lookup" in json.dumps(report)
    if result.stdout.strip():
        assert json.loads(result.stdout) == report


def test_validate_can_write_json_and_junit_reports(tmp_path):
    snapshot = write_json(tmp_path, "snapshot.json", {"tools": [tool()]})
    output, junit = tmp_path / "report.json", tmp_path / "report.xml"
    result = run_cli("validate", snapshot, "--format", "json", "--output", output, "--junit", junit)
    assert result.returncode == 0, result.stdout + result.stderr
    assert isinstance(json.loads(output.read_text(encoding="utf-8")), dict)
    root = ET.parse(junit).getroot()
    assert root.tag in {"testsuite", "testsuites"}


def test_junit_report_escapes_special_characters(tmp_path):
    candidate = tool()
    candidate["inputSchema"]["properties"]["query"]["minLength"] = 5
    before, after = snapshots(tmp_path, [tool()], [candidate])
    case_id = 'case <one> & "two"'
    fixture = write_json(
        tmp_path,
        "cases.json",
        {"cases": [{"id": case_id, "tool": "lookup", "arguments": {"query": "hi"}}]},
    )
    junit = tmp_path / "report.xml"
    result = run_cli("compare", before, after, "--fixtures", fixture, "--junit", junit)
    assert result.returncode == 1, result.stdout + result.stderr
    root = ET.parse(junit).getroot()
    assert root.tag in {"testsuite", "testsuites"}
    assert list(root.iter("testcase"))
    assert list(root.iter("failure"))
    decoded = ET.tostring(root, encoding="unicode", method="text") + str(
        [node.attrib for node in root.iter()]
    )
    assert case_id in decoded


@pytest.mark.parametrize("option", ["--output", "--junit"])
def test_report_write_failure_is_clean_configuration_error(tmp_path, option):
    snapshot = write_json(tmp_path, "snapshot.json", {"tools": [tool()]})
    # A directory is a portable invalid file destination, including when tests run as root.
    assert_clean_error(run_cli("validate", snapshot, option, tmp_path))


def test_missing_file_is_clean_configuration_error(tmp_path):
    assert_clean_error(run_cli("validate", tmp_path / "missing.json"))


def test_malformed_json_is_clean_configuration_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"tools": [', encoding="utf-8")
    assert_clean_error(run_cli("validate", path))


@pytest.mark.parametrize(
    "snapshot",
    [
        [],
        {},
        {"tools": "not-a-list"},
        {"tools": [tool(), tool()]},
        {"tools": [{"name": "missing-schema"}]},
        {"tools": [tool()], "nextCursor": "next-page"},
        {"tools": [tool()], "nextCursor": ""},
        {"jsonrpc": "2.0", "id": 1, "result": {"tools": [tool()], "nextCursor": "next-page"}},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "failure"}},
    ],
)
def test_invalid_or_partial_snapshot_rejected(tmp_path, snapshot):
    path = write_json(tmp_path, "invalid.json", snapshot)
    assert_clean_error(run_cli("validate", path, "--fail-on", "none"))


@pytest.mark.parametrize(
    "cases",
    [
        {
            "cases": [
                {"id": "duplicate", "tool": "lookup", "arguments": {}},
                {"id": "duplicate", "tool": "lookup", "arguments": {}},
            ]
        },
        {"cases": [{"id": 1, "tool": "lookup", "arguments": {"query": "ok"}}]},
        {"cases": [{"id": "missing-args", "tool": "lookup"}]},
        {"cases": [{"id": "list-args", "tool": "lookup", "arguments": []}]},
        {"cases": [{"id": "unknown-tool", "tool": "absent", "arguments": {}}]},
        {"cases": [{"id": "invalid-before", "tool": "lookup", "arguments": {"query": 12}}]},
        {"cases": "not-a-list"},
    ],
)
def test_invalid_fixture_configuration_rejected(tmp_path, cases):
    before, after = snapshots(tmp_path, [tool()], [tool()])
    fixture = write_json(tmp_path, "invalid-cases.json", cases)
    assert_clean_error(
        run_cli("compare", before, after, "--fixtures", fixture, "--fail-on", "none")
    )


def test_baseline_invalid_saved_output_is_configuration_error(tmp_path):
    item = tool(
        outputSchema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        }
    )
    before, after = snapshots(tmp_path, [item], [item])
    fixture = write_json(
        tmp_path,
        "cases.json",
        {
            "cases": [
                {
                    "id": "invalid-output",
                    "tool": "lookup",
                    "arguments": {"query": "ok"},
                    "structuredContent": {"count": "not-an-integer"},
                }
            ]
        },
    )
    assert_clean_error(run_cli("compare", before, after, "--fixtures", fixture))
