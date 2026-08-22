# 선행연구 조사 응답의 검증 — 순서 의존성 도구와 R12 분류 (2026-08-18)

조사 에이전트의 응답에 대한 독립 검증. 이 응답은 이전과 달리 **버전·날짜·분류자를
구체적으로** 제시했고, 구체적인 주장은 검증 가능하다.

검증 방식: PyPI 조회와 격리 venv(Python 3.13.13, pytest 9.1.1) 실제 설치·실행.
대조 대상은 **수정 이전 트리** — `vault-backlinks-mcp` `95aefdb`를 `git archive`로
꺼낸 것이며, F2 결함이 살아 있는 리비전이다. 수정 후 트리에서는 결함 신호가
소멸하므로(§4) 그쪽에서 측정하면 어떤 도구도 아무것도 못 찾는다.

## 1. 확인된 것

| 주장 | 판정 |
|---|---|
| `pytest-randomly` 최신 4.1.0 | **확인**. PyPI 최신 버전 일치 |
| Python 3.13 + pytest 9 호환 | **확인**. venv에 설치되어 실제 실행됨 (3.13.13 / 9.1.1) |
| `detect-test-pollution` 최신 1.2.0 | **확인** |
| `detect-test-pollution`이 3.13/pytest 9에서 도는지 | **확인**. 크래시 없음, 88 tests 정상 discover |
| `icontract` 최신 2.7.3 | **확인** (버전만) |
| `ipflakies` 최신 1.1.1 | **확인** (버전만) |
| `pytest-randomly`가 F2를 잡는다 | **확인**. 적대적 환경에서 40 seed 중 23개가 검출 |
| polluter/victim/cleaner/**brittle** 분류가 실재하고 유용하다 | **확인, 그리고 예측력이 있었다** — §3 참조 |

## 2. 정정 1 — 환경 한계는 내 도구의 약점이 아니라 결함의 속성이다

조사자는 내 순서 검사기의 "특정 환경변수에서만 찾는다"는 한계를 기존 도구 대비
열등함의 근거로 제시했다. **측정하면 반대다.**

같은 결함, 같은 트리, F2를 확실히 잡는 seed 12345로:

```
VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0  →  FAILED  (검출)
기본 환경                                →  88 passed  (아무것도 없음)

seed 스윕:
  적대적 환경  23/40 seeds 검출  (57%)
  기본 환경     0/15 seeds 검출  ( 0%)
```

`pytest-randomly`도 기본 환경에서는 **0/15**다. 환경 의존성은 도구의 성숙도와
무관하며, 어떤 순서 탐지기를 쓰든 **적대적 설정을 공급하는 것이 선행 조건**이다.

그 공급을 담당하는 것이 이 프로젝트 하네스의 `ENV_SENSITIVE` 검사이며, 조사자가
"BUILD, 통용 명칭 없음"으로 분류한 항목이다. 즉 **조사자가 가장 낮게 평가한 요소가
실제로는 나머지 전부의 전제 조건**이다.

## 3. 정정 2 — `detect-test-pollution`은 이 결함 클래스에 적용 불가다

조사자는 "compatibility smoke test 후 VENDOR"로 권고했다. smoke test는 통과했다.
**적용 가능성에서 막힌다.**

```
$ detect-test-pollution --failing-test "...FILESYSTEM_FALLBACK_USED..." --tests tests/
discovering all tests...
-> discovered 88 tests!
ensuring test passes by itself...
-> test failed! (output printed above)
```

이 도구는 **단독으로는 통과하고 스위트에서 실패하는** 테스트만 다룬다. 우리 결함은
정반대다 — **단독 실패, 스위트 통과.**

flaky-test 분류로 이것은 `victim`이 아니라 **`brittle`**이다: 선행 state-setter
없이 실행하면 실패하는 테스트. 여기서 state-setter는 `test_contracts.py`의
`importlib.reload(contracts)`다.

**조사자가 "Brittle — 필요한 선행 state-setter 없이 실행하면 실패"라고 그 용어를
직접 나열했는데, 우리 사례가 brittle임을 적용하지 않은 채 victim 전용 도구를
권고했다.** 분류를 알고도 대입하지 않은 것이다.

`--help`로 확인한 모드는 `--fuzz`와 `--failing-test` 둘뿐이고 brittle 방향이 없다.
`--fuzz`를 적대적 환경에서 돌리면 순서와 무관하게 실패하는 `test_contracts` 건을
찾아 다시 `--failing-test`로 안내하는데, 그것은 pass-alone 전제에서 다시 막힌다.

판정: **REJECT**(호환성 문제가 아니라 적용 범위 문제). 나중에 victim 유형 결함이
생기면 재검토할 값이 있다.

역설적으로, 조사자가 제공한 **분류 어휘가 그 자신의 도구 권고를 반증하는 수단이
되었다.** 그것이 이 조사의 가장 큰 실질 소득이다 — 도구 추천이 아니라 어휘다.

## 4. 정정 3 — `pytest-randomly` 채택은 seed 고정이 없으면 퇴행이다

조사자의 1순위 권고는 "내 검사기의 범용 탐지기 역할을 버리고 `pytest-randomly`를
채택"이다. 방향은 맞다. **조건이 빠졌다.**

```
적대적 환경 적중률 57% (23/40)
  랜덤 seed 1개로 놓칠 확률   42.5%
  랜덤 seed 3개로 놓칠 확률    7.7%
  랜덤 seed 5개로 놓칠 확률    1.4%
  랜덤 seed 10개로 놓칠 확률   0.0%
```

내 검사기는 이 결함을 **매 실행 결정적으로** 잡는다. `pytest-randomly`를 기본
동작(매 실행 랜덤 seed)으로 채택하면 CI에서 **동전 던지기**가 되고, 회귀 가드로는
기존보다 나빠진다.

정정된 결론:

- **seed를 고정하면** `pytest-randomly`가 우월하다 — 항목 단위 granularity(내 것은
  파일 단위)에 결정성까지 갖춘다. 그러면 내 검사기는 진짜로 불필요해진다.
- **seed를 고정하지 않으면** 채택이 퇴행이다.

조사자의 결론은 맞지만 근거와 조건이 틀렸고, 그 차이가 작동과 미작동을 가른다.

## 5. R12 3분할은 채택한다 — 우리 결함이 그것을 증명한다

조사자는 내 2분할(도달 불가능 / 도달 가능하지만 목격자 없음)을 3분할로 바꾸라고
했다:

| 분류 | 뜻 |
|---|---|
| `UNREACHABLE` | 시스템 불변식과 모순되어 어떤 실행에서도 참이 될 수 없음 |
| `REACHABLE_NOT_EXERCISED` | 발동 가능하지만 테스트가 그 결과를 만들지 않음 |
| `EXECUTED_NOT_CHECKED` | 실행됐지만 어떤 단정도 그 결과를 관측하지 않음 |

**인용 문헌은 검증하지 못했다**(논문 접근 없음). 그러나 이 분류는 인용과 무관하게
자기 값을 증명한다 — 이번 적대적 검증이 독립적으로 찾은 F5가 정확히 세 번째
칸이고, **내 2분할에는 그것을 넣을 자리가 없었다.**

F5: witness가 `review_checks`의 `code` 필드 존재만 확인하고 `required_action`,
`dropped_by_reason`, `returned_count` 등 payload는 검사하지 않는다. 가드는
실행되고 발동한다. 어떤 단정도 그 결과를 관측하지 않는다.

`retriever.py:37`은 두 번째 칸, 기록된 2건의 구조적 도달 불가능 가드는 첫 번째 칸이다.
세 칸이 모두 실제 사례를 갖는다. 채택한다.

`covered but unchecked` / Checked Coverage라는 명칭 주장은 **미검증**으로 남긴다.
분류 자체의 유용성과 명칭의 정확성은 별개 문제다.

## 6. 검증하지 못한 것 — 문헌 주장 전부

논문에 접근할 수 없어 다음은 전부 **미검증**이다. 인용 형식이 그럴듯하다는 것은
근거가 아니다.

- Beer/Ben-David/Eisner/Rodeh의 vacuity, antecedent failure, interesting witness
- Schuler–Zeller의 Checked Coverage
- Beyer 등의 Conditional Model Checking 3분류
- Defects4J / BugsInPy의 buggy/fixed revision 관행
- "Python flaky test 7,571건 중 59%가 order dependency" 수치
- iPFlakies의 알고리즘 세부
- Nagios `UNKNOWN`의 정식 정의
- Claude Code / OpenAI Agents SDK 샌드박스 세부

### 정정 — SARIF는 위임 없이 직접 확인했다 (2026-08-18, 같은 날 추가)

이 문서를 커밋한 직후, "논문·규격에 접근할 수 없다"가 **내가 확인하지 않은
가정**이었음을 발견했다. 웹 조회 도구가 있었다. 두 번의 조회로 결론이 났다.

규격 본문은 커서 해당 절 앞에서 잘렸지만 목차에서 세 속성의 존재가 확인된다
(`executionSuccessful` §3.20.14, `toolExecutionNotifications` §3.20.21,
`results` §3.14.23). 결정적인 것은 공식 JSON 스키마다:

- `invocation.executionSuccessful` — **필수** boolean.
  *"Specifies whether the tool's execution completed successfully."*
- `run.results` — 선택 배열.
  *"The results array can be omitted when a run is solely exporting rules
  metadata. It must be present (but may be empty) if a log file represents an
  actual scan."*

**부재와 빈 배열이 의미상 구별된다.** 조사자의 주장은 실질적으로 확증됐고, 이
하네스의 핵심 규칙("실행되지 않은 검사는 통과한 검사가 아니다")이 이미 표준에
있다. 첫 적대적 검증의 `refuted: []`를 "반박 없음"으로 읽은 오독은, SARIF 용어로는
`executionSuccessful=false`인 run의 결과를 완전한 것으로 취급한 것에 해당한다.

**다만 대체재는 아니다.** `executionSuccessful`은 invocation 단위 boolean이라
"5개 검사 중 3개만 실행됨"을 표현하지 못한다. 이 하네스의 `checks_skipped` /
`CHECK_DID_NOT_RUN`이 더 세밀하다. 검사 단위 미실행을 SARIF로 실으려면
`toolExecutionNotifications`에 태워야 하고, 그 의미론은 아직 확인하지 않았다.

판정: **외부 export adapter로 채택할 값이 있다. 내부 계약의 대체재는 아니다.**
조사자의 "내부 계약 유지 + SARIF adapter 추가" 권고와 일치한다.

교훈은 도구가 아니라 나에 대한 것이다. **"접근할 수 없다"고 적기 전에 접근을
시도해야 한다.** 이 문서의 원래 §6이 미검증 목록을 "논문 접근 없음"으로 뭉갠 것은,
이 세션이 반복해서 지적해온 "확인하지 않은 것을 확인된 제약처럼 적는" 패턴이다.

조사자가 스스로 "Wolfram으로 형식화", "Ace Knowledge Graph에 저장"을 언급했는데,
그 산출물은 이 검증에서 사용하지 않았다. 3상태 집계 대수
(`PROBLEM > UNKNOWN > OK`)는 도구 없이도 자명하고, 이미 하네스에 구현되어 있다.

## 7. 이 문서가 주장하지 않는 것

- **문헌 주장을 반박하지 않았다.** 검증하지 못한 것과 틀린 것은 다르다.
- `pytest-randomly`를 아직 채택하지 않았다. venv에서 측정만 했고 프로젝트
  의존성에 넣지 않았다.
- 적중률 57%는 **이 결함, 이 트리, 40 seed** 기준이다. 다른 순서 의존성의
  적중률은 다를 수 있다.
- `ipflakies`와 `icontract`는 버전만 확인했고 **실행하지 않았다.**
- 전부 host lane, 각 1회 측정이다.
