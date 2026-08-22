# 사전등록 — vault-backlinks-mcp 실 MCP transport 독립 테스트 (2026-08-22)

피험자 실행 **전에** 기대값을 동결한다. 이전 독립 테스트(haiku,
evidence-vault-mcp)와 같은 규율: 정답 무누출, 파라미터 고정, 검증자는 자기
보고를 재현으로 대조.

## 연결 상태

- 서버: `~/.claude/scripts/run_vault_backlinks_mcp.sh` (stdio, fastmcp 3.4.6,
  pinned python3.13). initialize handshake 실측 통과.
- 코드: **subtree 정본** (`mcp-v01-backlinks/vault-backlinks-mcp`) — 독립
  저장소는 error_code 채널이 없으므로 대상이 아니다. merge 후 재지정 예정
  (launcher 주석에 기록).
- registry: `~/.claude/scripts/vault_backlinks_registry.json`,
  `project-in-progress` → 실제 vault.
- 등록: user 스코프(`~/.claude.json`, `claude mcp add`) — worktree 격리가
  `Project_in_progress/.mcp.json` 편집을 막았기 때문(I194와 같은 권한 조임).
  **다음 세션 시작부터 연결된다.**

## 사전등록 기대값 (in-process ground truth, host lane, 2026-08-22)

transport(stdio MCP)는 얇은 wrapper이므로 내용 필드는 아래와 일치해야 한다.
불일치는 transport 층 결함이거나 vault 상태 변화이며, 둘을 구별해 보고한다.

| 세계 | 입력 | 기대 |
|---|---|---|
| 정상+잘림 | `HARNESS_KNOWHOW.md`, max_results=3 | `backend_used: live`, total 9(±vault 변화), returned 3, codes에 `TRUNCATED`·`BASENAME_COLLISION`, `review_required: true`, error_code 없음 |
| max_results=0 | | `error_code: INVALID_MAX_RESULTS`, backend none |
| `../escape.md` | | `error_code: INVALID_PATH` |
| `hidden_gold/g.md` | | `error_code: PATH_FORBIDDEN` |
| 미등록 vault_id | | `error_code: REGISTRY_ERROR` |
| 없는 파일 | | `error_code: PATH_NOT_IN_VAULT` |

degraded 두 세계(`VAULT_HARNESS_DIR`를 빈 디렉터리로)는 in-process에서만
구성 가능하므로 MCP 독립 테스트 범위 밖 — in-process 실측값만 기록한다:
fallback 켬 → `backend_used: filesystem_fallback` + `FILESYSTEM_FALLBACK_USED`,
끔 → `error_code: BACKEND_UNAVAILABLE`.

## 피험자 설계 (재시작 후 실행)

- haiku, zero-context, workflows 승인됨 (사용자, 2026-08-22).
- 렌즈 3: 정상+잘림 계약 / 거부 5종에서 **error_code가 cold user에게 원인을
  전달하는가**(이번 세션 F7 수리의 사용성 검증) / `review_checks`의
  `required_action`을 cold user가 실행 가능한 지시로 읽는가.
- 보고 규율: 전 필드 원문, 파라미터 명시, 오류는 원문 인용.
- 채점: 이 표와 대조. total 등 live 값은 vault 상태 변화 허용, error_code와
  구조 필드는 정확 일치 요구.
