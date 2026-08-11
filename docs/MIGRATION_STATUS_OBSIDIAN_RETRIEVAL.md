# Obsidian Retrieval Migration Status

## Status

`evidence_evaluator.retrieval` is the canonical reusable implementation for
read-only Markdown vault retrieval. It is implemented in this repository and
has synthetic transport coverage. It is **not** yet a replacement claim for
the project-specific ranking policy in
`Project_in_progress/.vault-harness/vault-md-retrieval`.

The source harness remains read-only during this migration. Consumers should
adopt the new profile-based service rather than importing source-harness
internals. A compatibility adapter for an existing consumer such as
`vault-backlinks-mcp` is a later, separately tested migration.

## Boundary

Moved into this repository:

- profile-owned path and authority policy;
- filesystem Markdown corpus, canonical identity, local links and backlinks;
- recall-first exact/BM25/graph retrieval;
- optional Obsidian CLI graph adapter;
- shared Python service, CLI, and read-only MCP transport.

Deliberately external:

- every project vault and its index lifecycle;
- cases, hidden gold, private evaluation material, and run results;
- dynamic-controller qualification, approval, provider, and audit protocol.

This prevents copying the source experiment's public `hidden_gold` history
into a reusable search package. See the ownership decision in
[`DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md`](DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md).

## Implemented invariants

1. A single `VaultProfile` policy controls inventory, search, reads, and
   graph edges. VCS directories, `hidden_gold`, `private_eval`, dependency
   trees, and symlink escape paths are blocked before content is exposed.
2. A symlink alias resolves to its canonical physical Markdown file. Alias
   paths are never returned as separate authority and are not sent to
   Obsidian CLI.
3. Local Markdown/wiki links provide graph traversal even without Obsidian.
   Obsidian links/backlinks add edges only when the CLI can answer for the
   canonical path.
4. Graph discoveries use a separate cumulative frontier. Lexical candidate
   truncation cannot suppress an eligible graph neighbor on a later turn.
5. CLI, MCP, and Python callers use `RetrievalService`; transports do not
   own a second ranking or path-policy implementation.
6. `exhaustive: false`, zero hits, a turn budget stop, and CLI failure are
   inconclusive states. They require review rather than proving absence.
7. `output_k` bounds both `candidates` and `retrieved_paths`. The bounded
   `candidate_pool` is intentionally larger for a controller that wants more
   leads; total internal graph discovery is exposed only as a count.

## Verification evidence

Synthetic coverage currently verifies:

- private paths and symlink escapes cannot be searched or read;
- title-bearing Markdown links are indexed as graph edges;
- a graph-only authority document survives a small lexical candidate pool;
- diagnostics and error-like CLI output cannot become paths;
- MCP uses the same output limits as the service and rejects invalid reads;
- CLI and MCP round trips use the same service contract.
- `output_k=1` cannot expose a larger `retrieved_paths` list even when graph
  traversal found additional documents.

An implementation red-team independently found graph-frontier starvation,
Markdown title-link loss, an `exhaustive`/`complete` contradiction, MCP limit
drift, permissive CLI parsing, and uppercase `.MD` omission. Each resulted in
a code change and a regression test before this status was written.

## Actual Obsidian observation (2026-08-11)

On the host, Obsidian `1.13.4` answered a direct backlink query for the
`Project_in_progress` vault and returned four known incoming links to
`CLAUDE.md`. The same Python subprocess under the managed sandbox reported
that it could not find Obsidian, while an unsandboxed backend smoke with the
same `cwd` and command returned those links.

This is a runtime permission/IPC lane difference, not evidence that the
filesystem fallback is wrong. A server deployment must test the CLI in the
same process boundary that will serve MCP. The service retains filesystem
retrieval and returns warnings when Obsidian graph expansion is unavailable.

The final host-capable smoke used `output_k=3`, `candidate_pool_k=12`, and
three graph turns. It returned three canonical candidates, a 12-document
candidate pool, a separate discovery count, and one non-fatal warning. This
checks the transport bound without claiming ranking parity with a
project-specific profile.

## Comparison boundary

For the query `Obsidian CLI`, the source harness and new service both invoked
the live graph but returned different top-three documents. That is expected
at this stage: the source harness embeds `Project_in_progress` inclusion and
ranking policy, while the new service uses an intentionally generic profile
and therefore retains eligible worktree documents. Ranking equality is not a
migration criterion.

The required parity criteria are instead:

- canonical source identity and private-path exclusion;
- readable filesystem fallback when CLI graph access is unavailable;
- explicit warnings for unavailable live graph expansion;
- equivalent service behavior across Python, CLI, and MCP transports;
- a project profile plus retrieval evaluation before replacing a
  project-specific harness.

## Before a consumer migration

1. Create and review a vault-specific profile with explicit authority and
   exclusion rules.
2. Run a small retrieval evaluation set containing direct term, alias,
   graph-only, stale/archive, symlink, and no-evidence cases.
3. Run the MCP server in its production permission lane and record whether
   Obsidian IPC is available there.
4. Switch one consumer to the service contract; do not duplicate retrieval
   internals or raw source-harness shell-outs.
5. Keep the source harness as a read-only oracle until the consumer's
   expected recall and authority-boundary checks pass.
