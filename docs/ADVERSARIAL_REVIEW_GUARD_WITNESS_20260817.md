# 적대적 검증 — 손으로 쓴 Guard Witness Registry (2026-08-17)

> "손으로 구현 한 것에 문제가 있을 수 있으니 적대적 검증을 권장하고"

대상: `vault-backlinks-mcp/tests/test_guard_witness.py`
패널: haiku subagent 19개, calibration 게이트 + 4 렌즈 + 반박 담당 verify

## 1. 이 문서를 먼저 읽어야 하는 이유 — workflow 헤드라인은 오해를 부른다

workflow가 최종 반환한 값은 이렇다:

```json
{"status": "CALIBRATION_PASSED", "raw_finding_count": 10,
 "confirmed": [ ...1건... ], "refuted": []}
```

**"1 confirmed, 0 refuted"를 "결함 1건뿐"으로 읽으면 틀린다.**
verify 에이전트 10개 중 **9개가 org 월 지출 한도로 죽었다.**

```
[verify:witness-pairs]   failed: monthly spend limit
[verify:meta-guard]      failed: monthly spend limit
[verify:test-isolation]  failed: monthly spend limit
[verify:coverage-gap] x6 failed: monthly spend limit
```

`refuted: []`는 **"반박된 것이 없다"가 아니라 "반박 시도가 완료된 것이
없다"**는 뜻이다. 9건은 **미검증**이며, 판정되지 않았다.

이것 자체가 P4(게이트가 게이트를 가림)의 새 사례다 — calibration 게이트는
통과했는데, 그 뒤 verify 단계가 조용히 붕괴했고 **집계 형식이 붕괴를
"깨끗한 결과"처럼 보이게 만들었다.** 앞으로 이 workflow의 반환값에는
`verify_died` 카운트가 있어야 하고, 그것이 0이 아니면 `status`가
`CALIBRATION_PASSED`로 나와서는 안 된다. (아직 고치지 않았다.)

## 2. calibration은 통과했다 — 패널의 능력은 확인됨

레지스트리가 공허해지는 3가지 방식을 사본에 심고, 패널이 그것을 찾지
못하면 실제 파일에 대한 판정을 신뢰하지 않기로 사전에 정했다.

| 주입 | 내용 | 검출 |
|---|---|---|
| INJ-1 | `ACTIVE_VAULT_UNKNOWN`의 positive/negative가 **같은 세계**(둘 다 `active_vault='unknown'`) | ✓ |
| INJ-2 | 완전성 메타가드를 `assert True`로 무력화 | ✓ |
| INJ-3 | negative witness가 침묵 대신 `result is not None`을 검사 | ✓ |

**3/3.** 패널은 볼 능력이 있다. 따라서 아래 지적들을 "haiku가 헛것을
봤다"로 치부할 근거가 없다.

## 3. 유일하게 검증된 1건 — 서술은 맞지만 **의미가 과장됐다**

패널 주장: *`backend_used`가 witness assertion으로 검증되지 않는다.*
verify 에이전트 판정: `CONFIRMED`, 근거로 poison test 제시 —
`contracts.py`의 `backend_used`를 `"wrong_value"`로 바꿨는데
`test_guard_fires_on_its_positive_witness[FILESYSTEM_FALLBACK_USED]`가
**통과했다**고.

**에이전트 보고를 그대로 받지 않고 직접 재현했다. 결과가 다르다.**

```
backend_used = "live_obsidian_cli"   # 출처를 거짓말하게 만드는 mutation
전체 스위트 실행 →
  FAILED tests/test_contracts.py::test_obsidian_unavailable_falls_back_but_is_clearly_labeled
  AssertionError: assert 'live_obsidian_cli' == 'filesystem_fallback'
  1 failed, 87 passed
```

**이 회귀는 이미 잡힌다.** 잡는 주체가 witness registry가 아니라
`test_contracts.py`의 기존 테스트일 뿐이다.

에이전트가 틀린 지점은 결론이 아니라 **방법**이다. poison test를 의심 대상
테스트 하나(`-k FILESYSTEM_FALLBACK_USED`)로 좁혀 돌렸다. 그러면
"이 테스트가 안 잡는다"는 참이지만 **"아무 테스트도 안 잡는다"로 읽히는
보고문이 나온다.**

교훈, 그리고 이번 세션에 실제로 대가를 치른 구분:

> **"이 테스트가 X를 잡지 않는다"와 "스위트가 X를 잡지 않는다"는 다른
> 주장이다. 후자를 주장하려면 전체 스위트를 돌려야 한다.**

대조: `retriever.py:37`은 **전체 스위트 131 passed**로 확인했으므로
진짜로 안 잡히는 것이 맞다(`docs/TOOL_SURVEY_MUTATION_20260817.md` §3c-2).
같은 세션에서 같은 형태의 주장이 하나는 참, 하나는 과장이었고 **차이는
스위트 범위 하나였다.**

판정: **부분 확인.** witness가 코드 존재만 보고 결과의 의미를 보지 않는 것은
사실이다. 그러나 이것이 무방비 구멍이라는 함의는 **거짓**이다. 수리하지
않았고, 근거를 남겨 수용한다.

## 4. 미검증 9건 중 1건은 내가 직접 검증했다 — 진짜였고 고쳤다

패널 주장(meta-guard 렌즈): *`_codes_in_source()`의 `[A-Z_]+`가 자릿수를
포함한 가드 코드를 매칭하지 못한다.*

이 verify는 지출 한도로 죽었다. 직접 poison test했다 — **실제 저장소를
건드리지 않고 별도 사본에서**:

```
contracts.py에 {"code": "STALE_INDEX_V2"} 추가, witness 없음
  [A-Z_]+   → 3 passed   ← 공허. 등록 안 된 가드를 못 본다
  [A-Z0-9_]+ → FAILED    ← 의도대로 잡는다
```

**진짜다.** 완전성 메타가드가 "witness 없는 가드를 잡는다"는 것이 존재
이유인데, 대상의 한 부류에 대해 공허했다 — **메타가드 자신에게서 재발한
"게이트가 게이트를 가림"**이다.

수리: `vault-backlinks-mcp` `95aefdb`. 실제 저장소 88 passed.

현재 가드 중 자릿수를 가진 것은 **없다.** 즉 이 수정은 지금 아무 버그도
고치지 않는다 — 아직 쓰이지 않은 가드를 보호하며, 그것이 메타가드의 유일한
목적이다. 이것을 "결함 1건 수리"로 부풀리지 않는다.

## 5. 사고 — 죽은 검증 에이전트가 실제 운영 파일을 망가진 상태로 남겼다

이번 검증의 가장 중요한 산출물은 레지스트리에 대한 지적이 아니라 이것이다.

verify 에이전트들은 주장을 반박하려고 **실제 저장소를 직접 mutate**했다
(`lastToolName`이 `Edit`/`Write`/`Bash`). 그리고 mutation을 되돌리기 전에
지출 한도로 죽었다. 발견 당시 `vault-backlinks-mcp` 상태:

```
 M vault_backlinks_mcp/contracts.py
?? test_claim.py  test_claim_verification.py
?? test_defect_check.py  test_malformed_witness.py
?? vault_backlinks_mcp/contracts.py.backup
```

`contracts.py`에 남아 있던 것:

```python
-        "review_required": bool(review_checks) or truncated,
+        "review_required": False,  # BROKEN: always False for testing
```

**리뷰 필요 신호 전체를 항상 `False`로 만드는 상태.** 이 MCP의 안전 장치가
통째로 무력화된 채였고, 테스트는 통과했을 것이다 —
`review_required` 계산을 검사하는 테스트가 없기 때문이며, 그것 자체가
미검증 9건 중 두 건이 지적한 내용이다(§6의 #4, #8).

조치: 한 줄을 원상 복구(HEAD와 바이트 동일 확인), scratch 5개를
`$CLAUDE_JOB_DIR/tmp/agent_debris/`로 이동(삭제하지 않음), `.backup`이
HEAD와 동일함을 확인해 다른 숨은 mutation이 없음을 확인, 88 passed 확인.

**과정 결함으로 등록한다:**

> 적대적 검증 에이전트에게 실제 저장소를 mutate하게 하면, 그 에이전트가
> 죽는 순간 저장소가 망가진 채로 남는다. mutation은 **사본에서만**
> 하게 하고, verify 프롬프트에 실제 경로를 쓰기 대상으로 주지 말아야 한다.
> calibration 단계는 이미 사본을 썼는데(`tmp/witness_calib`), **verify
> 단계에는 같은 규율을 적용하지 않았다.** 내가 쓴 workflow의 결함이다.

이것이 이 세션에서 반복된 P2/P4와 같은 형태다 — 규율을 한 곳에 적어놓고
바로 옆에서 위반했다.

## 6. 미검증으로 남은 8건 — 잃어버리지 않기 위해 그대로 옮긴다

**아래는 판정되지 않았다.** 참인지 거짓인지 모른다. 후속 작업의 입력이다.

1. (witness-pairs) `FILESYSTEM_FALLBACK_USED` positive witness가
   `filesystem_fallback_backlinks`를 mock하지 않고 실제로 호출한다 —
   그것이 예외를 던지면 `fallback_paths`가 `None`이 되어 가드가 아예
   추가되지 않는다.
2. (test-isolation) 같은 witness가 모듈 로드 시점에 fallback이 꺼져 있으면
   발동할 수 없다 — `_query`의 monkeypatch는
   `FILESYSTEM_FALLBACK_ENABLED`만 덮고 `filesystem_fallback_backlinks`는
   덮지 않는다.
3. (test-isolation) `BASENAME_COLLISION` witness에서 positive가 만든
   `docs/target.md`가 negative 호출로 상태가 새어 나간다.
4. (coverage-gap) `contracts.py:388`의
   `review_required = bool(review_checks) or truncated` 계산을 검사하는
   테스트가 없다. **§5의 사고가 이 지적을 실증한다.**
5. (coverage-gap) `_codes()`가 코드만 뽑아 `dropped_by_reason` 등
   나머지 결과 필드를 전부 무시한다.
6. (coverage-gap) `ALL_RESULTS_FILTERED` witness가 `forbidden` 경로만
   검사하고 `malformed` 경로는 검사하지 않는다.
7. (coverage-gap) 오류 경로 가드(max_results 검증, path 검증, registry
   오류)는 `review_checks`의 코드로 표현되지 않으므로 **레지스트리에 애초에
   들어오지 못한다.** 사실이라면 레지스트리의 커버리지 주장 범위 자체가
   좁아진다 — 가장 중요한 후속 확인 대상.
8. (coverage-gap) `confirm_active_vault`가 예외를 던지면
   `contracts.py:225`에서 잡히지 않고 전파된다.

#7이 특히 중요하다. 사실이라면 "모든 가드에 witness가 있다"는 문장이
**"`review_checks`에 코드로 표현된 모든 가드에 witness가 있다"**로
축소되며, 그 차이는 레지스트리 docstring이 주장하는 것과 다르다.

## 7. 이 문서가 주장하지 않는 것

- **레지스트리가 검증을 통과했다고 주장하지 않는다.** 10건 중 2건만
  판정했고(1건 부분 확인, 1건 확인·수리), 8건은 미검증이다.
- **haiku 패널이 신뢰할 수 없다고 주장하지 않는다.** calibration 3/3이고,
  직접 검증한 2건 중 1건은 완전히 참, 1건은 서술 참·함의 과장이었다.
- 지출 한도는 **조직 월 한도**이며 이 workflow의 설계 문제가 아니다.
  다만 그 한도에 걸렸을 때 저장소가 망가진 채 남는 것은 설계 문제다(§5).
