# 세션 회고 4차 — 기계화와 검증 계층 (2026-08-17 ~ 08-22)

직전 로그
[`session_retrospective_20260817_ranking_defects_and_self_testing_review.md`](session_retrospective_20260817_ranking_defects_and_self_testing_review.md)가
**I172**에서 끝났다. 이 로그는 **I173부터**. 반복 패턴은 누적 횟수를 갱신한다.

구간: `055b237`(mutation 도구 대조) ~ `3d50800`(F7 error_code). 주제는 하나로
요약된다 — **산문 규율을 실행 가능한 기제로 옮기고, 그 기제 자신을 같은
방법으로 검증했다.** 그 과정에서 기제가 나를 여섯 번 잡았다.

권한·도구 차이가 이 구간의 사건들에 직접 개입했다(§0). 이 문서의 이슈 중
일부는 Codex/다른 세션이었다면 발생 형태가 달랐거나 발생하지 않았다.

## (0) 세션 간 권한·도구 차이가 만든 사건들

이전 회고들이 기록한 차이(Codex의 AF_UNIX bind 권한이 6개 테스트를 가름,
Desktop GUI 세션의 도구 부재)에 이번 구간의 신규 관측을 더한다:

1. **같은 세션 안에서 권한이 조여졌다.** 세션 초에는 독립 저장소
   `vault-backlinks-mcp`에 `git -C` 커밋이 허용됐다(`fe0b706`, `95aefdb` 등
   실재). 후반에는 동일 작업이 worktree 격리로 전면 거부됐다(Edit·`git -C`
   모두). 결과: subtree가 정본으로 승격되고 독립 저장소는 뒤처짐(§I194).
   **권한은 세션 속성이 아니라 시점 속성이다.** handoff에 "무엇이 되는지"를
   적을 때 언제 확인했는지도 적어야 한다.
2. **org 지출 한도가 검증 차선을 두 번 끊었다.** 적대 검증 1라운드 verify
   10 중 9 사망(I176), 조사 workflow 2라운드 4레인 중 2레인+합성 사망.
   주 에이전트 차선과 subagent 차선의 예산이 별도로 고갈된다. 사용자
   지시로 조사는 사용자의 조사 에이전트로 이관됐다 — **차선별 토큰 경제가
   다르므로 작업 배치가 권한 배치다.**
3. **auto mode 전환이 도구 사용 형태를 바꿨다** (Bash 우선 ↔ 전용 도구).
   같은 편집이 어떤 모드에서는 sed로, 어떤 모드에서는 Edit로 이뤄져 격리
   가드에 다르게 걸렸다.
4. **모델 전환(Opus 5 → Fable 5)이 구간 중 있었고**, 커밋 trailer로 추적
   가능하다. 판정 방식 차이는 관측되지 않았으나 회고가 기록할 사실이다.
5. **haiku subagent는 zero-context가 강점 차이다** — 독립 테스트(I189)의
   가치가 정확히 "이 세션의 맥락이 없음"에서 나왔다. 권한이 적은 세션이
   더 나은 측정 도구가 되는 경우가 있다.

## (1) 신규 이슈 I173~I194

### A. 실제 코드·테스트 결함 (도구 또는 검증이 찾음)

- **I173** `retriever.py:37` `graph_seed_k` 검증에 목격자 없음 — mutatest가
  지적, poison으로 확정(분기를 `if False:`로 죽여도 131 passed). **도구가
  처음으로 찾은 P1**이며 새 하위 유형: 도달 가능하지만 목격자 없음.
- **I174** 목격자 레지스트리의 완전성 정규식 `[A-Z_]+`가 자릿수 포함 코드를
  못 봄 — 메타가드가 바로 자기 대상에 공허.
- **I175** F2: fallback witness가 import-시점 환경에 의존. 단독 실행
  FAILED / 전체 스위트 PASSED. 원인은 `test_contracts.py`의
  `monkeypatch.delenv` 후 `importlib.reload` — **monkeypatch는 reload를
  되돌릴 수 없어** 세션 내내 모듈이 재구성된 채 남아 뒤 테스트의 환경
  의존을 가림.
- **I180** 내 selftest-harness의 `ORDER_DEPENDENT`가 주변 환경에서 한 번만
  검사기를 돌려, 결함 생존 리비전에서 `passed`를 반환 — **하네스 자신의
  위양성 음성.**
- **I181** 순서 검사기의 outcome 정규식이 ANSI 색상에 전멸 → "clean"을
  잘못된 이유로 보고할 뻔함. `--color=no`가 load-bearing.
- **I185** ITEMWISE 검사가 세션 job 디렉터리의 venv 경로에 고정 — job은
  세션과 함께 삭제되므로 다음 세션에서 조용히 깨질 내구성 결함.
- **I186** 내 separation 테스트가 내 버그 2개를 잡음: fixture 테스트 수
  오산(3을 2로), 실행 불가 인터프리터에서 하네스가 크래시해 JSON을 아예
  안 냄(OSError → did_not_run으로 수리).
- **I190** 분류 순서 고정 테스트의 fixture가 공허 — `"No such file or
  directory"`는 `"not found"` 매칭에 안 걸려 순서를 뒤집어도 통과.
  **poison test가 poison test의 재료(fixture)를 잡은 첫 사례.** 적대적
  철자(`"command not found"`)로 교체 후 판별력 확보.
- **I191** F4 확정·수리: `or truncated`를 지워도 92 passed. 원인은
  표현식의 `review_checks`가 TRUNCATED append **이전에** 평가됨.
- **I192** F8 재검증이 판정을 바꿈: 제안된 트리거(symlink 순환
  RuntimeError)는 **이 인터프리터에서 발생하지 않음**(3.13 non-strict
  resolve 실측). mock 없는 진짜 세계(상대경로 root + 삭제된 cwd →
  FileNotFoundError)를 실측으로 찾아 목격자화. 코드 변경 없음 — 확장
  제안은 목격자를 만들 수 없는 견고성 연극이라 기각.
- **I193** F7 확정·수리: 거부 채널(검증 오류 6곳)이 코드 없이 나가
  레지스트리가 구조적으로 못 봄 → `error_code` 의무화 + 오류 코드
  레지스트리.

### B. 판정·과정 결함 (내가 저지름)

- **I176** 적대 검증 1라운드: verify 9/10 사망 상태에서 집계가
  `{"confirmed":[1], "refuted":[]}` — **"반박 시도가 완료된 것 없음"이
  "반박된 것 없음"으로 읽히는 형식.** 이후 `CHECK_DID_NOT_RUN` 계약의
  존재 이유가 됨.
- **I177** 죽은 verify 에이전트들이 **실제 운영 저장소에**
  `review_required = False  # BROKEN`을 남김. 내 workflow가 calibration에는
  사본을 쓰면서 verify에는 같은 규율을 적용하지 않았다. 2라운드는
  에이전트별 사본으로 오염 0.
- **I178** verify 에이전트의 CONFIRMED가 `-k`로 좁힌 실행 근거 — 전체
  스위트는 그 회귀를 이미 잡음. "이 테스트가 안 잡는다" ≠ "스위트가 안
  잡는다".
- **I179** F2 verify의 근거가 null mutation(기본 환경에서 항진명제 절
  제거) — 판정은 맞았으나 기제가 틀림. 직접 이분탐색으로 진짜 기제(reload
  누출)를 찾음.
- **I182** 문헌 주장을 "논문 접근 없음"으로 미검증 처리 — **접근을
  시도하지 않은 채 제약으로 적음.** 웹 조회 도구가 있었고 SARIF는 2회
  조회로 확정됐다.
- **I183** cwd 함정 3회 재발(사본 디렉터리 잔류로 오보 1회, 다른 저장소
  커밋 시도 1회, subtree cwd 가드 거부 1회). HANDOFF §6(d)에 **직접 적은
  뒤에도** 재발 — 산문이 왜 실패하는지의 자기 사례.
- **I184** 이미 있는 정본(`HARNESS_KNOWHOW.md` §B4a,
  `test_guard_negative_coverage.py`)의 열등한 재발명 — CLAUDE.md 검색
  순서를 어기고 수동 grep을 먼저 함. 도구를 돌리자 첫 질의 상위 8건에 정본
  둘이 들어옴. worktree 분산은 원인이 아니었다(8곳 사본은 한 저장소의
  체크아웃).

### C. 외부 권고의 정정 (실측이 뒤집음)

- **I187** "pytest-randomly 채택" 권고에 조건 누락 — 적중률 57%(23/40
  seed)이므로 seed 고정 없이는 결정적 검사기 대비 퇴행. 고정하면 우월.
- **I188** "detect-test-pollution smoke test 후 VENDOR" 권고가 적용성에서
  기각 — 도구는 단독통과·스위트실패(victim)만 다루고 우리 결함은
  정반대(brittle). **조사자가 brittle 용어를 나열하고도 대입하지 않음.**
  호환성 확인 ≠ 적용성 확인.
- **I189** 집계 경고 오독(haiku 독립 테스트 발견): "probes unavailable or
  failed: 18"이 CLI 다운으로 읽혔으나 실측은 CLI 건강 + 점 디렉터리
  18건 비색인. 문구가 아니라 **타입 부재**가 원인.

### D. 환경·내구성

- **I194** 이중 존재 분기: worktree 격리 강화(§0-1)로 독립 저장소가 subtree
  대비 4커밋 뒤(0e45caf, 898f57b, dd51896, 3d50800 미반영). 따라잡기 명령은
  HANDOFF §3에 기록.

## (2) 반복 재현 횟수가 증가한 이슈

### P1 — 공허한 가드/테스트 (17건 → **26건**)

이번 구간 +9: I173(#18), 집계 경고의 negative witness 부재(#19, I189의
원인), I174(#20), I175(#21), I180(#22), I190(#23), I191/F4(#24),
I192/F8의 미목격 except 분기(#25), I193/F7의 미등록 거부 채널(#26).

질적 변화 둘: (a) #18은 **도구가** 찾은 첫 사례, #23은 **poison test가
poison 재료를** 잡은 첫 사례 — 발견 채널이 사람에서 기제로 이동 중.
(b) 2분류가 부족함이 실증되어 3분류 채택: `UNREACHABLE` /
`REACHABLE_NOT_EXERCISED`(#18) / `EXECUTED_NOT_CHECKED`(F5, #19).

### P3 — 자기/외부 보고를 검증 없이 신뢰할 뻔함 (+4)

I178, I179(하위 에이전트 CONFIRMED 2건), I187, I188(외부 조사 권고 2건).
네 건 모두 **재현이 판정을 바꾸거나 조건을 붙였다.** 5차 검증 중 2건이
결론을 바꾼 직전 구간 비율이 유지된다 — 재현 없는 채택은 여전히 불가.

### P4 — 게이트가 게이트를 가림 (2건 → **4건**)

+2: I176(집계 형식이 9 사망을 깨끗한 결과로 위장 — calibration 게이트
통과가 뒤 단계 붕괴를 가림), I175(한 테스트의 reload cleanup이 다른
테스트의 환경 의존을 가림 — 그래서 F2가 스위트에서 안 보였다).

### P-선행사소실 — 이미 있는 것의 재발명 (2건 → **3건**)

I184. 원인 규명이 진전: 분산이 아니라 **검색 순서 위반**이 주원인, 실재
간극은 저장소 간(evidence-evaluator ↔ concept-gate-taxonomy)이며 유일한
교량이 검색 도구다.

### P-cwd — Bash cwd 잔류 (신규 패턴, 이번 구간 3건)

I183. 산문 경고(HANDOFF §6(d)) 후에도 재발했으므로 산문으로는 안 닫힌다.
후보 기제: 테스트/커밋 명령에 `cd <절대경로> &&`를 강제하는 습관은 이미
후반부에 적용 — 기계화(예: hook) 여부는 미결.

## (3)(4) 해결 근거가 있는 이슈와 해결 유무

| 이슈 | 해결 | 근거 (전부 재현 가능) |
|---|---|---|
| I173 | ✅ `26024e7` | 분기별 poison: 각 분기를 죽이면 자기 케이스만 실패(3/3/2) |
| I174 | ✅ `95aefdb` → AST로 대체(`fe0b706`) | poison 4종; AST 전환 시 동작 불변(11개=11개) 실측 |
| I175 | ✅ `5398501` + reload 수리 `0e45caf` | env=0 단독 실행 PASSED; 회귀 가드가 기본 환경에서 수리 제거를 잡음 |
| I176 | ✅ 하네스 계약 | `CHECK_DID_NOT_RUN`이 complete 차단; separation 케이스가 skip-as-pass poison을 잡음 |
| I177 | ✅ 사본 시딩 | 2라운드 오염 0 (clean tree assert 후 시딩) |
| I178/I179 | ✅ 스키마 강제 | `full_suite_command`·`registry_gap/suite_gap` 분리 → 2라운드 `suspect_method: []` |
| I180 | ✅ `b4712c3` | 결함 생존 리비전 before/after: passed → 정확한 테스트 지목 |
| I181 | ✅ | `--color=no` + 파싱 실패를 exit 2로 |
| I182 | ✅ `323588a` | SARIF 스키마 원문 인용으로 확정; 교훈 문서화 |
| I183 | ⚠️ 부분 | 습관 적용 중, 기제 미구현 |
| I184 | ✅ 재사용 완료 | AST·KNOWN_UNPROVEN 도입(`fe0b706`, `94452f5`); 회고에 원인 기록 |
| I185 | ✅ `d1b6101` | 내구 venv + 3단계 발견; env var 없이 155 passed |
| I186 | ✅ 같은 커밋 | 개수 대신 "실패 없음" 단정; OSError→did_not_run |
| I187/I188 | ✅ 문서 + 하네스 | 고정 seed {2,3,4,5,8}로 `ORDER_DEPENDENT_ITEMWISE`; d-t-p는 REJECT 기록 |
| I189 | ✅ `1873e52` | 타입 분류 + 코드화; host lane에서 오독 세계가 정확히 말함 |
| I190 | ✅ 같은 커밋 | 적대 철자 fixture; poison 상태에서 3 failed |
| I191 | ✅ `898f57b` | poison 트리 red → revert green |
| I192 | ✅ `dd51896` | 살아남던 mutation이 목격자 1개에 죽음(1 failed, 94 passed) |
| I193 | ✅ `3d50800` | TDD red 10 → green 108; poison 2종 |
| I194 | ⚠️ 미해결 | 격리 세션에서는 불가; 따라잡기 명령 기록됨 |

미해결 잔여: F5(payload 미검증 — `EXECUTED_NOT_CHECKED`의 대표), backlinks
도구의 코드화, C4 recall, mutation survivor 잔여, I183 기계화, I194 동기화.

## (5) 해결 근거가 있고 반복된 이슈의 문제 정의

### P1 (정제됨)

> 검사의 존재와 검사의 증명력은 별개 사실이며, 긍정 테스트는 원리적으로
> 둘을 구별하지 못한다(측정 채널 부재). 이번 구간의 추가: **공허함은 검사
> 본체만이 아니라 그 재료(fixture)·집계(경고 문구)·완전성 검사(정규식)
> 어디서든 생기며**, 세 하위 유형(도달불가/미발동/미관측)은 처방이 다르다.

### P3 (정제됨)

> 판정의 신뢰도는 판정자가 아니라 **검증 방법의 종류**에 붙는다.
> `ran_it`/`quoted_source`/`inferred`는 다른 등급이고, 도구 권고는
> 호환성(설치됨)과 적용성(이 결함에 대고 돌림)을 분리해야 한다. 스키마
> 필드로 강제하면 지켜지고 산문으로 요구하면 안 지켜진다(실측).

### P4 (정제됨)

> 개별 단위의 계약이 건전해도 **집계 계층이 별도 계약을 갖지 않으면**
> 붕괴가 깨끗한 결과로 위장된다. "실행되지 않은 검사는 통과한 검사가
> 아니다"는 단위가 아니라 집계의 규칙이다.

### P-선행사소실

> 재발명의 주 원인은 자료의 분산이 아니라 **검색 절차 생략**이다. 정본이
> 다른 저장소에 있을 때 유일한 교량은 검색 도구이며, 그것을 건너뛰는 것은
> 교량을 철거하는 것과 같다.

## (6) 해결 유무 판단에 쓴 가설과 검증 방식

1. **poison test 5단계** (수정마다): 통과 확인 → 정확한 mutation → FAIL
   확인 → revert → 통과 확인. 이번 구간 신규 규칙: **poison이 통과하면
   테스트가 아니라 fixture를 의심하라**(I190).
2. **결함 생존 리비전 원칙**: 수리가 검출기의 증거를 파괴할 수 있으므로
   (F2의 finally-reload가 가림 자체를 제거), 검출기의 능력은
   `git archive <수정 전 SHA>`로 꺼낸 트리에서 증명한다.
3. **환경 행렬**: 한 환경의 OK는 순서/환경 독립의 근거가 아니다. 기본 +
   `--env` 전부에서 돌린 것만 인정 (I180의 수리 원리).
4. **결정적 재현 대조**: 같은 질의·파라미터의 재실행이 digest까지 일치해야
   보고를 채택 (haiku 독립 테스트 채점).
5. **calibration 게이트**: 심은 결함 K/N 미검출이면 실제 판정 거부.
6. **TDD red 확인**: 새 테스트는 결함 존재 상태에서 실패하는 것을 먼저
   보여야 한다 (F4는 poison 트리에서 red, F7은 미구현 상태에서 red 10).
7. **API 동작은 문서가 아니라 실측**: symlink 순환 resolve가 안 던지는 것,
   삭제된 cwd의 상대경로 resolve가 던지는 것 — 둘 다 이 인터프리터에서
   직접 측정 후에만 설계에 반영 (I192).

## (7) 문제의 해결 방법 (구체적)

### P1 → 목격자 레지스트리 3종 + 자기검사 하네스

- 코드 채널별 레지스트리: review_checks 가드
  (`test_guard_witness.py`, 11코드), 검색 review 코드
  (`test_search_review_check_witness.py`, 3코드), 거부 error_code
  (`test_error_code_witness.py`, 7코드). 전부 발동/침묵 쌍 + AST 완전성
  양방향 + `KNOWN_UNPROVEN`(양방향 staleness + 자기 음성 테스트).
- 리터럴 강제: 코드는 call site의 문자열 리터럴이어야 AST에 걸린다 —
  계산식으로 쓰면 완전성 검사가 실패한다(poison으로 확인).
- `selftest-harness/`: 검사 6종, `CHECK_DID_NOT_RUN`이 complete 차단,
  separation 12케이스, poison 4종. `--python` 자동 발견.

### P3 → 스키마 필드

`verification_method`(4값)·`applicability_tested`·`full_suite_command`·
`registry_gap`/`suite_gap` 분리·`reverted_clean`. 프롬프트 훈계가 아니라
**반환 타입**으로 강제 — 1라운드에서 어긴 규율이 2라운드에서 8/8 준수됨.

### P4 → 집계 계약

`checks_run`/`checks_skipped` 분리 보고, skip은 `CHECK_DID_NOT_RUN`으로
가시화, `refuted: []`류의 형식은 "완료된 시도 수"를 함께 싣지 않으면 금지.
workflow 반환값에 `verify_died` 카운트(1라운드 회고의 미구현 항목)는
`agents_error` 필드가 사실상 대체 — 그것을 읽는 규율이 하네스의
`CHECK_DID_NOT_RUN`으로 기계화됐다.

### P-선행사소실 → 검색 선행을 절차의 1단계로

이번 구간 후반의 모든 구현(F4/F8/F7, typed codes)은 vault_search를 먼저
돌리고 시작했다. GitHub은 workspace에 없을 때만, 그리고 도구는 설치가
아니라 **실제 결함에 대고** 판정한다.

### P-cwd → 미결

절대경로 `cd` 습관은 적용 중이나 기제가 아니다. 후보: 테스트 실행 명령을
스크립트화(하네스가 이미 `cwd=repo`를 명시적으로 받는 것이 그 방향).

## 이 문서가 주장하지 않는 것

- P1 26건이 전수라는 주장 — 발견 채널이 늘었을 뿐 미발견 잔여는 정의상
  알 수 없다.
- 수치는 전부 host lane, 각 1회 측정. seed 적중률은 해당 결함·트리·seed
  집합에 국한된다.
- I192의 "RuntimeError 불발생"은 Python 3.13.13/macOS 실측이다. 다른
  버전·플랫폼에서는 다를 수 있고, 그래서 가드 자체(except OSError)는
  유지했다.
