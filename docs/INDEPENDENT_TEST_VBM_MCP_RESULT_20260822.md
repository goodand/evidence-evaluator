# 독립 테스트 결과 — vault-backlinks-mcp, 실 MCP transport (2026-08-22)

사전등록: [`PREREG_VBM_MCP_INDEPENDENT_TEST_20260822.md`](PREREG_VBM_MCP_INDEPENDENT_TEST_20260822.md)
피험자: haiku 3명(workflow), zero-context, 실 `mcp__vault-backlinks-mcp__vault_backlinks` 사용.
검증자 대조: 피험자 실행 전 검증자의 실 transport 호출 1건 + in-process ground truth.

## 1. 사전등록 대비 — 동결 기대값 전부 일치

| 세계 | 사전등록 기대 | 피험자 보고 | 판정 |
|---|---|---|---|
| 정상+잘림 | live, total 9, returned 3, TRUNCATED·BASENAME_COLLISION, error null | 전부 동일 (원문) | ✅ |
| max_results=0 | `INVALID_MAX_RESULTS` | 동일 | ✅ |
| `../escape.md` | `INVALID_PATH` | 동일 | ✅ |
| `hidden_gold/g.md` | `PATH_FORBIDDEN` | 동일 | ✅ |
| 미등록 vault | `REGISTRY_ERROR` | 동일 | ✅ |
| 없는 파일 | `PATH_NOT_IN_VAULT` | 동일 | ✅ |

피험자들의 error 첫 문장 원문이 in-process ground truth와 일치 —
**in-process 차선과 MCP transport 차선이 내용 동일함**이 교차 확인됐다.

## 2. 핵심 질문의 답 — error_code는 cold user에게 작동하는가

거부 렌즈 피험자의 측정된 판정:

- **분류로서는 완전하다.** 5개 실패가 5개 서로 다른 코드로 왔고 충돌 없음.
  "branch on error_code — that is the only field that reliably distinguishes
  different error types"; 산문 파싱 없이 기계 분기 가능. **F7 수리의 설계
  목표가 cold user에게서 확인됐다.**
- **수정 지시로서는 2/5만 자족적이다.** `INVALID_MAX_RESULTS`·
  `PATH_NOT_IN_VAULT`는 코드만으로 고칠 수 있으나, `INVALID_PATH`(무엇이
  invalid인지), `PATH_FORBIDDEN`(어떤 segment가 금지인지),
  `REGISTRY_ERROR`(어떤 vault_id가 유효한지)는 산문이 필요하다.

판정: **결함 아님, 측정된 역할 분담.** 코드=분류(기계 분기), 산문=수정
정보(금지 목록·allowlist가 error 문장에 열거돼 있고 피험자가 그걸로 전부
고쳤다). 산문의 수정 정보를 구조화 필드(예: `allowed_vault_ids`)로 올리는
것은 선택적 개선으로 남긴다 — 지금 요구하는 소비자가 없다.

## 3. 나머지 두 렌즈

- **잘림 계약**: `total`(9)과 `returned_count`(3)를 필드명까지 정확히
  구별했고, "혼동 가능하냐"는 질문에 두 필드의 스코프 차이로 답했다.
  도구 설명의 미묘한 규칙 — review_checks가 있어도 count 신뢰를 낮추지
  말 것, 예외는 `AMBIGUOUS_ACROSS_REGISTERED_VAULTS`뿐 — 을 **해당 문장을
  원문 인용하며 정확히 적용**했다. 다음 행동도 required_action대로.
- **required_action 실행 가능성**: TRUNCATED는 즉시 실행 가능(재호출),
  BASENAME_COLLISION은 이 도구만으로는 확인 불가(다른 도구 필요)라고
  정확히 판별. AMBIGUOUS 미수신과 count 신뢰 유지 판단도 옳다.

## 4. confusions: 3명 전원 빈 목록

이전 독립 테스트(evidence-vault-mcp, 같은 방법론)에서는 피험자가 혼동 3건을
보고했고 그중 1건이 실전 수리(typed codes)로 이어졌다. 이번엔 0건이다.
**이번 세션에서 만든 것들 — error_code 채널, 명시적 도구 설명(count 신뢰
규칙과 그 예외), required_action에 열거된 수정 정보 — 이 cold user 경험에서
혼동으로 보고될 것을 남기지 않았다.**

## 5. 이 문서가 주장하지 않는 것

- **피험자 각 1명, 실행 각 1회.** confusions 0이 "혼동 불가능"을 뜻하지
  않는다 — 지난 테스트와의 비교는 방법론이 같다는 조건에서의 관측이다.
- degraded 두 세계(`FILESYSTEM_FALLBACK_USED`/`BACKEND_UNAVAILABLE`)는 env
  조작이 서버 쪽이라 **MCP transport 렌즈로는 검증하지 않았다** — 사전등록에
  적힌 대로 in-process 실측만 있다.
- live 수치(total 9)는 vault 상태에 의존한다. 사전등록·검증자 호출·피험자
  호출이 같은 날이라 일치했을 뿐, 시점이 벌어지면 달라질 수 있다.
- 서버가 가리키는 코드는 subtree 정본이다. merge 전까지 독립 저장소와
  다르다는 사실은 HANDOFF §3에 있다.
