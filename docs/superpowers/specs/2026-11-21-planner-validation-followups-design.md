# 플래닝 검수 보완 설계 (PR #40 후속)

## 목적

PR #40(검수를 오디오 근거로 판단)은 "검증되지 않은 소스는 GPU 처리에서 제외한다"는 규칙을 추가했다. 리뷰에서 이 규칙이 일부 경로에서 지켜지지 않거나, 반대로 지나치게 적용되는 문제를 찾았다. 이 문서는 그 문제들과, 기존 코드부터 있던 계획·검수 흐름의 구조 문제를 함께 고친다.

- 이 PR에서 생긴 문제: 오디오 크기 제한 없음, 분리 단계가 문제 종류를 구분하지 않음, 오디오를 못 받는 설정에서 모든 소스 폐기, 빈 계획 안내 없음.
- 기존 코드부터 있던 문제: 형식 문제가 하나라도 있으면 검수 없이 목록 전체를 재계획함, 건너뛴 소스가 화면에 보이지 않음.

## 목표

1. 검수 모델의 능력에 맞는 검수 방식을 쓴다. 오디오를 받을 수 있으면 오디오 검수, 받을 수 없으면 시각 검수. 두 방식을 대등하게 지원한다.
2. 계획과 검수를 소스 단위로 처리한다. 검수를 통과한 소스는 확정하고, 문제가 있는 소스만 재계획한다.
3. 검수 문제가 아닌 이유로 소스를 폐기하지 않는다.
4. 사용자가 어떤 소스가 왜 빠졌는지 알 수 있게 한다.

## 비목표

- 검수 정확도 향상, 프롬프트 튜닝, 유료 API 평가 실행.
- 긴 오디오를 여러 요청으로 나눠 검수하는 기능 (한계로 표시만 한다).
- 확정된 소스를 플래너가 이름만 바꿔 다시 내는 경우의 의미상 중복 제거.
- 건너뛴 소스를 트랙 목록에서 다시 시도하는 기능.

## 반목표 (이렇게 되면 실패)

- 오디오를 받을 수 있는 설정에서 화면에만 보이는 소리를 다시 승인하게 됨 (PR #40의 목적을 되돌림).
- 확정된 소스가 다음 라운드에서 다시 검수되거나, 빠지거나, 사용자 편집(keep, gain 등)을 잃음.
- 검수 모델 오류로 작업 전체가 실패함.

## 제약

- 유료 API, GPU를 쓰지 않는다. 검증은 단위 테스트와 stub 실행으로 한다.
- 도구 함수 시그니처 `plan(video, audio, duration, feedback)`, `validate_plan(video, audio, plans)`는 바꾸지 않는다. 요청별 정보는 PR #40의 `planning_scope`(ContextVar)로 전달한다.
- `contracts.py`는 바꾸지 않는다. `graph.py`, `settings.py`는 핵심 파일이므로 @Zero-woo 리뷰가 필요하다.
- PR #40이 테스트로 정한 동작 중 이 설계가 바꾸는 것은 PR 설명에 이유와 함께 적는다.
- `tests/`에는 ruff format을 적용하지 않는다.

## 접근 방식

### 검수 방식 선택
- **선택한 방식: 능력 기반 두 방식.** 검수 모델이 오디오를 받을 수 있는지를 설정으로 명시하고, 그에 맞는 입력·프롬프트·판단 규칙을 쓴다.
- 고려한 다른 방식: (a) 오디오를 못 받으면 폐기(현재 PR #40) — 설정에 따라 결과가 비어 쓸 수 없음. (b) 오디오를 못 받으면 작업 실패 — 흐름 코드가 도구 설정을 알아야 하고 stub 모드와 충돌.

### 재계획 단위
- **선택한 방식: 소스 단위 확정.** 형식 정상 → 검수 → 통과 시 확정. 문제 소스만 재계획.
- 고려한 다른 방식: (a) 현재 방식(형식 문제가 있으면 목록 전체 재계획) — 잘 뽑은 소스를 버리고, 검수 결과가 늦게 나와 고칠 기회가 없음. (b) 마지막 라운드에서만 형식 정상 소스 검수 — 구멍은 막지만 재계획 구조 문제는 남음.

## 설계

### 1. 검수 방식 (`settings.py`, `tools/planning/real.py`, `tools/planning/prompts.py`)

**방식 선택**
- 새 설정 `validator_audio: bool | None = None` (`AUDYSSEY_VALIDATOR_AUDIO`). 값이 있으면 그 값을, 없으면 기존 기준(`input == "video" and video_audio`)을 쓴다.
- `hears = request.audio_available and validator_audio`.

**오디오 검수 (hears가 참)**
- PR #40 동작을 유지한다. 분리는 "실제로 들리는가", 생성은 "장면에 어울리는가".
- 오디오 전송: `validator_audio_only`가 참이거나 엔드포인트가 영상에 오디오를 실을 수 없으면(`not _hears(endpoint)`) WAV를 보낸다. 그 외에는 오디오가 실린 영상 클립을 보낸다.

**시각 검수 (hears가 거짓)**
- 분리 작업:
  - 음악·배경음(`kind in {"music", "ambience"}`)과 화면 밖 소리(`visual_hint is None`)는 검수 모델을 부르지 않고 통과시킨다. 정보용 문제 `PlanIssue(kind="not_validated")`를 붙인다 (아래 "문제 종류" 참고).
  - 나머지는 시각 검수 프롬프트로 검수한다. 판단 기준은 PR #40 이전 프롬프트와 같다: 소스가 말하는 소리를 내는 객체(같은 종류의 사람·동물·물건) 또는 그 행동이 대상 구간 화면에 보이면 통과, 다른 것이거나 없으면 탈락. 보이는 것을 reason에 적는다.
  - 출력은 PR #40 형식(status, evidence, reason). 시각 검수에서는 evidence가 `visual`이면 통과를 인정한다. evidence가 `audio`/`audio_visual`이면 불확실로 처리한다 (못 듣는 모델이 소리를 주장).
- 생성 작업: 현재 동작 유지.
- 시각 검수 프롬프트는 `prompts.py`에 `validator_prompt`의 분기로 추가하고 `VERSION`을 올린다.

**변하지 않는 것**
- 응답이 두 번 깨지면 `validation_error`.
- 분리 작업인데 요청에 오디오가 없는 경우(`audio_available` 거짓): 앱에서는 무음 영상이 생성으로 바뀌므로 도달하지 않는다. 평가 데이터용으로 `validation_unavailable`을 유지한다.

### 2. 오디오 크기 (`real.py`)
- WAV를 만들기 전에 48 kHz → 16 kHz로 낮춘다 (`scipy.signal.resample_poly(data, 1, 3, axis=0)`, 스테레오 유지). WAV 헤더의 샘플레이트도 16000.
- base64 크기 합계가 `_MAX_INLINE_B64`를 넘으면 그 소스는 시각 검수로 처리한다 (위 시각 검수 규칙을 그대로 적용). 약 3.5분이 한계이며 `ponytail:` 주석으로 남긴다.

### 3. 소스 단위 계획·검수 흐름 (`graph.py`, `prompts.py`)

**상태**
- `AnalysisState`에 `accepted: list[str] = []` (확정된 소스 이름)를 추가한다. 그래프 내부 상태이며 `contracts.py`는 바꾸지 않는다.
- `PlanningRequest`(PR #40의 ContextVar)에 `accepted: tuple[SourcePlan, ...] = ()`를 추가한다.

**계획 단계**
1. `planning_scope(..., accepted=확정된 소스의 plan)`로 플래너를 부른다. 피드백은 직전 라운드의 문제 목록(정보용 제외).
2. 플래너 출력 중 확정된 이름과 같은 소스는 버린다.
3. 남은 출력에 `check_plans`(형식 검사)를 한다.
4. `job.sources` = 확정된 소스(기존 `Source` 객체 그대로, 순서 유지) + 새 소스. 새 소스는 기존처럼 이름이 같은 이전 `Source`가 있으면 그 객체를 이어받는다(사용자 편집 유지). id는 지금처럼 순서대로 다시 매긴다.
5. `job.sources`가 비면 계획 단계 상태를 `warning`, 메시지 "No sources proposed"로 표시한다.

**검수 단계**
1. 이번 라운드 새 소스 중 형식 문제가 없는 것만 `validate_plan`에 보낸다. 확정된 소스는 보내지 않는다. 형식 문제가 있어도 다른 소스의 검수는 건너뛰지 않는다 (기존 `state.issues or validate_plan(...)` 제거).
2. 위치 찾기(`visual_prompt`일 때)도 새 소스에만 한다.
3. 문제 목록 = 형식 문제 + 검수 문제 + 위치 찾기 문제 + 정보용 문제.
4. 차단 문제(아래)가 없는 새 소스를 `accepted`에 추가한다.
5. `job.plan_issues`에 문제 목록을 저장한다. 검수 단계 메시지에는 정보용 문제(`not_validated`)도 표시한다.

**재계획 조건**
- 재계획 대상 문제(정보용 제외)가 있고 `round < max_plan_rounds`이면 계획 단계로 돌아간다.

**플래너 지시 (`prompts.py`)**
- 요청 컨텍스트에 `accepted_sources`(name, kind, description, spans)를 넣는다.
- 지시 추가: 확정된 소스는 최종이므로 다시 내지 말 것. 피드백에 나온 소스의 수정안과 아직 없는 소스만 낼 것. 빈 목록도 유효.

**문제 종류와 처리**

| 종류 | 재계획 대상 | 분리 단계에서 건너뜀 | 확정 막음 |
|---|---|---|---|
| `empty_description`, `span_out_of_range` | 예 | 예 | 예 |
| `not_found`, `validation_uncertain`, `validation_error`, `unsupported_source`, `validation_unavailable` | 예 | 예 | 예 |
| `visual_hint_not_found` | 예 | **아니오** (텍스트 설명으로 분리) | 예 (위치를 고칠 기회를 줌) |
| `not_validated` (정보용) | 아니오 | 아니오 | 아니오 |

### 4. 분리 단계 (`graph.py`)
- 소스에 붙은 문제 중 "분리 단계에서 건너뜀"이 예인 것이 있으면 건너뛴다. `visual_hint_not_found`, `not_validated`는 건너뛰지 않는다.

### 5. 화면 (`ui/index.html`)
- 트랙 목록 위에 안내 한 줄: "검수를 통과하지 못해 건너뛴 소스 N개: 이름 — 사유, …". 대상은 `status == "skipped"`이고 `job.plan_issues`에 이름이 있는 소스. 사유는 서버 메시지 그대로.
- 대사를 생성하지 않아 건너뛴 소스는 `plan_issues`에 없으므로 기존처럼 숨는다.

## 바뀌는 PR #40 테스트
- `test_separation_music_and_ambience_also_require_audio` → 시각 검수에서 음악·배경음은 `not_validated`로 통과.
- `test_separation_without_audio_is_unverified_without_model_call` → 시각 검수 프롬프트로 모델 호출.
- `test_visual_evidence_does_not_approve_separation` → 오디오 검수에서만 유지, 시각 검수에서는 시각 근거로 통과.
- 오디오 WAV를 48 kHz로 가정한 테스트 → 16 kHz.
- `test_analyze_runs_both_validation_loops`, `test_plan_round_limit_warns`, `test_hint_not_found_triggers_replan`, `test_edit_during_planning_survives_replan`은 새 흐름에서도 통과해야 한다 (기대값이 흐름 변경으로 달라지면 이유를 적고 고친다).

## 설계자가 정한 세부 사항 (빌더 점검 질문에 대한 답)
- **`validator_audio` 값의 의미:** 사용자가 "이 검수 모델은 오디오 입력을 받는다"고 선언하는 값으로 보고 그대로 따른다. 값이 참이면 `input` 설정과 상관없이 WAV를 보낸다. 엔드포인트 능력을 별도로 확인하지 않는다. 값이 없을 때만 `_hears(endpoint)`를 쓴다.
- **`accepted` 초기화:** 분석을 실행할 때마다 `prepare`에서 빈 목록으로 시작한다. 이전 실행의 `Source` 객체는 지금처럼 이름이 같으면 이어받는다.
- **확정된 소스의 plan:** 플래너에 넘기는 확정 소스는 `job.sources`의 현재 `Source.plan`에서 읽는다. 사용자 편집(Drop은 `keep=False`일 뿐 삭제가 아님)은 그대로 유지된다.
- **검수 단계 상태:** 차단 문제가 있을 때만 `warning`으로 표시한다. 정보용 문제(`not_validated`)만 있으면 `done`으로 두고 메시지에만 적는다. 라운드 제한 경고도 차단 문제 기준으로 판단한다.
- **오디오가 너무 길 때의 대체 처리:** 해당 소스는 시각 검수와 완전히 같게 처리한다. 즉 시스템 프롬프트, `audio_available` 필드, evidence 판정, 음악·배경음·화면 밖 소리 통과 규칙을 모두 시각 검수 기준으로 적용한다. `validation_unavailable`(요청에 오디오가 없음)과는 별개다.
- **재계획에서 플래너가 다시 내지 않은 실패 소스:** 목록에서 제거한다. 플래너가 검수 피드백을 보고 그 소스가 없다고 판단해 뺀 것이므로 올바른 결과다. 경위는 이전 라운드 검수 단계 메시지와 실행 기록(trace)에 남는다. 화면 안내는 마지막 라운드까지 문제가 남아 건너뛴 소스만 대상으로 한다.
- **stub:** 바꾸지 않는다. 새 흐름은 가짜 도구를 쓰는 단위 테스트로 검증한다.

## 빌더에게 맡기는 것
- 함수·변수 이름, 차단/재계획 종류 집합을 둘 위치.
- 시각 검수 프롬프트의 정확한 영어 문장 (판단 기준은 위와 같아야 함).
- 화면 안내 줄의 스타일 (기존 경고 스타일 재사용).
