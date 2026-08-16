# 설계 판정 수신 — D3 graph 채널 순위 (2026-08-16)

- 요청서: 이 세션이 CLI로 출력해 사용자 경유 전달
- 판정: 외부 설계 담당 (저장소 접근 없음), 문헌 조사 기반
- 상태: **수신 기록.** 결과가 이 판정을 소급 수정하지 못한다. 변경이 필요하면
  새 문서로 남긴다.

## 1. 판정 (요지)

> **D 계열로 진행하되, 단순 global inbound가 아니라 query-local inbound로
> 구현한다. 발견 순서는 rank signal에서 제거한다. zero-overlap 테스트와 seed
> 민감도 테스트를 통과한 뒤 승인한다. 실패 시 seed-weighted +
> distance-decayed authority score로 확장한다. B는 임시 완화책 또는 최후
> fallback으로만 둔다.**

단계 순서: **D0**(query-local inbound) → 실패 시 **D1**(seed-weighted +
depth-decay) → 불안정하면 **D2**(log/cap) → 그래도 안 되면 **B**(가중치 완화).

제시된 실험식:

```
graph_score(v) = log1p( Σ_{p→v, p ∈ visited_frontier}
                         1/(60 + best_seed_rank(p)) * 0.7^(depth(p)-1) )
graph_channel = graph_score desc, min_depth asc, path asc
```

## 2. 문헌 근거 (판정문에서 인용된 축)

| 논문 | 이 문제와의 관계 |
|---|---|
| Carrière & Kazman, WebQuery (WWW 1997) | lexical seed → link graph 확장 → **연결 다중성**으로 재랭킹. 구조가 거의 동일 |
| Henzinger, Link Analysis in Web IR (2000) | query-dependent 방식에서 neighborhood graph의 **indegree**로 rank. 단순 indegree의 약점(모든 링크를 동일 신뢰도로 취급)도 지적 |
| Kleinberg, HITS (JACM 1999) | 발견 순서가 아니라 query-local graph에서 authority/hub 반복 계산 |
| Balmin et al., ObjectRank (TODS 2008) | keyword base set에서 authority flow 전파. "많이 참조된 문서가 높아야 한다"를 일반화 |
| Haveliwala, Topic-Sensitive PageRank (2002) | **global** link score의 문제 — D를 global inbound로 구현하지 말라는 근거 |
| Bruch et al., Fusion Functions for Hybrid Retrieval (2022) | RRF의 파라미터 민감성 — B가 "완화책"인 이유 |

## 3. 이 세션이 판정 수신 후 검증한 것

### 3a. 정정 — 요청서의 "옵션 D" 서술과 실측이 불일치했다

요청서는 옵션 D를 "graph 채널 순위를 발견 순서 대신 inbound 링크 수로
매긴다"(= RRF 안에서 graph rank 교체)로 서술했고, **5문항 4/5**를 근거로 달았다.
그러나 실제로 측정한 코드는

```python
def rank_D(ch):
    return _staged(ch, lambda p, i: len(corpus.backlinks(p)))
```

로 **단계형(lexical 먼저) 변종**이었다. 같은 요청서가 단계형을 구조적 결함으로
이미 탈락시켰으므로, **D의 4/5는 D를 서술한 대로 측정한 값이 아니다.**
게다가 `corpus.backlinks(p)`는 **global** inbound여서, 판정문이 명시적으로
피하라고 한 바로 그 구현이었다.

판정 방향 자체는 이 오류와 독립적으로 성립한다(외부 담당이 문헌에서 도출).
그러나 **요청서가 제시한 D의 실측 근거는 무효**이며, D0는 아직 한 번도
측정된 적이 없다.

### 3b. query-local 다중성은 **이미 수집되고 있다**

`retriever.py`:

```python
if neighbor not in graph_order:
    graph_order.append(neighbor)          # dedup → 발견 순서
evidence = {"seed": seed_path, "relation": relation}
if evidence not in graph_evidence[neighbor]:
    graph_evidence[neighbor].append(evidence)   # ← 가드 바깥
```

`graph_evidence`는 dedup 가드 **바깥**에서 누적되므로, 각 경로에 도달한
**모든 distinct (seed, relation)** 을 이미 담고 있다. RRF에 들어가는 것은
`graph_order`(발견 순서)뿐이다. **D0에 새 데이터 수집이 필요 없다.**

### 3c. 실측 — query-local 다중성이 이 사례를 실제로 가른다

문제 질의에서:

| | 대상(top-8 탈락) | 8위 문서 |
|---|---:|---:|
| graph_evidence 항목 수 | **4** | 1 |
| **distinct parent 수** | **3** | **1** |
| global backlinks | 20 | 8 |

query-local(3 vs 1)로도 분리되고 global(20 vs 8)로도 분리되지만, 판정문의
Topic-Sensitive PageRank 근거에 따라 **query-local을 쓴다**.

### 3d. depth는 기존 trace에서 복원 가능하다

`turns[i]["new_paths"]`가 턴별 신규 발견을 기록하므로 depth = 최초 등장 턴.
(대상 문서는 turn 1 = lexical 진입이라 depth 0.)

### 3e. **게이트 3은 지정된 테스트로 성립하지 않는다**

판정문 게이트 3은 "`test_graph_frontier_beats_a_full_lexical_tail`에서 정답이
top-8 유지"다. 그러나 그 테스트의 실제 단언은:

```python
assert any("deep/authority.md" in turn["new_paths"] for turn in result["turns"])
assert result["discovered_path_count"] >= 3
assert result["turns"][2]["seed_paths"] == ["bridge.md"]
```

**발견만 검사하고 `retrieved_paths`를 전혀 보지 않는다.** 정답이 출력에서
사라져도 통과한다. 출력을 지키는 테스트는 옆의
`test_recall_first_recovers_zero_overlap_authority_by_two_graph_hops`
(`assert "deep/authority.md" in result["retrieved_paths"]`, output_k=4)다.

→ 게이트 3은 **새 테스트로 구현**한다. 기존 테스트 통과를 게이트 충족으로
읽으면 안 된다.

## 4. 구현 결과 (D0)

`graph_channel_order()` 신설 — `channels["graph"]`에 발견 순서 대신
**(distinct parent 수 desc, depth asc, parent의 최고 lexical rank asc,
path asc)** 로 정렬한 같은 멤버십을 넘긴다. `reciprocal_rank_fusion`은
손대지 않았다(리스트 위치를 rank로 쓰므로 순서만 바꾸면 된다).

### 게이트 결과 — `scripts/d3_ranking_gates.py`

| 게이트 | 수정 전 | 수정 후 |
|---|---|---|
| 1. 5문항 회수 ≥ 4/5 | FAIL (3/5) | **PASS (4/5)** |
| 2. symlink-vs-moc top-8 | FAIL (없음) | **PASS (rank 1)** |
| 3. zero-overlap 출력 유지 | PASS (rank 3) | PASS (rank 3) |
| 4. seed 민감도 | FAIL (4→6→없음→없음) | **PASS (전부 rank 1)** |

게이트 4가 가장 강한 신호다: seed 4/8/12/20에서 **전부 rank 1로 완전히
안정**됐다. 이전에는 seed가 커질수록 단조적으로 나빠졌다.

### ⚠️ 합성 테스트로는 이 회귀를 잡을 수 없다 (측정)

`tests/`에 넣은 통합 테스트 2개는 **수정을 되돌려도 통과한다.** poison test로
확인했다. 판별하는 합성 fixture를 **네 번 설계했고 네 번 다 실패**했다:

1. 노이즈 30개 zero-overlap — 두 모드 다 rank 3
2. hub가 junk 50개를 먼저 쏟아내는 구조 — 두 모드 다 rank 7
3. junk에 약한 어휘 매치 부여 — D0에서 오히려 MISS(시나리오 자체가 틀림:
   실제 결함은 **강한 어휘 매치** 문서가 밀리는 것)
4. target을 강한 어휘 매치로 교정 — 차이는 생겼으나(rank 2~3 vs 4) 둘 다
   top-8 안이라 in/out 단언으로는 판별 불가

**이 결함은 실제 vault(1,766문서)의 규모와 링크 위상에서만 재현된다.**
따라서:

- **단위 테스트 3개**(`graph_channel_order` 직접 호출)는 유효하다 — 함수의
  정렬 계약을 실제로 검사한다.
- **통합 테스트 2개**는 회귀 가드가 **아니다.** docstring에 그렇게 명시했고,
  각각이 실제로 무엇을 잡는지(단계형 순위는 잡는다) 적었다.
- **진짜 회귀 가드는 `scripts/d3_ranking_gates.py`** 이며 실제 vault를
  필요로 한다. hermetic한 `tests/`와 분리해 스크립트로 둔 것은
  vault-backlinks-mcp의 `scripts/parity_check_backends.py`와 같은 이유다.

### 아직 하지 않은 것

- **C4는 여전히 MISS.** D0로 풀리지 않았고 원인 미확정이다.
- **D1(seed-weighted + depth-decay)과 D2(log/cap)는 구현하지 않았다.**
  판정문은 D0 실패 시 확장하라고 했고, D0가 게이트를 통과했으므로 멈췄다.
- 판정문이 제시한 `log1p(Σ 1/(60+rank) * 0.7^depth)` 형태의 연속 점수는
  쓰지 않았다 — D0의 사전식(lexicographic) 정렬로 게이트가 충족됐다.
