# 적대적 검증 기록 — push 직전 (2026-08-09)

두 저장소(`vault-backlinks-mcp`, `evidence-evaluator`)를 push하기 전에 실행한
독립 적대적 검증의 **전체 기록**. 원시 발견 17건 전문은
`adversarial_review_20260809_raw_findings.json`에 그대로 보존한다.

## 0. 실행 조건과 그 결과의 지위 — 먼저 읽을 것

- **설계**: 2 repo × 3 관점(correctness / security / claims-vs-code) = 6개
  독립 리뷰 → 각 발견마다 **반증 전용 검증 에이전트** 1개씩.
- **실제**: 리뷰 6개는 전부 완료(원시 발견 **17건**). 검증 에이전트는
  **23개 중 17개가 월 지출 한도로 실패**했다.

워크플로우가 반환한 `confirmedCount: 0`은 **"확정된 결함이 0건"이 아니다.**
검증 단계가 실행되지 않아 **아무것도 확정되지도 반증되지도 못한** 상태다.
이 저장소 계열의 어휘로 **PASS가 아니라 BLOCKED**다
(`concept-gate-taxonomy/CLAUDE.md`의 PASS/FAIL/BLOCKED 3값 계약).

> `confirmedCount: 0`을 "깨끗하다"로 읽는 것이 정확히 이 저장소가 15회 기록한
> P1 패턴(참이지만 필요하지 않은 명제를 근거로 삼기)이다. 그렇게 읽지 않았다.

**대응**: 자동 검증이 못 한 몫을 **메인 세션이 직접 실행으로 재현**했다.
아래 §1의 두 건은 그 재현 결과이며, 나머지는 미검증 상태로 남긴다.

## 1. 직접 재현해 확정한 것

### C1 — `run_clean_judge()`의 무결성 검사가 기본 경로에서 발동하지 않음
**(evidence-evaluator, blocker, 리뷰어 2명 독립 수렴 — 발견 #7, #13)**

`evaluator.py`의 모듈 docstring은 이 서브프로세스 구조의 **존재 이유 자체**를
"채점기 소스가 패치되지 않았음을 채점 전에 검증한다"로 선언한다. 그런데:

```python
def run_clean_judge(payload_path: Path, pins: dict | None = None) -> dict:
    ...
    if pins:                      # ← pins가 없으면 --pins를 안 붙임
        cmd += ["--pins", json.dumps(pins)]

# main() 안:
if args.verify_self and args.pins:   # ← 따라서 이 블록이 통째로 안 돌음
```

**재현(메인 세션 실측)**: `evaluate()`를 "항상 통과 + `TAMPERED: true`"로
치환한 뒤,

| 호출 | 결과 |
|---|---|
| `run_clean_judge(path)` — **기본값** | `{"full_hard_gate": true, "failure_codes": [], "TAMPERED": true}` — 오류 없음, 경고 없음, exit 0 |
| `run_clean_judge(path, pins=<정상 핀>)` | `{"judge_error": "judge source drifted: ['evaluator.py']", "returncode": 3}` |

**같은 변조 상태에서 한쪽은 조용히 통과시키고 한쪽은 잡는다.** 즉 기능은
있으나 **호출자가 매번 `pins`를 기억해야만** 작동한다.

부수 확인(발견 #14): `tests/` 어디에서도 `run_clean_judge`를 호출하지 않는다.
원본 실험에서는 모든 호출부가 항상 `pins=source_hashes()`를 넘겨서 이 문제가
드러나지 않았고, **그 안전망은 이식과 함께 오지 않았다.**

이것은 P1의 16번째다 — 그리고 이번엔 **"이 저장소의 존재 이유"라고 쓴 기능**
에서 났다.

### C2 — 배포 docstring이 존재하지 않는 필드명을 지시
**(vault-backlinks-mcp, major, 리뷰어 2명 독립 수렴 — 발견 #0, #5)**

`server.py`의 T3 docstring(제가 2026-08-09에 추가한 수정문)이
`backlink_count`를 도구 응답의 필드인 것처럼 지시한다.

**재현(메인 세션 실측)**:
```
grep -rn backlink_count vault_backlinks_mcp/   →  server.py:42, server.py:45  (docstring 2곳뿐)
실제 반환 키: contract_version, vault_id, path, backend_used, backlinks,
             total, dropped_out_of_scope, review_required, review_checks, error
'backlink_count' in result  →  False
```

`backlink_count`는 **실험의 응답 스키마**(`_gen_prompts.py`의
`RESPONSE_SCHEMA` — Haiku 피험자가 자기 답을 담는 필드) 이름이다. T3 수정문을
쓸 때 **피험자 답변 스키마와 도구 출력 스키마를 혼동해** 그 이름을 그대로
배포 docstring에 넣었다.

**이 결함의 성격이 특히 나쁘다**: T3 실험은 이 docstring이 Haiku의 이해도를
개선했음을 보였다(§OPERATIONS_LOG §7). 그런데 실험 프롬프트에서는 피험자가
같은 이름의 필드를 **자기 출력으로** 갖고 있었기 때문에 혼동이 드러나지
않았다. **실험 설정이 결함을 가렸다.**

## 2. 미검증으로 남은 것 (자동 검증 실패분)

아래는 리뷰어가 "실행으로 확인했다"고 보고했으나 **독립 반증 검증을 거치지
않았다.** 원문은 raw findings JSON 참조.

| # | 심각도 | 파일 | 요지 |
|---|---|---|---|
| 2 | blocker | `security.py` | `is_forbidden()`이 **문자열만** 검사 → (a) symlink 별칭 우회 (b) 대소문자 우회(APFS 기본 대소문자 무시). `exists_under_root()`는 resolve하므로 통과 |
| 3 | blocker | `security.py` | `find_basename_collisions()`가 `is_forbidden` 필터 없이 `rglob` → **`hidden_gold/...` 경로가 `BASENAME_COLLISION` 메시지로 유출** |
| 4 | major | `security.py` | forbidden 밖의 symlink가 `hidden_gold` 내부를 가리키면 질의 대상으로 수용되어 외부 CLI까지 도달 |
| 1, 6 | minor | `contracts.py` | `dropped` 카운터가 4가지 이유로 증가하는데 `ALL_RESULTS_OUT_OF_SCOPE` 문구는 **항상 vault 불일치로 단정** → 오진 유도 |
| 9, 14 | major | `evaluator.py` | C1의 다른 서술 + `run_clean_judge` 테스트 0건 |
| 8, 11, 12, 15, 16 | minor | `README.md`, `.gitignore` | 문서/설정 관련 |
| 10 | minor | `providers.py` | — |

**#2와 #3은 blocker이며 보안 성격이다.** 리뷰어는 실제 파이프라인으로
재현했다고 보고하지만, 메인 세션이 아직 독립 확인하지 않았다.

## 3. 판정

**두 저장소 모두 push 보류.**

근거:
1. 직접 재현한 blocker 1건(C1)이 미수정 상태다.
2. 미검증 blocker 2건(#2, #3)이 **보안 성격**이며, 그중 #3은 gold 데이터 경로
   유출이다 — 이 도구가 막겠다고 선언한 바로 그것.
3. 자동 검증이 BLOCKED이므로 "17건 중 나머지는 무해하다"고 말할 근거가 없다.

`evidence-evaluator`의 remote(`goodand/evidence-evaluator`)는 존재하고
비어 있으며, `vault-backlinks-mcp`는 **remote 미설정**이다.

## 4. 다음 행동 (순서 고정)

1. **C1 수정** — `pins`를 사실상 필수로. 후보: `pins=None`이면 자체 계산해
   항상 검증하거나, 검증 없이 돈 경우 결과에
   `"integrity_verified": false`를 **반드시 표시**. 조용한 no-op만은 금지.
2. **C1 회귀 테스트** — 변조된 채점기가 통과하지 못함을 뮤테이션으로 고정.
   현재 `run_clean_judge` 테스트는 0건이다.
3. **C2 수정** — docstring의 `backlink_count` → `total`. T1 동결본은
   **건드리지 않는다**(이미 채점된 실험의 입력).
   → T3 텍스트가 바뀌므로 `_prompts_t3.json` 재생성 + `trials_t3.json` 무효화
   여부 판단 필요. **이미 나온 T3 결과는 낡은 문구로 측정된 것**임을 기록할 것.
4. **#2, #3 직접 재현** 후 수정.
5. 전부 통과하면 push.
