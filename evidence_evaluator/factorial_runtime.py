"""Host-owned action runtime for the handoff workflow factorial experiment.

The model sees one MCP action tool. This module owns the retrieval service,
candidate pool, reads, action budget, static policy, and terminal guard. A
model response can describe a trace, but it cannot create or edit this trace.
"""

from __future__ import annotations

import json
import socketserver
import threading
import time
from pathlib import Path
from typing import Any

from .runner import BudgetGuard
from .retrieval.service import RetrievalService, ServiceError

MAIN_RETRIEVAL_BUDGET = 10
HELPER_RETRIEVAL_BUDGET = 4
MAX_TERMINAL_ATTEMPTS = 3
MAX_READ_END = 400
STATIC_PRE_GRAPH_READS = 3
STATIC_POST_GRAPH_READS = 3
MODEL_CANDIDATE_VIEW_K = 12


class FactorialRuntimeError(RuntimeError):
    """The host action runtime could not preserve its experiment contract."""


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or value.startswith("/"):
        return None
    path = Path(value)
    if ".." in path.parts:
        return None
    return path.as_posix()


class FactorialHostState:
    """Retrieval state and immutable trace for one fresh subject process."""

    def __init__(
        self,
        service: RetrievalService,
        case: dict[str, Any],
        *,
        initial_candidates: list[str] | None = None,
        static: bool,
        guard_enabled: bool = True,
        max_retrieval_actions: int = MAIN_RETRIEVAL_BUDGET,
        output_k: int = 3,
        candidate_pool_k: int = 50,
    ) -> None:
        self.service = service
        self.case = case
        self.static = static
        self.guard_enabled = guard_enabled
        self.max_retrieval_actions = max_retrieval_actions
        self.output_k = output_k
        self.candidate_pool_k = candidate_pool_k
        self.guard = BudgetGuard()
        self.started = time.perf_counter()
        self.candidates: list[str] = []
        self.actions: list[dict[str, Any]] = []
        self.reads: list[dict[str, Any]] = []
        self.guard_rejections: list[dict[str, Any]] = []
        self.failure_codes: list[str] = []
        self.tool_errors: list[str] = []
        self.stop_reason: str | None = None
        self._candidate_pools: list[list[str]] = []
        self._static_plan: list[tuple[str, str | None]] = [
            ("search", None),
            ("search", None),
            ("expand_candidates", None),
        ]
        self._static_cursor = 0
        self._static_graph_planned = False
        self._lock = threading.Lock()
        self._retrieval_actions = 0
        self._requests = 0
        for path in initial_candidates or []:
            self._add_candidate(path)
        if case.get("condition") == "direct-handoff":
            handoff = case.get("handoff_path")
            if isinstance(handoff, str):
                self._add_candidate(handoff, front=True)
                # The public handoff is the entry surface. Graph-expanded
                # documents count as independent exploration even when the
                # controller chooses to search only after reading the entry.
                if self.candidates:
                    self.guard.first_search_paths = {self.candidates[0]}

    def _add_candidate(self, raw_path: str, *, front: bool = False) -> bool:
        canonical = self.service.corpus.canonicalize(raw_path)
        if canonical is None:
            return False
        path = canonical.relative
        if path in self.candidates:
            return False
        if front:
            self.candidates.insert(0, path)
        else:
            self.candidates.append(path)
        return True

    def _record(
        self,
        action: str,
        before: list[str],
        *,
        query: str | None = None,
        read_range: dict[str, Any] | None = None,
        accepted: bool = True,
        reject_reason: str | None = None,
    ) -> None:
        self.actions.append({
            "i": len(self.actions),
            "action": action,
            "query": query,
            "candidates_before": before,
            "candidates_after": list(self.candidates),
            "read_range": read_range,
            "accepted": accepted,
            "reject_reason": reject_reason,
            "elapsed_ms": int((time.perf_counter() - self.started) * 1000),
        })

    def _reject(self, message: str, *, code: str | None = None) -> dict[str, Any]:
        self.tool_errors.append(message)
        if code and code not in self.failure_codes:
            self.failure_codes.append(code)
        if code == "V1":
            self.stop_reason = "V1"
        return {"ok": False, "error": message, **self._candidate_view()}

    def _candidate_view(self) -> dict[str, Any]:
        visible = list(self.candidates[:MODEL_CANDIDATE_VIEW_K])
        return {
            "candidates": visible,
            "candidate_count": len(self.candidates),
            "candidates_truncated": len(self.candidates) > len(visible),
        }

    def _candidate_summary(self) -> dict[str, Any]:
        return {
            "candidate_count": len(self.candidates),
            "candidates_truncated": len(self.candidates) > MODEL_CANDIDATE_VIEW_K,
        }

    def _expected_static(self) -> tuple[str, str | None] | None:
        if not self.static:
            return None
        if self._static_cursor >= len(self._static_plan):
            return ("finish", None)
        return self._static_plan[self._static_cursor]

    def _advance_static(self) -> None:
        if self.static:
            self._static_cursor += 1

    def _plan_after_expand(self) -> None:
        unread = [path for path in self.candidates if path not in self.read_paths]
        selected = unread[:STATIC_PRE_GRAPH_READS]
        self._static_plan.extend(("read_candidate", path) for path in selected)
        follow = selected[0] if selected else (self.candidates[0] if self.candidates else None)
        if follow:
            self._static_plan.append(("follow_link", follow))
        else:
            self._static_plan.append(("finish", None))

    def _plan_after_follow(self, discovered: list[str]) -> None:
        if self._static_graph_planned:
            return
        self._static_graph_planned = True
        unread = [
            path for path in [*discovered, *self.candidates]
            if path not in self.read_paths
        ]
        unique = list(dict.fromkeys(unread))[:STATIC_POST_GRAPH_READS]
        self._static_plan.extend(("read_candidate", path) for path in unique)
        self._static_plan.append(("finish", None))

    @property
    def read_paths(self) -> set[str]:
        return {str(item["path"]) for item in self.reads}

    def _check_static(self, name: str, path: str | None) -> dict[str, Any] | None:
        expected = self._expected_static()
        if expected is None:
            return None
        expected_action, expected_path = expected
        if name != expected_action:
            return self._reject(
                f"static protocol expected {expected_action!r}, got {name!r}",
                code="V1",
            )
        if expected_path is not None and path != expected_path:
            return self._reject(
                f"static protocol expected path {expected_path!r}, got {path!r}",
                code="V1",
            )
        return None

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._requests += 1
            name = request.get("action")
            if name == "status":
                expected = self._expected_static()
                return {
                    "ok": True,
                    **self._candidate_view(),
                    "retrieval_actions_used": self._retrieval_actions,
                    "retrieval_actions_limit": self.max_retrieval_actions,
                    "terminal_rejections": self.guard.terminal_attempts,
                    "stop_reason": self.stop_reason,
                    "static_next": (
                        {"action": expected[0], "path": expected[1]}
                        if expected else None
                    ),
                }
            if name not in {
                "search", "follow_link", "expand_candidates",
                "read_candidate", "finish",
            }:
                return self._reject(f"unknown host action: {name!r}", code="C2")
            if self.stop_reason:
                return self._reject(f"run already stopped: {self.stop_reason}")

            requested_path = _safe_relative(request.get("path"))
            static_rejection = self._check_static(name, requested_path)
            if static_rejection:
                return static_rejection
            if name != "finish" and self._retrieval_actions >= self.max_retrieval_actions:
                return self._reject("retrieval action budget exhausted", code="C1")

            before = list(self.candidates)
            try:
                if name == "search":
                    query = request.get("query")
                    if not isinstance(query, str) or not query.strip():
                        return self._reject("search query must be non-empty")
                    normalized = query.strip()
                    if self.static and self._static_cursor == 0 \
                            and normalized != self.case.get("query"):
                        return self._reject(
                            "static first search must use the public case query", code="V1")
                    if self.static and self._static_cursor == 1 \
                            and normalized.casefold() in self.guard.queries:
                        return self._reject(
                            "static second search must reformulate the query", code="V1")
                    result = self.service.search(
                        normalized,
                        output_k=self.output_k,
                        candidate_pool_k=self.candidate_pool_k,
                    )
                    visible = list(result.get("retrieved_paths") or [])
                    pool = list(result.get("candidate_pool") or [])
                    self._candidate_pools.append(pool)
                    first_search = self.guard.first_search_paths is None
                    for candidate in visible:
                        self._add_candidate(candidate)
                    self.guard.observe("reformulate_query", normalized,
                                       visible[0] if visible else None)
                    if first_search:
                        self.guard.first_search_paths = set(visible)
                    self._retrieval_actions += 1
                    self._record("reformulate_query", before, query=normalized)
                    self._advance_static()
                    return {
                        "ok": True,
                        "action": "search",
                        "result_paths": visible,
                        "review_required": result.get("review_required", False),
                        **self._candidate_summary(),
                        "static_next": self._static_next_payload(),
                    }

                if name == "expand_candidates":
                    discovered: list[str] = []
                    for pool in self._candidate_pools:
                        for candidate in pool:
                            if len(self.candidates) >= self.candidate_pool_k:
                                break
                            if self._add_candidate(candidate):
                                discovered.append(candidate)
                    for path in list(self.candidates):
                        for candidate in self.service.corpus.links(path):
                            if self._add_candidate(candidate):
                                discovered.append(candidate)
                    self.guard.observe("expand_candidates", None, None)
                    self._retrieval_actions += 1
                    self._record("expand_candidates", before)
                    self._advance_static()
                    if self.static:
                        self._plan_after_expand()
                    return {
                        "ok": True,
                        "action": "expand_candidates",
                        "result_paths": discovered[:MODEL_CANDIDATE_VIEW_K],
                        "result_path_count": len(discovered),
                        **self._candidate_summary(),
                        "static_next": self._static_next_payload(),
                    }

                if name == "follow_link":
                    if not requested_path or requested_path not in self.candidates:
                        return self._reject(
                            "follow_link path must be an observed candidate")
                    discovered = []
                    linked = list(self.service.corpus.links(requested_path))
                    try:
                        linked.extend(
                            self.service.backlinks(requested_path, limit=20)["backlinks"]
                        )
                    except ServiceError as exc:
                        self.tool_errors.append(f"backlinks degraded: {exc}")
                    for candidate in dict.fromkeys(linked):
                        if self._add_candidate(candidate):
                            discovered.append(candidate)
                    self.guard.observe("follow_link", None, requested_path)
                    self._retrieval_actions += 1
                    self._record("follow_link", before)
                    self._advance_static()
                    if self.static:
                        self._plan_after_follow(discovered)
                    return {
                        "ok": True,
                        "action": "follow_link",
                        "from_path": requested_path,
                        "result_paths": discovered[:MODEL_CANDIDATE_VIEW_K],
                        "result_path_count": len(discovered),
                        **self._candidate_summary(),
                        "static_next": self._static_next_payload(),
                    }

                if name == "read_candidate":
                    if not requested_path or requested_path not in self.candidates:
                        return self._reject(
                            "read_candidate path must be an observed candidate")
                    start = request.get("start", 1)
                    end = request.get("end", 80)
                    if (not isinstance(start, int) or not isinstance(end, int)
                            or start < 1 or end < start or end > MAX_READ_END):
                        return self._reject(
                            f"read range must satisfy 1 <= start <= end <= {MAX_READ_END}")
                    result = self.service.read(
                        requested_path, line_start=start,
                        line_count=end - start + 1,
                    )
                    actual = {
                        "path": result["canonical_path"],
                        "start": result["line_start"],
                        "end": result["line_end"],
                    }
                    self.reads.append(actual)
                    self.guard.observe("read_candidate", None, actual["path"])
                    self._retrieval_actions += 1
                    self._record("read_candidate", before, read_range=actual)
                    self._advance_static()
                    numbered = "\n".join(
                        f"{number}: {line}" for number, line in enumerate(
                            result["content"].splitlines(), start=result["line_start"])
                    )
                    return {
                        "ok": True,
                        "action": "read_candidate",
                        "path": actual["path"],
                        "start": actual["start"],
                        "end": actual["end"],
                        "content": numbered,
                        **self._candidate_summary(),
                        "static_next": self._static_next_payload(),
                    }

                terminal = request.get("terminal_action")
                if terminal not in {"answer", "abstain"}:
                    return self._reject(
                        "finish requires terminal_action answer or abstain")
                reason = self.guard.check(terminal) if self.guard_enabled else None
                if reason:
                    self.guard.terminal_attempts += 1
                    rejection = {
                        "i": len(self.actions), "action": terminal, "reason": reason,
                    }
                    self.guard_rejections.append(rejection)
                    self._record(terminal, before, accepted=False,
                                 reject_reason=reason)
                    if self.guard.terminal_attempts >= MAX_TERMINAL_ATTEMPTS:
                        return self._reject(
                            "terminal action refused too many times", code="C1")
                    return {
                        "ok": False,
                        "error": "terminal action refused",
                        "reason": reason,
                        **self._candidate_view(),
                    }
                self.stop_reason = terminal
                self._record(terminal, before)
                self._advance_static()
                return {
                    "ok": True,
                    "action": "finish",
                    "terminal_action": terminal,
                    **self._candidate_summary(),
                }
            except ServiceError as exc:
                return self._reject(f"retrieval service error: {exc}")

    def _static_next_payload(self) -> dict[str, Any] | None:
        expected = self._expected_static()
        if expected is None:
            return None
        payload: dict[str, Any] = {"action": expected[0]}
        if expected[1] is not None:
            payload["path"] = expected[1]
        return payload

    def trace_fields(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "reads": list(self.reads),
            "guard_rejections": list(self.guard_rejections),
            "failure_codes": list(dict.fromkeys(self.failure_codes)),
            "tool_errors": list(self.tool_errors),
            "stop_reason": self.stop_reason,
            "n_search": sum(
                step["action"] == "reformulate_query" and step["accepted"]
                for step in self.actions
            ),
            "n_read": len(self.reads),
            "retrieval_actions": self._retrieval_actions,
            "requests": self._requests,
            "wall_clock_ms": int((time.perf_counter() - self.started) * 1000),
        }


class _ToolHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            line = self.rfile.readline(1024 * 1024)
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            response = self.server.state.dispatch(request)  # type: ignore[attr-defined]
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as exc:
            response = {"ok": False, "error": f"invalid host request: {exc}"}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))


class ToolServer:
    """Short-lived Unix socket server for one subject process."""

    def __init__(self, socket_path: Path, state: FactorialHostState) -> None:
        if socket_path.exists():
            raise FactorialRuntimeError(f"socket path exists: {socket_path}")
        self.server = socketserver.ThreadingUnixStreamServer(
            str(socket_path), _ToolHandler)
        self.server.state = state  # type: ignore[attr-defined]
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )
        self.socket_path = socket_path

    def __enter__(self) -> "ToolServer":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.socket_path.exists():
            self.socket_path.unlink()
