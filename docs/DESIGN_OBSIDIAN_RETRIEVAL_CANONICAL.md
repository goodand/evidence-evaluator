# Canonical Obsidian Retrieval Design

Status: implementation target  
Date: 2026-08-11

## 1. Decision

`evidence-evaluator` becomes the canonical repository for reusable Obsidian
retrieval code. The existing `.vault-harness/vault-md-retrieval` tree remains
read-only reference material until parity tests pass. The dynamic-controller
experiment remains a consumer and evaluation fixture; it is not the owner of
retrieval infrastructure.

This change moves behavior, not a workspace snapshot. Project-specific paths,
active-worktree precedence, generated indexes, results, hidden gold, and model
caches do not move into this public repository.

## 2. Product boundary

The product answers two questions:

1. Can a zero-context agent retrieve the handoff and supporting documents
   needed to reconstruct current state and next action?
2. Do static/dynamic search workflows and a retrieval-only subagent improve
   that retrieval?

The retrieval package supplies the search/read mechanism. The existing
evaluator supplies experimental scoring and controller traces. Repository
release governance, paid-run authorization, safety adjudication, and the
dynamic-controller's frozen-surface machinery are outside this package.

## 3. Canonical modules

The first complete vertical slice has six cohesive modules:

| Module | Owns | Must not own |
|---|---|---|
| `profile` | vault root, CLI path, exclusions, aliases, authority-prefix order | corpus data or global workspace constants |
| `corpus` | safe Markdown inventory, canonical/replica identity, bounded reads, exact/BM25 ranking | Obsidian process lifecycle |
| `obsidian` | CLI invocation and output normalization, with `cwd=vault_root` as the vault boundary | ranking or authority decisions |
| `retriever` | recall-first turns, graph walk, RRF, pool/output separation | gold labels or answer interpretation |
| `service` | stable `search`/`read` contracts and path validation | MCP transport details |
| `mcp_server` / `cli` | read-only transports over the same service | duplicate retrieval logic |

`VaultCorpus` intentionally implements `search`, `links`, and `read`, matching
the small interface consumed by `evidence_evaluator.runner`. This permits the
same corpus to be used by live retrieval and by static/dynamic/subagent
experiments without another adapter copy.

## 4. Search pipeline

The deterministic default is recall-first:

1. Normalize the query and apply deterministic aliases.
2. Build a candidate pool using exact and in-memory BM25 channels.
3. Fuse channels with reciprocal-rank fusion (RRF).
4. Walk outgoing links and backlinks from cumulative high-ranked seeds.
5. Re-fuse lexical and graph evidence; retain up to `candidate_pool_k`.
6. Return a diverse top `output_k`, always with `candidate_pool_k >= output_k`.
7. Report turn-budget exhaustion as non-exhaustive. Never infer absence from
   zero hits.

The filesystem graph is always available. The Obsidian CLI graph is additive:
CLI failure records a warning and does not erase filesystem evidence.

The graph frontier is cumulative, not tied to a magic turn number. Each graph
turn expands the highest-ranked canonical identities that have not previously
been expanded. Newly discovered graph identities are prioritized ahead of the
unexpanded lexical tail, so a fixed display pool cannot starve a multi-hop
chain. Candidates discovered by a later lexical or graph turn therefore remain
eligible as seeds on the next turn.

## 5. Obsidian contract

- Every CLI invocation runs with `cwd` equal to the resolved vault root.
- `vault=<name>` is a compatibility hint, not the security or routing boundary.
- Output parsing accepts JSON, newline output, and Obsidian's `No ...` forms.
- A command may be retried once for transient app-discovery failures.
- Search remains read-only; no note, tag, link, index, or Obsidian setting is
  modified.
- Symlink aliases are never sent to Obsidian. They resolve to an in-root,
  non-symlink canonical Markdown path before graph lookup or reading.

## 6. Authority and security

Authority is configured, not inferred from a repository name. Ordered
`authority_prefixes` in a profile choose among byte-identical replicas; absent
configuration, a physical non-symlink path wins deterministically.

The following are fail-closed for search and read:

- paths outside the vault;
- symlink chains for reads;
- non-Markdown files;
- `.git`, virtual environments, caches, `private_eval`, and `hidden_gold`;
- profile-defined excluded path globs.

Evaluation exclusion and path security are separate policies. A filename that
looks like an evaluation report is not automatically a security boundary;
private material must be under a blocked path or explicit profile exclusion.

One profile-owned `is_blocked_path` predicate is applied at every admission
point: inventory, lexical candidates, filesystem edges, Obsidian edges, result
projection, and reads. Transport layers may not maintain their own reduced
blocklists.

`corpus` emits a canonical identity object after replica collapse. `obsidian`
accepts that object rather than an arbitrary string path, so callers cannot
accidentally send a symlink alias or a project-specific replica to the CLI.

## 7. Data and repository boundary

Tracked public assets:

- reusable source code;
- synthetic fixtures;
- example profiles without machine-specific absolute paths;
- public evaluation schemas and documentation.

Ignored or external assets:

- `private_eval/`, hidden gold, answer keys;
- live vault contents and generated search indexes;
- model caches and result runs;
- credentials and absolute user profiles.

No raw `subtree split` from the dynamic-controller experiment is allowed,
because its history contains evaluation answers. Migration is source-selected
and reviewed file by file.

## 8. Compatibility and retirement

Phase 1 adds the canonical implementation without modifying the dirty
`.vault-harness` source. The old harness can be retired or changed into a thin
wrapper only after all of these hold:

1. Synthetic lexical-miss/graph-hit E2E passes.
2. Obsidian CLI parsing and `cwd` scoping characterization tests pass.
3. Private/evaluation path negative tests pass.
4. Package CLI and MCP expose the same search/read service.
5. Representative live-vault queries are compared against the old harness and
   material recall regressions are recorded rather than hidden.

Neural rerankers, SQLite sidecars, and LLM-selected dynamic actions are later
plugins. They do not block the portable vertical slice and must not be copied
into the core before an interface and an independent benefit test exist.

## 9. Verification plan

1. Unit: profile validation, tokenization, BM25/RRF, safe path resolution,
   symlink canonicalization, and CLI output parsing.
2. Characterization: each Obsidian call uses `cwd=vault_root`; compatibility
   `vault=` never substitutes for that boundary.
3. Integration: lexical search finds an entry note and a graph walk recovers a
   zero-lexical-overlap authority note.
4. Transport: CLI and stdio MCP list only read-only search/read operations and
   return the same canonical paths.
5. Experiment compatibility: `VaultCorpus` drives the existing `run_case`
   workflow without changing evaluator semantics.
6. Red team: attempt traversal, symlink read, hidden-gold read, fabricated
   Obsidian output, `candidate_pool_k < output_k`, and no-op graph mutations.

Every service search result includes structured `exhaustive`,
`terminal_reason`, and `warnings` fields. `exhaustive` is false for zero-hit,
budget-limited, or partially unavailable graph runs; CLI and MCP render that
field but do not derive a different absence claim.

## 10. Non-goals for this change

- Moving or deleting active experiment artifacts.
- Publishing private evaluation data.
- Reproducing every project-specific authority heuristic.
- Claiming retrieval parity from unit tests alone.
- Running a paid/live model experiment.
