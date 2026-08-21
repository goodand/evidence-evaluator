# 독립 테스트 — zero-context haiku 피험자의 evidence-vault-mcp 사용 (2026-08-22)

> "subagent haiku가 그 MCP를 사용하게 해서 독립 test를 진행시켜라"

피험자: haiku subagent 1개, 이 세션 컨텍스트 없음, 읽기 전용(쓰기·Bash 금지).
설계에 반영한 이번 세션 교훈: 정답 무누출, **파라미터 고정**(Desktop 라운드의
`graph_seed_k` 사고 방지), 전 필드 원문 보고 강제(자기 보고 과장 방지),
검증자는 피험자 보고를 그대로 받지 않고 재현 대조한다.

## 1. 채점 — 세 축 전부 검증 통과

| Task | 검증 방법 | 결과 |
|---|---|---|
| A `vault_search` (질의·파라미터 고정) | **결정적 재현 대조** — 내가 피험자 실행 전 같은 호출로 ground truth 확보 | 전 필드 일치. `artifact_digest`까지 동일 (`e3c427f0…`) — 같은 artifact라는 가장 강한 증거 |
| B `vault_read` (경로 명시) | 실제 파일과 인용 대조 | §B4a 표 4행·"7회 처방되고 7회 실패" 문장 축자 일치(개행 결합만 허용 범위). "총 326행" 보고도 `wc -l` 실측과 일치 |
| C `vault_backlinks` | 내가 같은 호출 재현 | **바이트 일치** — backlinks 20개 순서, `discovered 33`, `truncated`, `fallback_used: null` 전부 |

날조·과장 없음. 특히 피험자는 `next_action`을 따르지 **않았음**을 지어내지
않고 이유와 함께 보고했다(내 과제 지시가 "응답만 보고하라"였기 때문 — 도구가
아니라 내 프롬프트의 제약이다).

## 2. 피험자가 낸 발견 — 검증자가 뿌리까지 파서 판정

### 2a. 확정 — 집계 경고 문구가 "CLI 다운"으로 오독된다

피험자의 cold-user 판단: *"TASK A는 CLI unavailable이라 했고, B·C는
`fallback_used: null`이니 live source다."* **앞 절반이 오독인데, 오독의
책임이 문구에 있다.** 나도 같은 세션에서 같은 오독을 했다.

실측으로 뿌리를 확정했다:

1. `/usr/local/bin/obsidian backlinks path=…` 직접 probe → **exit 0, 정답.**
   CLI는 살아 있다. 따라서 backlinks의 `fallback_used: null`은 정확한 라벨이다.
2. `include_diagnostics=true`로 원본 경고 18건 추출 → **전부 점 디렉터리
   경로다** (`evidence-evaluator/.claude/worktrees/…`, `.vault-harness/…`,
   `concept-gate-taxonomy/.claude/worktrees/…`). Obsidian은 점 디렉터리를
   색인하지 않으므로 CLI가 `Error: File … not found`를 답한 것.
3. 코드 확인(`service.py:_compact_warnings`): "obsidian"이 들어간 경고를
   전부 세어 `"Obsidian CLI graph probes unavailable or failed: N;
   filesystem fallback used."` 한 줄로 뭉갠다.

즉 실제 의미는 *"N개 경로가 Obsidian 색인 밖이라 그 경로들만 filesystem
그래프를 썼다"*인데, 문구는 *"CLI가 죽었다"*로 읽힌다. **하이브리드 동작
자체는 설계대로 작동하고 있다** — 문구만 두 상황(CLI 다운 vs 경로별 비색인)을
구별하지 못한다.

개선 후보(미구현): `_compact_warnings`에서 `File … not found`류와 진짜
CLI-다운류를 분리 집계. 예: `"Obsidian이 색인하지 않는 경로 N건은 filesystem
그래프 사용"` vs `"Obsidian CLI 응답 불가"`.

### 2b. 유효 — `vault_read` 잘림이 본문에는 보이지 않는다

피험자: 326행 중 1–200행만 반환됐고, 그 사실이 `truncated`/`total_lines`
메타필드에만 있어 **본문을 훑는 사용자는 모른다.** 정당한 지적이다. 다만
피험자는 메타필드를 읽고 스스로 알아챘으므로 계약은 작동했다 — "더 명료할 수
있다"이지 "고장"이 아니다.

### 2c. 유효 — `review_required=true`의 결과가 cold user에게 불명확

`next_action`을 읽으면 해소되지만, 피험자 지적대로 "무엇을 검토해야 하고 안
하면 어떻게 되는가"가 필드만으로는 안 보인다. 이건 CLAUDE.md의 계약(모든
`review_checks[].required_action` 실행)이 **호출자 문서**에 있고 응답 자체에는
압축된 형태로만 있기 때문이다. 기록해 두고, 응답 필드 확장은 계약 변경이므로
별도 판단 대상.

## 3. 부수 확인 — 이 테스트가 지나가며 증명한 것

- backlinks 목록에 이 worktree의 `HANDOFF_SELFTEST_HARNESS_20260818.md`가
  들어 있다 — **2026-08-14에 얼린 색인이 아니라 살아 있는 그래프**를 보고
  있다는 뜻이다(그 문서는 8-18에 생겼다).
- `notes/00-moc/` 경로들이 상위에 오지 않았다 — demoted prefix 설정이 MCP
  경로에서도 작동.
- 도구 스키마의 계약 문구("a CLI failure degrades the answer and says so")가
  실제 동작과 일치함을 CLI 생존 상태에서 확인.

## 4. 이 문서가 주장하지 않는 것

- **피험자 1명, 실행 1회다.** cold-user 오독이 보편적이라는 주장은 n=2
  (haiku 피험자 + 검증자인 나)에 근거하며, 둘 다 같은 문구에서 같은 방향으로
  틀렸다는 것까지만 사실이다.
- Task B의 개행 결합은 축자성의 완화이며, 채점 기준을 "문장 인용"으로 둔 내
  과제 설계상 허용했다.
- 2a의 개선 후보는 **구현하지 않았다.** 문구 수정은 running MCP 서버의 계약
  표면이므로 별도 커밋과 poison test가 필요하다.
- 피험자가 `next_action` 미이행을 보고한 것은 도구 계약 위반의 증거가 아니다
  — 내 과제 지시가 이행을 배제했다. **계약 준수 여부 자체를 검증하려면 과제
  지시에서 그것을 열어둔 별도 실험이 필요하다.**
