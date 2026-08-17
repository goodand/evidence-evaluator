# 조사 결과 수신 및 검증 — P1 공허한 가드 (2026-08-17)

- 요청서: 이 세션이 CLI로 출력, 사용자 경유 전달 (자족형, 저장소 접근 없는 조사자용)
- 응답: 외부 조사 에이전트, 문헌 기반
- 상태: **수신 + 로컬 검증 기록.** 결과가 이 기록을 소급 수정하지 못한다.

## 1. 응답 요지

9건을 하나로 덮는 정식 학술 용어는 **없다**. 대신 **세 종류의 adequacy 실패가
겹친 현상**으로 보는 것이 정확하다는 결론:

| 축 | 질문 | 이 세션의 사례 |
|---|---|---|
| **Reachability** | 가드가 발화 가능한 입력이 존재하는가 | (e) — infeasible test requirement |
| **Oracle** | 틀린 구현과 옳은 구현을 구별하는가 | (b)(d)(h) — pseudo-tested |
| **Input/fixture** | 그 차이가 드러나는 입력을 만드는가 | (c)(i) |

**(c)가 왜 두 번 공허했는지가 이 틀로 설명된다**: spy를 추가해 Oracle 축은
강화했으나 fixture 축(빈 vault)은 그대로였다. **한 축을 강화해도 다른 축이
따라오지 않는다.**

핵심 문헌 용어:
- **pseudo-tested method** (Vera-Pérez et al., arXiv:1807.05030) — 코드를
  실행하지만 그 효과를 제거해도 어떤 테스트도 실패하지 않음. 우리 poison
  test가 묻는 질문과 사실상 동일
- **infeasible test requirement** (Bardin et al., ICST 2015) — (e)에 정확히 대응
- **rotten green test** (arXiv:1912.07322) — 좁은 정의(assertion이 실행되지
  않음), 우리 9건 전체를 이 이름으로 부르면 **틀림**
- **checked coverage** (Schuler & Zeller, ICST 2011) — assertion에 영향을 주는
  statement만 세는 지표. **Python 표준 구현 없음**

권고 3개: ① Guard Witness Registry(양방향 witness 의무화) ② mutmut scoped
mutation ③ Hypothesis + metamorphic + 실제 corpus tier.

## 2. 로컬 검증 — 실측한 것

응답의 문헌 인용은 검증하지 않았다(웹 접근 범위 밖으로 판단). **로컬에서
확정 가능한 것만** 실측했다.

### 2a. 도구 가용성 — 권고 3개 전부 미설치

```
mutmut      미설치 (PyPI 최신 3.7.0 확인 ✓ 응답 주장과 일치)
pylint      미설치
hypothesis  미설치
coverage    미설치
```

**응답이 반영하지 않은 비용**: 이 머신의 Python은 PEP 668
externally-managed라 `pip install`이 거부된다. `--break-system-packages`
또는 venv가 필요하다. 즉 권고 3개 모두 **환경 구성부터** 시작한다.

### 2b. mutmut은 이 프로젝트에서 **그대로 돌지 않는다** (신규 발견)

mutmut 3.7은 소스 트리를 `mutants/`로 복사해 그 안에서 pytest를 돌린다.
이 프로젝트 테스트는 `sys.path` 조작 import를 쓰므로 재배치에서 깨진다.

```
source_paths=evidence_evaluator/retrieval/retriever.py   (단일 파일)
→ ModuleNotFoundError: No module named 'evidence_evaluator.retrieval.corpus'
   (패키지가 불완전하게 복사됨)

tests_dir=tests/  (전체)
→ ModuleNotFoundError: No module named 'contract'
   (test_clean_judge.py의 sys.path 조작이 깨짐)

source_paths=evidence_evaluator  + 테스트 파일 1개로 좁힘
→ 실행됨
```

**결론: "변경 함수 단위 scoped mutation"이라는 응답의 제안은 이 프로젝트에
그대로 적용되지 않는다.** 패키지 전체를 `source_paths`로 주고 테스트 쪽을
좁혀야 한다.

### 2c. 실행 비용 — 응답이 "예측할 수 없다"고 한 값

```
mutants 생성   : 10,236개 (evidence_evaluator 패키지 전체)
실행 시간      : 58초  (33.21 mutations/second, 359% CPU)
killed         : 1,009
survived       : 554
not covered    : 8,673   ← 테스트를 retrieval 1개 파일로 좁힌 결과
```

**런타임은 병목이 아니다**(58초). 진짜 비용은 **554개 survivor의 분류
노동**이다. 응답은 이 구분을 하지 않았다.

`mutmut show <mutant>` 는 **120초 초과로 응답하지 않았다** — 결과 열람
도구에도 마찰이 있다.

### 2d. **가장 중요한 실측 — 내가 방금 쓴 함수가 걸렸다**

`graph_channel_order`는 이 세션에서 D3를 고치며 새로 작성했고, **전용 단위
테스트 3개**를 붙였으며, poison test로 검증까지 했다. 그런데:

```
evidence_evaluator.retrieval.retriever.x_graph_channel_order__mutmut_2, 3, 8,
10, 11, 13, 15, 16, 22, 24, 25 : survived     ← 11개
```

`reciprocal_rank_fusion`도 7개, `RecallFirstRetriever.retrieve`도 다수
survivor가 있다.

**즉 mutation testing은 "내가 충분히 테스트했다고 믿은 코드"에서 즉시 약점을
찾아냈다.** 이것이 권고 ②에 대한 가장 강한 경험적 근거이며, 동시에 이
세션의 P1 반복이 아직 끝나지 않았다는 증거다.

survivor 하나를 실제로 열어봤다(`mutmut show`가 120초를 넘겨 백그라운드로
넘어간 뒤 완료):

```diff
-        return (-len(parents), depth.get(path, 0), best_parent, path)
+        return (-len(parents), depth.get(path, None), best_parent, path)
```

**판단**: `depth`에 없는 경로가 들어오면 정렬 키에 `None`이 섞여
`None < int` 비교에서 `TypeError`가 난다. 즉 의미가 다른 mutant다. 그런데 내
테스트는 전부 `depth`를 완전히 채워 넘기므로 **기본값 `0`이 한 번도
실행되지 않는다.**

실제 호출부에서는 `graph_depth.setdefault(neighbor, turn_number)`가 모든
neighbor에 대해 불리고 `graph_channel_order`는 그 neighbor들만 받으므로,
production에서 이 기본값은 **도달 불가능**하다 — 즉 이 mutant는
*equivalent-in-practice*이고 진짜 결함은 아니다. 다만 **`0`이라는 기본값이
죽은 코드**라는 사실은 새로 알게 됐다.

이 한 건이 mutation testing의 **가치와 비용을 동시에** 보여준다: 테스트되지
않은 경로를 정확히 짚어냈고(가치), 그것이 진짜 결함인지 판단하려면 사람이
호출부까지 읽어야 했다(비용). 554개에 이 노동을 곱하면 된다.

(나머지 553개는 **분류하지 않았다.** 11개 중 1개만 열어보고 전체를 판단할 수
없다.)

## 3. 응답에 대한 평가

**신뢰할 만한 부분** — 요청서의 규칙("전부 잡는다는 답은 신뢰하지 않는다")을
실제로 지켰다:

- 9건 × 6기법 매핑에서 **어떤 기법도 9개를 전부 잡지 못한다**고 명시
- (g)에 mutation은 `—`(거의 부적합), (i)에 `△`로 정직하게 표기
- "assertion strength를 하나의 보편적 scalar로 계산하는 표준 metric은 **없다**"
  는 부정적 근거를 명시
- checked coverage의 **Python 구현이 없다**고 인정
- 체크리스트의 효과에 대해 **유의한 차이가 없었던 연구**를 인용 — 자기
  권고를 약화시키는 근거를 스스로 제시
- "LLM 때문에 생긴 새로운 failure class라고 하면 근거가 부족하다"고 과장을 억제
- Unknown Test 47~50% 수치에 **Java benchmark라 Python으로 일반화하면 안
  된다**는 caveat를 붙임

**보완이 필요한 부분** (위 2b·2c가 근거):

- 도입 비용을 "설정/실행시간/유지보수"로만 나눴는데, 실측하니 **환경 제약
  (PEP 668)**과 **실행 모델 비호환(tree copy vs sys.path)**이 더 큰 장벽이었다
- 진짜 비용은 런타임이 아니라 **survivor 분류 노동**인데 그 구분이 없었다

## 4. 이 프로젝트가 채택할 것

응답의 우선순위를 **뒤집는다.** 근거는 2b~2d다.

| 순위 | 응답 권고 | 이 세션 판단 |
|---|---|---|
| 1 | Guard Witness Registry | **유지** — 설치 불필요, (a)(c)(e)(f)(g)에 직접 대응, 이 세션이 이미 캘리브레이션 게이트로 원리를 검증함 |
| 2 | mutmut scoped | **조건부 채택** — 58초로 저렴하고 즉시 실효(2d)가 있으나, 실행 모델 비호환을 먼저 해결해야 하고 survivor 554개 분류 정책이 필요 |
| 3 | Hypothesis + metamorphic + corpus tier | **부분 채택** — corpus tier는 **이미 함**(`scripts/d3_ranking_gates.py`). Hypothesis/metamorphic은 미도입 |

**즉시 할 수 있는 것은 ①뿐이다.** ②는 준비 작업이 있고, ③의 3분의 1은 이미
하고 있다.

## 5. 2차 응답과 후속 검증 (같은 날)

조사자에게 위 실측을 전달했고, **두 건을 스스로 정정**하고 자기 권고 2위를
철회했다.

### 5a. 조사자의 정정

1. **3축(reachability / oracle / input-fixture)은 확립된 단일 taxonomy가
   아니다** — 이 프로젝트 9건에 맞춰 합성한 분석 틀이다. 각 축은 기존 문헌
   개념과 대응하지만 묶음 자체가 표준은 아니다.
2. **(c)에서 spy 추가를 "Oracle 축 강화"라 한 것은 너무 넓었다.** spy가
   증명한 것은 semantic correctness가 아니라 **interaction이 발생했다**는
   것뿐이다. 정확히는 *interaction observability는 확보, output
   discriminability와 fixture adequacy는 미확보*.

### 5b. mutmut 내부 주장 — 소스로 검증 완료

조사자가 소스를 보지 않고 주장한 실행 모델을 실제 코드로 확인했다:

```python
# mutmut/__main__.py:264
def setup_source_paths() -> None:
    # ensure that the mutated source code can be imported by the tests
    ...  sys.path.insert(0, str(mutated_path.absolute()))
    # ensure that the original code CANNOT be imported by the tests
    ...  del sys.path[i]          ← 원본 경로를 의도적으로 제거
```

`copy_src_dir()`(195), `setup_source_paths()`(264),
`change_cwd("mutants")`(479·483·487) 전부 존재. **내가 겪은 import 충돌은
설정 실수가 아니라 mutmut 3의 실행 모델 그 자체다.** 원본 경로를 의도적으로
제거하므로 `sys.path`를 조작하는 테스트는 구조적으로 깨지고, 설정으로 해결되지
않는다.

여기서 나온 일반 규칙 — 다음 mutation 도구를 고를 때 operator 품질보다 먼저
물을 것:

> **Does its execution model preserve our real pytest/import environment?**

### 5c. `DEAD-CONTRACT` — 새 분류, 그리고 실측으로 확정

조사자가 survivor 상태에 4번째를 추가했다:

```
ACTIONABLE          production 동작을 바꾸며 test가 놓침
EQUIVALENT          production 도달 가능 영역에서 동작 동일
UNKNOWN             판정 비용이 높음
DEAD-CONTRACT       mutant는 equivalent이지만, 그 사실이 불필요한
                    fallback/분기를 드러냄        ← 신규
```

**이 분류가 없으면 554 survivor가 "554개의 테스트 결함"으로 부풀려지고,
mutation testing이 test-quality 도구가 아니라 triage backlog 생성기가 된다.**

`depth.get(path, 0)`을 이 분류로 판정하기 전에 **읽기가 아니라 계측으로**
확인했다 — 실제 vault 5질의 × seed 2종:

```
graph_channel_order 호출 : 50
depth에 없던 경로        : 0
→ DEAD-CONTRACT 확정 (기본값이 한 번도 쓰이지 않음)
```

따라서 `depth.get(path, 0)` → `depth[path]`로 바꿨다. 죽은 분기를 지우고,
그 불변식이 깨지면 조용히 틀린 정렬 키 대신 `KeyError`가 나게 했다.

### 5d. 채택 — 1순위 구현 완료

**Guard Witness Registry**를 vault-backlinks-mcp에 구현했다
(`tests/test_guard_witness.py`, 커밋 `63a0646`). 가드 코드 11개 각각에
**발화해야 하는 세계**와 **침묵해야 하는 세계**를 등록한다.

negative witness가 load-bearing이다 — 무조건 발화하는 가드는 어떤 positive
검사도 통과한다. 이 프로젝트에서 `review_required`가 정보량 0이 된 경로가
정확히 그것이었다.

**레지스트리 자체가 가드이므로 같은 대우를 했다.** 가드를 추가하고 등록을
잊으면 이 파일이 조용히 커버리지를 잃는다 — 이미 두 번 겪은 "게이트가
게이트를 가림"과 같은 형태다. 그래서
`test_every_guard_in_the_source_is_registered`가 `contracts.py`에서 코드를
직접 파싱해 대조하고, 반대 방향(삭제된 가드의 witness가 남아 허위 커버리지를
주장하는 것)도 검사한다.

양방향 poison test로 검증:

| mutation | 결과 |
|---|---|
| `contracts.py`에 미등록 가드 주입 | 완전성 테스트 **FAIL** (의도대로) |
| `if is_symlink_under_root(...)` → `if True` | SYMLINK_TARGET negative witness **FAIL** (의도대로) |

되돌리면 둘 다 통과. **88 passed** (64 + 신규 24).

witness를 만드는 작업 자체가 검사였다 — positive witness를 구성할 수 없는
가드는 도달 불가능한 가드이고, 그게 결함이지 테스트의 공백이 아니다.
11개 전부 구성 가능했다.

## 6. 이 문서가 주장하지 않는 것

- **응답의 문헌 인용을 검증하지 않았다.** 논문 존재·수치·연도를 확인하지
  않았고, 인용이 정확하다고 보증하지 않는다.
- **survivor 554개 중 어느 것이 진짜 결함인지 판정하지 않았다.**
  `graph_channel_order`의 11개도 마찬가지다 — "살아남았다"는 사실만 기록했다.
- **mutation score를 목표로 삼지 않는다.** 응답도 같은 취지로 경고했다.
- 위 수치는 전부 **host lane**, 이 머신 1회 실행 값이다.
