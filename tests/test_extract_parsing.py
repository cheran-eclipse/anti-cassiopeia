import pytest

from anticassiopeia.retrieval.extract import _parse_response


def test_parses_clean_found_json():
    p = _parse_response(
        '{"found": true, "chunk_id": "DOC1#0", "quote": "300 m", "value": 300, "unit": "m", "kind": "rated"}'
    )
    assert p is not None
    assert p.chunk_id == "DOC1#0"
    assert p.quote == "300 m"
    assert p.value == 300
    assert p.kind == "rated"


def test_honest_not_found_returns_none_not_a_guess():
    assert _parse_response('{"found": false, "reason": "not stated"}') is None


def test_strips_markdown_code_fence_some_models_add_anyway():
    p = _parse_response('```json\n{"found": true, "chunk_id": "DOC1#0", "quote": "x"}\n```')
    assert p is not None
    assert p.chunk_id == "DOC1#0"


def test_malformed_json_raises_rather_than_silently_failing():
    with pytest.raises(ValueError):
        _parse_response("not json at all, just prose")


def test_missing_required_field_raises_with_field_named():
    with pytest.raises(ValueError, match="quote"):
        _parse_response('{"found": true, "chunk_id": "DOC1#0"}')


def test_optional_fields_default_to_none_when_absent():
    p = _parse_response('{"found": true, "chunk_id": "DOC1#0", "quote": "x"}')
    assert p.value is None
    assert p.unit is None
    assert p.kind is None
