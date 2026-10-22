"""Independent local-reference correctness and offline-boundary audit regressions."""

import pytest

from mcp_contract_guard.loading import prepare_schema
from mcp_contract_guard.models import InputError


@pytest.mark.parametrize("index", ["-1", "+0", "00", "01", "-0", " 0", "0 ", "-", "\u0660"])
def test_noncanonical_array_pointer_indexes_are_configuration_errors(index):
    with pytest.raises(InputError):
        prepare_schema({"$ref": f"#/prefixItems/{index}", "prefixItems": [{}, {}]})


@pytest.mark.parametrize("key", ["a~2b", "a~", "a~~0b"])
def test_invalid_pointer_escapes_do_not_resolve_literal_keys(key):
    with pytest.raises(InputError):
        prepare_schema({"$ref": f"#/$defs/{key}", "$defs": {key: {}}})


@pytest.mark.parametrize("fragment", ["a%", "a%Z0", "a%0Z", "%FF", "%C0%AF"])
def test_invalid_percent_encoding_is_rejected(fragment):
    with pytest.raises(InputError):
        prepare_schema({"$ref": f"#/$defs/{fragment}", "$defs": {fragment: {}}})


@pytest.mark.parametrize("value", [True, False, {}])
@pytest.mark.parametrize("keyword", ["const", "default", "examples"])
def test_references_to_instance_data_are_rejected_by_location(value, keyword):
    data = [value] if keyword == "examples" else value
    ref = f"#/{keyword}/0" if keyword == "examples" else f"#/{keyword}"
    with pytest.raises(InputError):
        prepare_schema({"$ref": ref, keyword: data, "$defs": {"valid": value}})


@pytest.mark.parametrize("keyword", ["$anchor", "$dynamicAnchor"])
def test_duplicate_anchors_are_configuration_errors_even_without_refs(keyword):
    with pytest.raises(InputError):
        prepare_schema({"$defs": {"a": {"$anchor": "duplicate"}, "b": {keyword: "duplicate"}}})


def test_both_anchor_keywords_cannot_reuse_a_name_on_one_node():
    with pytest.raises(InputError):
        prepare_schema({"$anchor": "duplicate", "$dynamicAnchor": "duplicate"})


@pytest.mark.parametrize("value", [True, False, {"type": "string"}])
def test_references_to_schema_locations_keep_boolean_and_object_support(value):
    validator = prepare_schema({"$defs": {"value": value}, "$ref": "#/$defs/value"})
    assert validator.is_valid("text") is (value is not False)


@pytest.mark.parametrize(
    "ref, key", [("#/$defs/a~1b~0c", "a/b~c"), ("#/$defs/a%7E1b", "a/b"), ("#/$defs/01", "01")]
)
def test_valid_escaped_and_numeric_object_keys_remain_supported(ref, key):
    validator = prepare_schema({"$ref": ref, "$defs": {key: {"type": "string"}}})
    assert validator.is_valid("text")
    assert not validator.is_valid(7)


def test_valid_array_index_remains_supported():
    validator = prepare_schema({"$ref": "#/prefixItems/1", "prefixItems": [{}, {"type": "string"}]})
    assert validator.is_valid("text")
    assert not validator.is_valid(7)


def test_references_and_anchors_inside_instance_data_are_not_schema_keywords():
    data = {"$ref": "https://example.invalid/schema", "$anchor": "same", "$id": "remote"}
    validator = prepare_schema(
        {"$anchor": "same", "const": data, "default": data, "examples": [data]}
    )
    assert validator.is_valid(data)


@pytest.mark.parametrize("keyword", ["$anchor", "$dynamicAnchor"])
def test_unique_local_anchors_remain_supported(keyword):
    validator = prepare_schema(
        {"$defs": {"value": {keyword: "value", "type": "string"}}, "$ref": "#value"}
    )
    assert validator.is_valid("text")
    assert not validator.is_valid(7)
