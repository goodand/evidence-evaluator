# Codex Commit Log

- Repository: `goodand/evidence-evaluator`
- Working tree: `/Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator`
- Recorded: 2026-08-12
- Recorder: Codex
- Local branch: `main`
- Current local tip: `745323c`
- Remote state at recording time: `origin/main` was not present in the local remote-tracking refs; remote ref inspection was also blocked by DNS/network failure.

## Purpose

This log records the commits Codex organized and verified while extracting a reusable,
read-only evidence-evaluator and Obsidian Markdown retrieval service. It is an engineering
history, not an evaluation result and not an authorization for live or paid experiments.

The repository boundary is deliberately narrow:

- reusable evaluator and retrieval code;
- generic schemas, tests, documentation, and example profile;
- no project-specific corpus, hidden gold, answer keys, live results, credentials, or
  dynamic-controller qualification machinery.

## Commit sequence

| Order | Commit | Date | Role | Verification / boundary |
|---:|---|---|---|---|
| 1 | `a3be5a4` | 2026-08-08 | Extract portable `evidence-evaluator` engine from the handoff dynamic-controller experiment | Established the reusable engine boundary and generic evidence-gathering schema. Project data and experiment-specific protocol stayed outside this repository. |
| 2 | `9e13b47` | 2026-08-08 | Fix review findings: broken quickstart, dropped arm, dead link, and vacuous test coverage | Corrected user-facing setup and evaluator behavior; added the corresponding regression coverage. |
| 3 | `00a21ca` | 2026-08-09 | Fix `run_clean_judge()` integrity verification on its default path | Closed the path where the integrity check existed but was silently skipped. The change preserves the evaluator's source-integrity boundary. |
| 4 | `31b1892` | 2026-08-09 | Repair README quickstart and stale test-count documentation | Made the documented startup path runnable and aligned the documentation with the measured local suite. |
| 5 | `f23ffbe` | 2026-08-09 | Fix schema validation and ignore nested worktrees | Prevented unsupported schema keywords from passing silently and excluded nested Claude worktrees from repository contents. This avoids maintaining accidental second copies of the same source. |
| 6 | `745323c` | 2026-08-11 | Add canonical Obsidian retrieval service | Added the reusable `evidence_evaluator.retrieval` package, profile-based path policy, filesystem Markdown corpus, exact/BM25/graph retrieval, optional Obsidian CLI integration, CLI/MCP transports, examples, design/migration docs, and 52 retrieval tests. |

## What the final commit contains

`745323c` added or changed:

- `evidence_evaluator/retrieval/profile.py`
- `evidence_evaluator/retrieval/corpus.py`
- `evidence_evaluator/retrieval/obsidian.py`
- `evidence_evaluator/retrieval/retriever.py`
- `evidence_evaluator/retrieval/service.py`
- `evidence_evaluator/retrieval/cli.py`
- `evidence_evaluator/retrieval/mcp_server.py`
- `evidence_evaluator/retrieval/__init__.py`
- `tests/test_vault_retrieval_core.py`
- `tests/test_vault_retrieval_transports.py`
- `examples/vault-profile.example.json`
- `docs/DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md`
- `docs/MIGRATION_STATUS_OBSIDIAN_RETRIEVAL.md`
- README and package metadata updates

The retrieval implementation has these intended properties:

1. `VaultProfile` owns vault root, exclusions, aliases, and authority order.
2. Filesystem Markdown retrieval remains available when Obsidian IPC is unavailable.
3. Obsidian CLI calls use `cwd=vault_root`; `vault=` is only a compatibility hint.
4. Symlink aliases resolve to canonical in-root Markdown paths and are not sent to Obsidian.
5. Exact, BM25, and graph evidence are fused under a recall-first policy.
6. `candidate_pool_k` and `output_k` are separate, while caller-visible paths remain bounded by
   `output_k`.
7. Zero hits, budget exhaustion, and partial CLI failure are inconclusive and return warnings.
8. CLI, Python, and MCP transports share the same retrieval service rather than duplicating
   ranking or path-policy logic.

## Verification record

The final retrieval implementation was verified with 52 local tests at the time of the
commit. Additional direct host observations confirmed that Obsidian could return backlinks
for the configured vault, while the managed process lane could lack Obsidian IPC access. The
two observations are recorded as different runtime capabilities, not collapsed into one
global PASS/FAIL claim.

The following were intentionally not claimed by these commits:

- ranking parity with the project-specific `.vault-harness`;
- retrieval performance on a private live vault;
- semantic handoff reconstruction accuracy;
- static/dynamic or subagent arm effects;
- production MCP permission equivalence across Claude Code and Codex;
- any hidden-gold or paid-provider result.

## Public repository safety check

At log creation time, `git ls-files` showed no tracked `hidden_gold`, `private_eval`, answer,
result, credential, or `.env` paths. `.gitignore` excludes `private_eval/`, `hidden_gold/`,
`results/`, SQLite indexes, virtual environments, and nested Claude worktrees.

The dynamic-controller experiment and `.vault-harness` were not moved into this repository.
They remain external reference/consumer material.

## Push status

Push was not completed during this recording because the environment could not resolve
`github.com` while running `git ls-remote`. The local branch contains the six commits above
and has no local changes after this log commit. Once network access is available, the intended
non-destructive command is:

```bash
git push -u origin main
```

Before pushing, rerun `git status --short`, `git diff --check`, and the tracked-sensitive-path
check. Do not force-push or rewrite history. If the remote has since recreated `main` with
unrelated commits, fetch and inspect the divergence before choosing a merge strategy.
