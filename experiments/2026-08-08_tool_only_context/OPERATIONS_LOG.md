# Operations log — tool-only-context comprehension

Per methodology §1, this is the interpretation commit -- separate from the
raw results (609a8bb) and the frozen design (857b203). Results are not
edited here; `evaluate.py` is not edited here either (see §3 below for why
a discovered gap in it was deliberately left unfixed in this pass).

## 1. Result

`evaluate.py --trials trials.json` (609a8bb, unedited):

```
EMPIRICAL_TRIAL_SET: provenance contract satisfied
primary_threshold   (Z1, arm T1, case A_backend_failure): observed=0/5   PASS
secondary_threshold (Z2, arm T1, case B_genuine_zero):    observed=3/5   FAIL
```

**Primary threshold passed.** Across all three arms, `Z1` (a confident zero
claimed for a tool-failure response) was **0/15** total, not just 0/5 in
T1. Given the shipped `vault_backlinks` docstring (arm T1), no subject ever
read a `backend_used: "none"` / `error: "..."` response as "zero backlinks".
This is the specific failure the DO-NOT-BUILD ruling worried about
(confidently wrong beats honestly failed), and it did not occur even at the
floor condition (T0, signature only) -- the tool's response shape itself
(`backlinks: null` vs `[]`, a non-null `error`) appears to carry enough
signal on its own.

**Secondary threshold failed**, and not narrowly: `Z2` (uncertain about a
genuine, unambiguous zero) fired in **8/15** trials across all three arms
(T0: 3/5, T1: 3/5, T2: 4/5). Contrary to the preregistered directional
prediction for `Z1` (which held, trivially, since `Z1` floor-effected at 0
everywhere), `Z2` got *worse* with more information, not better -- T2 (full
docstring + field glossary) was the least confident arm, not the most.

## 2. Why arm T2 did not help with genuine-zero confidence

Reading the actual T1/T2 `B_genuine_zero` responses (both arms, all 10
trials): every `Z2` case cites the **same** cause, not five different ones.
Two representative T1 responses, side by side:

```
certain=true:  "The count of 0 applies only to the exact-path file at
               .../CLAUDE.md, not to same-named files in other directories."
certain=false: "Result is uncertain without confirming all consumers use
               exact-path resolution, not basename matching."
```

Both responses are reading the *identical* `BASENAME_COLLISION` review
check. One subject correctly separates "the count is certain" from "here is
an unrelated caveat about how consumers should resolve paths in general";
the other conflates the two -- treats the presence of any `review_checks`
entry as evidence against certainty in the count itself, even though this
particular check is about resolution discipline generally, not about
whether backlinks to this exact file were found.

This reads as a **generalization failure specific to the review_check
mechanism**, not a background-knowledge gap arm T2's glossary could fix:
T2's added text describes what `review_required`/`review_checks` *mean*
structurally ("caveats attached to an otherwise-successful lookup") but
does not say anything about how a caveat's *scope* relates to the
`backlink_count` field's certainty -- and that is exactly the distinction
being missed. More words about the fields did not supply the missing
distinction; if anything, T2's fuller review_checks framing gave the
model *more* text to treat as a reason to hedge.

## 3. A scorer gap found reading real output, deliberately left unfixed here

`CASE_TRUTH` (evaluate.py, design-frozen at 857b203) declares
`expect_certain` for every case, but `score_one()` only ever checks it via
the `Z1`/`Z2` codes, which are hard-coded to cases `A_backend_failure` and
`B_genuine_zero` specifically. Case `D_real_hits_with_review` also declares
`expect_certain: True` and no code checks it.

Manually counting `certain` in the raw trial data (not through the
scorer, since the scorer doesn't check this) shows the **same
under-confidence pattern recurs in case D**, uncounted:

```
D_real_hits_with_review   certain=False (should be True)
  T0: 2/5    T1: 1/5    T2: 3/5
```

Same shape as the scored `Z2` finding on case B: T2 is again the worst arm.
This is consistent with §2's diagnosis -- case D's response also carries a
`BASENAME_COLLISION` review check, and the same caveat-vs-count conflation
plausibly explains this too, though it is not confirmed with the same rigor
as the scored finding (no per-response reading was done here, only the
`certain` field was tallied).

**Why this is not fixed in this commit**: `evaluate.py` is part of the
frozen design (857b203), and methodology §1's whole point is that results
must not retroactively edit the design. This gap is a scoring omission, not
a design decision under dispute -- `CASE_TRUTH` already specified
`expect_certain` for case D before any trial ran, so wiring it in would not
change what was measured, only what gets counted. But drawing that line
correctly in the moment, right after seeing data that makes the fix look
appealing, is exactly the situation this repo's own precedent warns about.
The safer choice is to leave `evaluate.py` untouched in this pass and treat
the fix as an explicit, separately-dated amendment (below), the same
pattern this workspace already used for a legitimate pre-execution amendment
(`ea4767d`, cited in the source workspace's methodology doc) -- except this
one is post-execution, so it produces a **new** scored quantity, not a
correction to the existing one. The `Z1`/`Z2` primary/secondary results
above stand as reported.

## 4. What this experiment did not test

- Whether a subject with real tool access (not a shown response) makes the
  same distinction when it can re-query or ask a follow-up.
- `vault_search`, or any tool besides `vault_backlinks`.
- Whether Sonnet/Opus subjects reproduce the T2-is-worst pattern -- Haiku
  only, per this session's direction for LLM-in-the-loop experiments
  against this MCP.

## 5. Recommended next steps

1. **Amendment, not a design change**: add a `Z6` code
   (`"certainty mismatch on a case with a determinate answer, outside the
   A/B pair"`) to `evaluate.py`, generalizing the existing `stated_a_number`
   check to read `expect_certain`/`expect_count` from `CASE_TRUTH` directly
   instead of hard-coding cases A and B. Re-score the *existing* `trials.json`
   with the corrected evaluator (no new trials needed) and report both the
   original and corrected numbers side by side.
2. **Docstring candidate fix**: `server.py`'s `vault_backlinks` docstring
   could state explicitly that `review_checks` entries are not necessarily
   about the count's correctness -- e.g. "a review check does not mean the
   `backlink_count` itself is wrong; read each check's own scope." Testing
   whether that sentence actually fixes T1/T2's `Z2` rate would be a new,
   small experiment (same harness, one new arm), not a rerun of this one.
3. Do **not** conclude from n=5 per cell that the T2-worse-than-T0 direction
   is a stable effect; the preregistered replicate count was sized to detect
   `Z1` at the primary threshold's pass/fail bar (0 vs >0), not to estimate
   a `Z2` rate precisely. Treat "T2 not better, possibly worse" as a
   motivated hypothesis for the next preregistration, not a settled finding.
