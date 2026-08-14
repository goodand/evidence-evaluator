# Handoff confirmatory result — 2026-08-14

## Result

The frozen `handoff-confirmatory-v1` set was executed once per case with a
fresh ephemeral Codex subject using model `gpt-5.6-sol`. Each subject could use
only the MCP tools `vault_search`, `vault_read`, and `vault_backlinks`.

Freeze digest:
`5187e0e9442b70131eb8bdc440f5d6990076d44198912ae721946ef3afe3c255`

| Layer | Result |
|---|---|
| Runtime | 6/6 valid; 0 invalid runs |
| Retrieval | 6/6 full critical-path and navigation recall; 6/6 exact authority hits |
| Reconstruction | 6/6 correct state, next action, and stop conditions |
| Evidence | 6/6 claims supported by actual reads and authority citations |

All six cases were accepted on their first and only subject run. The subjects
made 20 MCP calls in total, or 3.33 calls per case.

## Case observations

| ID | Tested condition | Result |
|---|---|---|
| CONF-01 | paraphrased request | accepted |
| CONF-02 | Korean alias to English canonical material | accepted |
| CONF-03 | multi-hop navigation | accepted |
| CONF-04 | dated superseded collision | accepted |
| CONF-05 | active/archive same-name collision | accepted |
| CONF-06 | backlink-entry vocabulary | accepted |

`CONF-06` is the clearest graph-follow observation. Its deterministic search
qualification placed the authority outside the output top three, but the live
subject read the entry and handoff and then reached the authority. This shows
that the complete search/read workflow succeeded for this case. It does not
isolate backlinks as the causal mechanism.

## Provenance

The six original subject artifacts and their aggregate summary are ignored
under `results/`. Corpus, case definitions, and gold remain ignored under
`private_eval/handoff-confirmatory-v1/`. They must not be committed to the
public repository.

The frozen inputs and harness were not changed between or after the six runs.
Run the following command to verify the freeze:

```bash
python3 scripts/verify_handoff_confirmatory_freeze.py \
  private_eval/handoff-confirmatory-v1
```

## Claims not established

This six-case synthetic result does not establish:

- vault-wide recall;
- performance on a naturally evolved project vault;
- an effect relative to grep-only or another workflow;
- an effect from static versus dynamic search behavior;
- an effect from using a retrieval subagent;
- backlinks as a necessary causal component;
- model-to-model generalization.

Those claims require separate arms, larger independently curated samples, or
both. This result establishes only that the frozen zero-context MCP handoff
path completed end to end on all six confirmatory cases.
