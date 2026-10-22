"""Offline schema resolution and diagnostic redaction regression tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "PRIVATE_FIXTURE_VALUE_42_do_not_emit"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


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


def write_json(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def snapshot(tmp_path: Path, name: str, schema: dict, output: dict | None = None) -> Path:
    item = {"name": "lookup", "inputSchema": schema}
    if output is not None:
        item["outputSchema"] = output
    return write_json(tmp_path, name, {"tools": [item]})


def assert_error(result):
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.strip()
    assert "Traceback" not in result.stdout + result.stderr
    assert SECRET not in result.stdout + result.stderr


@contextmanager
def local_schema_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            payload = b'{"type": "string"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/schema+json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/schema.json", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("ref_keyword", ["$ref", "$dynamicRef"])
def test_external_references_are_rejected_without_network_requests(tmp_path, ref_keyword):
    with local_schema_server() as (url, requests):
        path = snapshot(
            tmp_path,
            "external.json",
            {
                "type": "object",
                "properties": {"query": {ref_keyword: url}},
            },
        )
        assert_error(run_cli("validate", path))
        assert requests == [], "Validation must not fetch an external schema"


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.invalid/schema.json",
        "relative.json#/$defs/query",
        "//example.invalid/schema.json",
    ],
)
def test_other_nonlocal_references_are_rejected(tmp_path, reference):
    path = snapshot(
        tmp_path,
        "external.json",
        {
            "type": "object",
            "$defs": {"unused": {"$ref": reference}},
        },
    )
    assert_error(run_cli("validate", path))


def test_file_uri_reference_is_rejected(tmp_path):
    external = write_json(tmp_path, "private-schema.json", {"const": SECRET})
    path = snapshot(
        tmp_path,
        "external.json",
        {
            "type": "object",
            "properties": {"query": {"$ref": external.as_uri()}},
        },
    )
    assert_error(run_cli("validate", path))


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"query": {"$ref": "#/$defs/missing"}}},
        {"type": "object", "$defs": {"unused": {"$ref": "#/$defs/missing"}}},
        {"type": "object", "properties": {"query": {"$ref": "#missing-anchor"}}},
    ],
)
def test_unresolved_local_references_are_configuration_errors(tmp_path, schema):
    assert_error(run_cli("validate", snapshot(tmp_path, "unresolved.json", schema)))


def test_local_defs_and_escaped_json_pointer_references_are_supported(tmp_path):
    path = snapshot(
        tmp_path,
        "local.json",
        {
            "type": "object",
            "$defs": {"query/name~kind": {"type": "string"}},
            "properties": {"query": {"$ref": "#/$defs/query~1name~0kind"}},
            "required": ["query"],
        },
    )
    fixture = write_json(
        tmp_path,
        "cases.json",
        {"cases": [{"id": "local-ref", "tool": "lookup", "arguments": {"query": "ok"}}]},
    )
    result = run_cli("compare", path, path, "--fixtures", fixture)
    assert result.returncode == 0, result.stdout + result.stderr


def test_recursive_local_reference_is_valid_for_finite_instance(tmp_path):
    path = snapshot(
        tmp_path,
        "recursive.json",
        {
            "type": "object",
            "properties": {"child": {"$ref": "#"}, "query": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    fixture = write_json(
        tmp_path,
        "cases.json",
        {
            "cases": [
                {"id": "recursive", "tool": "lookup", "arguments": {"child": {"query": "leaf"}}}
            ]
        },
    )
    result = run_cli("compare", path, path, "--fixtures", fixture)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("dialect", [None, DIALECT, DIALECT + "#"])
def test_default_and_explicit_supported_schema_dialect(tmp_path, dialect):
    schema = {"type": "object"}
    if dialect is not None:
        schema["$schema"] = dialect
    result = run_cli("validate", snapshot(tmp_path, "schema.json", schema))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "dialect",
    [
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2019-09/schema",
        "https://example.invalid/custom-dialect",
    ],
)
def test_unsupported_explicit_dialects_are_rejected(tmp_path, dialect):
    path = snapshot(tmp_path, "schema.json", {"$schema": dialect, "type": "object"})
    assert_error(run_cli("validate", path))


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "not-a-json-schema-type"},
        {"type": "object", "required": "query"},
        {"type": "object", "properties": {"query": {"minLength": -1}}},
        {"type": "object", "properties": {"query": {"type": "string", "pattern": "["}}},
        {"type": "object", "properties": {"query": {"enum": "not-an-array"}}},
    ],
)
def test_schema_definition_errors_are_clean_configuration_errors(tmp_path, schema):
    assert_error(run_cli("validate", snapshot(tmp_path, "schema.json", schema)))


@pytest.mark.parametrize("format", ["text", "json"])
def test_candidate_input_failure_never_emits_raw_instance_values(tmp_path, format):
    old_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    new_schema = {
        "type": "object",
        "properties": {"query": {"type": "integer"}},
        "required": ["query"],
    }
    before = snapshot(tmp_path, "before.json", old_schema)
    after = snapshot(tmp_path, "after.json", new_schema)
    fixtures = write_json(
        tmp_path,
        "cases.json",
        {"cases": [{"id": "private-input", "tool": "lookup", "arguments": {"query": SECRET}}]},
    )
    report, junit = tmp_path / "report.json", tmp_path / "report.xml"
    result = run_cli(
        "compare",
        before,
        after,
        "--fixtures",
        fixtures,
        "--format",
        format,
        "--output",
        report,
        "--junit",
        junit,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    rendered = result.stdout + result.stderr + report.read_text() + junit.read_text()
    assert SECRET not in rendered
    assert "Traceback" not in rendered
    assert "private-input" in rendered


@pytest.mark.parametrize("mode", ["input", "output"])
def test_baseline_fixture_errors_do_not_leak_instance_values(tmp_path, mode):
    schema = {"type": "object", "properties": {"query": {"type": "integer"}}, "required": ["query"]}
    output = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}
    path = snapshot(tmp_path, "baseline.json", schema, output)
    case = {"id": "private-baseline", "tool": "lookup", "arguments": {"query": 1}}
    if mode == "input":
        case["arguments"]["query"] = SECRET
    else:
        case["structuredContent"] = {"count": SECRET}
    fixtures = write_json(tmp_path, "cases.json", {"cases": [case]})
    assert_error(run_cli("compare", path, path, "--fixtures", fixtures, "--format", "json"))


def test_candidate_output_failure_does_not_leak_instance_values(tmp_path):
    inputs = {"type": "object"}
    old_output = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    new_output = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 1}},
        "required": ["value"],
    }
    before = snapshot(tmp_path, "before.json", inputs, old_output)
    after = snapshot(tmp_path, "after.json", inputs, new_output)
    fixtures = write_json(
        tmp_path,
        "cases.json",
        {
            "cases": [
                {
                    "id": "private-output",
                    "tool": "lookup",
                    "arguments": {},
                    "structuredContent": {"value": SECRET},
                }
            ]
        },
    )
    result = run_cli("compare", before, after, "--fixtures", fixtures, "--format", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert SECRET not in result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["breaking"] == 0
    assert report["summary"]["output_mismatches"] == 1
    assert any(
        f.get("fixture") == "private-output" and f["severity"] == "warning"
        for f in report["findings"]
    )


def test_malformed_json_diagnostic_does_not_echo_input_body(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text('{"tools": [], "private": "' + SECRET, encoding="utf-8")
    assert_error(run_cli("validate", path))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numeric_constants_are_rejected(tmp_path, constant):
    path = tmp_path / "non-json.json"
    path.write_text('{"tools": [], "extra": ' + constant + "}", encoding="utf-8")
    assert_error(run_cli("validate", path))
