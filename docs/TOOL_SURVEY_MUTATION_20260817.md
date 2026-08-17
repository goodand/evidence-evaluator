# 도구 대조 — mutation testing, subtree 재사용 후보 (2026-08-17)

`docs/RESEARCH_P1_VACUOUS_GUARDS_20260817.md`가 남긴 질문에 답한다:

> mutmut의 실행 모델이 이 프로젝트 import 구조와 충돌한다. 대안이 있는가?
> 그리고 **operator 품질보다 먼저 물어야 할 것**은
> "이 도구의 실행 모델이 우리의 실제 pytest/import 환경을 보존하는가?"다.

전부 이 머신에서 실제로 설치·실행한 결과다. README 비교가 아니다.

## 1. 결론 요약

| 도구 | 실행 모델 | 이 프로젝트에서 | subtree 후보 |
|---|---|---|---|
| **mutmut 3.7.0** | 소스 트리를 `mutants/`로 복사, `sys.path`에서 원본 제거 | **단일 파일 대상 불가.** 패키지 전체를 줘야 함 | ✗ pip 의존성이지 vendoring 대상 아님 |
| **mutatest 3.1.0** | `__pycache__` 바이트코드만 변경, **소스 무수정** | **한 줄 수정 후 동작.** 단일 파일 대상 가능 | **✓ 유일한 후보** |
| cosmic-ray | on-disk mutation + session DB | 미검증 | 미판정 |

## 2. mutmut — 실행 모델이 원인이다 (소스로 확인)

```python
# mutmut/__main__.py:264
def setup_source_paths() -> None:
    # ensure that the mutated source code can be imported by the tests
    ...  sys.path.insert(0, str(mutated_path.absolute()))
    # ensure that the original code CANNOT be imported by the tests
    ...  del sys.path[i]          ← 원본 경로를 의도적으로 제거
```

`copy_src_dir()`(195), `setup_source_paths()`(264),
`change_cwd("mutants")`(479·483·487).

**설정 문제가 아니다.** 원본 경로를 의도적으로 제거하므로 `sys.path`를 조작하는
테스트는 구조적으로 깨진다.

측정된 동작:

```
source_paths=<단일 파일>  → ModuleNotFoundError (패키지가 불완전 복사)
tests_dir=tests/          → ModuleNotFoundError: 'contract'
source_paths=<패키지 전체> → 동작. 10,236 mutants / 58초 / survivor 554
```

## 3. mutatest — 아키텍처는 맞고 도구가 낡았다

### 3a. 왜 아키텍처가 맞는가

소스를 건드리지 않고 `__pycache__`만 바꾸므로 **`sys.path`도 cwd도 그대로**다.
이 프로젝트 테스트가 하는 경로 조작이 깨지지 않는다.

### 3b. Python 3.13에서 크래시한다 (실측)

```
mutatest/run.py:530
    current_mutation = random.sample(mutant_operations, k=1)[0]
→ TypeError: Population must be a sequence. For dicts or sets, use sorted(d).
```

`random.sample()`의 set 인자는 Python 3.9에서 deprecate, **3.11에서 제거**됐다.
`mutatest`의 자체 코드다.

유지보수 상태: GitHub `EvanKepner/mutatest`의 copyright가 **2018–2020**,
문서가 Python **3.7–3.8**을 대상으로 한다. 사실상 중단.

### 3c. 수리 비용 — 한 줄

```python
- current_mutation = random.sample(mutant_operations, k=1)[0]
+ current_mutation = random.sample(sorted(mutant_operations, key=repr), k=1)[0]
```

(`run.py`에 `random.sample` 호출이 3곳 있으나 이 세션 시나리오에서 실제로
터진 것은 530행 하나다. 나머지 두 곳이 안전한지는 **확인하지 않았다** —
243행은 `sample_space`가 list로 보이나 검증하지 않았다.)

수정 후 실제 실행:

```
$ mutatest -s evidence_evaluator/retrieval/retriever.py -t "pytest tests/... -q" -n 5

DETECTED: 1   TOTAL RUNS: 6   (4.9초)

SURVIVED
 - retriever.py (l:37,  c:8)  If_Statement → If_False       ← RetrievalConfig 검증
 - retriever.py (l:176, c:48) Slice_UnboundLower → Slice_Unbounded
 - retriever.py (l:185, c:27) ast.NotIn → ast.In
 - retriever.py (l:217, c:27) ast.NotIn → ast.In
 - retriever.py (l:240, c:33) Slice_UnboundLower → Slice_Unbounded
```

**mutmut이 못 하던 단일 파일 대상 실행이 된다.** 이것이 도구 선택의 핵심
차이다.

### 3c-2. l:37 survivor는 진짜 결함이다 — poison test로 확인

도구 보고를 믿지 않고 직접 재현했다.

`retriever.py:37`은 `RetrievalConfig.__post_init__`의 **두 번째** 검증이다:

```python
if not 1 <= self.graph_seed_k <= min(self.candidate_pool_k, MAX_GRAPH_SEED_K):
    raise RetrievalError("Require 1 <= graph_seed_k <= candidate_pool_k")
```

`tests/test_vault_retrieval_core.py`에 `RetrievalError`를 기대하는 곳은
**261행 한 곳뿐**이고, 그 인자는 `RetrievalConfig(output_k=9, candidate_pool_k=8)` —
**첫 번째** 검증(32행)만 발동시킨다. `graph_seed_k` 분기를 발동시키는 테스트는
없다.

poison test:

```
1. 전체 통과 확인          → 131 passed
2. 37~39행을 `if False:`로 → 131 passed   ← 아무것도 실패하지 않음
3. 되돌림                  → 131 passed
```

**검증을 통째로 죽여도 테스트 스위트가 초록색이다.** P1(공허한 가드)의
18번째 사례이며, **손이 아니라 도구가 처음으로 찾아낸 사례**다.

이 가드가 도달 불가능한 것은 아니다 — 이 세션에서 내가 직접
`graph_seed_k` 기본값 12 > `candidate_pool_k=10`으로 이 오류를 맞았다.
발동은 하는데 **아무도 발동을 확인하지 않는다.** 그래서 이것은
"구조적으로 도달 불가능한 가드"(사례 2건)와 다른 하위 유형이다:
**도달 가능하지만 목격자가 없는 가드.**

Guard Witness Registry가 정확히 이것을 막는다 — 다만 지금은
`vault-backlinks-mcp`에만 적용돼 있고 `evidence-evaluator`에는 없다.
이 survivor가 그 미적용의 대가를 보여준다.

**아직 고치지 않았다.** 이 문서는 도구 대조이지 결함 수리가 아니고,
`RetrievalConfig` 검증에 witness를 붙이는 것은 별도 작업이다.

### 3d. 부작용 — 의존성 충돌

`mutatest`가 `coverage`를 5.5로 다운그레이드해 `mutmut 3.7`(coverage≥7.3
요구)과 **같은 환경에 공존할 수 없다.** 둘을 쓰려면 venv를 분리해야 한다.

## 4. subtree 판정

**"pip install로 쓰는 도구"와 "vendoring 대상"을 구분해야 한다.**

- **mutmut**: 활발히 유지보수되고 우리가 고칠 것이 없다. 실행 모델이 안 맞으면
  **쓰지 않으면 되는** 문제다. **subtree 대상이 아니다.**
- **mutatest**: 아키텍처가 이 프로젝트에 맞는 **유일한** 후보인데 **버려졌고**,
  수리가 한 줄이다. 이것이 정확히 subtree(vendoring)가 존재하는 이유다 —
  upstream이 고쳐줄 가망이 없고, 우리가 소유해야 하며, 변경이 작다.

다만 **아직 subtree로 들이지 않았다.** 판단을 미루는 근거:

1. 이 세션의 도구 우선순위에서 mutation은 **3순위 조건부 진단**이고,
   1순위(Guard Witness Registry)만 구현된 상태다.
2. 한 줄로 크래시가 사라졌다고 **Python 3.13 호환이 확인된 것은 아니다.**
   6 trial만 돌렸고, 나머지 `random.sample` 2곳과 다른 3.9~3.13 제거 API는
   검사하지 않았다.
3. 2018–2020 코드베이스를 vendoring하면 **그 유지보수를 이 프로젝트가
   떠안는다.** 그 비용이 survivor triage 비용보다 작다는 근거가 아직 없다.

## 5. Guard Witness Registry에 대응하는 기존 구현은 찾지 못했다

`pytest-check`, `pytest-github` 등은 다른 문제를 푼다. "선언된 모든 가드 코드에
positive/negative witness를 의무화하고 레지스트리 자체의 완전성을 소스와
대조한다"는 패턴에 해당하는 공개 패키지는 **검색으로 찾지 못했다.**

가장 가까운 선행은 이 워크스페이스 내부에 있다 —
`.vault-harness/…/experiments/2026-08-08_tool_only_context/test_protocol.py`의

```python
@pytest.mark.parametrize("code", sorted(FAILURE_CODES))
def test_every_declared_failure_code_is_reachable(code):
    assert any(code in score_one(p) for p in probes)
```

이번에 구현한 `tests/test_guard_witness.py`는 이것을 **negative witness와
레지스트리 완전성 메타가드로 확장**한 것이다. 외부에서 가져올 모듈이 없으므로
subtree 대상도 없다.

**부정적 근거로 기록한다**: 없다는 것도 결과다. 검색 범위 밖에 존재할
가능성은 배제하지 않는다.

## 6. 이 문서가 주장하지 않는 것

- **cosmic-ray를 검증하지 않았다.** on-disk mutation이라 mutmut과 같은 문제를
  가질 가능성이 있으나 확인하지 않았다.
- **mutatest의 Python 3.13 호환을 확인하지 않았다.** 한 줄 수정 후 6 trial이
  돌았을 뿐이다.
- **survivor 5건 중 1건(`l:37`)만 판정했다** — 그것은 §3c-2에서 poison test로
  진짜 결함임을 확인했다. 나머지 4건(`Slice_UnboundLower` 2건,
  `ast.NotIn → ast.In` 2건)은 **판정하지 않았다.**
- 위 수치는 전부 **host lane**, 각 1회 실행 값이다.
