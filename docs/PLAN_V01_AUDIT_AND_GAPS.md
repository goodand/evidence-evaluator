# v0.1 계획 — 현재 구현 감사, 확인된 결함, 구현 순서

작성 2026-08-12. 대상 커밋 `745323c`("Add canonical Obsidian retrieval service").
작업 위치: worktree `worktree-mcp-v01-backlinks`.

**이 문서는 지시서의 상태 서술을 검증한 결과다.** 지시서가 "파일 수·테스트 수·구현
상태가 최신이라고 가정하지 마라"고 요구했고 실제로 상태가 달랐다 — 지목된 다섯
파일이 **전부 실재하며**, 다른 agent가 `745323c`(08-11 23:42)로 retrieval service를
이미 커밋했다. 작업 트리는 clean이므로 덮어쓸 미커밋 변경은 없다.

## 1. Step 1 — 현재 구현 감사 (실측)

| 기능 | 이미 구현 | 부분 구현 | 없음 | 실사용 차단 |
|---|---|---|---|---|
| **search** | ✅ `service.search` → `retriever` | | | 아니오 |
| **bounded output** | ✅ `1 <= output_k <= candidate_pool_k <= 500`을 `__post_init__`이 강제, 선택은 `pool_paths[:output_k]` | | | 아니오 |
| **read** | ✅ `service.read` | | | 아니오 |
| **backlinks** | | ⚠️ **내부 graph walk에만 존재**(`corpus.backlinks`, Obsidian live backlinks) | **MCP 도구·service 메서드 없음** | **예** |
| **Obsidian fallback** | ✅ `available: bool`, per-path warning, `OSError`/`TimeoutExpired` 처리, retriever가 warning 병합 | | | 아니오 |
| **path security** | ✅ `blocked_parts`(`hidden_gold`·`private_eval` 포함) + `resolve()` | | | 아니오 |
| **vault profile** | ✅ `profile.py` | | | 아니오 |
| **MCP registration** | | ⚠️ **2/3** — `vault_search`, `vault_read` | `vault_backlinks` | **예** |
| **structured errors** | ✅ `status`·`warnings`·`review_required`·`exhaustive`·`terminal_reason`·`discovered_path_count` | | **`fallback_used` 없음** | **예** |

실측 근거:

```
retrieval 패키지  7 모듈 (mcp_server.py 포함), 테스트 52 passed (host lane)
search 출력 키    artifact_digest, candidate_pool, candidates, contract_version,
                  discovered_path_count, exhaustive, next_action, retrieved_paths,
                  review_required, status, terminal_reason, turns, warnings
계약 대비 누락    fallback_used
output_k 경계     output_k=9, pool=4 → RetrievalError (강제됨)
obsidian CLI      /usr/local/bin/obsidian 존재 (`--version` 없음, `version` 사용)
fastmcp           3.4.6
```

**v0.1을 막는 것은 두 가지다.**

1. `vault_backlinks` 도구가 없다 — **능력은 이미 있고 노출만 없다**
2. `fallback_used` 계약 필드가 없다

지시서가 "실사용 전 반드시 해결"로 든 나머지(path security, output_k 경계, vault
profile, 구조화 응답, Obsidian fallback)는 **이미 구현돼 있다.** 새로 만들면
정본이 두 벌 된다.

## 2. 재사용 후보 — 새 service를 만들지 않는다

| 후보 | 위치 | 이번 작업에서 |
|---|---|---|
| `corpus.backlinks(path)` | `retrieval/corpus.py` | **`vault_backlinks`의 filesystem 본체.** graph walk가 이미 쓴다 |
| `ObsidianGraph`(`backlinks`·`available`·`warnings`) | `retrieval/obsidian.py` | **live 경로.** CLI 실패를 이미 warning으로 강등 |
| `VaultProfile` 경로 검증 | `retrieval/profile.py` | `vault_backlinks`도 같은 함수를 통과 |
| `service.read`의 거부 로직 | `retrieval/service.py` | 입력 검증 재사용 |
| `.vault-harness/vault-md-retrieval`, `vault-backlinks-mcp` | 참고 전용 | **읽기만** — 지시서가 수정·이동·복사를 금지 |

**`vault_backlinks`는 새 알고리즘이 아니라 얇은 노출층이다** — 지시서의 "기존
service 위에 얇게 연결하라"가 정확히 이 경우다.

## 3. 검증 방법 설계

원칙: **가드를 만들면 그 가드를 통과시키는 잘못된 입력을 실제로 만들어 본다.**
지시서의 "헬퍼 함수를 직접 호출한 테스트만으로 완료 판정하지 마라"와 같은 요구다.

| # | 먼저 빨갛게 | 통과 기준 |
|---|---|---|
| B1 | `vault_backlinks` 부재 | service 메서드 + MCP 도구 둘 다 |
| B2 | vault 밖 경로 | `read`와 **같은** 거부 |
| B3 | `hidden_gold`/`private_eval` | fail-closed |
| B4 | symlink escape | canonical physical path만 |
| B5 | non-Markdown | 거부 |
| B6 | `limit` 초과 | `len(backlinks) <= limit` |
| B7 | CLI 불가 | 서버가 죽지 않고 filesystem 결과 + warning, `fallback_used="filesystem"` |
| F1 | 정상 검색에 `fallback_used` 없음 | 모든 응답이 그 필드를 갖는다 |
| F2 | CLI 실패에 `fallback_used=null` | `"filesystem"` |

B7·F2는 CLI를 **실제로 실패시켜** 검증한다(존재하지 않는 바이너리를 profile에
주입). mock이 아니라 실행 경계다.

## 4. 의존성 분석

```
profile / corpus / obsidian   ← 변경 없음, 재사용
        ↓
service.py    + backlinks(),  + fallback_used
        ↓
mcp_server.py + vault_backlinks
        ↓
tests/
```

**한 방향, 순환 없음.** `retriever.py`는 건드리지 않는다 — `fallback_used`는
service 층에서 warning으로 파생하면 되고, 그러면 검색 알고리즘을 열지 않는다
(지시서: "public API는 안정화하고 내부 알고리즘은 교체 가능하게 둔다").

`.vault-harness`와 active experiment는 손대지 않는다. 이 저장소가 정본이다.

## 5. 구현 순서

```
1. service.backlinks(path, limit)      — profile 검증 재사용 + corpus/obsidian 조합
2. service.search/read에 fallback_used — warning에서 파생
3. mcp_server에 vault_backlinks 등록
4. 음성 테스트 B1~B7, F1~F2 + 오염 시험
5. 전체 테스트
6. 실제 Vault E2E 5건   (Step 3)
7. 오류 E2E             (Step 4)
8. README               (완료 조건 8)
9. 로컬 커밋
```

## 6. 이 문서가 주장하지 않는 것

- **"Obsidian 통합 완료"** — MCP 프로세스 경계에서 control query를 아직 돌리지
  않았다. `/usr/local/bin/obsidian`이 있는 것과 MCP 권한 lane에서 IPC가 되는 것은
  다른 사실이다(지시서 "권한 환경 검증").
- **"검색 성능 검증"** — E2E 5건 미실행.
- **52 passed** — 이 환경(host lane) 값이다.
