---
title: Fresh Session Handoff - Held-out Factorial Confirm
date: 2026-08-14
status: active-handoff
scope: handoff-retrieval-factorial-v2
tags:
  - doc/handoff
  - topic/retrieval
  - topic/evaluation
  - status/confirm-ready
---

# Fresh-session handoff: held-out 2x2 confirm

이 문서는 이전 대화를 전혀 모르는 세션의 실행 진입점이다. 새 세션은 아래 읽기
순서와 preflight를 마친 뒤에만 held-out confirm을 실행한다.

- 탐색 진입점: [[HANDOFF_FACTORIAL_V2]]
- 현재 상태 정본: [[HANDOFF_FACTORIAL_V2_EVIDENCE]]
- Codex 직접 이슈와 남은 trust 경계: [[CODEX_SESSION_ISSUE_LOG_20260814]]
- historical plumbing 근거: [[HANDOFF_FACTORIAL_OPERATIONAL_CANARY_20260814]]

## 1. 현재 상태와 작업 목적

저장소와 branch:

```text
/Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator
main
```

실험은 오직 다음 두 질문을 다룬다.

1. dynamic search controller가 fixed recall-first controller보다 무맥락 handoff
   복구를 개선하는가?
2. retrieval-only helper(subagent)가 같은 복구를 개선하는가?

현재 상태 코드는 `SCREEN_COMPLETE_CONFIRM_PINNED`다. development screen은
16/16 valid였고, `S_DYNAMIC`은 세 paired case를 개선했으며 회귀, false absence,
premature stop은 모두 0이었다. 따라서 gate는 `FULL_2X2`를 선택했다.

이는 **development evidence**일 뿐이다. held-out 성능, helper 효과, interaction은
아직 측정하지 않았다. 다음에 허용된 행동은 정확히
`RUN_HELD_OUT_FULL_2X2_CONFIRM`이다.

신뢰 기준값:

```text
transport receipt digest
6b41b82d36d2c2782bed583f3655af7b9dc9d8c62aa71febd3f341dd0752ca4e

factorial freeze digest
a01569b7a1add4ae0a02ac18882384164617c7da6540c16340db0bdb510d2564

screen receipt digest
40027887b71d7bc23b20bb7b397233c4a9c492440f6ee3a2c9dc934b995f6568
```

성능 측정용 subject model은 동결된 `gpt-5.6-sol`이다. `gpt-5.6-luna`는 transport
requalification과 단순 operational handoff에 사용한 모델일 뿐, factorial 성능
모델을 바꾸는 근거가 아니다.

## 2. 절대 변경 금지

held-out confirm 전에는 다음을 변경하지 않는다.

- `evidence_evaluator/`의 factorial harness, evaluator, provider, frozen pin
- `private_eval/handoff-factorial-v2/`의 manifest, corpus, cases, gold, freeze
- `results/handoff-factorial-v2/`의 screen cell, summary, receipt
- subject model, arms, split, replicate 수, action budget

다음 stop code를 그대로 적용한다.

- `NO_TUNING_AFTER_SCREEN`
- `PRESERVE_SCREEN_RECEIPT_AND_PIN`
- `NO_HELD_OUT_CLAIMS_BEFORE_CONFIRM`

`private_eval/`, `results/`, hidden gold, credentials는 ignored private assets다.
읽거나 실행에 사용하더라도 public remote에 push하거나 문서에 원문을 옮기지 마라.
이 handoff 자체는 push를 승인하지 않는다.

## 3. 새 세션 read order

1. 이 문서를 끝까지 읽는다.
2. [[HANDOFF_FACTORIAL_V2_EVIDENCE]]를 읽어 현재 state code, digests, stop code를
   대조한다.
3. [[HANDOFF_FACTORIAL_V2]]에서 arm 정의, split, outcome 정의, CLI 계약을 읽는다.
4. [[CODEX_SESSION_ISSUE_LOG_20260814]]에서 `C-I28`을 읽는다. receipt self-digest와
   Git-tracked trusted expected digest는 다르다. 이 residual은 public release 또는
   다음 qualification hardening 범위이며, held-out 전 수정 대상이 아니다.
5. `git status --short --branch`를 실행한다. 예상은 clean working tree와
   `main...origin/main [ahead N]`일 수 있다. ahead 수 자체는 성공 조건이 아니다.

## 4. 실행 전 preflight

다음 명령을 저장소 root에서 순서대로 실행한다.

```bash
cd /Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator

python3 -m pytest -q

python3 -m evidence_evaluator.transport_qualification verify \
  --confirmatory-dir private_eval/handoff-confirmatory-v1 \
  --results-dir results \
  --output private_eval/transport-requalification-v1/receipt.json

python3 -m evidence_evaluator.factorial freeze \
  --manifest private_eval/handoff-factorial-v2/manifest.json \
  --output private_eval/handoff-factorial-v2/freeze.json --verify

python3 -m evidence_evaluator.factorial score \
  --output-dir results/handoff-factorial-v2 \
  --stage screen \
  --manifest private_eval/handoff-factorial-v2/manifest.json \
  --freeze private_eval/handoff-factorial-v2/freeze.json
```

기대값:

- pytest: 현재 Codex 환경에서 `113 passed, 6 skipped`. skip은 host-only 또는
  optional dependency 경계일 수 있으므로, 새 세션은 숫자를 추정하지 말고 skip
  사유가 기존 것인지 확인한다.
- transport receipt verify: `PASS`, 6/6 accepted, invalid 0
- freeze verify: `PASS`, factorial freeze digest 일치
- screen score: `FULL_2X2`, 16-cell screen receipt digest 일치

하나라도 실패하면 **confirm을 실행하지 않는다**. 실패 출력, `git status`, 생성된
새 artifact 이름만 기록한다. freeze/receipt를 재생성하거나 code를 고쳐 실패를
없애지 않는다. 이 경우 다음 행동은 원인 분류와 별도 승인이지 held-out 재시도가
아니다.

## 5. Held-out confirm 실행

preflight가 모두 PASS일 때만 다음 한 명령을 실행한다.

```bash
python3 -m evidence_evaluator.factorial confirm \
  --manifest private_eval/handoff-factorial-v2/manifest.json \
  --freeze private_eval/handoff-factorial-v2/freeze.json \
  --output-dir results/handoff-factorial-v2
```

이 명령은 held-out 8 cases x 4 arms x 3 replicates, 총 **96 subject cells**를
append-only로 만든다. retrieval arm은 case/replicate마다 helper를 한 번 실행하므로
**24 helper provider calls**와 helper artifact가 추가된다.
실행이 길어도 process를 강제 종료하거나 같은 output path로 재실행하지 않는다.
진행 상태가 필요하면 결과 디렉터리의 파일 수를 읽기 전용으로 확인한다.

실행 중 새 cell/helper/summary artifact가 이미 존재해 overwrite 거부가 나면, 그
artifact를 보존하고 중단한다. 일부 결과만으로 score를 만들거나 held-out 효과를
추정하지 않는다.

## 6. Confirm 후 검증과 기록

confirm command가 정상 종료한 뒤에만 다음을 실행한다.

```bash
python3 -m evidence_evaluator.factorial score \
  --output-dir results/handoff-factorial-v2 \
  --stage confirm \
  --manifest private_eval/handoff-factorial-v2/manifest.json \
  --freeze private_eval/handoff-factorial-v2/freeze.json
```

그 후 `results/handoff-factorial-v2/confirm-summary.json`과
`confirm-receipt.json`의 status, matrix completeness, invalid-run denominator,
primary/secondary outcomes를 읽는다. raw cell만 보고 arm 효과나 interaction을
주장하지 않는다.

새로운 tracked post-confirm handoff에는 최소한 다음만 기록한다.

- confirm command, 종료 상태, 시각, model과 freeze/screen/confirm receipt digests
- expected matrix와 actual artifact matrix의 일치 여부
- invalid runs와 intention-to-run denominator
- preregistered outcome와 `not established` claim의 분리
- 환경 차이 또는 provider failure가 있으면 `BLOCKED`, `invalid`, `retrieval`,
  `reconstruction` 중 어느 층인지

문서 변경 전후에 해당 문서의 wikilink가 이 handoff 및
[[HANDOFF_FACTORIAL_V2_EVIDENCE]]로 연결되는지도 확인한다. 새 상태는 navigation
handoff와 canonical evidence authority를 같은 batch에서 함께 갱신한다.

## 7. 실패와 잔여 위험의 처리

`C-I28`은 current transport receipt에 separate trusted expected digest verifier가
없는 residual이다. 이것을 held-out 실행 전에 고치면 frozen surface와 screen을
무효화해 development outcome 뒤 tuning이 된다. 따라서 이번 세션에서는 기록만 하고
변경하지 않는다.

managed sandbox와 host lane의 권한은 다를 수 있다. managed lane에서 process
telemetry가 막힌다고 provider 또는 retrieval failure라고 해석하지 않는다. 결과
artifact를 읽을 수 있으면 읽기 전용 관측으로 진행하고, provider/MCP 실행 자체가
불가능하면 `BLOCKED`로 기록하고 종료한다.

## 8. 완료 정의

이 세션의 완료는 아래 둘 중 하나다.

1. preflight PASS, 96-cell confirm complete, confirm score PASS, 그리고 새로운
   상태 handoff가 artifact evidence와 backlink로 연결됨.
2. preflight 또는 runtime block을 변경 없이 재현하고, 원인과 보존된 artifacts를
   next-action handoff에 기록함.

둘 다 아닌 상태에서 code 수정, model 교체, fixture 추가, screen 재실행, held-out
부분 score 계산을 시작하지 않는다.
