"""Exact-decimal regression checks: do not invent or lose concrete witnesses."""

from decimal import Decimal

import pytest

from mcp_contract_guard.diffing import SchemaDiffer, _json_key
from mcp_contract_guard.loading import DIALECT, InputError, prepare_schema, read_json
from mcp_contract_guard.models import Report


def parsed(tmp_path, text):
    path = tmp_path / "number.json"
    path.write_text(text)
    return read_json(path)


@pytest.mark.parametrize(
    "literal,expected",
    [
        ("0.3", Decimal("0.3")),
        ("0.30", Decimal("0.30")),
        ("9007199254740993.0", 9007199254740993),
        ("1.0", 1),
        ("1e100", 10**100),
        ("-0.0", 0),
        ("1e-300", Decimal("1e-300")),
        ("0.30000000000000001", Decimal("0.30000000000000001")),
    ],
)
def test_decimal_literals_are_lossless(tmp_path, literal, expected):
    actual = parsed(tmp_path, literal)
    assert actual == expected
    assert not isinstance(actual, float)


@pytest.mark.parametrize(
    "literal", ["1e-9999", "1e9999", "-1e9999", "NaN", "Infinity", "-Infinity"]
)
def test_out_of_profile_numbers_are_controlled(tmp_path, literal):
    with pytest.raises(InputError):
        parsed(tmp_path, literal)


@pytest.mark.parametrize("nested_dialect", [False, True])
@pytest.mark.parametrize(
    "instance,valid",
    [
        (Decimal("0.3"), True),
        (Decimal("0.31"), False),
        (10**400, True),
        ("not-a-number", True),
        (True, True),
        (-3, True),
        (Decimal("1e-300"), False),
    ],
)
def test_exact_multiple_of_with_optional_nested_dialect(instance, valid, nested_dialect):
    child = {"multipleOf": Decimal("0.1")}
    if nested_dialect:
        child["$schema"] = DIALECT
    schema = {"$schema": DIALECT, "properties": {"q": child}}
    validator = prepare_schema(schema)
    assert validator.is_valid({"q": instance}) is valid
    # Preparing the evaluator must never mutate the original contract snapshot.
    assert schema["$schema"] == DIALECT
    assert ("$schema" in child) is nested_dialect


def test_numeric_local_ref_uses_custom_evaluator():
    schema = {
        "$defs": {"n": {"$schema": DIALECT, "multipleOf": Decimal("0.1")}},
        "properties": {"q": {"$ref": "#/$defs/n"}},
    }
    assert prepare_schema(schema).is_valid({"q": 10**400})


def test_schema_decimal_enum_order_is_semantically_stable():
    old = {"enum": [Decimal("0.30"), {"nested": Decimal("0.2")}, 1]}
    new = {"enum": [1, {"nested": Decimal("0.20")}, Decimal("0.3")]}
    report = Report("compare")
    SchemaDiffer(report, "tool", "input").compare(old, new, ("inputSchema",))
    assert report.findings == []
    assert _json_key(Decimal("10")) == "10"


def test_large_integral_decimal_has_correct_const_semantics(tmp_path):
    instance = parsed(tmp_path, '{"q":9007199254740993.0}')
    old = {"properties": {"q": {"const": 9007199254740992}}}
    new = {"properties": {"q": {"const": 9007199254740993}}}
    assert not prepare_schema(old).is_valid(instance)
    assert prepare_schema(new).is_valid(instance)


def test_arbitrary_python_objects_are_not_sortable_schema_values():
    with pytest.raises(TypeError):
        _json_key(object())


@pytest.mark.parametrize("ref", ["#%76alue", "#%2F$defs%2Fv", "#/$defs/%76"])
def test_canonical_reference_rewrite_accepts_valid_encoded_fragments(ref):
    validator = prepare_schema(
        {"$defs": {"v": {"$anchor": "value", "type": "string"}}, "$ref": ref}
    )
    assert validator.is_valid("yes")
    assert not validator.is_valid(False)


@pytest.mark.parametrize("dialect", [DIALECT + "##", DIALECT + "###"])
def test_repeated_dialect_fragment_markers_rejected(dialect):
    with pytest.raises(InputError):
        prepare_schema({"$schema": dialect})
