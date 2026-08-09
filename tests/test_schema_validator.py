"""Regression tests for `providers.validate_against_schema`.

Finding #10 (adversarial review, 2026-08-09): the validator recognised only
`type`-bearing nodes plus `const`/`enum`. Any node using `oneOf`, `anyOf`,
`allOf`, `$ref`, `not`, `patternProperties`, ... fell through every branch
and returned None -- i.e. reported success for constraints it never checked.
Reproduced: `{"oneOf": [{"type": "object", "required": ["answer_text"]}]}`
accepted `{"totally": "wrong"}` silently.

The fix refuses unimplemented keywords rather than ignoring them. These tests
pin both directions: the refusal, and that real schemas still pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "evidence_evaluator"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from providers import ProviderError, validate_against_schema  # noqa: E402


@pytest.mark.parametrize("keyword", ["oneOf", "anyOf", "allOf", "not", "$ref"])
def test_unimplemented_keywords_are_refused_not_ignored(keyword):
    schema = {keyword: [{"type": "object", "required": ["answer_text"]}]}
    with pytest.raises(ProviderError, match="does not implement"):
        validate_against_schema({"totally": "wrong"}, schema)


def test_a_node_with_nothing_to_check_is_refused():
    """`{}` or a description-only node constrains nothing. Accepting it would
    mean the call verified nothing while returning normally."""
    with pytest.raises(ProviderError, match="nothing to validate"):
        validate_against_schema({"anything": 1}, {})
    with pytest.raises(ProviderError, match="nothing to validate"):
        validate_against_schema("x", {"description": "just prose"})


def test_const_and_enum_alone_are_still_valid_nodes():
    """These constrain without a `type`, so they must NOT trip the new
    no-type refusal."""
    validate_against_schema("v1", {"const": "v1"})
    validate_against_schema("answer", {"enum": ["answer", "abstain"]})
    with pytest.raises(ProviderError):
        validate_against_schema("v2", {"const": "v1"})


def _assert_every_node_supported(node, name, path="$"):
    from providers import _SUPPORTED_SCHEMA_KEYWORDS
    if not isinstance(node, dict):
        return
    unsupported = sorted(set(node) - _SUPPORTED_SCHEMA_KEYWORDS)
    assert not unsupported, f"{name} at {path} uses {unsupported}"
    for key, value in node.get("properties", {}).items():
        _assert_every_node_supported(value, name, f"{path}.{key}")
    if "items" in node:
        _assert_every_node_supported(node["items"], name, f"{path}[]")


def test_the_real_shipped_schemas_are_expressible_in_this_subset():
    """The guard must not break the schemas this package actually targets.
    Checked against the source experiment's two real response schemas -- if
    either ever needs a keyword this validator lacks, this fails loudly
    instead of the validator silently waving that node through."""
    base = Path("/Users/jaehyuntak/Desktop/Project_in_progress/"
                "concept-gate-codex-mcp-wt/experiments/"
                "2026-08-07_handoff_dynamic_controller")
    names = ["live_subject_response.schema.json",
             "retrieval_subagent_response.schema.json"]
    if not all((base / n).is_file() for n in names):
        pytest.skip("source experiment schemas not present on this machine")

    for name in names:
        schema = json.loads((base / name).read_text(encoding="utf-8"))
        _assert_every_node_supported(schema, name)


def test_a_normal_object_schema_still_enforces_its_constraints():
    """Sanity: the refusal did not replace real validation."""
    schema = {"type": "object", "additionalProperties": False,
              "required": ["a"],
              "properties": {"a": {"type": "string", "minLength": 1},
                             "b": {"type": "array",
                                   "items": {"type": "integer", "minimum": 0}}}}
    validate_against_schema({"a": "hi", "b": [1, 2]}, schema)

    with pytest.raises(ProviderError, match="missing required"):
        validate_against_schema({}, schema)
    with pytest.raises(ProviderError, match="minLength"):
        validate_against_schema({"a": ""}, schema)
    with pytest.raises(ProviderError, match="unexpected key"):
        validate_against_schema({"a": "hi", "zz": 1}, schema)
