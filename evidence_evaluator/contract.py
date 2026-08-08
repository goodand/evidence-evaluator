"""Frozen contract: what a case, its gold, and a subject's trace must contain.

Extracted from `concept-gate-codex-mcp-wt/experiments/2026-08-07_handoff_dynamic_controller/_contract.py`
(2026-08-08), where it validated whether a zero-context coding agent could find
the files it needed to resume work in a specific handoff document. The schema
itself is generic evidence-gathering vocabulary -- a case (query + entry
condition), gold (expected paths, critical paths, claims with cited support
ranges), and a trace (search/read/cite actions) -- so it travels to any
"did the agent find and correctly cite the right sources" evaluation, not just
that one repository's handoff files.

The `C1-C4` failure codes are specific to that source experiment's controller
(recall-first budget, closed action set, subagent leakage). Reuse what applies;
`FAILURE_CODES` is a plain dict, so adding or dropping entries for your own
setup does not require touching the validators below.
"""

from __future__ import annotations

import re
from typing import Any

CASE_VERSION = "evidence-case-v1"
GOLD_VERSION = "evidence-gold-v1"
TRACE_VERSION = "evidence-trace-v1"
SUBAGENT_VERSION = "evidence-subagent-v1"

# Closed action set. Anything else is C2. Adapt to your own tool surface --
# these are the four retrieval actions plus the two terminal ones the source
# experiment used.
ACTIONS = ("reformulate_query", "follow_link", "read_candidate",
           "expand_candidates", "abstain", "answer")
TERMINAL_ACTIONS = ("answer", "abstain")

# Keys that must never appear in anything a subject or a subagent can see.
# Leakage of any of these is E1 -- the evaluator's own answer key leaking into
# the thing being evaluated.
FORBIDDEN_RUNTIME_KEYS = frozenset({
    "expected_paths", "critical_paths", "expected_authority",
    "reference_claims", "gold", "gold_labels", "hidden_gold", "claim_support",
    "permitted_authority_paths", "support_ranges",
})

# A retrieval-only subagent may return these four keys and nothing else. A
# conclusion, a state, or an authority label from a retrieval-only component
# has stopped being retrieval-only -- that is the boundary C3 checks.
SUBAGENT_ALLOWED_KEYS = frozenset({
    "contract_version", "candidate_paths", "read_ranges", "search_trace",
    "uncertainty",
})

FAILURE_CODES = {
    "D0": "handoff entry point not discovered",
    "R1": "critical path not retrieved",
    "R2": "expected path recall below threshold",
    "X1": "citation outside exposed context",
    "I1": "interpretation claim unsupported",
    "A1": "false absence declared",
    "S1": "safety violation (protected asset / forbidden action)",
    "T1": "answer without a reproducible authority-read trace",
    "E0": "evaluator cannot separate positive from negative control",
    "E1": "gold or evaluator surface leaked into runtime",
    "V1": "invalid run (API, timeout, tool unavailable)",
    "C1": "terminated below the recall-first minimum exploration budget",
    "C2": "action outside the closed action set",
    "C3": "subagent output carried a forbidden field",
    "C4": "cited a path the subject never read itself",
}

_TOKEN = re.compile(r"[a-z0-9]+")

# Overlap on a function word is not lexical signal. Kept minimal and explicit
# rather than pulled from a library: a long stopword list could hide real
# content-word overlap and quietly make a 0%-overlap case vacuous.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for",
    "from", "has", "have", "in", "is", "it", "of", "on", "or", "that", "the",
    "to", "was", "were", "what", "when", "where", "which", "who", "why", "with",
})


class ContractError(ValueError):
    """A payload violated the frozen contract."""


def tokens(text: str) -> set[str]:
    """Lowercase + alphanumeric split, minus STOPWORDS.

    Pinned here rather than in a caller so a case builder and its checker
    cannot drift apart -- a 0%-overlap claim verified under a different
    tokenizer than the one that built the case is not a verified claim.
    """
    return {t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS}


def find_forbidden_key(value: Any, prefix: str = "$") -> str | None:
    """Deep scan for gold-bearing key names. Returns the first path found."""
    if isinstance(value, dict):
        for key, sub in value.items():
            if key in FORBIDDEN_RUNTIME_KEYS:
                return f"{prefix}.{key}"
            found = find_forbidden_key(sub, f"{prefix}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            found = find_forbidden_key(sub, f"{prefix}[{i}]")
            if found:
                return found
    return None


def _rel(value: Any) -> bool:
    return (isinstance(value, str) and bool(value)
            and not value.startswith("/") and ".." not in value.split("/"))


def _str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(_rel(v) for v in value):
        raise ContractError(f"{name} must be a list of repo-relative paths.")
    return value


def validate_case(case: dict) -> dict:
    """A PUBLIC case. Must carry no gold and must not reveal the handoff path
    in a discovery condition -- that is the whole difference between the two
    entry conditions this schema distinguishes."""
    if case.get("contract_version") != CASE_VERSION:
        raise ContractError("unsupported case contract version")
    for key in ("id", "query", "condition"):
        if not isinstance(case.get(key), str) or not case[key]:
            raise ContractError(f"case {key} is required")
    if case["condition"] not in ("direct-handoff", "discovery"):
        raise ContractError("condition must be direct-handoff or discovery")
    if case["condition"] == "direct-handoff" and not _rel(case.get("handoff_path")):
        raise ContractError("direct-handoff case needs a relative handoff_path")
    if case["condition"] == "discovery" and "handoff_path" in case:
        raise ContractError("discovery case must not reveal handoff_path")
    leaked = find_forbidden_key(case)
    if leaked:
        raise ContractError(f"case leaks a gold key at {leaked} (E1)")
    return case


def validate_gold(gold: dict, case: dict) -> dict:
    if gold.get("contract_version") != GOLD_VERSION:
        raise ContractError("unsupported gold contract version")
    if gold.get("case_id") != case["id"]:
        raise ContractError("gold case_id does not match the public case")
    if not _rel(gold.get("handoff_path")):
        raise ContractError("gold handoff_path must be relative")
    _str_list(gold.get("expected_paths"), "expected_paths")
    _str_list(gold.get("critical_paths"), "critical_paths")
    _str_list(gold.get("expected_authority"), "expected_authority")
    permitted = gold.get("permitted_authority_paths", gold["expected_authority"])
    _str_list(permitted, "permitted_authority_paths")
    if not set(gold["critical_paths"]) <= set(gold["expected_paths"]):
        raise ContractError("critical_paths must be a subset of expected_paths")
    if not set(gold["expected_authority"]) <= set(permitted):
        raise ContractError("expected_authority must be within permitted_authority_paths")
    claims = gold.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ContractError("gold needs at least one claim")
    for claim in claims:
        if not isinstance(claim.get("claim_id"), str) or not claim["claim_id"]:
            raise ContractError("claim_id is required")
        ranges = claim.get("support_ranges")
        if not isinstance(ranges, list) or not ranges:
            raise ContractError("claim must declare support_ranges")
        for item in ranges:
            if (not isinstance(item, dict) or not _rel(item.get("path"))
                    or not isinstance(item.get("start"), int)
                    or not isinstance(item.get("end"), int)
                    or item["start"] > item["end"]):
                raise ContractError("support_range needs path/start/end with start<=end")
    if not isinstance(gold.get("is_absent"), bool):
        raise ContractError("gold must state is_absent explicitly (abstention truth)")
    return gold


def validate_subagent_output(payload: dict) -> dict:
    """C3. A retrieval-only component that returns a conclusion has stopped
    being retrieval-only, and the main subject would then be grading itself
    against another agent's answer rather than against sources."""
    if payload.get("contract_version") != SUBAGENT_VERSION:
        raise ContractError("unsupported subagent contract version")
    extra = set(payload) - SUBAGENT_ALLOWED_KEYS
    if extra:
        raise ContractError(f"C3: subagent returned forbidden field(s): {sorted(extra)}")
    leaked = find_forbidden_key(payload)
    if leaked:
        raise ContractError(f"C3: subagent output leaks a gold key at {leaked}")
    _str_list(payload.get("candidate_paths"), "candidate_paths")
    return payload


def validate_trace(trace: dict) -> dict:
    if trace.get("contract_version") != TRACE_VERSION:
        raise ContractError("unsupported trace contract version")
    actions = trace.get("actions")
    if not isinstance(actions, list):
        raise ContractError("trace.actions must be a list")
    for step in actions:
        if step.get("action") not in ACTIONS:
            raise ContractError(f"C2: action {step.get('action')!r} is outside the closed set")
        for key in ("candidates_before", "candidates_after"):
            _str_list(step.get(key), f"action.{key}")
    if not isinstance(trace.get("reads"), list):
        raise ContractError("trace.reads must be a list")
    leaked = find_forbidden_key(trace)
    if leaked:
        raise ContractError(f"E1: trace leaks a gold key at {leaked}")
    return trace
