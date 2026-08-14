---
title: Codex Session Issue Log - Transport Requalification and Factorial Screen
date: 2026-08-14
status: active-handoff
scope: current-codex-session
tags:
  - doc/issue-analysis
  - topic/handoff
  - topic/retrieval
  - topic/evaluation
---

# Codex 직접 이슈·반복 패턴·해결 근거 기록

- 선행 Codex 기록: [[concept-gate-codex-mcp-wt/docs/feedback/session_retrospective_20260811_codex_retrieval_migration_and_canary|Codex retrieval migration retrospective]]
- 현재 실험 handoff: [[HANDOFF_FACTORIAL_V2]]
- 현재 상태 정본: [[HANDOFF_FACTORIAL_V2_EVIDENCE]]
- 실행 기록: [[HANDOFF_FACTORIAL_OPERATIONAL_CANARY_20260814]]
- 저장소 이력: [[CODEX_COMMIT_LOG_20260812]]

## 0. 범위와 판정 규칙

이 문서는 Claude Code의 보고를 옮긴 것이 아니다. 현재 Codex 세션이 직접 명령을
실행하거나 코드를 읽는 과정에서 발생·재현·발견한 항목만 기록한다. 선행 기록의
마지막 ID `C-I21` 다음인 `C-I22`부터 이어간다.

상태는 다음 의미로 사용한다.

| 상태 | 의미 |
|---|---|
| 해결 | 원래 실패를 재현했고 수정 후 같은 실패와 짝 음성 테스트가 통과 |
| 부분 해결 | 현재 경로는 작동하지만 더 일반적인 계약이나 trust boundary는 남음 |
| 경계 확정 | 코드 결함이 아니라 실행 환경·역사 artifact의 한계로 분리해 기록 |
| 미해결 | 위험과 판정 기준은 확인했지만 기계적 차단이 없음 |

`pytest PASS`, live subject PASS, receipt 검증 PASS, held-out 성능은 서로 다른
주장이다. 하나를 다른 것의 근거로 사용하지 않는다.

## 1. Codex가 직접 겪은 신규 이슈

| ID | Codex가 직접 겪은 이슈 | 직접 관측 | 영향 | 상태 |
|---|---|---|---|---|
| `C-I22` | 존재하지 않는 `factorial verify` subcommand를 먼저 실행 | CLI가 valid choices를 출력하며 종료 | 명령 계약을 읽지 않고 추정 | 해결 |
| `C-I23` | 존재하지 않는 `tests/test_factorial.py`를 지정 | pytest가 file not found로 종료 | 테스트 이름을 추정해 검증 1회 무효 | 해결 |
| `C-I24` | 실패한 provider MCP call을 성공 call 목록에 섞음 | Luna attempt 3은 provider 5건, server audit 4건으로 runtime reject | 재시도 가능한 도구 오류가 retrieval failure로 오분류 | 해결 |
| `C-I25` | append-only freeze를 그대로 덮어쓰려 시도 | freeze CLI가 overwrite를 거부 | 역사 보존 계약을 실행 전 읽지 않음 | 해결 |
| `C-I26` | canary result에 실제 subject model이 없음 | provider 이름은 있었지만 `--model` 값은 artifact에 부재 | Luna 재qualification 주장을 결과만으로 검증 불가 | 해결 |
| `C-I27` | 기존 `factorial qualify`가 과거 attempt1 이름과 과거 freeze digest에 고정 | 현재 6개 결과를 같은 명령으로 qualification할 수 없음 | 역사 qualification 보존과 current requalification을 한 API가 표현하지 못함 | 부분 해결 |
| `C-I28` | current transport receipt digest가 문서에는 있으나 verifier expected pin으로 강제되지 않음 | verifier가 receipt 내부의 model/prefix를 다시 입력으로 사용 | receipt와 결과를 함께 재결속한 악의적 변경을 Git 문서 확인 없이 자동 거부하지 못함 | **미해결** |
| `C-I29` | 상태 전환 시 문서 일부가 이전 상태를 계속 가르침 | attempt 4 기록 뒤 “다음은 requalification”, screen 기록 뒤 “screen has not run” 문장이 잔존 | zero-context subject의 입력 자체가 모순될 수 있음 | 해결 |
| `C-I30` | managed lane에서 진행 확인용 `ps`가 차단 | `operation not permitted`; result file count는 읽을 수 있었음 | 동일 checkout이라도 관측 가능한 runtime telemetry가 다름 | 경계 확정 |
| `C-I31` | 16-cell screen이 최종 aggregate 전 stdout 진행률을 내지 않음 | 약 25분 동안 cell 파일 수로만 2/6/10/13 진행 확인 | 정상 장기 실행과 hang 구분 비용 증가 | 부분 해결 |
| `C-I32` | 이 로그 초안에 filesystem-relative Obsidian wikilink를 다시 작성 | 커밋 전 outgoing-link 검토에서 `../concept-gate...` 발견 | 선행 `C-I21`과 같은 재발 | 해결 |

## 2. 반복된 이슈와 증가한 Codex-only 하한

Claude 또는 프로젝트 전체 횟수는 합산하지 않는다.

| 반복 패턴 | 이전 하한 | 이번 증가 | 현재 하한 | 근거 |
|---|---:|---:|---:|---|
| `C-P7` permission-lane conflation | 3 | +1 | **4** | `C-I30`; `ps`는 막혔지만 동일 프로세스의 결과 파일은 계속 생성 |
| `C-P8` schema/path/command를 읽기 전에 추정 | 2 | +3 | **5** | `C-I22`, `C-I23`, `C-I25` |
| `C-P10` green 내부 검증을 외부 provenance 증명으로 확대 | 1 | +1 | **2** | `C-I26`; tests는 통과했지만 model identity가 artifact에 없었음 |
| `C-P11` filesystem path semantics를 vault link에 적용 | 1 | +1 | **2** | `C-I32`; 이 로그 초안에서 재발, 커밋 전 수정 |
| `C-P12` 상태 전환의 부분 문서 갱신 | 0 | +2 | **2** | `C-I29`의 requalification 전환과 screen 전환에서 각각 잔존 문장 발견 |
| `C-P13` 서로 다른 provenance event를 한 목록으로 합침 | 1 | +1 | **2** | started/completed 중복 선행 수정 뒤 failed/success 혼합이 attempt 3에서 재발 |
| `C-P14` hash 기록을 trusted consumer로 오인 | 1 | +1 | **2** | 선행 `C-I19` sidecar와 현재 `C-I28` receipt |

가장 큰 수치 증가는 `C-P8`이다. 가장 위험한 증가는 `C-P14`다. 전자는 시간을
낭비하지만 대개 fail-loud한다. 후자는 그럴듯한 PASS receipt를 만들 수 있어
qualification 의미를 바꿀 수 있다.

## 3. 해결 근거가 있는 이슈

### C-I22/C-I23/C-I25 - 추정한 명령·경로·overwrite 계약

1. 실패 출력을 숨기지 않고 invalid command/file/overwrite로 분류했다.
2. `factorial --help`, `factorial freeze --help`, 실제 `rg --files tests`를 읽었다.
3. freeze는 append-only 거부를 우회하지 않고, 이전 digest를 Git 이력에 보존한
   뒤 private receipt를 명시적으로 새 세대로 재생성했다.
4. 새 freeze `a01569b7...d2564`를 Git pin과 문서에 반영하고 `--verify` PASS를
   확인했다.

판정: 직접 실패는 **해결**. 그러나 모든 명령을 실행 전 자동 discovery하는
공통 wrapper는 없으므로 `C-P8` 재발 가능성은 남는다.

### C-I24 - 실패 call과 성공 call의 provenance 혼합

원인:

```text
provider completed event
  = successful MCP call 또는 provider-level failed attempt

server audit event
  = 서버에 도달해 처리된 call
```

기존 parser는 두 provider event를 모두 `mcp_tools`에 넣었다. attempt 3의 첫
`vault_search(question=...)`는 서버 전 단계에서 실패했고, 재시도
`vault_search(query=...)`만 audit에 남았다.

해결:

1. `providers.py`가 `mcp_tools`와 `failed_mcp_tools`를 분리한다.
2. 성공 provider trace는 server audit와 정확히 같아야 한다.
3. 실패 attempt도 `provider_attempt_count`에 포함한다.
4. 총 attempt가 `max_calls`를 넘으면 fail-closed한다.
5. 회귀 테스트 두 개로 recovered failure PASS와 budget exceed FAIL을 고정했다.
6. Luna attempt 6이 실패 search 1회 + 성공 audited call 4회, 총 5/6으로 실제
   accepted되어 live 경로를 검증했다.

판정: **해결**. 근거 커밋 `d4671d5`, 전체 suite 116/118 PASS, attempt 6 result
SHA-256 `8a168858...a530cfc`.

### C-I26 - 모델 provenance 누락

해결:

- 성공과 ProviderError artifact 모두 `execution.subject_model`, reasoning,
  timeout, `max_calls`, `output_k`를 기록한다.
- scripted E2E가 정확한 execution manifest를 검사한다.
- Luna current-harness qualification 6건 모두 artifact 안에서 모델을 재검증했다.

판정: **해결**. 근거 커밋 `00432f0`, current receipt accepted 6/6, invalid 0.

### C-I27 - historical qualifier와 current requalification 충돌

해결:

- 과거 `factorial qualify`와 결과는 덮어쓰지 않았다.
- `transport_qualification.py`를 별도 high-cohesion verifier로 만들었다.
- 과거 frozen private assets의 무변조, 현재 transport source hashes, 정확한 6개
  result 집합, 모델, result/audit/source provenance를 함께 검사한다.
- receipt는 factorial private tree 밖에 두어 factorial asset set을 오염시키지
  않았다.

판정: **부분 해결**. 정상·우발적 drift 검증은 PASS지만 trusted expected digest
문제는 `C-I28`로 남는다.

### C-I29 - 문서 상태 전환 부분 갱신

해결:

1. `rg`로 이전 state/action code와 오래된 test count를 검색했다.
2. navigation handoff, canonical evidence authority, 상위 HANDOFF, operational
   record, private operational gold를 같은 batch에서 갱신했다.
3. requalification 뒤 Luna attempt 5가 새 screen-ready 상태를 회수했다.
4. screen 뒤 Luna attempt 6이 `SCREEN_COMPLETE_CONFIRM_PINNED`, held-out next
   action, 세 stop code를 모두 회수했다.

판정: 현재 전환은 **해결**. 장래 전환을 원자적으로 강제하는 linter는 없다.

## 4. 해결 유무 총괄

| 상태 | ID | 남은 위험 |
|---|---|---|
| 해결 | C-I22, C-I23, C-I24, C-I25, C-I26, C-I29, C-I32 | 공통 process guard 부재 |
| 부분 해결 | C-I27, C-I31 | trusted pin과 progress telemetry 부족 |
| 경계 확정 | C-I30 | managed lane capability 자체는 변하지 않음 |
| 미해결 | **C-I28** | 재결속 공격을 verifier 단독으로 거부 못 함 |

현재 실험 자체는 screen까지 완료됐다. 16/16 valid, dynamic paired improvement 3,
regression 0, screen decision `FULL_2X2`, pinned receipt digest
`40027887...f6568`이다. held-out은 실행하지 않았다.

## 5. 해결 근거가 있고 반복된 이슈의 문제 정의

### P-A. 실행 전 계약 discovery가 없는 자동화

`C-P8`의 공통 원인은 명령·파일·overwrite 정책을 “비슷한 인터페이스일 것”으로
추정한 것이다. 실패가 fail-loud였기 때문에 데이터 손상은 없었지만, 자동화의
정확성은 사전 introspection에 의존한다.

```text
실행 가능성 = 명령 존재 + 실제 argument contract + 입력 경로 존재 + write policy
```

네 조건 중 하나라도 읽지 않았다면 예상 output을 검증한 것이 아니다.

### P-B. provenance channel의 의미 단위가 다름

provider event, MCP server audit, result artifact는 같은 “tool call”을 서로 다른
경계에서 관측한다. 이들을 단순 list equality로 비교하려면 먼저 success/failure와
started/completed 의미를 정규화해야 한다.

```text
successful provider completions == server audited calls
all provider attempts <= budget
failed provider attempts are visible but not fabricated as server calls
```

### P-C. 문서는 zero-context subject의 실행 입력이다

이 프로젝트에서 문서 drift는 설명 품질 문제가 아니라 treatment contamination이다.
한 state transition에서 authority만 바꾸고 진입 handoff나 historical record를
바꾸지 않으면 검색 성공 subject가 서로 모순된 정답을 받는다.

### P-D. digest가 있다는 사실과 trusted pin 검증은 다르다

receipt self-digest는 우발적 손상을 찾는다. 공격자가 receipt와 대상 artifacts를
함께 바꾸고 digest를 다시 계산할 수 있다면 신뢰 근거가 아니다. 외부 Git-tracked
expected digest를 verifier input으로 받아 비교해야 한다.

## 6. 사용한 가설과 검증 방식

### H-22. recovered provider failure는 성공 trace 일치와 budget으로 판정할 수 있다

- 가설: 실패 attempt가 별도 기록되고 총 budget 안이며 성공 trace가 audit와
  같다면 run을 무조건 invalid로 만들 필요가 없다.
- 반증 조건: 성공 provider 목록과 audit 불일치, 또는 전체 attempt > budget.
- 검증: 짝 unit test + attempt 6 live run.
- 결과: PASS. `C-I24` 해결.

### H-23. 현재 transport qualification은 과거 inputs와 현재 harness를 함께 묶어야 한다

- 가설: 과거 private asset digest가 같고, 현재 source/result/audit/model hashes가
  모두 맞으며 6/6 valid·accepted면 screen 전 transport readiness를 회복한다.
- 반증 조건: asset path/hash drift, case 누락/중복, model mismatch, audit mismatch,
  invalid 또는 rejected result.
- 검증: 변조·wrong-model·missing-case 음성 테스트, 실제 Luna 6-case 실행,
  receipt create 후 verify.
- 결과: 정상·우발적 drift 범위 PASS. 악의적 재결속은 H-25로 분리.

### H-24. handoff 상태 전환은 fresh subject가 찾아야 완료다

- 가설: 문서 편집 자체가 아니라 zero-context search/read subject가 새 state,
  next action, stop codes를 모두 회수해야 transition이 operationally complete다.
- 검증: attempt 5와 6을 fresh Luna process로 실행하고 실제 MCP audit/read citation을
  evaluator가 확인.
- 결과: 두 전환 모두 PASS.

### H-25. current receipt verifier는 trusted digest 없이 재결속을 막지 못한다

- 가설: receipt의 model/prefix와 결과를 함께 바꾸고 새 digest를 계산하면 현재
  verifier는 Git 문서의 원래 digest를 자동 비교하지 않는다.
- 검증 방식: 코드 경로 검사. `verify_receipt()`는 expected receipt에서 model과
  prefix를 읽어 actual을 재구축하고 equality만 검사한다. 외부 expected digest
  인자가 없다.
- 판정: **미해결**. 실제 private artifact mutation은 수행하지 않았다. 현재
  single-user local screen 결과를 소급 무효화하지는 않지만, public release 또는
  다음 qualification 세대 전에 고쳐야 할 trust hardening이다.

## 7. 구체적인 해결 절차

### 7.1 C-I28 필수 수정

1. `factorial_pin.py`와 분리된 Git-tracked transport qualification pin을 둔다.
2. `verify_receipt(..., expected_digest)`를 필수 인자로 바꾼다.
3. receipt self-digest, rebuilt receipt equality, external expected digest 세 검사를
   모두 통과해야 PASS하도록 한다.
4. expected digest 부재·한 글자 변경·receipt/result 재결속을 각각 거부하는 음성
   테스트를 추가한다.
5. 현재 screen 뒤에는 `NO_TUNING_AFTER_SCREEN`이 우선한다. held-out 전에 이
   hardening을 끼워 넣지 말고, confirm 종료 후 다음 qualification 세대에서 pin과
   verifier를 함께 도입한다. public release 전에 반드시 닫는다.

### 7.2 상태 전환 절차

1. canonical evidence authority를 먼저 편집한다.
2. navigation handoff, 상위 HANDOFF, operational record, private operational gold를
   같은 batch에서 갱신한다.
3. 이전 state/action/stop code를 `rg`로 전수 검색한다.
4. historical 문맥의 잔존만 허용하고 current claim 잔존은 제거한다.
5. fresh Luna operational canary가 새 코드를 회수해야 transition을 완료로 판정한다.

### 7.3 장기 실행 절차

1. 실행 전 output directory가 비어 있는지 확인한다.
2. frozen model과 manifest를 바꾸지 않는다.
3. process telemetry가 막히면 실행을 재시작하지 말고 append-only cell artifact 수로
   진행률을 관측한다.
4. 완료 후 receipt pin 전 score가 fail-closed하는지 먼저 확인한다.
5. receipt digest를 별도 commit으로 pin한다.
6. score를 다시 실행해 freeze, pin, cells, summary를 검증한다.
7. handoff의 stop condition을 지켜 다음 stage를 같은 작업에서 자동 실행하지 않는다.

## 8. 다음 세션 진입점

다음 agent는 [[HANDOFF_FACTORIAL_V2_EVIDENCE]]를 먼저 읽는다. 현재 허용된 다음
실험은 frozen held-out full 2x2 confirm이다. `C-I28`은 결과 해석의 residual trust
limit로 유지하고, screen 결과를 보고 실행 표면을 바꾸지 않는다. confirm 이후 새
qualification 세대에서 external pin을 기계 강제한다.
