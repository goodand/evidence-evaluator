---
title: Semantic Boundary - Vault Backlinks Implementations
date: 2026-08-15
status: decision-record
scope: obsidian-retrieval-migration
tags:
  - doc/design-decision
  - topic/retrieval
  - topic/obsidian
  - topic/migration
---

# `vault_backlinks` 두 구현의 의미 경계

이 문서는 같은 도구 이름을 가진 두 구현을 하나로 간주하지 않기 위한 계약 기록이다.

- 범용 정본: `evidence_evaluator.retrieval`
- compatibility 소비자: `vault-backlinks-mcp`
- 호환성 오라클: `.vault-harness/vault-md-retrieval`
- 선행 결정: [[DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL]]
- migration 상태: [[MIGRATION_STATUS_OBSIDIAN_RETRIEVAL]]
- stale index 반증 근거:
  [[notes/audits/vault/correspondence/ADVERSARIAL_REVIEW_vault_backlinks_mcp_20260808]]

## 1. 결론

두 구현은 동일한 질문에 대한 대체 구현이 아니다.

```text
vault-backlinks-mcp
  = "지금 Obsidian CLI가 이 정확한 경로에 대해 무엇을 답했는가?"

evidence_evaluator.retrieval
  = "현재 service가 안전하게 회수할 수 있는 incoming navigation edge는 무엇인가?"
```

전자는 live observation 도구이고 후자는 recall-first navigation service다. 같은
`vault_backlinks` 이름을 사용하지만 authority, failure, completeness의 의미가
다르다. 따라서 단순 흡수, subtree 편입, 반환 schema 통합으로 migration을 완료했다고
판정할 수 없다.

## 2. 의미 차이표

| 축 | `vault-backlinks-mcp` | `evidence_evaluator.retrieval` | migration에서 보존할 의미 |
|---|---|---|---|
| 상위 목적 | exact-path live diagnostic | handoff 검색을 위한 reusable navigation | diagnostic과 retrieval을 구분한다 |
| 질문 | “Obsidian이 지금 무엇을 답했는가” | “안전하게 회수 가능한 incoming edge가 무엇인가” | 같은 도구 이름으로 동일성을 추정하지 않는다 |
| 입력 경계 | `vault_id` + relative `path` | server/profile 하나 + relative `path` | multi-vault registry와 per-server profile은 별도 배포 모델이다 |
| 주 backend | Obsidian CLI만 | filesystem Markdown graph + optional Obsidian CLI | backend provenance를 결과에 유지한다 |
| CLI 불가 | `backend_used="none"`, `backlinks=null`, `error` | filesystem 결과, `status="partial"`, `fallback_used="filesystem"` | 실패와 degraded evidence를 서로 변환하지 않는다 |
| zero의 의미 | live 성공 후 빈 목록이어야 live zero | fallback/warning/빈 목록이면 `review_required=true` | zero를 absence로 자동 승격하지 않는다 |
| filesystem의 성격 | 사용하지 않음 | service 시작 시 Vault Markdown에서 만든 in-memory graph | 3일 stale SQLite와 동일한 것으로 취급하지 않는다 |
| stale 위험 | live IPC 시점 관측, 앱/index 자체 freshness는 외부 조건 | 장기 실행 중 파일 변경 시 in-memory snapshot이 stale해질 수 있음 | service generation 또는 restart 시점을 기록한다 |
| stale 대응 | CLI 실패를 정직하게 반환 | partial + warning + review 요구 | filesystem fallback을 complete live evidence로 표시하지 않는다 |
| 경로 권위 | registry root에 input/output을 재대조 | profile policy와 canonical identity로 input/output을 정규화 | 둘 다 path admission을 유지하되 정책 사본을 만들지 않는다 |
| wrong-vault 방어 | 다른 등록 Vault의 동명 path, active-vault 확인 실패를 review check로 노출 | `cwd=vault_root`, profile canonicalization, out-of-root drop | multi-vault ambiguity 검사는 adapter에서 잃지 않는다 |
| symlink | symlink query를 review 대상으로 두고 canonical 재질의 요구 | canonical physical Markdown으로 정규화하고 alias를 CLI에 보내지 않음 | migration 시 canonical path 결과를 정본으로 한다 |
| 반환 backlink | `{source_path, link_count}` | canonical relative path 문자열 | count 정보가 필요한 소비자인지 먼저 확인한다 |
| truncation | `total`, `returned_count`, `max_results`, `TRUNCATED` review check | `discovered_path_count`, `limit`, `truncated` | total-before-truncation 의미를 보존한다 |
| dropped 결과 | malformed/forbidden/out-of-scope별 계수 | profile/corpus admission에서 차단, 별도 drop breakdown 없음 | 보안 감사에 drop reason이 필요하면 adapter가 명시한다 |
| caller error | caller-facing 문제도 구조화된 result로 반환 | service error, MCP에서는 `ToolError` | error channel 변경은 breaking change로 취급한다 |
| review 계약 | code별 `review_checks[].required_action` | `review_required`, warning, next action | review 필요 여부뿐 아니라 이유도 손실 없이 매핑한다 |
| 도구 범위 | `vault_backlinks` 하나 | `vault_search`, `vault_read`, `vault_backlinks` | compatibility tool을 전체 retrieval package와 동일시하지 않는다 |
| 현재 의존성 | `.vault-harness` subprocess/parser를 runtime import | 자체 canonical service | raw harness import 제거가 migration 목표다 |
| 현재 지위 | 별도 실험 자산을 포함한 미이주 소비자 | reusable implementation 정본 | repo subtree가 아니라 consumer migration을 수행한다 |

## 3. fallback 충돌에 대한 정정

선행 적대 리뷰의 `DO-NOT-BUILD`는 다음 구현을 반증했다.

```text
3일 stale SQLite index
  -> 사람이 쓴 backlink 5/10 누락
  -> 해소된 orphan을 계속 orphan으로 보고
  -> 정상적인 fallback 답처럼 반환
```

`evidence_evaluator.retrieval`의 filesystem fallback은 이 SQLite index를 사용하지
않는다. Vault Markdown을 읽어 만든 graph를 사용하며, CLI가 없으면
`fallback_used="filesystem"`, `status="partial"`, `review_required=true`를 반환한다.
따라서 stale indexed answer를 확정적인 live answer로 위장했던 실패 모드를 그대로
되살린 것은 아니다.

그러나 새로운 residual은 있다. `VaultCorpus`는 service 생성 시점의 snapshot이므로,
장시간 실행되는 MCP process에서 Vault 파일이 바뀌면 재시작 전까지 filesystem graph가
뒤처질 수 있다. partial 표시는 과신을 막지만 freshness를 증명하지 않는다. migration
검증은 다음을 별도로 기록해야 한다.

- service process 시작 시각 또는 corpus generation ID;
- 비교 대상 Markdown의 최종 수정 시각;
- Obsidian CLI 사용 가능 여부;
- live와 filesystem 결과의 차집합;
- 빈 결과를 absence로 사용했는지 여부.

## 4. 보안·authority 차이

두 구현 모두 raw CLI output을 그대로 authority로 사용하지 않는다.

`vault-backlinks-mcp`는 registry의 target root를 기준으로 모든 returned path의 실제
존재를 다시 검사한다. 같은 relative path가 여러 등록 Vault에 존재하거나 active
Vault를 확인할 수 없으면 review check를 남긴다. 이는 multi-vault live diagnostic의
위협 모델이다.

`evidence_evaluator.retrieval`은 profile 하나가 inventory, canonical identity,
blocked path, symlink, authority policy를 소유한다. Obsidian output은 canonicalize를
통과한 in-profile Markdown만 filesystem graph에 추가된다. 이는 per-server retrieval
service의 위협 모델이다.

따라서 adapter가 legacy registry를 제거하려면 “한 MCP server instance는 정확히 한
profile/Vault를 소유한다”는 배포 조건을 먼저 고정해야 한다. 그렇지 않으면
`AMBIGUOUS_ACROSS_REGISTERED_VAULTS`와 active-vault review 의미가 사라진다.

## 5. migration 계약

### 보존해야 하는 것

1. exact relative path만 입력받는다.
2. blocked/private path는 input과 output 양쪽에서 fail-closed한다.
3. live 결과는 canonical target Vault 안의 path로 재검증한다.
4. CLI 불가와 confirmed live zero를 구분한다.
5. truncation 전 전체 수와 반환 수를 구분한다.
6. multi-vault ambiguity 또는 이를 제거하는 one-profile-per-server 조건을 명시한다.
7. 별도 사전등록 실험 자산은 이동·병합·공개하지 않는다.

### 그대로 보존할 필요가 없는 것

1. `.vault-harness`의 Python module을 `sys.path`로 import하는 방식;
2. package-local registry가 유일한 Vault 구성 방식이라는 가정;
3. flat imports(`from registry import ...`)와 standalone script layout;
4. live-only 도구와 recall-first retrieval service가 같은 제품이라는 설명.

### 금지하는 것

- `vault-backlinks-mcp` 전체를 subtree로 넣어 retrieval 정본을 두 벌 만드는 것;
- `.vault-harness` source를 복사해 adapter 내부에 숨기는 것;
- filesystem partial을 `backend_used="live"`로 표현하는 것;
- live failure를 빈 backlink 목록으로 바꾸는 것;
- parity 없이 기존 runtime import를 삭제하는 것;
- tool-only-context 사전등록 실험을 migration fixture로 재사용해 confirmatory 지위를
  오염시키는 것.

## 6. 검증 순서

1. 기존 `vault-backlinks-mcp` contract를 characterization test로 고정한다.
2. direct backlink, zero backlink, CLI unavailable, wrong-vault overlap, symlink,
   forbidden path, truncation case를 fixture로 만든다.
3. `evidence_evaluator.retrieval` adapter가 같은 입력을 처리하게 한다.
4. 결과를 값 일치가 아니라 의미 등가로 비교한다.
5. live available lane에서는 live 결과와 canonical path set을 비교한다.
6. live unavailable lane에서는 legacy error와 new partial을 모두 보존하고, 어느 쪽도
   confirmed zero로 해석되지 않는지 확인한다.
7. profile 하나로 multi-vault ambiguity가 제거되지 않으면 review reason mapping을
   구현한다.
8. representative live-vault queries의 material recall regression을 기록한다.
9. 모든 검증 뒤에만 `.vault-harness` runtime import를 제거한다.

## 7. 완료 판정

migration 완료는 “한 저장소에 들어갔다”가 아니다. 다음이 모두 성립해야 한다.

- retrieval algorithm과 path policy의 정본이 `evidence_evaluator.retrieval` 하나다.
- compatibility consumer는 service contract만 호출한다.
- live failure, degraded filesystem evidence, confirmed live zero가 서로 다른 상태로
  남는다.
- canonical identity, private-path exclusion, truncation, wrong-vault 위험이 회귀하지
  않는다.
- 별도 실험 자산과 `.vault-harness` oracle은 이동하지 않는다.
- parity 결과와 알려진 의미 손실이 문서로 남는다.

이 조건 전에는 `vault-backlinks-mcp`를 삭제하거나 subtree로 편입하지 않는다.
