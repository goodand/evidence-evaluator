# HANDOFF — Obsidian retrieval MCP v0.1

이 문서 하나로 재개할 수 있게 쓴다. 이전 대화를 모른다고 가정한다.
갱신 2026-08-14.

## 1. 지금 상태 한 줄

**세 MCP 도구는 동작하며, 동결한 zero-context confirmatory 6문항은 6/6
통과했다.** Runtime, Retrieval, Reconstruction을 분리해 측정했고 실행 무효는
0건이다. 이 결과를 qualification으로만 사용하는 단계형 2x2 검색 실험도
구현·동결했으며 아직 subject run은 하지 않았다. 설계 정본은
[`HANDOFF_FACTORIAL_V2.md`](HANDOFF_FACTORIAL_V2.md)다. 공개 qualification 결과는
[`HANDOFF_CONFIRMATORY_RESULT_20260814.md`](HANDOFF_CONFIRMATORY_RESULT_20260814.md)에
있다. 아래의 실제 Vault 2/5 결과는 2026-08-12 개발 기준선이며 최신 confirmatory
결과와 혼동하지 마라.

**추측하지 말고 물어라. 읽기 전용 두 명령이 상태를 말한다:**

```bash
cd /Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator
python3 -m pytest tests/ -q                        # 현재 기대: 104 passed
python3 -m pytest tests/test_v01_tool_contract.py -q  # 12 passed — 실제 MCP 프로세스
```

기대값(2026-08-12 종료 시점, **host lane**):

```
tests/            74 passed
v0.1 계약         12 passed  (stdio MCP 서버 프로세스에서 검증)
실제 Vault E2E    2/5 회수   ← 조건 미달. docs/E2E_REAL_VAULT_2026-08-12.md
```

**"host lane"이 붙은 이유**: 이 수치는 Obsidian CLI와 subprocess 실행이 허용된
환경의 값이다. 권한이 다른 관리형 sandbox에서는 달라질 수 있고, 그것은 회귀가
아니라 **BLOCKED**다.

## 2. 이 저장소가 무엇인가

**무맥락 agent가 Markdown 코퍼스에서 handoff와 근거를 찾아 작업 상태·다음 행동을
복구할 수 있는가**를 실험하는 검색 도구와 최소 평가 실행기다.

검색 표면은 **MCP 도구 세 개**뿐이다:

| 도구 | 하는 일 |
|---|---|
| `vault_search` | recall-first 검색. lexical seed → graph 확장 → 재순위 |
| `vault_read` | canonical Markdown 경로의 **범위 제한** 읽기 |
| `vault_backlinks` | 이 문서로 들어오는 링크. CLI가 답하면 live, 아니면 filesystem |

**범위 밖(확장하지 마라)**: repository patch 평가, safety audit, primary 승인
ledger, reviewer isolation, release attestation, GraphRAG, neural reranker.

## 3. git 상태

```
repo    /Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator
branch  main

8566851  feat — stdio launcher
ea3c94c  docs — vault_backlinks와 fallback_used
b6e74c2  fix — D2 exhaustive 계산
7482549  docs — 실제 Vault E2E 5건, 2/5 회수, 조건 3 FAIL
d93929c  feat — vault_backlinks 도구 + fallback_used 계약 필드
```

기능 branch는 `main`에 병합됐고 `origin/main`으로 게시한다. force push, history
rewrite, destructive reset은 금지한다.

## 4. 절대 하면 안 되는 것

- **`.vault-harness/`와 active experiment artifact를 수정·이동·삭제·이름변경하지
  마라.** 참고 자료로 **읽기만** 한다.
- **코드를 손으로 복사해 정본을 두 벌 만들지 마라.** 이 저장소가 검색 구현의
  정본이다.
- `hidden_gold`, private answer key, credential을 읽거나 공개 저장소로 옮기지 마라.
- 승인되지 않은 push, force push, history rewrite, destructive reset 금지.
- **오류를 빈 배열로 삼키거나 성공으로 위장하지 마라** — 아래 §5가 계약이다.

## 5. 계약 — 오류 허용과 fail-closed의 경계

이 둘을 섞으면 안 된다. **provider 문제는 강등, 보안 경계는 거부다.**

| 상황 | 동작 |
|---|---|
| Obsidian CLI 불가 | filesystem graph로 **계속**. `status=partial`, `fallback_used="filesystem"`, `review_required=true`, warning 기록 |
| BM25/graph walk 실패 | 현재 lexical 후보 **반환** |
| 일부 파일 읽기 실패 | 성공분 + 실패 경로 **함께** 반환 |
| 검색 0건 | **`review_required=true`.** "문서가 없다"고 확정하지 않는다 |
| vault 밖 · `hidden_gold` · `private_eval` · symlink escape · non-Markdown | **fail-closed 거부.** partial이 아니다 |

불변식: `1 <= output_k <= candidate_pool_k <= 500`,
`len(retrieved_paths) <= output_k`, backlinks는 `limit`으로 잘리고 `truncated`를
표시한다.

## 6. 지금 막혀 있는 것 — 결함 3건 (D2는 §7에서 고쳤다)

전문은 [`E2E_REAL_VAULT_2026-08-12.md`](E2E_REAL_VAULT_2026-08-12.md).
**D1·D3는 증상만 기록했고 원인은 확정하지 않았다.**

| # | 증상 | 왜 문제인가 |
|---|---|---|
| **D2** | ~~`review_required`가 5건 전부 true~~ **고쳤다(§7)** — 원인은 `exhaustive`가 상수 `False`로 하드코딩된 것이었다. 실제 vault에서는 여전히 5/5 true이지만, 이제 그래프 밀도 때문이라는 것을 측정으로 확인했다(§7) |
| **D1a** | 바이트 동일 사본 9벌 중 **worktree 사본**이 정본 슬롯을 가져간다 | `concept-gate-codex-mcp-wt/docs/…`가 canonical이 되고 `concept-gate-taxonomy/docs/…`가 replica로 밀렸다. **여기가 `authority_rank`의 유일한 사용처다**(§6a) |
| **D1b** | 내용이 다른 **stale archive 문서**가 현재판보다 먼저 온다 | C1 top-8의 2위가 `archive/…/e2.1-wt/…`(10,278 B)이고 현재판(19,477 B)은 **pool 10위, 8칸 밖**이다. 둘은 digest가 달라 **replica가 아니다** — `authority_rank`는 이 경로에 아예 없다 |
| **D3** | `symlink-vs-moc`이 후보 풀에는 **있는데** 출력 8칸에 못 든다 | 이 workspace의 `CLAUDE.md`가 **recall 실패 사례로 명시한** 문서다. **graph walk는 도달했다 — D1b와 같은 계열의 순위 문제다**(아래 측정) |

### D3는 측정으로 구별됐다 — graph walk가 아니라 재순위다

이 handoff를 검증하며 실행한 결과:

```
symlink-vs-moc in retrieved_paths : False
symlink-vs-moc in candidates      : False   ← 출력 8칸
symlink-vs-moc in candidate_pool  : True    ← 후보 풀에는 있다
discovered_path_count             : 247
```

**따라서 고칠 곳은 graph walk가 아니라 재순위다.** 다만 **그 재순위는
`authority_rank`가 아니다** — 아래 §6a가 그 이유다.

주의 두 가지:

- **`candidates`와 `candidate_pool`은 다른 필드다.** `candidates`는 `output_k`로
  잘린 출력이고, 도달 여부는 `candidate_pool`로 봐야 한다. 이 문서의 초안이 그
  둘을 뭉뚱그렸고, 그대로 따르면 "graph walk가 못 닿았다"는 **반대 결론**이 나왔다.
- `discovered_path_count`는 **파라미터에 따라 달라진다** — 5문항 E2E는
  `graph_seed_k=4, max_turns=4`로 132였고, 기본값으로는 247이다. 두 수를 같은
  측정으로 취급하지 마라.

### 6a. `authority_rank`는 검색 순위를 매기지 않는다 (측정)

**이 절은 이 handoff의 이전 판을 정정한다.** 이전 판은 D1·D3의 수정 지점으로
`authority_rank`를 지목했다. 코드를 읽고 측정한 결과 **틀렸다.**

**사용처는 코드 전체에서 한 곳뿐이다** — `corpus.py:185-188`:

```python
for digest, replicas in sorted(by_digest.items()):     # sha256으로 묶은 뒤
    canonical = min(replicas, key=lambda i: self.profile.authority_rank(i.relative))
```

즉 **바이트 동일 사본들 중 대표 하나를 고르는 것**이 전부다. 검색 순위는
`retriever.py`의 RRF가 `exact`/`bm25`/`graph`(weight 3.0) 세 채널로만 정하고,
**`authority_rank`를 한 번도 참조하지 않는다.**

**순위 함수 자체도 지금은 알파벳순이다.** `authority_rank`는
`authority_prefixes`에서 접두사를 찾아 그 인덱스를 돌려주는데,
MCP 서버가 쓰는 `VaultProfile.from_env()`는 **이 필드를 아예 넘기지 않는다** →
`authority_prefixes = ()`. 측정값:

```
from_env authority_prefixes = ()
authority_rank('archive/…')             = (0, 'archive/…')
authority_rank('concept-gate-taxonomy/…') = (0, 'concept-gate-taxonomy/…')
```

1항이 둘 다 `0`이므로 `min`은 2항, 즉 **경로 문자열 사전순**으로 결정된다.
`examples/vault-profile.example.json`에는 `authority_prefixes`가 있지만 **E2E는 그
프로파일을 쓰지 않았다.**

그래서 실제로 일어난 일(측정):

```
정본 후보 9벌은 전부 sha 78731601dbfe (19,477 B)
  → canonical = concept-gate-codex-mcp-wt/docs/…   ("codex" < "taxonomy")
  → concept-gate-taxonomy/docs/… 는 replica 로 강등            ← D1a

C1이 회수한 archive 사본 = sha 1fed33e8abce (10,278 B)
  → digest가 달라 애초에 같은 그룹이 아니다 = replica가 아니다
  → authority_rank는 이 둘을 비교한 적이 없고, 비교할 수도 없다  ← D1b
```

**두 결함은 코드 경로가 다르다:**

| | 무엇 | 고칠 곳 |
|---|---|---|
| **D1a** | 동일 사본 중 대표 선택이 알파벳순 | `authority_prefixes`를 실제로 설정한다(`from_env`가 넘기지 않는 것부터) |
| **D1b·D3** | 내용이 다른 stale/무관 문서가 RRF에서 이긴다 | **RRF 쪽이다.** `archive/`를 `excluded_globs`로 빼거나, 점수에 경로 권위 항을 넣거나 |

D1b를 `authority_prefixes`로 고치려 하지 마라 — **그 코드는 실행되지 않는다.**
stale archive는 replica가 아니라 별개 문서다.

참고로 현재판이 진 이유의 유력 후보는 **BM25 길이 정규화**다(1,094 vs 681 토큰,
짧은 stale 쪽이 유리). 다만 이건 **측정하지 않았다** — 가설이다.

### 이 문서는 자기 명령을 실행해서 검증했다

§1·§7의 모든 명령을 **그대로 실행**했고 기대값과 일치했다(73 passed / 12 passed /
D2 재현). 그 과정에서 **초안의 오류 하나가 잡혔다** — §6의 D3 지시가 `candidates`와
`candidate_pool`을 뭉뚱그려, 따라 했으면 "graph walk가 못 닿았다"는 반대 결론이
나왔을 것이다. 지금 본문은 정정본이고 정정 후 재실행까지 확인했다.

**이 절차를 유지하라**: handoff를 고치면 그 안의 명령을 다시 실행한다. 실행되지
않는 절차는 절차가 아니다.

## 7. D2 — 고쳤다 (2026-08-12)

**원인**: `retriever.py`가 `"exhaustive": False`를 **상수로 하드코딩**하고
있었다. `service.py`의 `review_required = not exhaustive or bool(warnings)`는
그래서 첫 항만으로 언제나 참이었다 — `terminal_reason`이 이미
`graph-frontier-exhausted`/`no-lexical-entry`/`turn-budget-exhausted`를 계산해
두고 있었는데도 반영하지 않았다.

**수정**: `exhaustive = (terminal_reason == "graph-frontier-exhausted")` —
그래프가 스스로 닫힌 경우만 참이고, 예산 소진(`turn-budget-exhausted`)이나 어휘
진입점이 아예 없던 경우(`no-lexical-entry`)는 계속 거짓이다.

**양방향 poison test로 확인**(`tests/test_vault_retrieval_core.py`):

- `test_non_exhaustive_hit_requires_evidence_review` — 3-hop 체인을
  `graph_seed_k=1, max_turns=2`로 예산만 소진시키는 fixture. **여전히
  `review_required=True`.**
- `test_a_fully_closed_search_can_report_review_required_false` (신규) — 작은
  그래프가 실제로 다 닫히는 fixture. **`review_required=False`, `status=complete`**
  — 이전 상수로는 낼 수 없던 값이다.

`python3 -m pytest tests/ -q` → **74 passed**(기존 73 + poison test 1개).

**실제 Vault에는 남는 한계가 있다** — 정직하게 적는다. 1,766문서·15,981엣지
그래프는 밀도가 높아 `max_turns=20`으로 올려도 `discovered_path_count`가
계속 늘어난다(175→218→257) — **닫히지 않고 계속 자란다.** 그래서 5문항 E2E는
여전히 5/5 `review_required=True`다. **이것은 이제 공허가 아니라 사실이다** —
이 규모의 vault에서 합리적인 turn 예산으로는 그래프가 진짜로 안 닫힌다. 신호
자체가 무의미했던 이전 상태와 다르다: 작은 fixture에서 신호가 구별되는 것을
단위테스트로 확인했고, 실제 vault에서 늘 `True`인 것은 이 vault의 그래프
밀도가 만든 **정직한** 결과다.

**D3는 이미 구별됐다**(§6) — `candidate_pool`에 있고 출력 8칸에 없으므로 **재순위
문제**다. **D1b와 함께 보라**(§6a): 둘 다 RRF 순위이지 `authority_rank`가 아니다.
graph walk나 `max_turns`를 늘려서 고치려 하지 마라 — 도달은 이미 하고 있다.
**D1a는 별개 작업이다**(대표 선택, `authority_prefixes` 설정).

재현:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.service import RetrievalService
svc = RetrievalService.from_profile(VaultProfile(
    root="/Users/jaehyuntak/Desktop/Project_in_progress",
    vault_name="Project_in_progress"))
out = svc.search("symlink versus MOC decision for canonical directory layout",
                 output_k=8, candidate_pool_k=50)
def paths(xs):
    return [x if isinstance(x, str) else (x.get("path") or x.get("canonical_path"))
            for x in (xs or [])]
for field in ("retrieved_paths", "candidates", "candidate_pool"):
    hit = any("symlink-vs-moc" in (p or "") for p in paths(out.get(field)))
    print(f"{field:<18}: {hit}")
PY
```

## 8. 5문항 E2E를 다시 돌리는 법

스크립트는 세션 tmp에 있었고 **커밋되지 않았다**. 재작성이 필요하면
[`E2E_REAL_VAULT_2026-08-12.md`](E2E_REAL_VAULT_2026-08-12.md)의 표에 5개 질의와
기대 문서가 그대로 있다. 요건:

- vault root는 **실제 workspace** (`/Users/jaehyuntak/Desktop/Project_in_progress`)
- 세 도구를 **실제 stdio MCP 프로세스**로 호출한다 (in-process 호출로 대체하지
  마라 — 지시서가 process boundary에서 판정하라고 요구한다)
- CLI 부재 lane도 함께 돌린다: `OBSIDIAN_CLI=/nonexistent/...`
- **실패 case를 지우거나 정답을 바꿔 맞추지 마라**

## 9. Obsidian CLI에 대해 확립된 것 / 아닌 것

**확립됨**: CLI는 **MCP 서버 프로세스에서 도달 가능하다** — C1의 backlinks가
`fallback_used: null`로 5건 반환했다.

**확립 안 됨**: "Obsidian 통합 완료"라고 쓰지 마라. `.handoff-reuse-subject-worktree/`,
`.vault-harness/`, 중첩 worktree 경로는 `File not found`로 **실패한다**(Obsidian
인덱스에 없는 dot 디렉터리). 그때 filesystem fallback이 동작하며, 그것은 **BLOCKED가
아니라 설계된 강등**이다.

## 10. 이 세션이 바꾼 파일

- `evidence_evaluator/retrieval/service.py` — `backlinks()`, `fallback_used`,
  `self.obsidian` 노출
- `evidence_evaluator/retrieval/mcp_server.py` — `vault_backlinks` 등록
- `tests/test_v01_tool_contract.py` (신규) — 실제 stdio 프로세스 12 cases
- `tests/test_vault_retrieval_core.py` — service 층 gap 테스트
- `tests/test_vault_retrieval_transports.py` — 도구 집합 2개 → 3개
- `docs/PLAN_V01_AUDIT_AND_GAPS.md`, `docs/E2E_REAL_VAULT_2026-08-12.md` (신규)
- `evidence_evaluator/retrieval/retriever.py` — D2 수정: `exhaustive`를
  `terminal_reason`에서 계산(이전엔 상수 `False`)
- `tests/test_vault_retrieval_core.py` — D2 poison test 1개 추가, 기존 2개를
  실제 측정값(`graph-frontier-exhausted`)으로 정정
- `docs/AUDIT_CLAUDE_MD_VACUOUS_PATTERNS.md` (신규) — CLAUDE.md·harness의
  공허 패턴 감사, D2 설계 제약의 근거
- `scripts/run_obsidian_vault_mcp.sh` — cwd와 무관한 stdio launcher
- `README.md` — Codex 전역 등록과 새 세션 검증 절차

## 11. v0.1 완료 조건 대비 현황

| # | 조건 | 상태 |
|---|---|---|
| 1 | 세 도구가 같은 canonical service를 쓴다 | **PASS** |
| 2 | 실제 MCP process에서 search→read→backlinks | **PASS** |
| 3 | 실제 Vault 5건 중 4건 이상 회수 | **FAIL (2/5)** |
| 4 | private/out-of-vault/symlink 노출 0건 | **PASS** (12 cases) |
| 5 | CLI 없어도 세 도구 작동 | **PASS** |
| 6 | `output_k` 경계가 service·MCP에서 유지 | **PASS** |
| 7 | 0건/partial을 absence로 과장하지 않음 | **PASS** |
| 8 | README에 설치·profile·실행·오류 의미 | **PASS** — `vault_backlinks`·`fallback_used` 추가(2026-08-12) |
| 9 | focused + 전체 테스트 통과 | **PASS** (74) |
| 10 | 실행 불가한 검증은 BLOCKED로 기록 | **PASS** |

**3번만 남았다.** MCP 등록 성공은 검색 성능 조건 3의 통과를 의미하지 않는다.

## 12. Codex 전역 등록과 실제 호출 검증 (2026-08-14)

`worktree-mcp-v01-backlinks`의 이력은 `main`에 병합됐고, Codex 사용자 전역 MCP는
다음 정본 launcher를 가리킨다:

```text
/Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator/scripts/run_obsidian_vault_mcp.sh
```

새 `codex exec --ephemeral` 세션에서 shell이나 기존 `vault-retrieval` 대신
`evidence-vault-mcp`만 사용하도록 한 smoke 결과:

| 단계 | 결과 |
|---|---|
| `vault_search("Obsidian CLI", output_k=3)` | 호출 성공, 3개 경로, `status=review_required`, filesystem fallback |
| 첫 canonical 경로 `vault_read` | 호출 성공, 1~10행 bounded read |
| 같은 경로 `vault_backlinks(limit=3)` | 호출 성공, 3개 backlink, limit 유지 |

이 검증은 Codex 등록과 search→read→backlinks 배관을 확립한다. 검색 품질 완료를
확립하지는 않는다. 두 문제가 그대로 남았다:

1. 통합 전 `evidence-evaluator-obsidian-wt` replica가 현재 `main`보다 먼저
   선택됐다.
2. `turns`, `graph_evidence`, 반복 warning을 포함한 search 도구 응답이 커서 smoke
   세션 입력이 약 28만 token까지 증가했다. caller-visible 결과는 `output_k`로
   제한되지만 진단 payload는 아직 실사용에 충분히 작지 않다.

다음 검색 개선은 새 아키텍처가 아니라 authority profile과 MCP compact projection의
최소 수정으로 수행한다. 현재 smoke artifact는 등록 성공 근거로만 사용한다.

## 13. Zero-context MCP handoff canary (2026-08-14)

compact projection, content-free MCP audit, Codex allowlisted MCP provider,
그리고 1-case canary runner를 구현했다. 실제 host-lane subject는 search 1회와
read 2회로 handoff·authority를 모두 읽고 Runtime/Retrieval/Reconstruction을
통과했다. 관리형 lane은 Codex app-server 권한 때문에 invalid-run이었다.

계약과 결과:

- [[HANDOFF_MCP_CANARY|canary contract and usage]]
- [[HANDOFF_MCP_CANARY_RESULT_20260814|live result and permission-lane boundary]]

이 결과를 v0.1 전체 검색 성능 조건 3의 통과로 해석하지 마라. 1개 case의 수직
배관과 복구 정확성만 확립했다.

## 14. Three-case development pilot (2026-08-14)

direct, graph-entry, stale-authority 세 case를 host lane에서 실행했다. 실행 중
navigation discovery를 evidence read와 혼동한 gold 결함, authority를 읽기만 하고
주장에 쓰지 않아도 통과하던 evaluator 결함, compact 응답의 반복 provider warning을
수정했다. 원본 run과 수정 전 gold는 보존했고 graph case는 동일 trace로 재평가했다.

상세 결과: [[HANDOFF_MCP_PILOT_RESULT_20260814|three-case development pilot]].

이 파일들은 하네스 개발에 사용됐으므로 confirmatory test set으로 재사용하지 마라.

## 15. Independent confirmatory set (2026-08-14)

별도 zero-context curator subagent가 6개 신규 case를 만들었고, main agent는 subject
실행 전에 구조 감사와 retrieval qualification만 수행했다. isolated private corpus,
case, gold, harness surface는 freeze digest로 동결됐으며 live subject run은 0건이다.

상세 계약: [[HANDOFF_CONFIRMATORY_SET_20260814|independently curated set]].

이 set에서 결함을 발견해 하네스를 수정하면 해당 case를 development로 강등하고
새 case를 다시 curate해야 한다.
