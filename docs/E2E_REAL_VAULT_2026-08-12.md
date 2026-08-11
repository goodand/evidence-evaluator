# 실제 Vault E2E — 2026-08-12, stdio MCP 프로세스

대상 커밋 `d93929c`. vault root = `/Users/jaehyuntak/Desktop/Project_in_progress`
(합성 fixture 아님). 세 도구 전부 **실제 stdio MCP 서버 프로세스**를 통해 호출.

## 판정 요약 — v0.1 완료 조건 3번 **FAIL**

> 조건 3: 실제 Vault E2E 5건 중 **최소 4건**에서 필요한 문서가 회수된다.

**실측 2/5.** 아키텍처를 다시 설계하지 않는다 — 지시서대로 실패 query를 fixture로
만들고 최소 수정한다.

| # | case | 회수 | status | fallback | discovered | 시간 |
|---|---|---|---|---|---|---|
| C1 | direct keyword (`obligation_layer_roadmap`) | **RECOVERED**(약함, 아래) | review_required | — | 174 | 0.2s |
| C2 | wikilink hop (`HANDOFF_REUSE_VALIDATION`) | **RECOVERED** | review_required | filesystem | 185 | 0.1s |
| C3 | backlink-only (`symlink-vs-moc`) | **MISS** | review_required | filesystem | 132 | 0.1s |
| C4 | stale/동명 (`NEXT_SESSION_TRAPS`) | **MISS** | review_required | filesystem | 75 | 0.1s |
| C5 | 정답 없음 | n/a — **absence로 확정하지 않음** ✅ | review_required | filesystem | 100 | 0.1s |

`vault_read`는 5건 전부 성공. `vault_backlinks`는 5건 전부 응답(1~5건).

## 답해진 질문 — Obsidian CLI는 MCP 프로세스에서 도달 가능하다

지시서가 "터미널 결과로 판정하지 말고 MCP가 실행되는 process boundary에서
control query를 실행하라"고 요구했다. 결과:

- **C1의 backlinks가 `fallback_used: null`로 5건 반환** → 그 경로에서 **CLI가
  실제로 응답했다.** IPC는 이 lane에서 살아 있다.
- 그러나 **경로별로 실패한다**: `.handoff-reuse-subject-worktree/…`,
  `.vault-harness/…`, `concept-gate-taxonomy/.claude/worktrees/…`에 대해
  `Error: File "..." not found.` — Obsidian 인덱스에 없는 dot-디렉터리·중첩
  worktree다.
- 그때마다 filesystem fallback이 동작하고 warning이 남았다. **오류 허용 정책이
  설계대로 작동한 실측이다.**

기록: 실행 환경 macOS host lane / CLI `/usr/local/bin/obsidian` (`--version` 없음,
`version` 사용) / vault root 위와 같음 / MCP control query **성공(부분)** /
filesystem fallback **성공** / 경로별 CLI 실패는 **BLOCKED가 아니라 정상 강등**.

## 발견된 결함 3건 — 다음 최소 수정 대상

### D1. archive 사본이 정본보다 먼저 온다 (C1이 "약한 회수"인 이유)

C1은 `archive/worktrees/concept-gate-e2.1-wt/docs/obligation_layer_roadmap.md`를
회수했다 — **archive 사본**이고 정본은
`concept-gate-taxonomy/docs/obligation_layer_roadmap.md`다. top-1은 아예 다른
문서였다. `authority_rank`가 archive/worktree 사본을 정본보다 낮게 놓지 못한다.

**C4의 MISS도 같은 계열이다** — 동명·중복 경로가 8칸을 채웠다.

### D2. `review_required`가 항상 true라 정보가 없다

5건 전부 `review_required: true`, `exhaustive: false`,
`terminal_reason: turn-budget-exhausted`. 회수에 성공한 C1·C2도 같다. **모든 응답이
같은 값을 내면 그 필드로 두 경우를 구별할 수 없다** — 이 저장소가 반복해서 기록한
"관측값이 같으면 측정 채널이 없다"와 같은 형태다.

`turn-budget-exhausted`가 기본값처럼 나오는 것이 원인으로 보인다(`max_turns=4`).

### D3. C3는 graph walk가 닿아야 하는 케이스인데 닿지 못했다

`symlink-vs-moc`은 이 workspace의 `CLAUDE.md`가 **recall 실패 사례로 명시한**
문서다(경로가 질문 어휘를 하나도 포함하지 않음). `discovered: 132`인데 output 8칸에
들지 못했다 — 후보로는 닿았는지, 재순위에서 밀렸는지 아직 구별하지 않았다.

## 이 문서가 주장하지 않는 것

- **"Obsidian 통합 완료"** — CLI가 응답하는 경로와 실패하는 경로가 둘 다 있다.
  확립된 것은 "MCP 프로세스에서 도달 가능하고, 실패는 정상 강등된다"까지다.
- **"검색 성능"** — 5문항은 배관 확인용이고 recall 추정치가 아니다.
- **"D1~D3의 원인"** — 증상만 기록했다. D3는 후보 누락인지 재순위 문제인지 아직
  측정하지 않았다.
- 위 수치는 **host lane** 값이다.

## 다음 (지시서 Step 5의 최소 수정 루프)

```
실패 query 1개(C3 또는 C4) → fixture 추가 → 최소 수정 → 회귀 테스트 → 재실행
```

D2는 계약 필드의 의미 문제라 fixture 없이도 고칠 수 있고, **회수율보다 먼저
고쳐야 한다** — 지금 상태로는 "검토가 필요하다"가 늘 참이어서 agent가 그 신호를
무시하게 된다.
