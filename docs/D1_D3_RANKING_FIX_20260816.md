# D1/D3 — 순위 결함 수정 (2026-08-16)

`docs/HANDOFF.md` §6에 증상만 기록돼 있던 D1a·D1b·D3를 고쳤다. 완료 조건 3번
(실제 Vault 5문항 중 4건 이상 회수)이 **3/5 → 4/5**로 충족됐다.

## 1. 무엇이 문제였나 — 실측

수정 전, 같은 5문항에서:

| case | 결과 | top-4의 모습 |
|---|---|---|
| C1 direct keyword | HIT (rank 2) | **4개 전부 `archive/`** — 현재판은 출력 밖 |
| C3 backlink-only | **MISS** | **3개 전부 `notes/00-moc/`** — 그 MOC들이 색인하는 결정 문서가 밀림 |

이건 relevance ranking이 고장난 게 아니다. **자기 역사를 함께 보관하는 코퍼스**에서
관련도만으로 줄을 세운 정직한 결과다. 빠져 있던 입력은 "코퍼스의 어느 부분이
현재인가"였다.

## 2. 세 결함은 코드 경로가 서로 다르다

| | 무엇 | 실제 원인 |
|---|---|---|
| **D1a** | 바이트 동일 사본 중 worktree 사본이 정본 슬롯을 가져감 | `authority_rank`는 잘 작동하나 `authority_prefixes`가 비어 있어 **경로 사전순**으로 퇴화 |
| **D1b** | 내용이 다른 stale archive 문서가 현재판을 이김 | `authority_rank`는 **이 경로에 아예 없다**(replica가 아니므로). RRF 자체 문제 |
| **D3** | `symlink-vs-moc`이 pool엔 있는데 출력 8칸 밖 | D1b와 같은 계열 — graph walk는 도달했고 순위에서 밀렸다 |

## 3. 수정

**(a) `demoted_prefixes` 신설** — D1b·D3

`VaultProfile.demoted_prefixes`에 걸린 경로는 **검색되고 반환되지만**, 동등하게
관련 있는 비강등 경로보다 **뒤에 정렬**된다. `retriever.py`의 최종 정렬 키가
`(is_demoted, -score, path)`가 됐다.

- 순서만 바꾸고 **소속은 바꾸지 않는다** — archive 자료도 caller가 필요로 할 수
  있는 실제 증거다. 회귀 테스트가 이걸 강제한다.
- **같은 tier 안의 상대 순서는 건드리지 않는다** — 재점수화가 아니라 tier 경계다.
- 기본값이 비어 있어, **설정하지 않은 vault의 동작은 이전과 완전히 동일**하다.

**(b) `from_env()`가 순위 정책을 실제로 전달** — D1a의 근본 원인

이전에는 순위 정책이 **profile JSON 파일로만** 도달 가능했다. 그래서
`EVIDENCE_VAULT_ROOT`로 띄우는 MCP 서버 — **정상적인 기동 방식** — 는 권위 순서도
강등도 **전혀 없이** 돌고 있었다. 정책이 존재하되 닿을 수 없었다.

```
EVIDENCE_VAULT_AUTHORITY_PREFIXES   쉼표 구분
EVIDENCE_VAULT_DEMOTED_PREFIXES
EVIDENCE_VAULT_EXCLUDED_GLOBS
```

## 4. 측정 결과

```
설정 없음                    3/5   C1 rank 2(archive 사본), C3 MISS
demoted=archive/,notes/00-moc/   4/5   C1 rank 1(archive 아님), C3 HIT rank 3
  + authority=…/docs/, notes/audits/  4/5   정본 신원은 정확, C1 rank 6
```

`~/.claude/scripts/run_obsidian_vault_mcp.sh`에 `demoted` 설정을 넣었다.

## 5. 정직하게 남기는 것

- **C4는 여전히 MISS다.** top-4가 archive도 MOC도 아닌 `docs/feedback/*`이라
  강등으로 풀리지 않는다. 원인 미확정 — 별도 작업이다.
- **`authority_prefixes`는 순위를 개선하지 않는다.** D1a(정본 신원)만 고친다.
  위 표에서 C1의 rank가 오히려 6으로 내려간 것이 그 증거다. 회수는 4/5로 같다.
  두 knob은 서로 다른 것을 고치며, 어느 한 설정이 절대 우위가 아니다.
- **접두사는 문자열 매치다.** `concept-gate-taxonomy/`는 그 안의 중첩 worktree
  (`concept-gate-taxonomy/.claude/worktrees/…`)까지 매치해서, 정본이 아닌 사본이
  대표가 될 수 있다. 실제로 한 번 잘못된 결론을 냈다. 정밀한 접두사
  (`concept-gate-taxonomy/docs/`)를 써야 한다. 회귀 테스트로 이 동작을 못박았다.
- 위 수치는 전부 **host lane**, 이 vault 한 곳의 값이다. 5문항은 배관 확인용이지
  recall 추정치가 아니다.

## 6. 검증

- `python3 -m pytest -q` → **211 passed**
- poison test: 강등 정렬을 제거하면
  `test_demoted_paths_rank_below_equally_relevant_current_ones`가 정확히
  `archive/old.md != docs/current.md`로 실패하고, 되돌리면 통과한다.
- 기준선 테스트(`test_without_demotion_the_archived_copy_wins`)를 함께 뒀다 —
  이게 깨지면 강등 테스트가 아무것도 증명하지 못하게 되므로 둘을 같이 고쳐야 한다.
