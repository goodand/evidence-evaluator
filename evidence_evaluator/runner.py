#!/usr/bin/env python3
"""Corpus, budget guard, and run loop that drives a controller through a case.

Extracted from `_runner.py` in the source experiment. The controller is a
plug: `run_case` drives it and records everything. The controller never sees
gold, never sees the evaluator, and never sees a prior trace -- it only sees
the observation this module hands it.

ADAPTATION FROM THE SOURCE
---------------------------
The source experiment fixed four named arms (S_STATIC/R_STATIC/S_DYNAMIC/
R_DYNAMIC) with a lookup table mapping each to `has_subagent`/`is_dynamic`
booleans. That is a specific experimental design, not a generic evaluator
concept, so `run_case` here takes `has_subagent` and `is_dynamic` directly as
keyword arguments and `arm` is a free-form string tag carried into the trace
for your own bookkeeping -- `evidence_evaluator.contract` no longer validates
it against a fixed set.

THE GUARD IS THE INTERESTING PART
----------------------------------
A dynamic controller decides for itself when it has enough. That is the whole
point of letting a controller be dynamic, and it is also the cheapest way to
score well for the wrong reason: stop early, spend little, look efficient.
So terminal actions are REFUSED until the run has actually explored, and the
refusal is fed back as an observation rather than silently ignored. Refusal
is an execution rule, not a judgement -- `evaluator.evaluate()` decides
correctness separately.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from pathlib import Path

from contract import (ACTIONS, SUBAGENT_VERSION, TERMINAL_ACTIONS,
                      TRACE_VERSION, ContractError, validate_subagent_output,
                      validate_trace)

WORD = re.compile(r"[a-z0-9]+")
_LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)\)")
_MENTION = re.compile(r"`([^`\s]+\.(?:md|py|json|txt))`")

# Guard thresholds. Tune for your own corpus size and case difficulty --
# these are the source experiment's preregistered values.
MIN_READS = 1
MAX_TERMINAL_ATTEMPTS = 3
MAX_ACTIONS = 24


class Corpus:
    """Read-only view of one corpus directory (Markdown files)."""

    def __init__(self, root: Path):
        self.root = root
        self.docs = {
            str(p.relative_to(root)): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*.md"))
        }
        self._df = Counter()
        for text in self.docs.values():
            self._df.update(set(WORD.findall(text.lower())))
        self._n = len(self.docs)

    def search(self, query: str, k: int = 4) -> list[str]:
        """Deterministic lexical ranking (tf-idf, cosine-free).

        ponytail: no BM25 tuning; the point is a *realistic miss*, not a good
        search engine. Upgrade only if a case stops being reachable at all.
        """
        terms = [t for t in WORD.findall(query.lower()) if self._df[t]]
        scored = []
        for path, text in self.docs.items():
            tf = Counter(WORD.findall(text.lower()))
            score = sum(
                (1 + math.log(tf[t])) * math.log(self._n / self._df[t])
                for t in terms if tf[t]
            )
            # path and title carry weight, as in any real retriever
            head = path + " " + text.split("\n", 1)[0]
            score += 2.0 * sum(1 for t in terms if t in WORD.findall(head.lower()))
            if score:
                scored.append((score, path))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [p for _, p in scored[:k]]

    def links(self, path: str) -> list[str]:
        """Outgoing edges. Prose mentions of a filename count as edges too --
        a reader following `docs/x.md` in prose finds the file -- but the two
        channels are kept distinct so link-only vs mention-only reachability
        can be measured separately."""
        text = self.docs.get(path, "")
        out = []
        for raw in _LINK.findall(text) + _MENTION.findall(text):
            target = self._resolve(raw, path)
            if target and target not in out:
                out.append(target)
        return out

    def _resolve(self, raw: str, from_path: str) -> str | None:
        if raw.startswith(("http://", "https://")) or "*" in raw:
            return None
        for base in (Path(from_path).parent, Path(".")):
            cand = (base / raw).as_posix()
            cand = Path(cand).resolve().relative_to(Path(".").resolve()).as_posix() \
                if not cand.startswith("..") else cand
            cand = cand.lstrip("./")
            if cand in self.docs:
                return cand
        return None

    def read(self, path: str, start: int = 1, end: int = 10**6) -> str:
        lines = self.docs.get(path, "").splitlines()
        return "\n".join(lines[max(0, start - 1):end])


class BudgetGuard:
    """Recall-first minimum exploration before a terminal action is allowed."""

    def __init__(self):
        self.queries: set[str] = set()
        self.follow_links = 0
        self.reformulations = 0
        self.reads = 0
        self.first_search_paths: set[str] | None = None
        self.beyond_first_search = 0
        self.terminal_attempts = 0
        self.rejections: list[str] = []

    def observe(self, action: str, query: str | None, target: str | None) -> None:
        if action == "reformulate_query" and query:
            if self.first_search_paths is not None:
                self.reformulations += 1
            self.queries.add(query.strip().lower())
        elif action == "follow_link":
            self.follow_links += 1
        elif action == "read_candidate":
            self.reads += 1
        if target and self.first_search_paths is not None \
                and target not in self.first_search_paths:
            self.beyond_first_search += 1

    def check(self, action: str) -> str | None:
        """Return a refusal reason, or None when the terminal action is allowed."""
        unmet = []
        if len(self.queries) < 2 and self.follow_links < 1:
            unmet.append("need 2 distinct queries, or 1 query plus 1 follow_link")
        if self.reads < MIN_READS:
            unmet.append(f"need at least {MIN_READS} read_candidate")
        if self.beyond_first_search < 1:
            unmet.append("need one read or follow_link on a candidate the first "
                         "search did not surface")
        if action == "abstain":
            # zero hits is not proof of absence
            if self.reformulations < 1 or self.follow_links < 1:
                unmet.append("abstention needs >=1 reformulation AND >=1 follow_link; "
                             "a first-search miss is not evidence of absence")
        return "; ".join(unmet) if unmet else None


def retrieval_subagent(corpus: Corpus, case: dict) -> dict:
    """Retrieval-only reference implementation. Returns candidates and where
    it looked -- never a conclusion, a state, or an authority label.
    `validate_subagent_output` enforces the boundary; this function is merely
    an honest implementation of it. Feed a dishonest one in your own tests to
    confirm C3 actually fires."""
    trace, candidates = [], []
    q1 = case["query"]
    hits = corpus.search(q1)
    trace.append({"query": q1, "hits": hits})
    candidates.extend(hits)
    # one graph hop from the top hits -- widening, not deciding
    for path in list(hits[:2]):
        for target in corpus.links(path):
            if target not in candidates:
                candidates.append(target)
                trace.append({"followed": path, "found": target})
    return {
        "contract_version": SUBAGENT_VERSION,
        "candidate_paths": candidates,
        "read_ranges": [{"path": p, "start": 1, "end": 40} for p in candidates[:3]],
        "search_trace": trace,
        "uncertainty": "candidates only; authority not assessed",
    }


def run_case(case: dict, controller, corpus: Corpus, *,
            arm: str = "default", has_subagent: bool = False,
            is_dynamic: bool = False) -> dict:
    """Drive one (case, controller) run and return a trace.

    `arm` is a free-form tag carried into the trace for your own bookkeeping;
    `has_subagent`/`is_dynamic` decide this run's behaviour directly rather
    than being looked up from a fixed arm-name table (see module docstring).

    Never raises for subject misbehaviour -- misbehaviour is recorded as a
    failure code so one bad run cannot abort a sweep.
    """
    started = time.perf_counter()
    guard = BudgetGuard()
    trace = {
        "contract_version": TRACE_VERSION, "case_id": case["id"], "arm": arm,
        "subagent_output": None, "actions": [], "reads": [], "claims": [],
        "current_state": "", "next_action": "", "stop_conditions": [],
        "uncertainties": [], "tool_errors": [], "stop_reason": None,
        "recommended_actions": [],
        "answer_text": "", "declared_absent": False,
        "guard_rejections": [], "failure_codes": [],
    }

    if has_subagent:
        try:
            trace["subagent_output"] = validate_subagent_output(
                retrieval_subagent(corpus, case))
        except ContractError as exc:
            trace["failure_codes"].append("C3")
            trace["tool_errors"].append(str(exc))

    candidates: list[str] = list(
        (trace["subagent_output"] or {}).get("candidate_paths", []))
    if case["condition"] == "direct-handoff":
        candidates = [case["handoff_path"]] + [c for c in candidates
                                               if c != case["handoff_path"]]
    observation = {
        "query": case["query"], "condition": case["condition"],
        "handoff_path": case.get("handoff_path"), "candidates": list(candidates),
        "last_result": None, "reject_reason": None,
        "dynamic": is_dynamic,
        "subagent_candidates": list(
            (trace["subagent_output"] or {}).get("candidate_paths", [])),
    }

    for i in range(MAX_ACTIONS):
        step = controller(observation)
        name = step.get("action")
        if name not in ACTIONS:
            trace["failure_codes"].append("C2")
            trace["stop_reason"] = "C2"
            break

        before = list(candidates)
        result, read_range, target = None, None, None

        if name in TERMINAL_ACTIONS:
            reason = guard.check(name)
            if reason:
                guard.terminal_attempts += 1
                guard.rejections.append(reason)
                trace["guard_rejections"].append(
                    {"i": i, "action": name, "reason": reason})
                trace["actions"].append({
                    "i": i, "action": name, "query": None,
                    "candidates_before": before, "candidates_after": list(candidates),
                    "read_range": None, "accepted": False, "reject_reason": reason,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000)})
                if guard.terminal_attempts >= MAX_TERMINAL_ATTEMPTS:
                    trace["failure_codes"].append("C1")
                    trace["stop_reason"] = "C1"
                    break
                observation = dict(observation, reject_reason=reason,
                                   candidates=list(candidates))
                continue
            # accepted terminal
            trace["stop_reason"] = name
            trace["answer_text"] = step.get("answer_text", "")
            trace["declared_absent"] = (name == "abstain")
            trace["claims"] = step.get("claims", [])
            trace["current_state"] = step.get("current_state", "")
            trace["next_action"] = step.get("next_action", "")
            trace["stop_conditions"] = step.get("stop_conditions", [])
            trace["uncertainties"] = step.get("uncertainties", [])
            trace["recommended_actions"] = step.get("recommended_actions", [])
            trace["actions"].append({
                "i": i, "action": name, "query": None,
                "candidates_before": before, "candidates_after": list(candidates),
                "read_range": None, "accepted": True, "reject_reason": None,
                "elapsed_ms": int((time.perf_counter() - started) * 1000)})
            break

        if name == "reformulate_query":
            query = step.get("query", "")
            result = corpus.search(query)
            if guard.first_search_paths is None:
                guard.first_search_paths = set(result)
            for path in result:
                if path not in candidates:
                    candidates.append(path)
            target = result[0] if result else None
        elif name == "follow_link":
            target = step.get("target")
            result = corpus.links(target) if target else []
            for path in result:
                if path not in candidates:
                    candidates.append(path)
        elif name == "expand_candidates":
            result = []
            for path in list(candidates):
                for t in corpus.links(path):
                    if t not in candidates:
                        candidates.append(t)
                        result.append(t)
            target = None
        elif name == "read_candidate":
            # accept either key: controllers naturally say `path` for a read
            # and `target` for a hop. Requiring one spelling silently produced
            # a read of None and every run scored D0 in the source experiment
            # -- measured, not imagined.
            target = step.get("target") or step.get("path")
            start, end = step.get("start", 1), step.get("end", 10**6)
            result = corpus.read(target, start, end) if target else ""
            read_range = {"path": target, "start": start, "end": end}
            trace["reads"].append(read_range)

        guard.observe(name, step.get("query"), target)
        trace["actions"].append({
            "i": i, "action": name, "query": step.get("query"),
            "candidates_before": before, "candidates_after": list(candidates),
            "read_range": read_range, "accepted": True, "reject_reason": None,
            "elapsed_ms": int((time.perf_counter() - started) * 1000)})
        observation = dict(observation, candidates=list(candidates),
                           last_result=result, reject_reason=None)
    else:
        trace["stop_reason"] = "budget_exhausted"

    trace["wall_clock_ms"] = int((time.perf_counter() - started) * 1000)
    trace["n_search"] = sum(1 for a in trace["actions"]
                            if a["action"] == "reformulate_query" and a["accepted"])
    trace["n_read"] = len(trace["reads"])
    try:
        validate_trace(trace)
    except ContractError as exc:
        trace["tool_errors"].append(str(exc))
        for code in ("C2", "E1"):
            if code in str(exc) and code not in trace["failure_codes"]:
                trace["failure_codes"].append(code)
    return trace
