# Independently curated handoff confirmatory set — 2026-08-14

## Status

`handoff-confirmatory-v1` is **frozen-unrun**. No live subject has received any
of its six questions or corpus files.

Freeze digest:
`5187e0e9442b70131eb8bdc440f5d6990076d44198912ae721946ef3afe3c255`

The corpus, cases, gold, qualification, curator draft, and freeze receipt are
under ignored `private_eval/handoff-confirmatory-v1/`. They must not be pushed
to the public repository.

## Independent curator

A fresh ephemeral Codex subagent generated exactly six drafts from a schema and
task brief. It had no prior conversation, native file/shell tools, user rules,
or private evaluation access. `vault_search` and `vault_read` were available,
but the event trace shows zero MCP calls; the drafts were invented rather than
copied from existing Vault material.

The curator output and provider trace are preserved under ignored `results/`.
The main agent then performed structural audit only, before any subject run.

## Cases

| ID | Difficulty | Qualification result |
|---|---|---|
| CONF-01 | paraphrase | entry, handoff, authority all top-3 |
| CONF-02 | Korean alias → English canonical | entry, handoff, authority all top-3 |
| CONF-03 | entry → embedded MOC → handoff → authority | all three files top-3 |
| CONF-04 | dated superseded collision | current entry, handoff, authority top-3 |
| CONF-05 | same-basename archive collision | active entry, handoff, authority top-3 |
| CONF-06 | backlink-entry vocabulary | entry and handoff top-3; authority pool rank 9 and linked from handoff |

Qualification used deterministic retrieval only. It did not invoke a subject or
score answers.

## Main-agent amendments before freeze

1. The paraphrase question lacked any project identifier and was ambiguous
   across a vault. The project label was added while state/action vocabulary
   remained paraphrased.
2. Dated and same-name collision drafts merely mentioned distractors. Physical
   stale/archive files were materialized so the conditions exist in the corpus.
3. Structural validation discovered that fully qualified wikilinks containing
   spaces were truncated at the first space. The parser now preserves wikilink
   syntax, and a characterization test covers links such as
   `Projects/Harbor Finch Survey/Handoff`.

The parser correction occurred before freeze and before any subject execution.
No question, gold code, or live result was used to tune retrieval ranking.

## Execution boundary

Run each case through `evidence_evaluator.handoff_canary` with the frozen
profile and a new output filename. Before starting, verify every hash in
`freeze.json`; after the first live run, change status in a new result artifact,
not by rewriting the freeze receipt.

```bash
python3 scripts/verify_handoff_confirmatory_freeze.py \
  private_eval/handoff-confirmatory-v1
```

Do not repair the harness using these cases and still call their later scores
confirmatory. If a case exposes a defect that is fixed, move that case to the
development set and curate a replacement with a new freeze digest.
