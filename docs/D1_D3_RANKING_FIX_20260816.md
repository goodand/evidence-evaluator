# D1/D3 — 순위 결함 수정 (2026-08-16)

`docs/HANDOFF.md` §6에 증상만 기록돼 있던 D1a·D1b·D3를 다뤘다. **D1b는 고쳤고,
D3는 고치지 못했다.**

> ## ⚠️ 이 문서의 첫 판을 정정한다 (2026-08-16, 같은 날)
>
> 첫 판은 **"3/5 → 4/5, 완료 조건 3번 충족"**이라고 적었다. **틀렸다.**
>
> 그 4/5는 `graph_seed_k=4, max_turns=4`에서만 나온다. **도구 기본값**
> (`graph_seed_k=12`)에서는 demotion을 켜도 **3/5**다. 실제 caller가 받는 것은
> 기본값이므로, 완료 조건 3번은 **여전히 미충족**이다.
>
> 이걸 잡은 것은 내 재측정이 아니라 **Claude Desktop의 독립 실험**이다. Desktop이
> 기본 파라미터로 같은 질의를 돌려 "symlink-vs-moc 파일이 직접 반환되지 않았다"고
> 보고했고, 실제 MCP 서버로 재현해보니 Desktop이 맞았다.
>
> 특히 나쁜 실수인 이유: 이 저장소는 **`discovered_path_count`가 파라미터에 따라
> 달라지니 두 수를 같은 측정으로 취급하지 말라**고 이미 `HANDOFF.md` §6에 적어
> 뒀다. 그 주의를 내가 쓰고 내가 어겼다.

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

## 4. 측정 결과 — 파라미터를 명시한다

**도구 기본값**(`output_k=8, candidate_pool_k=50, graph_seed_k=12,
max_turns=6`) — 실제 caller가 받는 값:

```
설정 없음                        3/5   C1=HIT@2(archive 사본)  C3=MISS  C4=MISS
demoted=archive/,notes/00-moc/   3/5   C1=HIT@1(archive 아님)  C3=MISS  C4=MISS
```

**demotion이 기본값에서 실제로 한 일**: 회수 건수는 그대로고, C1이 **archive
사본(rank 2)에서 현재 사본(rank 1)으로** 바뀌었다. 이건 D1b가 고쳐졌다는
뜻이지만 **binary hit count는 움직이지 않는다.**

### C3는 왜 파라미터를 타는가 (demotion ON, 실측)

```
graph_seed_k  max_turns   출력 순위   pool에 있나
           4          4          3        True
           4          6          3        True
           8          4          5        True
           8          6          5        True
          12          4       MISS        True
          12          6       MISS        True   <- 도구 기본값
```

`max_turns`는 무관하고 **`graph_seed_k`가 결정 변수**다. seed를 늘릴수록
graph 채널에 이웃이 더 많이 들어와 symlink-vs-moc을 8칸 밖으로 밀어낸다.

**모든 설정에서 `candidate_pool`에는 들어 있다.** 즉 D3는 여전히 "닿았는데
순위에서 밀린다"이고, demotion으로는 해결되지 않았다.

`~/.claude/scripts/run_obsidian_vault_mcp.sh`에 `demoted` 설정을 넣었다.

## 5. 정직하게 남기는 것

- **완료 조건 3번(≥4/5)은 미충족이다.** 기본값에서 3/5. D1b는 고쳤고 D3는 못
  고쳤다.
- **D3의 다음 단계는 `graph_seed_k`다** — demotion이 아니다. seed 수가 늘수록
  graph 채널이 출력 창을 잡아먹는다는 것까지는 실측했으나, 왜 그 문서가 특히
  밀리는지는 **아직 원인을 확정하지 않았다.**
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
