# CLAUDE.md 공허 패턴 감사 — 2026-08-12

대상: `Project_in_progress/CLAUDE.md`(vault 루트, 3,033 B)와 그것이 처방하는
`.vault-harness/vault-md-retrieval/vault_retrieval_agent_tool.py`.

**왜 이 저장소에 기록하는가**: 이 감사의 결론이 D2(`review_required`가 늘 참)의
**설계 입력**이다. 무엇을 만들지가 아니라 **무엇을 만들면 안 되는지**를 정한다.
`.vault-harness/`는 읽기만 했고 아무것도 수정하지 않았다.

공허한 패턴 = **조건이 늘 참이거나 늘 거짓이어서 따라도 아무것도 구별되지 않는
문장**. 주장이 아니라 측정으로 판정했다.

## 0. 이 감사가 스스로 정정한 것

첫 가설은 "harness의 `review_required`도 우리 D2처럼 항상 같은 값"이었다.
자연스러운 질의 6개(정답 있음 2, 알려진 recall 실패 1, 정답 없음 1, 무의미
토큰 1, 불용어 1)에서 **6/6 모두 `false`, `status: complete`, `checks: []`**가
나왔고 여기서 멈췄으면 "늘 거짓"으로 적었을 것이다.

**poison test가 그 가설을 죽였다** — 각 check의 조건을 만족하도록 설계한 질의를
넣었더니 6종 중 3종이 발화했다:

```
target check                      review_required  codes
NO_CONTEXT                        True             ['NO_CONTEXT']
SAME_BASENAME                     True             ['SAME_BASENAME']
SAME_BASENAME(en)                 True             ['SAME_BASENAME']
NAVIGATION_WITHOUT_AUTHORITY      False            []
NAVIGATION_WITHOUT_AUTHORITY(2)   False            []
WORKTREE_POLICY_CROSSCHECK        True             ['WORKTREE_POLICY_CROSSCHECK']
CONTEXT_BUDGET_DROPPED_PATHS      False            []
```

**`review_required`는 공허하지 않다.** 우리 MCP의 D2와 다른 결함이다. 자연 질의
6/6이 `false`인 것은 "늘 거짓"이 아니라 **아래 V1이다.**

`--compact` 때문도 아니다(플래그 없이 실행해도 동일). `review_required =
bool(checks)`이므로 원인은 전적으로 `exception_checks()`에 있다.

## V1. step 3은 증거가 아니라 **질의 어휘**로 발화한다 (코드 확정)

CLAUDE.md 27-28행:

> If it returns `review_required`, execute every `review_checks[].required_action`

이 문장은 일반적 안전망처럼 읽힌다. 실제 구현은 **키워드 tripwire**다.
`vault_retrieval_agent_tool.py:235-246`:

```python
path_identity_query = (any(m in folded for m in PATH_IDENTITY_MARKERS)
                       or ".md" in folded)
if ambiguous and path_identity_query:      # ← AND
    add_check(checks, "SAME_BASENAME", ...)
```

`ambiguous`(동명 파일이 실제로 여러 벌 회수됨)는 **증거**이고
`path_identity_query`는 사용자가 "동명"·"basename"·`path=`·`.md` 중 하나를
**입력했는지**다. 둘이 AND이므로:

> **동명 파일이 실제로 여러 벌 회수돼도, 질의에 그 단어가 없으면 경고가 나오지
> 않는다.**

`WORKTREE_POLICY_CROSSCHECK`도 같은 구조다(marker 8종: `reuse-now`,
`재사용`, `active worktree` …). 위험은 **회수 결과**에 있는데 발화는 **질문
문장**이 정한다. 위 6개 자연 질의가 전부 `complete`였던 이유가 이것이다 —
그 질의들에 marker가 없었을 뿐이다.

**우리 D2와의 관계**: 두 시스템이 정반대로 고장 나 있고 **정보량은 둘 다 0에
가깝다.**

| | 값 | 결과 |
|---|---|---|
| evidence-evaluator MCP | 늘 `true` | 늘 참이라 agent가 무시한다 |
| harness tool | 어휘가 맞을 때만 `true` | 위험한데 조용한 경우가 생긴다 |

## V2. blocking 등급 check 하나가 **구조적으로 발화 불가**다 (측정)

`NAVIGATION_WITHOUT_AUTHORITY`는 `severity="blocking"`이고, CLAUDE.md 62-63행
("Generated MOCs are navigation artifacts, not source authority")의 **유일한
집행 장치**다. 조건은 "navigation marker가 있고 **AND** P0/P1/P2 non-MOC
authority 문서가 하나도 없을 때".

marker는 맞췄는데도 발화하지 않았다. 이유를 측정했다:

```
query: canonical path backlink zqxjv9f8e7d          ← 무의미 토큰 포함
  observations=32  authority(non-MOC, P0/P1/P2)=15
  histogram: {'N0-navigation-view': 10, 'L0-frozen-provenance': 5,
              'P2-path-stable': 5, 'P1-direct-precedent': 5, ...}

query: MOC 목차 backlink 백링크
  observations=32  authority(non-MOC, P0/P1/P2)=12
```

**pool refill이 늘 32개를 채우고 그중 9~15개가 authority 등급을 달고 온다.**
질의가 무의미해도 그렇다. 따라서 조건의 뒷항("authority가 하나도 없다")은
사실상 성립할 수 없다.

곧 **recall을 올린 바로 그 기능(pool refill)이 blocking 게이트 하나를
무력화했다.** 이 저장소가 이미 이름 붙인 "게이트가 게이트를 가린다"와 같은
형태다. 게이트를 추가할 때 앞선 게이트의 변이 커버리지가 사라졌는지 재라는
규칙이 여기서도 적용된다.

발화하지 않은 나머지 2종:

- `CONTEXT_BUDGET_DROPPED_PATHS` — 조건이 `len(paths) < min(16, retrieved)`.
  `output_k=8`이면 `8 < 8`은 거짓이라 **기본 설정에서 도달 불가**로 보인다.
  (조건 읽기까지만 했고 poison test로 확정하지 않았다 — **가설**이다.)
- `GRAPH_UNAVAILABLE` — graph가 살아 있는 lane에서는 발화하지 않는 것이 정상.
  공허가 아니라 **이 lane에서 미검증**이다.

## V3. 절차를 정당화하는 숫자가 출처의 유보를 떼고 인용됐다

CLAUDE.md 33-35행:

> measured: initial lexical search reached recall 0.688, two graph walks
> reached 1.000

출처 `.vault-harness/vault-md-retrieval/MULTITURN_EXPERIMENT.md:80-96`:

| Policy | Turn 1 | Turn 2 | Turn 3 | Turn 4 |
|---|---:|---:|---:|---:|
| `recall-first-v2` | 0.688 | 0.812 | 0.958 | **1.000** |

같은 문서가 그 표 앞뒤에 이렇게 적는다:

> "The public Markdown development set has **eight cases**. It is **too small
> for a production decision**…"
>
> "**These public-v1 scores did not generalize to the frozen held-out v3 set.**
> `recall-first-v2` reached final Recall **0.802**…"

CLAUDE.md는 **N=8도, 일반화 실패도, held-out 0.802도 옮기지 않았다.** 셋 중
어느 하나만 있어도 독자의 신뢰도가 달라진다.

덧붙여 **"two graph walks"가 표와 어긋난다** — 1.000은 turn 4이고, turn 1이
lexical이므로 graph walk는 **세 번**이다. 두 번(turn 3) 시점은 0.958이다.

이 문장이 이 파일에서 가장 무거운 공허 생산자다. 규칙 전체의 **근거**로 놓여
있어서, 읽는 사람이 검증 없이 통과시킨다.

## V4. "validated" + "재도출하지 마라"의 결합

CLAUDE.md 37행:

> The full procedure is already written and validated. **Do not re-derive it**

"재도출 금지"는 정당한 목적이 있다(바퀴 재발명 방지). 문제는 **검증 불가능한
라벨과 확인 금지가 한 문장에 묶인 것**이다. V3에서 보듯 "validated"는 held-out
0.802를 포함한 이력을 가리는데, 그 아래 줄이 확인을 막는다. 이 조합은 뒤따르는
agent에게 **공허를 상속시킨다.**

## V5. `rg-only`가 이진 조건인데 실제 실패는 경로별이다

CLAUDE.md 50-51행: "If the CLI is unavailable, say `rg-only`".

우리 실제 Vault E2E 실측: 같은 세션 안에서 CLI가 어떤 경로엔 **응답하고**
(`fallback_used: null`, backlink 5건) 어떤 경로엔 `File not found`를 낸다
(dot-디렉터리·중첩 worktree). "unavailable"이 참/거짓 하나로 정해지지 않는다.

경로 A에서 성공을 본 agent가 "CLI 사용 가능"으로 판정하고 경로 B의 실패한
응답을 조용히 신뢰하게 된다. **이진 틀이 잘못된 추론을 허가한다.**

이미 알려진 항목이다 — 2026-08-08 감사 §7이 "`rg-only` 종단 상태 미정의"를
유효 인정으로 기록했고 **아직 열려 있다**.

## V6. 6단 권위 순서를 순위에 구현한 도구가 없다

CLAUDE.md 53-60행이 6단 권위 순서를 정하고 `archive/`를 **최하위(6)**로 둔다.
그러나 우리 MCP 실측(`docs/HANDOFF.md` §6a): archive stale 문서가 **pool 2위,
top-8 진입**, 현재판은 **10위, 8칸 밖**. 우리 쪽 RRF에는 권위 항이 아예 없다.

harness tool은 `authority_class`(P0/P1/P2/N0/L0)를 관측치에 **붙이기는 한다**.
다만 **그것이 순위에 쓰이는지는 측정하지 않았다** — 이 문서는 그 점을 주장하지
않는다.

세 어휘가 서로 다르다: CLAUDE.md의 6단, harness의 `authority_class`,
evidence-evaluator의 **없음**.

## V7. 이미 기록된 것 (재도출하지 않음)

`notes/audits/vault/claude-md-divergence-audit-2026-08-08.md` §4가 이미 적었다 —
CLAUDE.md 활성본이 backlink 1홉의 가치를 실측으로 논증하면서 **정작 자신은
나가는 wikilink가 0**이고 받는 backlink도 0이다. 규칙과 자기 적용의 불일치.

## D2 설계에 대한 결론

**D2를 회수율보다 먼저 고치는 판단이 이 측정으로 뒷받침된다.** 그리고 V1이
**어떻게 고치면 안 되는지**를 준다.

1. **늘 참으로 두지 마라** (지금 우리 상태) — 무시된다.
2. **질의 어휘로 발화시키지 마라** (harness의 V1) — 위험이 조용해진다.
3. **회수 결과의 관측 가능한 속성으로 발화시켜라** — 동명 회수 여부, fallback
   사용 여부, 정본/사본 혼재 여부처럼 **질문이 아니라 답에 있는 것**.
4. **게이트를 추가한 뒤 앞선 게이트가 여전히 발화하는지 재측정하라** (V2).
5. **회귀 테스트는 poison test여야 한다** — "성공한 검색이 `false`를 낼 수
   있다"와 "실제로 흔들린 검색이 `true`를 낸다" **둘 다** 필요하다. 한쪽만
   있으면 반대편 공허를 못 잡는다.

## 이 문서가 주장하지 않는 것

- **CLAUDE.md를 고쳤다** — 고치지 않았다. 읽고 측정만 했다.
  `.vault-harness/`도 수정하지 않았다.
- **`review_required`가 공허하다** — 아니다(§0). V1은 "공허"가 아니라
  "발화 조건이 증거가 아니라 어휘"다.
- **`CONTEXT_BUDGET_DROPPED_PATHS`가 도달 불가다** — 조건을 읽은 **가설**이고
  poison test로 확정하지 않았다.
- **harness의 `authority_class`가 순위에 쓰이지 않는다** — 측정하지 않았다.
- 위 수치는 전부 **host lane**, 인덱스 `built_at 2026-08-05`, 문서 1,766개
  기준이다.

## 재현

```bash
python3 /Users/jaehyuntak/.claude/jobs/<job>/tmp/probe_review.py    # 자연 질의 6개
python3 /Users/jaehyuntak/.claude/jobs/<job>/tmp/poison_checks.py   # check 6종 발화 시험
python3 /Users/jaehyuntak/.claude/jobs/<job>/tmp/why_nav_never.py   # V2 원인
```

스크립트는 job tmp에 있어 세션과 함께 사라진다. 유지가 필요하면 이 저장소
`tests/`로 옮기되, **poison test 형태를 유지하라** — 발화를 확인하지 않는
회귀 테스트는 이 문서가 기록한 결함을 그대로 재생산한다.
