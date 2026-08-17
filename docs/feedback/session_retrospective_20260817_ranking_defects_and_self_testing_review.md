# 세션 회고 — 순위 결함, 자기검증 리뷰, 그리고 내가 쓴 주의를 내가 어긴 일

작성 2026-08-17. 범위: evidence-evaluator `3e85fbd` ~ `bc74df1`,
vault-backlinks-mcp `88f8656` ~ `54474f7`.

직전 로그
[`concept-gate-codex-mcp-wt/docs/feedback/session_retrospective_20260811_forgeable_receipts_and_vacuous_guards.md`](../../../concept-gate-codex-mcp-wt/docs/feedback/session_retrospective_20260811_forgeable_receipts_and_vacuous_guards.md)가
**I147**에서 끝났으므로 이 로그는 **I148부터** 이어진다. Codex는 별도
namespace(`C-I…`)를 쓴다.

**저장 위치가 바뀌었다.** 이전 로그들은 `concept-gate-codex-mcp-wt`에 있으나,
이 세션의 대상은 evidence-evaluator와 vault-backlinks-mcp다. 세션 중
사용자가 확정한 저장소 경계("본실험은 concept-gate, handoff 평가와 obsidian
검색은 evidence-evaluator")에 따라 여기에 둔다. 번호만 이어받는다.

---

## (0) 이 세션의 주제

**내가 만든 방어를 내가 다시 반증한 횟수가, 외부가 반증한 횟수보다 많았다.**
그리고 가장 값비싼 오류 두 건은 **내가 직접 문서에 써 둔 주의를 내가 어긴
것**이었다.

---

## (1) 신규 이슈 I148~I172

### A. 실제 코드 결함 (내가 찾음)

| ID | 이슈 |
|---|---|
| **I148** | **D2 — `exhaustive`가 상수 `False`로 하드코딩.** `service.py`의 `review_required = not exhaustive or bool(warnings)`가 첫 항만으로 **언제나 참**이었다. `terminal_reason`이 이미 `graph-frontier-exhausted`/`no-lexical-entry`/`turn-budget-exhausted`를 계산해 두고 있었는데 반영하지 않았다 |
| **I149** | **D3 — graph 채널 점수가 BFS 발견 순서로 결정.** `reciprocal_rank_fusion`이 리스트 **위치**를 rank로 쓰는데 `graph_order`는 append-on-first-sighting이다. 실제 vault에서 **bm25 1위·exact 2위**(코퍼스 최고 어휘 매치)가 graph 183위로 밀려 탈락하고, **어휘 매치가 전혀 없는** 문서(graph 35위)가 8위를 차지했다 |
| **I150** | **다중성이 완전히 무시됨.** 대상 문서는 backlink 20개(query-local 3 parents)를 받지만 `if neighbor not in graph_order` 때문에 **한 번만** 카운트됐다 |
| **I151** | **`from_env()`가 순위 정책을 통째로 버렸다.** `authority_prefixes`/`excluded_globs`가 profile JSON으로만 도달 가능해, `EVIDENCE_VAULT_ROOT`로 띄우는 **정상 기동 방식**의 MCP 서버는 권위 순서 없이 돌았다. 정책이 존재하되 닿을 수 없었다 |
| **I152** | **D1b — stale archive 문서가 현재판을 이김.** C1 top-4가 전부 `archive/`였고 현재판은 pool 10위로 출력 밖 |
| **I153** | **security.py 금지 세그먼트 누락.** vault-backlinks-mcp가 `private_eval`·`.hg`·`.svn`·`.pytest_cache`·`__pycache__`를 빠뜨렸다(evidence-evaluator엔 있음) |
| **I154** | **CLAUDE.md step 3이 증거가 아니라 질의 어휘로 발화.** `if ambiguous and path_identity_query` — 동명 파일이 실제로 회수돼도 질의에 "동명"/"basename"이 없으면 침묵한다 |
| **I155** | **blocking 등급 check가 구조적으로 발화 불가.** `NAVIGATION_WITHOUT_AUTHORITY`의 조건은 "authority 문서가 하나도 없을 때"인데, pool refill이 늘 32개를 채우고 그중 9~15개가 authority 등급을 단다. **recall을 올린 기능이 blocking 게이트를 무력화** |
| **I156** | **CLAUDE.md가 출처의 유보를 떼고 수치를 인용.** `recall 0.688→1.000`을 쓰면서 출처의 "N=8", "too small for a production decision", "**did not generalize** to held-out (0.802)"를 전부 생략. "two graph walks"도 표와 어긋남(1.000은 turn 4) |

### B. 외부 검토가 찾은 것 (haiku 서브에이전트 패널)

| ID | 이슈 |
|---|---|
| **I157** | **blocker — fallback 호출이 무방비.** `filesystem_fallback_backlinks()`가 live 호출의 `except` 안에 있으면서 **자체 guard가 없어**, vault root가 사라지면 `OSError`가 `query_backlinks()`를 뚫고 MCP 경계로 탈출했다. "모든 실패는 구조화된 결과"라는 이 모듈의 핵심 계약 위반 |
| **I158** | **blocker — `backlinks_only()` 없는 checkout에서 `AttributeError` 탈출.** 기본 `EVIDENCE_EVALUATOR_DIR`가 가리키는 곳에 그 메서드가 없어 raw 예외가 MCP 경계로 나갔다. `contracts.py`는 `ObsidianUnavailable`만 잡는다 |
| **I159** | **env 파싱이 blocklist + 대소문자 구분.** `"FALSE"`/`"OFF"`/`"NO"`/`"disabled"`가 전부 **활성화**로 읽혀, 끄려는 조작자의 의도와 정반대로 동작 |
| **I160** | `EVIDENCE_EVALUATOR_DIR`에 `expanduser()` 누락 — `~` 경로가 문자 그대로 `sys.path`에 |

### C. 내가 구현 중 만든 결함

| ID | 이슈 |
|---|---|
| **I161** | **git plumbing이 공유 체크아웃을 뒤처지게 했다.** `update-ref`로 `main`만 옮기고 그 체크아웃의 작업 파일은 그대로 둬서, 5개 파일이 자기 브랜치보다 구버전이 됐다. **이것이 I158 blocker의 실제 원인**이었다 |
| **I162** | **셸 cwd가 공유 체크아웃에 갇혀 모든 Bash가 차단됐다.** 내가 거기서 pytest를 돌린 탓. `pwd`조차 거부됐고, **서브에이전트도 같은 셸 상태를 물려받아** 뚫지 못했다. `EnterWorktree`로 복구 |
| **I163** | **1라운드 적대적 리뷰 하네스에 self-test가 없었다.** lens 4개가 전부 빈 배열을 반환했다면 "코드가 깨끗함"과 "리뷰가 작동 안 함"을 **구별할 방법이 전혀 없었다.** 이번엔 6건이 나와 우연히 드러나지 않았을 뿐 |
| **I164** | **리뷰 서브에이전트가 저장소 루트에 스크래치 파일 3개를 남겼다**(`test_env_parsing.py` 등). Codex 하네스는 자기 실험 디렉터리 안에만 쓴다 |
| **I165** | **스케일링 테스트가 replica dedup에 무력화됐다.** 노이즈 문서 100개를 전부 같은 내용으로 만들어 corpus가 **1개로 합쳐**, "규모와 무관하게 rank 4"라는 **틀린 결론**을 냈다 |
| **I166** | **판별하는 합성 fixture를 네 번 설계해 네 번 실패.** ①노이즈 30개 ②hub가 junk 선점 ③junk에 약한 어휘(시나리오 자체가 틀림) ④target을 강한 어휘로 교정(차이는 났으나 둘 다 top-8 안). 이 결함은 실제 vault 규모에서만 재현된다 |
| **I167** | **테스트 인자 실수** — `graph_seed_k` 기본값 12가 `candidate_pool_k=10`을 넘어 새 테스트 3개가 `RetrievalError`로 실패 |

### D. 내 진단이 틀렸고 측정이 정정한 것

| ID | 이슈 |
|---|---|
| **I168** | **D1 진단이 성립 불가능한 문장이었다.** "`authority_rank`가 archive 사본을 정본보다 낮게 놓지 못한다"고 기록했으나, `authority_rank`는 **바이트 동일 사본** 중 대표를 고를 때만 쓰이고 그 archive 문서는 digest가 달라 **애초에 비교된 적이 없다** |
| **I169** | **harness `review_required`에 대한 첫 가설이 틀렸다.** 자연 질의 6/6이 `false`여서 "늘 거짓"으로 적을 뻔했으나, poison test로 조건을 만족시키는 입력을 넣으니 6종 중 3종이 발화 |
| **I170** | **Codex/Claude 테스트 수 차이를 `mcp` 미설치로 오진.** 실제 원인은 `_require_unix_socket()`의 **AF_UNIX bind 권한** — 정확히 6개 테스트를 게이트한다. 직접 probe해서 확정 |
| **I171** | **설계 요청서의 "옵션 D"가 내가 측정한 것과 달랐다.** 요청서는 RRF 변종으로 서술했으나 `rank_D`는 `_staged(...)`를 호출하는 **단계형 변종**이었고 `corpus.backlinks()`(**global**)를 썼다 — 판정문이 명시적으로 피하라고 한 구현. **D의 4/5 근거가 무효** |
| **I172** | **게이트 3이 지정된 테스트로 성립하지 않았다.** `test_graph_frontier_beats_a_full_lexical_tail`은 발견(`turn["new_paths"]`)만 검사하고 `retrieved_paths`를 전혀 보지 않는다. 통과해도 순위 회귀를 못 잡는다 |

---

## (2) 반복 재현 횟수가 증가한 이슈

### P1 — 공허한 가드/테스트 (누적 11건 → **17건**)

이 세션에서만 **6건 추가**되었고, 그중 두 건은 **같은 테스트를 두 번 강화한
뒤에도 여전히 공허**했다.

| 회차 | 무엇 |
|---|---|
| 1라운드 리뷰 | fallback 테스트가 결과 **모양만** 검사 → 호출을 하드코딩된 `[]`로 바꿔도 통과 |
| 1라운드 수정 | spy 추가 |
| **2라운드 리뷰** | **여전히 공허.** fixture에 wikilink가 없어 진짜 스캔도 `[]`를 반환 → `[] is not None`이 양쪽 다 통과 |
| 2라운드 수정 | 실제 링크를 넣고 **값 자체**를 단언 |
| D3 통합 테스트 2건 | poison test 결과 **수정을 되돌려도 통과** → 회귀 가드가 아님 |

**"강화했다"가 "공허하지 않다"를 뜻하지 않는다**는 것이 이 세션에서 두 번
실증됐다.

### P2 — 파라미터 의존 수치를 같은 측정으로 취급 (2건 → **3건**, 이번엔 내가 쓴 주의를 어김)

`docs/HANDOFF.md` §6에 **내가 직접** 이렇게 써 뒀다:

> `discovered_path_count`는 **파라미터에 따라 달라진다** — 두 수를 같은
> 측정으로 취급하지 마라.

그리고 D1/D3 수정 후 **"3/5 → 4/5, 완료 조건 충족"**이라고 커밋했다. 그 4/5는
`graph_seed_k=4`에서만 나오고 **도구 기본값(12)에서는 3/5**다. 잡은 것은 내
재측정이 아니라 **Claude Desktop의 독립 실험**이었다.

### P3 — 자기 보고를 검증 없이 신뢰할 뻔함 (누적 증가)

이 세션에서 **5회** 독립 검증을 수행했고 **매번 무언가가 바뀌었다**:

| 대상 | 검증 결과 |
|---|---|
| Codex `1419724` | 실재·일치 확인 |
| Codex `c3e6f88` | 실재하나 **파일 목록이 주장과 달랐다**(3개 vs 2개), 원인은 커밋 경계 |
| Codex `c25d49f` | 실재·일치 |
| Desktop 1차 보고 | "CLI 연동 빠짐" → **반증**(4번 중 3번 CLI 직접 응답) |
| Desktop 2차 보고 | **Desktop이 맞았다** — 내 4/5가 파라미터 의존(P2) |

### P4 — 게이트가 게이트를 가림 (1건 → **2건**)

I155가 새 사례다: **pool refill(recall을 올린 기능)이 blocking check를
무력화**했다. 21b라운드의 I136(isolation 게이트가 per-label 검사를 가림)과
같은 형태다.

---

## (3)(4) 해결 근거가 있는 이슈와 해결 유무

| ID | 해결 | 근거 |
|---|---|---|
| I148 D2 | **해결** | `exhaustive = (terminal_reason == "graph-frontier-exhausted")`. 양방향 poison test |
| I149/I150 D3 | **해결** | `graph_channel_order()`. 게이트 4개 전부 PASS |
| I151 from_env | **해결** | `EVIDENCE_VAULT_{AUTHORITY_PREFIXES,DEMOTED_PREFIXES,EXCLUDED_GLOBS}` |
| I152 D1b | **해결** | `demoted_prefixes`. C1이 archive 사본→현재 사본 |
| I153 금지 세그먼트 | **해결** | 목록 일치 |
| I154/I155/I156 CLAUDE.md | **부분** | 측정·기록 완료. I156(수치 인용)만 제거, I154/I155는 `.vault-harness` 수정 권한 밖이라 **기록만** |
| I157 blocker | **해결** | 자체 try/except. poison test로 `OSError` 탈출 재현 후 수정 |
| I158 blocker | **해결** | `hasattr` 가드 + **I161 근본 원인 제거**(체크아웃 동기화). E2E에서 `backend_used: "live"` 복구 |
| I159/I160 env | **해결** | casefold allowlist, `expanduser()` |
| I161 stale checkout | **해결** | 조상 커밋 blob 대조로 안전 확인 후 동기화(99/99 일치) |
| I162 셸 wedge | **해결** | `EnterWorktree`. 재발 방지는 "그 디렉터리에서 명령 실행 금지" |
| I163 self-test 부재 | **해결** | 2라운드에 캘리브레이션 게이트 도입, 3/3 검출 |
| I164 스크래치 파일 | **해결** | 삭제, 내용은 정식 테스트로 흡수 |
| I165~I167 내 실수 | **해결** | 각각 정정 후 재측정 |
| I168~I172 오진 | **해결** | 전부 문서에 정정 기록 |
| **C4 회수 실패** | **미해결** | demotion·D0 둘 다로 설명 안 됨. 원인 미확정 |
| **완료 조건 3번** | **충족** | 기본 파라미터 4/5 (D0 이후) |

---

## (5) 해결 근거가 있고 반복된 이슈의 문제 정의

### P1의 문제 정의

> **가드를 강화한 행위와, 그 가드가 실제로 발화하는지는 별개의 사실이다.**
> 전자를 확인하고 후자를 확인하지 않으면, "강화했다"는 기록만 남고 커버리지는
> 0인 상태가 만들어진다. 그리고 이 상태는 **한 번 강화한 뒤에도 다시 발생할
> 수 있다** — 2라운드가 1라운드의 강화를 반증한 것이 그 증거다.

### P2의 문제 정의

> **측정값에 파라미터를 명시하지 않으면 그 값은 비교 불가능하다.** 더 중요한
> 것은, 이 규칙을 아는 것과 지키는 것이 다르다는 점이다. 나는 이 주의를
> **문서에 써 놓고** 어겼다. 규칙을 아는 것은 방어가 아니다.

### P3의 문제 정의

> **자기 보고는 증거가 아니라 가설이다.** 5회 중 2회에서 검증이 결론을
> 바꿨고, 그중 1회는 **내 주장이 틀렸음**을 드러냈다.

### P4의 문제 정의

> **게이트를 추가하면 기존 게이트의 커버리지를 재측정해야 한다.** 특히
> "recall을 올리는" 개선은 "부재를 탐지하는" 게이트를 무력화하기 쉽다 —
> 둘의 방향이 정반대이기 때문이다.

---

## (6) 해결 유무 판단에 쓴 가설과 검증 방식

### 이 세션이 확립한 절차: **poison test를 수정마다 적용**

```
1. 수정한다
2. 테스트가 통과하는 것을 본다          ← 여기서 멈추면 P1이 재발한다
3. 리뷰어가 서술한 정확한 mutation을 적용한다
4. 테스트가 FAIL하는 것을 확인한다      ← 이것이 비공허성의 증거
5. mutation을 되돌리고 다시 통과를 확인한다
```

이 세션에서 이 절차가 **실제로 작동한 사례**:

| 수정 | mutation | 결과 |
|---|---|---|
| I157 fallback guard | try/except 제거 | `OSError: vault root vanished` 그대로 탈출 → FAIL |
| I158 hasattr guard | 가드 제거 | `AttributeError` → FAIL |
| I159 casefold | casefold 제거 | `'False' should map to enabled=False` → FAIL |
| spy 테스트 | fallback 호출을 `[]`로 대체 | "never actually called" → FAIL |
| D3 통합 테스트 2건 | 발견 순서로 복원 | **PASS (판별 실패)** → 공허함이 드러남 |

마지막 행이 핵심이다. **이 절차가 없었다면 D3 통합 테스트를 회귀 가드로
믿었을 것이다.**

### 하네스 자체의 비공허성 검증 (I163의 해결)

Codex의 `evaluate.py --self-test` 원칙 — *"채점기가 침묵하기 전에 말할 수
있음을 먼저 보여야 한다"* — 을 워크플로 **구조**로 옮겼다:

```
Phase Calibrate: 알려진 결함 3개를 심은 fixture에 같은 lens 4개를 돌린다
                 검출 판정은 발견자가 아닌 별도 심판이 엄격하게
Gate:            3개 중 2개 미만 검출 시 BLOCKED_CALIBRATION_FAILED로 종료
                 실제 코드 결과를 아예 보고하지 않는다
Phase Find/Verify: 패널이 작동함을 보인 뒤에만 실제 리뷰
```

결과 3/3 검출 → 통과 → 실제 리뷰에서 **blocker 1건(I158) 발견**. 1라운드는
이 blocker를 놓쳤다.

### D3 게이트 설계 — 구현 **전에** 게이트를 만들었다

| 게이트 | 수정 전 | 수정 후 |
|---|---|---|
| 5문항 ≥4/5 | FAIL 3/5 | PASS 4/5 |
| symlink-vs-moc top-8 | FAIL | PASS rank 1 |
| zero-overlap 출력 유지 | PASS | PASS |
| seed 민감도 | FAIL (4→6→없음→없음) | PASS (전부 rank 1) |

게이트를 먼저 만든 이유: **나중에 만들면 "통과했다"가 사후 합리화가 된다.**

---

## (7) 문제의 해결 방법 (구체적)

### P1 — 공허한 가드

1. **수정마다 poison test.** 위 5단계를 생략하지 않는다.
2. **fixture가 결함을 재현하는지 먼저 확인한다.** I166에서 네 번 실패했고,
   실패를 인정하고 **"이 회귀는 합성으로 못 잡는다"를 docstring에 명시**했다.
   억지로 통과하는 테스트를 만드는 것보다 낫다.
3. **기준선 테스트를 짝으로 둔다.**
   `test_without_demotion_the_archived_copy_wins`가 깨지면 강등 테스트가
   아무것도 증명하지 못하므로 **둘을 같이 고쳐야 한다**.
4. **hermetic 테스트와 실제 환경 게이트를 분리한다.**
   `scripts/d3_ranking_gates.py`, `scripts/parity_check_backends.py`.

### P2 — 파라미터 의존 수치

1. **모든 측정에 파라미터를 함께 기록한다.** 표 제목에 "도구 기본값" 명시.
2. **도구 기본값으로 최소 1회 측정한다** — 실제 caller가 받는 값이므로.
3. **외부 독립 실험을 순서에 넣는다.** Desktop이 잡은 것을 내가 못 잡은 이유는
   내가 내 파라미터를 계속 썼기 때문이다.

### P3 — 자기 보고 검증

1. **커밋 주장은 `git show --stat`으로 대조.** 파일 목록이 다르면 커밋 경계를
   의심한다(I169의 c3e6f88 사례).
2. **수치 주장은 재현.** 재현 환경이 다르면 그 차이를 먼저 설명한다
   (113 vs 119 → AF_UNIX).
3. **반증을 먼저 시도하도록 지시한다.** 검증 서브에이전트 프롬프트를
   "확인이 아니라 REFUTE가 네 일이다"로 썼고, 7건 중 1건이 기각됐다.

### P4 — 게이트가 게이트를 가림

1. **게이트 추가 후 기존 게이트의 발화를 재측정한다.**
2. **recall 개선과 부재 탐지를 같은 실행에서 함께 잰다.**

---

## 부록 — 권한과 도구 차이 (사용자 지시)

이 세션에서 **실측된** 차이다. 추정이 아니다.

### Codex ↔ Claude

| 축 | 차이 | 실측 근거 |
|---|---|---|
| **AF_UNIX 소켓** | Codex lane은 차단, Claude(host) lane은 허용 | `_require_unix_socket()`이 정확히 **6개** 테스트를 게이트. 113+6=119로 산수 일치. 직접 bind probe로 확정 |
| `mcp` 패키지 | **차이 아님** — 양쪽 다 설치됨 | 내 첫 오진(I170) |
| 저장소 쓰기 | Codex는 메인 체크아웃에 직접 커밋 | 나는 worktree 격리로 불가 → git plumbing 사용 → **I161 유발** |

### Claude Code 세션 내부

| 제약 | 결과 |
|---|---|
| worktree 격리 | `git -C <공유 체크아웃>`·`cd <공유 체크아웃>` **전부 거부** |
| cwd가 공유 체크아웃에 놓이면 | **모든** Bash 명령 거부(`pwd`조차). `EnterWorktree`로만 복구(I162) |
| 서브에이전트 | **같은 셸 상태를 상속** — 격리 문제를 서브에이전트로 우회할 수 없다 |
| 복합 명령 | `&&`/heredoc이 많으면 "too complex to verify" 거부 → 단순 명령으로 분해 |

### Claude Desktop

| 제약 | 결과 |
|---|---|
| GUI 최소 PATH | `python3`가 `mcp` 없는 `/usr/bin/python3`로 해석 → launcher에 인터프리터 **고정** 필요 |
| 설정 반영 | 재시작 필요 (세션 중 반영 안 됨) |
| 독립성 | **내 fixture·내 질의에 물들지 않음** → P2를 잡은 유일한 경로 |

### 이 차이들이 만든 실제 사고

**I161 → I158 연쇄**가 대표적이다. 내가 worktree 격리 때문에 plumbing을 쓸
수밖에 없었고, plumbing이 공유 체크아웃을 뒤처지게 했고, 그 뒤처진 체크아웃이
기본 설정에서 `AttributeError`를 MCP 경계로 탈출시켰다. **권한 제약이 코드
결함으로 전화(轉化)된 사례**이며, 2라운드 적대적 리뷰가 아니었다면 발견되지
않았을 것이다.
