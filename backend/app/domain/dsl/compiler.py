from __future__ import annotations

from typing import Any

from app.domain.dsl.schema import DslRuleSet


def compile_rule_set(rules_json: dict[str, Any]) -> tuple[DslRuleSet, str, dict[str, Any]]:
    """
    Compile == validate + canonicalize + hash.

    Returns:
    - parsed DslRuleSet (typed)
    - compiled_hash (sha256 of canonical JSON)
    - compiled_json (canonical JSON)
    """
    rule_set = DslRuleSet.model_validate(rules_json)
    compiled_json = rule_set.canonical_json()
    compiled_hash = rule_set.compiled_hash()
    return rule_set, compiled_hash, compiled_json


