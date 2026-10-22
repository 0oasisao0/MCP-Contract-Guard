"""Adversarial release checks independent of the implementation test suite."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args: object, seed: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mcp_contract_guard", *(str(arg) for arg in args)],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONHASHSEED": str(seed),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def snapshot(path: Path, schema: dict) -> Path:
    return write(path, {"tools": [{"name": "lookup", "inputSchema": schema}]})


def fixture(path: Path, value: object) -> Path:
    return write(path, {"cases": [{"id": "boundary", "tool": "lookup", "arguments": {"q": value}}]})


def test_report_order_does_not_depend_on_hash_seed_with_same_path_errors(tmp_path):
    old = snapshot(tmp_path / "old.json", {"type": "object"})
    new = snapshot(
        tmp_path / "new.json",
        {"type": "object", "properties": {"q": {"minLength": 10, "pattern": "^z"}}},
    )
    cases = fixture(tmp_path / "cases.json", "a")
    results = [
        cli("compare", old, new, "--fixtures", cases, "--format", "json", seed=seed)
        for seed in (0, 3, 11, 17)
    ]
    assert all(result.returncode == 1 for result in results)
    assert len({result.stdout for result in results}) == 1


def test_decimal_multipleof_does_not_create_false_regression_witness(tmp_path):
    old = snapshot(tmp_path / "old.json", {"type": "object"})
    new = snapshot(
        tmp_path / "new.json",
        {"type": "object", "properties": {"q": {"type": "number", "multipleOf": 0.1}}},
    )
    cases = fixture(tmp_path / "cases.json", 0.3)
    result = cli("compare", old, new, "--fixtures", cases, "--format", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["fixtures"][0]["input"]["after"] == "valid"
    assert not any(f["code"] == "fixture.input_regression" for f in report["findings"])


def test_huge_json_integer_never_causes_unhandled_numeric_exception(tmp_path):
    path = snapshot(
        tmp_path / "schema.json",
        {"type": "object", "properties": {"q": {"multipleOf": 0.1}}},
    )
    cases = fixture(tmp_path / "cases.json", 10**400)
    result = cli("validate", path, "--fixtures", cases)
    # Every integer is an integral multiple of one tenth.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_symlink_loop_is_clean_redacted_input_error(tmp_path):
    first, second = tmp_path / "private-first.json", tmp_path / "private-second.json"
    try:
        first.symlink_to(second)
        second.symlink_to(first)
    except OSError:
        pytest.skip("Symlinks are unavailable on this platform")
    result = cli("validate", first)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


@pytest.mark.parametrize("index", ["-1", "01", "+1"])
def test_local_ref_rejects_noncanonical_array_indices(tmp_path, index):
    path = snapshot(
        tmp_path / "schema.json",
        {
            "type": "object",
            "anyOf": [True, False],
            "properties": {"q": {"$ref": "#/anyOf/" + index}},
        },
    )
    result = cli("validate", path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_decimal_precision_cannot_turn_baseline_invalid_into_regression(tmp_path):
    old = snapshot(
        tmp_path / "old.json",
        {"type": "object", "properties": {"q": {"const": 9007199254740992}}},
    )
    new = snapshot(
        tmp_path / "new.json",
        {"type": "object", "properties": {"q": {"const": 9007199254740993}}},
    )
    cases = tmp_path / "cases.json"
    cases.write_text(
        '{"cases":[{"id":"precise","tool":"lookup","arguments":{"q":9007199254740993.0}}]}',
        encoding="utf-8",
    )
    result = cli("compare", old, new, "--fixtures", cases, "--format", "json")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "fixture.input_regression" not in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("payload", [True, False, {"type": "string"}])
def test_local_refs_cannot_target_non_schema_metadata(tmp_path, payload):
    path = snapshot(
        tmp_path / "schema.json",
        {
            "type": "object",
            "privateMetadata": payload,
            "properties": {"q": {"$ref": "#/privateMetadata"}},
        },
    )
    result = cli("validate", path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_duplicate_anchors_are_rejected_instead_of_arbitrarily_resolved(tmp_path):
    path = snapshot(
        tmp_path / "schema.json",
        {
            "type": "object",
            "$defs": {
                "one": {"$anchor": "duplicate", "const": 1},
                "two": {"$anchor": "duplicate", "const": 2},
            },
            "properties": {"q": {"$ref": "#duplicate"}},
        },
    )
    result = cli("validate", path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_nested_dialect_declaration_preserves_safe_numeric_validation(tmp_path):
    path = snapshot(
        tmp_path / "schema.json",
        {
            "type": "object",
            "properties": {
                "q": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "multipleOf": 0.1,
                }
            },
        },
    )
    cases = fixture(tmp_path / "cases.json", 10**400)
    result = cli("validate", path, "--fixtures", cases)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
