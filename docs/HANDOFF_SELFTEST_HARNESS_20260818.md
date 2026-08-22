# HANDOFF — 자기검사 하네스와 공허한 가드 (P1)

이 문서 하나로 재개할 수 있게 쓴다. 이전 대화를 모른다고 가정한다.
갱신 2026-08-18.

`docs/HANDOFF.md`는 **MCP v0.1 검색**의 정본이고 이 문서와 주제가 다르다.
둘을 섞지 마라.

## 1. 지금 상태 한 줄

**"가드를 추가하는 것"과 "가드가 발동할 수 있음을 확인하는 것"이 다르다는 반복
결함(P1, 기록 18건)을 산문 주의사항에서 실행 가능한 하네스로 옮겼다.** 목격자
레지스트리, 순서 의존성 검사기, 검사 5종+미실행 1종의 하네스를 만들고 각각을
poison test로 검증했다. 하네스는 첫 실행에서 실제 미수리 결함을 찾았고, 이후
**자기 자신의 위양성 음성**도 하나 드러냈다(§6). 적대적 검증으로 지적된 실제
구멍 3건(F4·F8·F5)은 **아직 수리하지 않았다**.

**추측하지 말고 물어라. 읽기 전용 명령이 상태를 말한다:**

```bash
cd /Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator/.claude/worktrees/mcp-v01-backlinks
python3 -m pytest tests/ selftest-harness/ -q     # 기대: 155 passed, 환경변수 불요
cd vault-backlinks-mcp                             # subtree가 정본 (§3)
python3 -m pytest tests/ -q                        # 기대: 92 passed
python3 scripts/order_independence_check.py        # 기대: exit 0, OK
```

하네스 자체를 대상에 돌리는 명령 (worktree 루트에서):

```bash
python3 selftest-harness/selftest_agent_tool.py vault-backlinks-mcp \
    --env VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0 \
    --guard-source vault_backlinks_mcp/contracts.py \
    --guard-registry tests/test_guard_witness.py
# 기대: exit 0, status=complete, 검사 6종 전부 checks_run, skip 0
```

`--python` 플래그는 필요 없다 — `~/.claude/venvs/itemwise`의 내구 venv를
자동 발견한다(없으면 그 검사만 `CHECK_DID_NOT_RUN`으로 내려간다. 재생성:
`python3 -m venv ~/.claude/venvs/itemwise && ~/.claude/venvs/itemwise/bin/pip
install pytest pytest-randomly`).

`complete`는 2026-08-22에 순서 의존 4건(§5)을 고치고 나서의 기대값이다.
그 전 커밋에서는 `ENV_SENSITIVE`와 `ORDER_DEPENDENT_ITEMWISE`가 나오는 것이
정상이었다 — 결과를 과거 문서와 대조할 때 시점을 확인하라.

모든 수치는 **host lane**(Obsidian CLI와 subprocess가 허용된 환경, macOS,
Python 3.13.13, pytest 9.1.1) 기준이며 각 1회 측정이다. 권한이 다른 sandbox에서
달라지면 회귀가 아니라 **BLOCKED**다.

## 2. 이 작업이 무엇인가

P1은 이 프로젝트의 반복 결함이다. 검사를 추가하지만 그것이 실제로 발동할 수
있는지는 확인되지 않는다. 산문 주의사항은 실패했다 — 주의사항을 쓴 세션이 바로
아래 단락에서 위반한 사례가 있다.

**범위 안**: 검사가 무언가를 증명하는지 기계적으로 확인하는 도구, 그 도구 자신의
검증, 재사용 가능한 선행 구현 조사.

**범위 밖(확장하지 마라)**: MCP v0.1 검색 성능, primary 승인, `hidden_gold`,
`results/`, 실험 artifact. `.vault-harness/`는 **읽기 전용 정본이다.**

## 3. git 상태

```
repo    evidence-evaluator (worktree .claude/worktrees/mcp-v01-backlinks)
branch  integrate-vbm
clean   yes

repo    vault-backlinks-mcp   ← 독립 저장소이며 위 저장소의 subtree로도 존재
branch  main
head    fe0b706
remote  없음. 로컬 커밋만 있다
```

**아무것도 push하지 않았다.** push는 매번 별도 승인이 필요하다. 로컬 커밋은 상시
허용이다.

**이중 존재의 현재 상태 (2026-08-22 갱신).** subtree를 `fe0b706`까지 동기화한 뒤
(`git subtree pull`, merge 커밋), 순서 의존 4건 수리(`0e45caf`)는 **subtree에만**
들어갔다. worktree 격리가 독립 저장소로의 쓰기(`git -C`, Edit 모두)를 차단해서
같은 세션에서 양쪽을 갱신할 수 없었다. 사용자 지시("vault-backlinks-mcp도
evidence-evaluator repo에서 다룬다")에 따라 **subtree가 정본이다.**

독립 저장소는 정확히 한 커밋 뒤에 있다. 격리 없는 세션에서 이렇게 따라잡는다:

```bash
git -C /Users/jaehyuntak/Desktop/Project_in_progress/vault-backlinks-mcp \
    am -p2 <(git -C <이 worktree> format-patch -1 0e45caf --stdout -- vault-backlinks-mcp)
# 또는 이미 만들어 둔 패치 파일이 남아 있다면 그것을 am -p2로.
# 적용 후 두 트리는 diff -r로 바이트 일치해야 한다.
```

## 4. 만든 것

| 산출물 | 위치 | 검증 |
|---|---|---|
| 목격자 레지스트리 | `vault-backlinks-mcp/tests/test_guard_witness.py` | 가드 11종에 발동/침묵 세계 쌍, 소스 파싱 완전성 메타가드 |
| 순서 의존성 검사기 | `vault-backlinks-mcp/scripts/order_independence_check.py` | 결함 생존 리비전에서 poison test 통과 |
| 자기검사 하네스 | `selftest-harness/` | Validation 12케이스, poison test 4종 |

계약과 하네스가 **확립하지 않는 것**은 `selftest-harness/AGENT_TOOL.md`에 적혀
있다. 먼저 읽어라. `complete`는 정확성이 아니라 "이 5가지 기계적 실패 모드가
없음"이다.

형식은 발명하지 않았다. `.vault-harness/vault-md-retrieval/AGENT_TOOL.md`의
Validation 절이 이미 코드별 발동/침묵 목격자를 쓰고 있었다. 계약을 재사용했다.

## 5. 수리한 결함과 미수리 결함

### 수리 완료

| 결함 | 커밋 |
|---|---|
| `graph_seed_k` 검증에 목격자 없음 (P1 18번째) | `26024e7` |
| meta-guard 정규식이 자릿수 포함 코드를 못 봄 | vbm `95aefdb` |
| fallback witness가 환경에 의존 (F2) | vbm `5398501` |
| 하네스가 순서 검사를 기본 환경에서만 돌림 | `b4712c3` |

### 미수리 — 다음 작업의 대상

적대적 검증으로 **확인된** 실제 구멍이다. 근거는
`docs/ADVERSARIAL_REVIEW_GUARD_WITNESS_20260817.md`에 있다.

1. **F4 — `review_required`의 `or truncated`를 어떤 테스트도 고정하지 않는다.**
   가장 나쁘다. 호출 agent가 실제로 분기하는 필드이고, 잘린 결과가
   `review_required: false`로 나가면 부분 풀에서 답하고 필수 조치를 건너뛴다.
   실증 있음: 이 결함이 살아 있는 상태를 죽은 검증 에이전트가 운영 코드에
   남겼는데 88 passed였다.
2. **F8 — `obsidian_backend.py`의 `except OSError:` 경로가 검사되지 않는다.**
   이 코드에 닿는 모든 테스트가 `confirm_active_vault`를 mock한다.
   `contracts.py`의 호출부에 try/except가 없어 예외가 MCP 경계로 새어나간다.
   `except (OSError, RuntimeError)`가 필요할 수 있다(symlink 순환).
3. **F5 — witness가 코드 존재만 보고 payload를 보지 않는다.** `_codes()`가
   `code` 필드만 뽑아서 `required_action`, `dropped_by_reason`,
   `returned_count`가 전부 미검증이다. 가드 하나가 아니라 **단정 축 하나가
   빠진 것**이다.
4. ~~환경 의존 2건~~ — **수리 완료 (2026-08-22, `0e45caf`, subtree).** 두
   테스트가 필요한 세계(fallback 켜짐)를 직접 만들도록 고쳤다. 발견 경로가
   중요하다: `ORDER_DEPENDENT_ITEMWISE`의 첫 실전 실행이 이 두 테스트가
   고정 seed 2–4에서 FAILED, seed 5·8에서 PASSED임을 보고했고, seed 5·8에서
   통과한 이유가 정확히 F2의 가림 기제였다.
5. ~~reload 누출~~ — **수리 완료 (같은 커밋).** try/finally로 원래 환경값
   (존재/부재 포함)을 복원하고 한 번 더 reload한다. monkeypatch는 환경은
   되돌리지만 모듈은 못 되돌린다.

미검증 상태로 남은 지적도 있다. `docs/ADVERSARIAL_REVIEW_...`의 §6 목록 중
F1·F3은 반박됐고 F7은 UNDETERMINED다. **F7이 사실이면 레지스트리의 커버리지
주장 범위가 docstring과 달라진다** — 오류 경로 가드가 `review_checks`의 코드로
표현되지 않아 애초에 레지스트리에 들어오지 못한다는 지적이다. 재검증 대상.

## 6. 함정 — 여기서 실제로 당한 것들

읽지 않으면 같은 것을 다시 당한다.

**(a) 결함을 고치면 검출기의 검증 근거가 사라질 수 있다.** F2 회귀 테스트의
`finally: reload`가 `test_contracts.py`의 누출을 되돌려서 순서 의존성이라는
신호 자체를 없앴다. **현재 트리에서는 어떤 순서 탐지기도 F2를 재현할 수 없다.**
검출기를 시험하려면 결함 생존 리비전을 꺼내야 한다:

```bash
git -C /Users/jaehyuntak/Desktop/Project_in_progress/vault-backlinks-mcp \
    archive 95aefdb -o /tmp/prefix.tar
mkdir -p /tmp/prefix && tar -xf /tmp/prefix.tar -C /tmp/prefix
cp /Users/jaehyuntak/Desktop/Project_in_progress/vault-backlinks-mcp/scripts/order_independence_check.py \
   /tmp/prefix/scripts/
cd /tmp/prefix && VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0 python3 scripts/order_independence_check.py
# 기대: exit 1, FILESYSTEM_FALLBACK_USED를 지목
```

이 트리는 이전에 `$CLAUDE_JOB_DIR/tmp/prefix`에 있었으나 **job과 함께 삭제된다.**
위 명령으로 다시 만들어라.

**(b) 환경변수를 설정하지 않으면 아무 도구도 아무것도 못 찾는다.** F2는
`VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0`에서만 드러난다. 기본 환경에서
`pytest-randomly`는 **0/15 seed**, 내 검사기는 검출 실패다. 이걸 모르면 "결함
없음"을 보고하게 된다.

**(c) "이 테스트가 X를 잡지 않는다"와 "스위트가 X를 잡지 않는다"는 다른
주장이다.** 후자를 주장하려면 **전체 스위트**를 돌려야 한다. 검증 에이전트가
`-k`로 좁혀 돌려서 이미 덮인 결함을 무방비 구멍으로 보고했다. 같은 세션에서
`retriever.py:37`은 전체 131 passed로 확인했으므로 그쪽은 참이었다. 차이는
스위트 범위 하나였다.

**(d) Bash 호출 사이에 cwd가 유지된다.** 이걸로 한 번 오보했다 — 사본
디렉터리에 남아 있는 채 테스트를 돌리고 실제 저장소의 결과로 읽었다. 테스트
실행에는 `cd`를 명시하라.

**(e) 하위 에이전트에게 실제 저장소를 쓰기 대상으로 주지 마라.** 1라운드에서
verify 에이전트를 실제 파일에 대고 돌렸고, 9개가 변형 도중 죽어
`review_required = False  # BROKEN`을 운영 코드에 남겼다. 2라운드는 각자 사본을
주고 오염 0이었다. 금지가 아니라 **불가능**으로 만들어야 한다.
사본 시딩: `$CLAUDE_JOB_DIR/tmp/make_verify_copies.py` 참조(clean tree를 assert
한 뒤 시딩한다).

**(f) 하위 에이전트의 CONFIRMED를 poison test 재현 없이 채택하지 마라.**
직접 재검증한 판정 중 2건이 틀렸거나 과장이었다. F2는 CONFIRMED가 맞았지만
근거가 null mutation이었고 기제를 완전히 틀렸다.

**(g) "접근할 수 없다"고 적기 전에 접근을 시도하라.** 문헌 주장을 "논문 접근
없음"으로 뭉갰는데 웹 조회 도구가 있었고 두 번의 조회로 SARIF가 확인됐다.
이것도 P1의 변종이다 — 확인하지 않은 것을 확인된 제약처럼 적었다.

## 7. 선행연구 — 확인된 것과 미확인

정본: `docs/PRIOR_ART_ORDER_DEPENDENCE_20260818.md`

**확인(직접 실행 또는 원문 인용)**:

- `pytest-randomly 4.1.0`이 Python 3.13.13 + pytest 9.1.1에서 동작하고 F2를
  잡는다 — 적대적 환경 **23/40 seed**, 기본 환경 **0/15**.
  → 채택하려면 **seed 고정이 필수다.** 랜덤 seed 1개는 42.5% 확률로 놓치고,
  그러면 결정적으로 잡는 기존 검사기보다 나빠진다.
- `detect-test-pollution 1.2.0`은 설치·실행되지만 **이 결함 클래스에 적용
  불가**다. 단독 통과·스위트 실패만 다루는데 우리 결함은 정반대다. 분류상
  `victim`이 아니라 **`brittle`**이다.
- SARIF 2.1.0: `invocation.executionSuccessful`은 필수 boolean,
  `run.results`는 *"must be present (but may be empty) if a log file
  represents an actual scan"*. 부재와 빈 배열이 의미상 구별된다. 외부 export
  adapter로 채택 값이 있으나 내부 계약의 대체재는 아니다(invocation 단위
  boolean이라 "5개 중 3개만 실행됨"을 표현 못 함).

**미확인**: vacuity(Beer 등), Checked Coverage(Schuler–Zeller), Conditional
Model Checking, Defects4J/BugsInPy, "flaky 중 59%가 order dependency" 수치,
Nagios UNKNOWN 정식 정의, `toolExecutionNotifications` 의미론.
**인용 형식이 그럴듯한 것은 근거가 아니다.**

**채택한 분류** — R12 3분할. 인용은 미검증이나 분류 자체가 값을 증명한다.
세 칸 모두 실제 사례가 있다:

| 분류 | 우리 사례 |
|---|---|
| `UNREACHABLE` | 기록된 구조적 도달 불가능 가드 2건 |
| `REACHABLE_NOT_EXERCISED` | `retriever.py:37` |
| `EXECUTED_NOT_CHECKED` | F5 |

**진행 중**: 위임한 조사 workflow `wdazqrfy8`(5 에이전트)이 이 문서 작성 시점에
아직 실행 중이다. 4 레인 — 규격 인용, 논문 검증, 실행 시험, GitHub/subtree
조사. 결과가 오면 §7을 갱신하라. **결과를 받아도 `applicability_tested`가
false인 도구 판정은 호환성만 확인된 것으로 취급하라.**

## 8. 다음 행동 — 값이 큰 순서

1. **F4 수리.** 잘림만으로 `review_required`가 true가 되는 케이스를 만들어야
   한다. `review_checks`가 truncation 외에 비어 있는 세계여야
   `bool(review_checks)`만으로 통과할 수 없다. poison test 필수.
2. **F8 수리.** `confirm_active_vault`를 mock하지 않는 테스트 하나.
   `tmp_path`에 자기참조 symlink를 만들면 `resolve()`가 `RuntimeError`를
   낸다. 예외가 아니라 라벨된 degradation이 나와야 한다.
3. **F5 수리.** 레지스트리에 `expected_payload`를 추가해 코드별로 payload
   부분집합 일치를 검사한다. 단정 축 하나를 세우는 일이라 F4·F8보다 크다.
4. **`pytest-randomly` 고정 seed 채택** — `ORDER_DEPENDENT_ITEMWISE` 검사로
   추가. 미설치 시 `CHECK_DID_NOT_RUN`으로 두어 의존성을 강제하지 않는다.
   Validation 케이스와 poison test 필수. 최소 seed 집합은 `wdazqrfy8`의
   `trials` 레인이 조사 중이다.
5. **같은 파일 내 오염 판정.** `pytest-randomly`가 그것을 잡으면 파일 단위
   검사기를 회수할 수 있다. **추측하지 말고 최소 재현으로 판정하라.**
6. **reload 누출 수리**(§5-5). 원래 환경을 복원한 뒤 다시 reload해야 한다.
7. **F7 재검증** — 오류 경로 가드가 레지스트리에 들어오지 못하는지.
8. **subtree 동기화** — `vault-backlinks-mcp`의 커밋 3건이 evidence-evaluator
   subtree에 반영되지 않았다.

`mutatest`는 subtree 후보로 판정했으나 **들이지 않았다**. 근거와 보류 이유는
`docs/TOOL_SURVEY_MUTATION_20260817.md`.

## 9. 조사를 맡기는 방식 (사용자 지시, 2026-08-18)

문헌·규격·GitHub 조사는 **자족적 프롬프트를 CLI에 출력해 사용자의 조사
에이전트에 넘긴다.** 하위 에이전트로 돌리지 마라. 이유는 두 가지 절감이다 —
조사 출력이 세션 컨텍스트를 거치지 않고, 전용 조사 에이전트가 더 효율적이다.

**예외**: 로컬 트리를 대상으로 하는 실행 시험은 이 머신의 인터프리터·venv·
체크아웃이 필요해 위임할 수 없다. 판정과 subtree 통합도 여기서 한다.

프롬프트 요건: 완전 자족(환경·대상·이미 배제한 후보와 실측 근거·사내 기존
산출물·답변 언어), `verification_method` 강제, 도구는 적용 가능성과 호환성 구분,
부정적 결과 명시적 요구.

## 9a. 이 세션은 이미 있는 것을 다시 만들었다 (2026-08-22 조사)

사용자 지시로 workspace를 검색한 결과다. **결론: 열등한 버전을 재발명했다.**

정본 두 개가 이미 있다:

- `concept-gate-codex-mcp-wt/docs/HARNESS_KNOWHOW.md` — 하네스 설계 노하우.
  §B4 "가드가 통과하는데도 결함이 남을 수 있다", **§B4a "B4를 규율에서 기제로
  옮겼다" (2026-08-05)**, §B1 "사전등록 게이트를 규율이 아니라 코드로",
  §B5 "제작자는 자기 산출물의 결함을 보지 못한다 — 리뷰를 분리하라".
  이번 세션의 논지 전체가 여기에 이미 있다.
- `concept-gate-taxonomy/test_guard_negative_coverage.py` — AST로 모듈 수준
  `assert_*`/`_assert_*`를 수집해, `with pytest.raises(...)` 안에서 호출되지
  않는 raising 가드가 있으면 실패한다.

`HARNESS_KNOWHOW.md` §B4a에 내가 재구성한 표가 그대로 있다:

| 가드의 실제 상태 | 정상입력 → pass? | 위반입력 → raise? |
|---|---|---|
| 정상 가드 | 통과 | 발동 |
| 공허한 가드 (no-op) | 통과 | **발동 안 함** |

> 긍정 테스트는 왼쪽 열만 본다. 두 행의 관측값이 같으므로 정보가 부족한 게
> 아니라 **측정 채널이 없다.**

그리고 그 문서는 이 규율이 **"7회 처방되고 7회 실패했다"**고 적고 있다.
이번 세션이 그 목록에 몇 건을 더 얹었다.

### 기존 구현이 내 것보다 나은 두 지점

1. **정규식이 아니라 AST.** 내 `_codes_in_source()`는
   `r'"code":\s*"([A-Z0-9_]+)"'`이다. 자릿수 문자열을 놓쳐서 수리한
   `95aefdb`는 **AST였다면 애초에 존재하지 않는 결함**이다. 기존 구현이 AST를
   고른 이유도 기록돼 있다 — import를 하지 않아 동명 모듈이
   `sys.modules`를 선점하는 함정을 구조적으로 회피하고, 그래서 root 테스트
   하나가 `norecursedirs`를 넘어 실험 폴더 전체를 덮는다.
2. **`KNOWN_UNPROVEN` 기제.** 이름 → 이유 + 담당을 코드에 두고,
   `test_known_unproven_entries_are_not_stale`이 (a) 그 가드가 사라지거나
   (b) raise 능력을 잃거나 (c) 음성 테스트를 갖게 되면 실패한다. 그리고 그
   예외 목록 자체도 검사기이므로 자기 음성 테스트를 갖는다
   (`test_the_staleness_check_itself_fires_on_a_bogus_entry`).
   나는 미해결 지적(F7 등)을 **문서 산문으로** 남겼다. 이쪽이 기제다.

또 내가 몰랐던 규칙이 하나 있다: **"음성 테스트를 날조하지 마라."**
모킹 기반 음성 테스트는 게이트를 초록으로 만들면서 아무것도 증명하지 않는다.
가드가 검사하는 명제를 코드가 이미 보장하는 경우, 처방은 음성 테스트가 아니라
**"이 가드가 잉여인가"를 판정하는 설계 결정**이다.

### 왜 놓쳤는가 — 워크트리 분산이 주원인이 아니다

`test_guard_negative_coverage.py`가 8곳에 있어 중복처럼 보이지만,
`git worktree list`로 확인하면 **전부 `concept-gate-taxonomy` 한 저장소의
worktree 체크아웃**이다. 정본은 이미 하나고, 줄 수 차이(268/276/325/326)는
브랜치 분기다. **워크트리 통합은 이 문제를 고치지 못한다.**

주원인은 **내가 CLAUDE.md의 검색 순서를 어긴 것**이다. 검색 도구를 1단계로
쓰지 않고 내 저장소 안에서 수동 grep을 했다. 뒤늦게 도구를 돌렸을 때 첫
질의의 상위 8건에 두 문서가 모두 들어왔고 `status: complete`,
`review_required: false`였다. **도구는 정상 작동했고 내가 우회했다.**

부차적이지만 실재하는 구조적 간극은 워크트리가 아니라 **저장소 간**이다.
내 작업은 `evidence-evaluator`에 있고 노하우는 `concept-gate-taxonomy`에 있다.
둘을 잇는 유일한 기제가 검색 도구이며, 그것이 바로 내가 건너뛴 것이다.

### 해야 할 재사용

1. `_codes_in_source()`를 정규식에서 **AST 파싱**으로 바꾼다. `95aefdb`의
   수리는 그때 잉여가 된다.
2. `KNOWN_UNPROVEN`을 도입해 F7 등 미해결 지적을 산문에서 기제로 옮긴다.
   staleness 테스트와 그 자신의 음성 테스트까지 함께.
3. `HARNESS_KNOWHOW.md`를 이 저장소에서 찾을 수 있게 포인터를 남긴다 —
   지금 이 절이 그 포인터다.

**아직 1·2를 구현하지 않았다.**

## 10. 이 문서가 주장하지 않는 것

- **하네스가 코드를 정확하다고 말하지 않는다.** 5가지 기계적 실패 모드의
  부재만 말한다.
- **P1이 해결되지 않았다.** 하네스는 **이미 당한** 실패 모드만 검사한다.
  아무도 안 당한 클래스는 못 찾는다. 발견 채널(손 작업, 적대적 검증, mutation
  testing)을 닫으면 인코딩할 새 실패 모드의 공급이 끊긴다.
- **적대적 검증이 완료되지 않았다.** 1라운드 10건 중 9건이 지출 한도로 미검증
  이었고 2라운드에서 8건을 판정했다. F7은 여전히 UNDETERMINED다.
- **수치는 전부 host lane, 각 1회 측정이다.** 적중률 23/40은 이 결함, 이 트리,
  40 seed 기준이며 다른 순서 의존성에는 다를 수 있다.
