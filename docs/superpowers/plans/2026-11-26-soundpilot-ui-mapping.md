# SoundPilot web UI -> Audyssey 이식 분석

대상 ref: SoundPilot `~/v2a_inspect` `fork/main` (0838ad7), Audyssey `~/audyssey` `origin/main` (808555b). 두 저장소는 읽기만 했고 수정하지 않았습니다.
인용 형식은 `파일:줄`이며 SoundPilot 경로는 `web/src/...` 또는 `src/v2a_inspect/ui/...`, Audyssey 경로는 `src/audyssey/...` 입니다.
확인하지 못한 항목은 **UNVERIFIED**로 표시했습니다.

---

## 0. 먼저 알아야 할 점 (요약)

1. SoundPilot UI는 "전역 VideoAsset 1개 + `/events` SSE + 프레임 단위 timeline" 구조이고, Audyssey는 "job 여러 개 + job별 SSE + 초 단위 Span" 구조입니다. 데이터 모델이 다르므로 SoundPilot의 `types.ts`, `api.ts`, `App.tsx`, `VideoEditor.tsx`는 그대로 쓸 수 없고 어댑터(Job -> SoundPilot view model)를 새로 만들어야 합니다.
2. SoundPilot 기능 중 contracts.py 변경 없이 이식할 수 있는 것이 많습니다: 상단 바/상태/진행, 모드 선택(시작 시), 영상 열기, 프로젝트 목록(축소판), stage + hint box 강조, 재생/solo/scrub, waveform dB 스케일, add track(`add_source`), span 편집 후 재분리(`reseparate.spans`), 설명 편집 재생성, residual 토글, 음량(0-200%), export.
3. Audyssey에 없는 기능은 clip trim/move, trim-to-spans, track 삭제, 음량 400%, span 편집의 생성 반영, 프로젝트 이름/삭제/bundle, SAM3 tracking mask 입니다. 앞의 네 가지는 `contracts.py` 변경이 필요하며 CODEOWNERS(`.github/CODEOWNERS`)상 @gwpark0741 또는 @Zero-woo 승인과 팀 합의가 필요합니다(`docs/contributing.md` "코드 규칙").
4. 빌드 통합에서 실제 함정이 두 가지 있습니다. (a) Audyssey `.gitignore`가 `*.json`과 `lib/`를 무시하므로 `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/src/lib/`가 커밋되지 않습니다(임시 저장소에서 `git check-ignore`로 확인함). (b) `tests/test_audyssey_api.py:233-238`이 `/` 응답에 `id="board"`와 "내보내기"가 들어 있는지 검사하므로 새 UI로 교체하면 이 테스트를 고쳐야 합니다.
5. 기존 `src/audyssey/ui/index.html`은 한국어, 밝은 테마, 외부 CDN 폰트를 쓰고 NL 편집 바(자연어 라우터)까지 있습니다. SoundPilot에는 NL 바가 없으므로 새 레이아웃에서 따로 자리를 정해야 합니다.

---

## 1. SoundPilot 기능 목록

### 1.1 구조와 데이터 흐름

- 상태 소스: `GET /api/asset-summary`(`routes.py:130`, payload `routes.py:948-982`)와 SSE `GET /events`(`routes.py:832-843`). `App.tsx:50-57`이 mount 시 summary를 읽고 `asset_update` 이벤트마다 다시 읽습니다. 응답이 뒤바뀌지 않도록 request counter를 둡니다(`App.tsx:59-66`).
- summary 응답 shape(`types.ts:7-20`): `{status: idle|running|complete|failed, stage, error, version, asset_version, updated_at, video{video_id, frame_count, fps, duration_sec, width, height}, timeline_rows[], audio_tracks[], audio_events[], track_targets{trackId: sceneTrackId[]}, track_target_fallbacks{}}`.
- 전체 asset: `GET /api/asset` -> `{...summary, asset: VideoAsset}`(`routes.py:109`, `routes.py:1031`). `VideoEditor.tsx:216-246`이 `state.version`이 바뀔 때마다 받아 `baseAsset`/`draftAsset`에 넣습니다.
- 모든 mutation은 `409 Pipeline is running`을 돌려주는 queue 방식입니다(예: `routes.py:272`). 응답은 `{status:"queued"}`이고 결과는 SSE로 옵니다. Audyssey의 `/commands`는 완료까지 응답을 막는 동기 방식입니다(4절 참고).
- 오류 문구: `lib/errors.ts`의 `errorDetail`(FastAPI `{"detail": ...}` 풀기), `failure(what, error, next)`, `trackFailureText`(`errors.ts:20-35`, "Audyssey tools server unreachable" 문구가 이미 들어 있음).

### 1.2 기능별 표

| # | 기능 | 컴포넌트 | API 호출 | 요청 / 응답 |
|---|---|---|---|---|
| 1 | 상단 바: 브랜드, "Original audio"/"Silent video" 배지 | `TopBar.tsx:82-85` | 없음(`baseAsset.has_audio`) | - |
| 2 | "Open video" 버튼, "Save bundle" 링크 | `TopBar.tsx:87-94` | `GET /api/bundle`(`routes.py:687`) | zip 다운로드(asset.json, bundle.json, files/**: `bundle.py:14-37`) |
| 3 | 상태줄 + 진행 막대. `stage` 문자열에서 `i/n`을 정규식으로 뽑아 진행률 표시, 없으면 indeterminate | `TopBar.tsx:25-60, 96-117` | summary의 `status`, `stage`, `error` | `stage`는 자유 문자열(`routes.py:486` 등 "planning separation") |
| 4 | 오디오 방식 선택 Generate/Separate(라디오). 원본 오디오가 없으면 Separate 비활성 + "No original audio to separate." | `TopBar.tsx:118-145`, `VideoEditor.tsx:733-750` | `POST /api/audio/mode` form `mode=generate|separate`(`api.ts:186`, `routes.py:460-490`) | `{status:"ok"|"queued"}`. separate 계획이 없으면 서버가 분리 계획을 먼저 돌립니다. 모드마다 timeline을 따로 보관(`asset.inactive_timeline`) |
| 5 | 주 실행 버튼 "Generate audio"/"Separate audio" | `TopBar.tsx:146-148`, `VideoEditor.tsx:752-769` | `POST /api/audio/generate` multipart `server_url?`, `asset?`(편집한 VideoAsset JSON)(`api.ts:111`, `routes.py:794-830`) | `{status:"queued"|"ignored"}`. 로컬 편집(span 이동/삭제)을 asset JSON으로 올려 반영 |
| 6 | Open video 대화상자(native `<dialog>`): 새 영상 분석, 저장된 bundle 불러오기, 최근 프로젝트, Advanced | `OpenVideoDialog.tsx:1-224` | 아래 7-12 | - |
| 7 | 새 영상 분석 "Run" | `OpenVideoDialog.tsx:96-111` | `POST /api/runs` multipart `video`, `work_dir?`, `server_url?`, `scene_threshold`, `max_keyframes_per_scene`(`api.ts:54`, `routes.py:584-620`) | `{status:"queued"}`. 서버가 project 디렉터리를 만들고 파이프라인 실행. 이전 asset은 즉시 비움 |
| 8 | bundle 불러오기 "Load" | `OpenVideoDialog.tsx:112-124` | `POST /api/bundle/import` multipart `bundle`, `work_dir?`(`api.ts:66`, `routes.py:702`) | `{status:"imported"}` |
| 9 | 최근 프로젝트 목록 | `OpenVideoDialog.tsx:125-167`, `lib/projects.ts` | `GET /api/projects`(`api.ts:77`, `routes.py:726`) | `ProjectSummary[]` `{id, name(업로드 파일명), created, updated, duration_sec, audio_mode, scenes, objects, tracks, has_preview, status: complete|running|failed}`(`types.ts:217-229`) |
| 10 | 프로젝트 열기 / 삭제(확인창) | `OpenVideoDialog.tsx:146-164` | `POST /api/projects/{id}/open`(`routes.py:732`), `DELETE /api/projects/{id}`(`routes.py:751`) | 실행 중이면 409 |
| 11 | Advanced: work dir, inference server URL, scene threshold, keyframes 수 | `OpenVideoDialog.tsx:168-207` | 7번 form 필드로 전달 | - |
| 12 | "Reset + rerun soundtrack", "Discard timeline edits", "Download edited JSON", "Download video (MP4)", "Clean workspace" | `OpenVideoDialog.tsx:208-222`, `VideoEditor.tsx:771-800` | `POST /api/sound-timeline/reset-run`(`routes.py:766`), `POST /api/asset/clean`(`routes.py:135`), MP4는 `GET /api/synthesized-video?asset_version=N`(`routes.py:158`) | JSON 다운로드는 클라이언트에서 Blob 생성 |
| 13 | Stage: `<video>`, 재생/일시정지, 프레임 슬라이더, 시간 표시 `x.xx s / y.yy s` | `Stage.tsx:57-143` | `GET /api/video`(원본) 또는 `/api/synthesized-video`(mix 완료본) | `VideoEditor.tsx:844-851`이 src를 파일 기준으로만 바꿔 재생 위치가 0으로 튀지 않게 함 |
| 14 | 선택한 track의 object mask 강조(SAM3), 선택 없으면 모든 object를 색별로 표시, "Highlighting X"/"X has no object mask" chip | `TrackingOverlay.tsx`, `Stage.tsx:92-138`, `VideoEditor.tsx:150-176` | `GET /api/tracks/window?start_frame&end_frame`(`api.ts:39`, `routes.py:534-555`) | `{version, start_frame, end_frame, tracks[{scene, track, scene_track_id, label, start_frame, end_frame, confidence, points[{frame_index, bbox_xyxy, confidence, mask_rle(COCO RLE)}]}]}`. ±300 프레임 window, 60프레임 여유(`lib/trackWindow.ts`). mask는 `lib/rle.ts`로 해독해 640x360 canvas에 칠함 |
| 15 | Timeline 눈금자 + playhead scrub | `Timeline.tsx:241-248, 357-398` | 없음 | pointer 위치 -> 프레임 |
| 16 | track lane: 이름, 상태(Done/Generating…/Queued/Failed), method 배지(Separated/SelVA w/ SelSync/ElevenLabs/TTS), 색 견본 | `Timeline.tsx:449-` , `lib/selection.ts:35-47, 82-90` | summary의 `track_status`(asset), `audio_tracks[]` | `AudioTrackArtifact{sound_track_id, track_label, track_type, path, duration_sec, event_count, waveform_peaks[], origin, seed, attempt, description, clip_path}`(`types.ts:67-80`) |
| 17 | lane별 Play(해당 stem을 현재 위치에서 재생), Solo 토글. 재생 중 Solo를 바꾸면 현재 프레임부터 다시 재생 | `Timeline.tsx:516-541`, `VideoEditor.tsx:391-478, 532-578` | `GET /api/audio/tracks/{id}?asset_version=N`(`routes.py:175`, clip 적용된 `playback_path`) | HTMLAudio 요소를 track별로 캐시하고 영상은 mute. 순수 함수 `transportAction`, `soloToggleAction`(`lib/selection.ts:92-105`) |
| 18 | waveform: server가 만든 `waveform_peaks`를 SVG polygon으로 그림 + gain 곱 | `Timeline.tsx:720-770, 809-834` | 서버 `_waveform_peaks`(`pipeline.py:1420-1442`): 768 bucket, 고정 dB 스케일(-60 dBFS -> 0, 0 dBFS -> 1) | 모든 track이 같은 dB 스케일 |
| 19 | span 박스(= sound event) 이동/양끝 resize 드래그, 박스 선택 후 Delete/Backspace 또는 x 버튼으로 삭제(track당 최소 1개). 변경은 로컬 pending | `Timeline.tsx:158-239, 570-640`, `lib/span.ts`, `lib/pendingEdits.ts`, `VideoEditor.tsx:584-618` | 서버 호출 없음. 적용은 14의 재생성 또는 trim에 `events` JSON으로 동봉 | `EventSpan{sound_event_id, start_frame, end_frame, deleted?}`(`pendingEdits.ts:16-20`) |
| 20 | 편집 모드 "Edit spans"/"Edit audio" | `Timeline.tsx:54-58, 359-380` | - | span 편집이 pending이면 audio 편집 비활성(`VideoEditor.tsx:71-86`) |
| 21 | Edit audio: clip trim(양끝)/move(본체) 드래그, 놓을 때 1회 commit | `Timeline.tsx:253-299, 720-770`, `lib/clip.ts` | `POST /api/audio/tracks/{id}/clip` JSON `{start, end, offset}`(`api.ts:209`, `routes.py:310-344`) | `{status:"queued", clip{start, end, offset}}`. 서버가 `clamp_clip` 후 `render_clip_wav`(5 ms fade)로 stem을 다시 만들고 preview 재생성(`audio_generation/clip.py`) |
| 22 | track별 음량 슬라이더 0-400%(gain 0-4, 더블클릭은 100% 복귀, 드래그 중 미리듣기, 놓을 때 commit) | `Timeline.tsx:770-807`, `lib/gain.ts`, `VideoEditor.tsx:493-498, 706-731` | `POST /api/audio/tracks/{id}/gain` JSON `{gain}`(0-4)(`api.ts:221`, `routes.py:346-366`) | `{status:"queued", gain}`. 브라우저 audio element는 1.0이 상한이라 미리듣기는 100%까지만 |
| 23 | Selected track 패널: 상태, method 배지, `Seed N`/`Attempt N`, 실패 메시지 + "Previous audio kept.", Description 편집, Model select(SelVA w/ SelSync/ElevenLabs/TTS/Separate), 주 버튼 라벨이 선택에 따라 "Regenerate track"/"Re-separate"/"Regenerate with X"/"Regenerate with new spans" | `SelectedTrackPanel.tsx:46-62, 148-` , `lib/selection.ts:49-73` | `POST /api/audio/tracks/{id}/regenerate` form `method=separate|generate|selsync`, `description?`, `seed?`, `model?=selsync|t2a|tts`, `events?`(JSON)(`api.ts:154`, `routes.py:258-308`) | `{status:"queued"}`. 422: speech 아닌 track에 tts, 원본 오디오 없이 separate |
| 24 | ElevenLabs/TTS track은 event별 Description, Spoken text, "Regenerate this span" | `SelectedTrackPanel.tsx:92-125` | `POST /api/audio/events/{id}/regenerate` form `description`, `spoken_text?`, `server_url?`(`api.ts:130`, `routes.py:230-256`) | - |
| 25 | "Trim to spans"(span 밖 오디오 무음 처리) / "Undo trim". 반영 안 된 span 편집이 있으면 함께 보냄 | `SelectedTrackPanel.tsx:176-208`, `Timeline.tsx:572-580`(`gate-dim`) | `POST /api/audio/tracks/{id}/trim-to-spans` form `events?`, `DELETE` 같은 경로(`api.ts:234-252`, `routes.py:368-409`) | track에 `clip_segments` 저장 후 렌더 |
| 26 | Add track: 타임라인 하단 "New track" 임시 lane(재생 위치부터 2초 span 1개, 빈 곳 드래그로 span 추가, 더블클릭 삭제) + 오른쪽 양식(Name, Description, Model: SelSync/ElevenLabs/Kokoro/SAM Audio, Kokoro는 Spoken text) "Create and generate"/"Cancel" | `Timeline.tsx:647-697`, `NewTrackPanel.tsx`, `lib/newTrack.ts`, `VideoEditor.tsx:830-836`, `App.tsx:261-278` | `POST /api/audio/tracks` JSON `{label, description, model, spoken_text?, spans[{start_frame, end_frame}]}`(`api.ts:270`, `routes.py:432-458`) 뒤에 곧바로 위 23번 regenerate 호출 | `{status:"ok", sound_track_id}`. 새 track이 timeline에 나타나면 자동 선택 |
| 27 | Delete track + 확인 dialog(Cancel에 초기 focus, Esc/배경 클릭 = 취소) | `SelectedTrackPanel.tsx:287-305`, `DeleteTrackDialog.tsx` | `DELETE /api/audio/tracks/{id}`(`api.ts:254`, `routes.py:411-430`) | `{status:"queued"}` |
| 28 | "Include rest of original audio" 스위치(원본 오디오가 있을 때) | `SelectedTrackPanel.tsx:321-340` | `POST /api/audio/residual` form `enabled`(`api.ts:196`, `routes.py:492-515`) | 원본 오디오 없이 켜면 422 |
| 29 | Analysis 패널: scene별 object와 visual event, 눌러 해당 프레임으로 이동 | `AnalysisPanel.tsx`, `lib/analysis.ts` | summary의 `timeline_rows`(kind scene/track/visual) | - |
| 30 | Objects lane(접이식): object별 등장 구간 막대 | `Timeline.tsx:400-440`, `lib/objects.ts` | summary의 `timeline_rows`, asset의 `visual_identity_layer` | - |
| 31 | pending 편집 폐기("Discard edits"), 방식 전환 시 confirm | `SelectedTrackPanel.tsx:306-314`, `VideoEditor.tsx:620-624, 733-750` | - | - |
| 32 | 오류 표시 3단: 상단 한 줄 요약, 대화상자 안 메시지, 제어 옆 메시지 | `App.tsx:68-278`, `VideoEditor.tsx:500-506` | - | - |
| 33 | 접근성: 상태 `role="status"`, 진행 `role="progressbar"`, 라디오 그룹, `aria-describedby`로 비활성 이유 연결, 대화상자 native `<dialog>` | 전반 | - | - |

키보드/포인터 단축키는 이것이 전부입니다(`git grep keydown`로 확인): span 박스 선택 후 Delete/Backspace(`Timeline.tsx:158-181`), draft span 더블클릭 삭제(`Timeline.tsx:668`), 음량 슬라이더 더블클릭 100%(`Timeline.tsx:792`), 대화상자 Esc. Space 재생 단축키는 없습니다.

### 1.3 SoundPilot 백엔드가 Audyssey tools에 의존하는 점

SoundPilot의 SelSync/분리는 이미 Audyssey tools server를 호출합니다(`docs/usage.md` 1절 표, `.github/workflows/publish-image.yaml:30-31`의 `soundpilot-tools` 이미지). 이식은 UI만 옮기는 것이고 모델 서버 연동은 Audyssey가 원래 가진 경로(`settings.separator/generator`)를 그대로 씁니다.

---

## 2. Audyssey 기능 목록

### 2.1 데이터 모델 (`src/audyssey/contracts.py`)

| 모델 | 필드 | 줄 |
|---|---|---|
| `Span` | `start`, `end`(초, end > start) | 10-18 |
| `VisualHint` | `time`(초), `box`(x0,y0,x1,y1 정규화 0..1), `description` | 21-30 |
| `SourcePlan` | `name`, `kind: dialogue|sfx|music|ambience`, `description`, `spans[]`, `visual_hint?` | 47-55 |
| `FilterResult` | `passed`, `scores{}`, `reason`, `suggestion?` | 64-68 |
| `Source` | `id`, `plan`, `origin: separated|generated`, `replaces?`, `track_path?`, `filter?`, `status: pending|running|done|failed|skipped`, `attempts`, `keep`, `gain`(0..2), `pitch_semitones`(-12..12) | 74-85 |
| `Residual` | `path?`, `keep`, `gain`(0..2) | 88-91 |
| `StepStatus` | `key`, `status`, `round`, `max_rounds`, `message` | 94-99 |
| `Job` | `id`, `video_path`, `silent`, `duration`, `audio_path`, `mono_path`, `peaks_path`, `sources[]`, `residual`, `plan_issues[]`, `steps[]`, `outputs?(mix_wav, video_mp4, stems[])`, `state: new|running|ready|failed`, `method: separate|generate|None`, `version`, `error` | 108-125 |

`Job`에는 파일명, 생성/수정 시각, fps, 해상도, frame_count가 없습니다. 모든 모델이 `extra="forbid"`입니다(`contracts.py:6-7`).

### 2.2 명령 (`contracts.py:131-180`, 처리 `graph.py:769-844`, 검증 `graph.py:729-766`)

| 명령 | 필드 | 동작 | 거절 조건 |
|---|---|---|---|
| `keep` / `drop` | `source_id`(`"residual"` 가능) | `keep` 플래그만 변경 | 없는 id -> 404 |
| `set_gain` | `source_id`, `gain` 0..2 | 즉시 저장 | - |
| `set_pitch` | `source_id`, `semitones` -12..12 | 값만 저장, 소리는 `render` 때 `shift_pitch`(`render.py:18-47`) | residual -> 422 |
| `reseparate` | `source_id`, `description?`, `spans?` | plan 갱신 후 `process_source` 재실행 + residual 재계산 | 생성 source, 무음 영상, residual -> 422 |
| `generate` | `source_id`, `description?` | 분리 source면 `<이름> (generated)` source를 만들어 짝으로 두고 원본은 `keep=False`. 생성 source면 제자리 재생성 | 대사, residual -> 422 |
| `add_source` | `plan`, `method` | 새 id `s{n+1}`로 source 추가, 즉시 분리/생성, 분리면 residual 재계산 | 같은 이름 중복, 빈 설명, span이 duration 초과, 무음+separate, 대사+generate -> 422 |
| `render` | `include_residual_stem` | `out/mix.wav`, `out/video.mp4`, `out/stems/*.wav` 생성(`render.py:50-108`) | - |

없는 명령: source 삭제, clip trim/move, span 단독 편집, trim-to-spans, 방식 전환.

### 2.3 API (`src/audyssey/api.py`)

| 엔드포인트 | 줄 | 설명 |
|---|---|---|
| `POST /api/jobs` | 60-82 | 업로드(최대 `max_upload_mb=200`, `max_duration_s=30`, `settings.py`) -> `Job`(state `new`, 전처리만 백그라운드 실행) |
| `POST /api/jobs/{id}/start` | 84-102 | `{method: separate|generate}` -> 분석 시작. 이미 시작했으면 409, 무음에 separate면 422, 바쁘면 409 |
| `GET /api/jobs`, `GET /api/jobs/{id}` | 104-110 | 전체 `Job` 목록(최근 mtime 순, `store.py:list`), 단건 |
| `GET /api/jobs/{id}/events` | 112-128 | SSE. 매 메시지가 `Job` 전체 JSON. 서버가 0.25초마다 저장소를 폴링 |
| `POST /api/jobs/{id}/route` | 130-145 | 자연어 -> 명령 제안(읽기 전용). `{route_id, decision}` |
| `POST /api/jobs/{id}/commands` | 147-168 | 명령 실행 -> 갱신된 `Job`. 실행형 명령(`reseparate`, `generate`, `add_source`, `render`)은 잠금(바쁘면 409), 완료까지 응답을 막음. 404 없는 source, 422 검증 오류 |
| `GET /api/jobs/{id}/files/{path}` | 170-175 | job 폴더 안 파일(영상, stem, residual, `out/*`, `trace/*`, `peaks.json`, `masks/*.mp4`) |
| `GET /api/router` | 177-180 | `{router: stub|real|hybrid}`; stub이면 NL 바 비활성 |
| `GET /api/system` | 182-227 | 서버별 lane(`id, name, models[], steps[], up`) |
| `GET /api/jobs/{id}/trace` | 229-232 | `trace.jsonl` 호출 기록 목록 |
| `GET /api/jobs/{id}/export` | 234-256 | render 결과를 zip(video.mp4, mix.wav, stems). render 전이면 409 |
| `GET /`, `GET /dev` | 258-268 | 각각 `files("audyssey.ui")/index.html`, `files("audyssey.devui")/index.html`을 `HTMLResponse`로 반환 |

삭제 엔드포인트, 프로젝트 이름, bundle 입출력은 없습니다.

### 2.4 Trace와 system (`src/audyssey/trace.py`)

- `trace.jsonl` 한 줄 = `{id, step, tool, server, started, seconds, inputs, requests[], output, error}`(`trace.py:96-107`). 호출이 주고받은 파일은 `trace/<id>/`에 보관(`trace.py:47-52`).
- `TOOL_STEPS`(`trace.py:183-192`)로 도구 이름을 lane 단계에 매핑합니다. `lanes(settings)`(`trace.py:136-179`)가 서버 배치를 계산합니다.
- 단계 키: `preprocess, plan, validate_plan, ground, separate, generate, judge, score, residual, render`(`index.html:451-455`, `graph.py` `update_step`).

### 2.5 현재 `ui/index.html`이 하는 일 (1528줄, 한국어, 밝은 테마)

| 기능 | 줄 |
|---|---|
| 상단: 프로젝트 `<select>`, 상태 점, 영상 올리기, 내보내기 | 372-380, 1422-1436, 1481-1514 |
| 업로드 후 "분리 시작/생성 시작" 선택 패널(state `new`) | 692-713 |
| 영상 + Web Audio mix 재생 엔진(영상은 mute, AudioContext가 master clock, 편집본/원본 토글, Space 재생, Esc 닫기) | 510-590, 404-410 |
| track 목록(`trackList`): 분리/생성 짝(`replaces`) 인접 배치, residual 행 | 591-614 |
| track 행: 사용 스위치(keep/drop, 짝이면 한쪽만), 음량 0-200%, 피치 ±1 st 스텝퍼, "다시 분리"/"생성으로 바꾸기" 메뉴, waveform canvas, 상태 표시 | 714-764, 812-858 |
| 계획 검수에서 건너뛴 source 안내(`plan_issues`) | 665-673 |
| NL 편집 바: `/route` 호출, 명령 카드(실행/수정/취소), clarify 칩, 대상 행 강조 | 901-1036 |
| 파이프라인 board(SVG): server lane별 단계 노드, 데이터 종류별 edge, 재시도 loop, 라운드/완료 수 | 1038-1223 |
| edge popover(해당 edge로 건너간 입력)와 inspector drawer(단계별 호출 기록: 입력, 프롬프트, 프레임/클립/오디오, 응답, 점수, 오류) | 1237-1420 |
| SSE로 job 따라가기, 행 서명(rowSignature) 비교 후 다시 그리기 | 1451-1479 |
| export: `render` 후 `/export` zip 다운로드 | 888-899 |
| 15초마다 `/api/system` 갱신 | 1514-1527 |

---

## 3. 대응표 (SoundPilot -> Audyssey)

범례: **AS-IS** = 백엔드 변경 없이 UI만으로 가능 / **SHAPE** = 있으나 형태가 달라 어댑터 필요 / **MISSING-UI** = 백엔드는 그대로 두고 UI만으로 대체 가능한 부분 구현 / **MISSING-BE** = 백엔드 변경 필요. `[C]` = `contracts.py` 변경 포함(팀 합의 필요).

| SoundPilot 기능 | Audyssey 대응 | 판정 | 필요한 변경 |
|---|---|---|---|
| 상단 바 상태/진행(1.2 #3) | `Job.state` + `Job.steps[]` | SHAPE | `stage` 문자열 파싱 대신 `StepStatus.round/max_rounds`와 source별 완료 수(`index.html:1044-1050` `nodeSub`)로 "Separating 2 of 3" 생성. 단계 한국어 라벨은 영어로 교체 |
| 원본/무음 배지 | `Job.silent` | AS-IS | - |
| 방식 선택 Generate/Separate + 실행 버튼 | `state=="new"`일 때 `POST /jobs/{id}/start {method}` (`api.py:84`) | SHAPE | 시작 전에만 라디오로 선택, 시작 후에는 읽기 전용 배지(`Job.method`). 무음이면 Separate 비활성(문구 "No original audio to separate." 재사용). 시작 후 방식 전환은 없음(4절 2번) |
| Open video: 새 영상 Run | `POST /api/jobs`(업로드+전처리) 뒤 `/start` | SHAPE | 업로드와 시작이 분리됨. Run 버튼 = 업로드 후 모드 선택 화면으로 이동. Advanced 항목(work_dir, server URL, scene threshold, keyframes)은 Audyssey에 없음 -> 제거 |
| 업로드 제한 안내 | `max_upload_mb`, `max_duration_s`(설정값) | MISSING-UI | 값을 알려주는 엔드포인트 없음. 400 `detail`을 그대로 표시하거나 `/api/router`처럼 작은 설정 엔드포인트 추가(api.py, core 파일) |
| Save bundle / Load bundle | 없음 (`/export`는 결과물 zip이며 재가져오기 불가) | MISSING-BE | 선택 사항. `GET /api/jobs/{id}/bundle`, `POST /api/jobs/import` 추가(api.py + store.py, contracts 변경 없음). job 디렉터리가 volume에 남으므로 우선순위 낮음 |
| 최근 프로젝트 목록(이름, 날짜, 길이, 방식, track 수, 상태) | `GET /api/jobs`(`Job[]`) | SHAPE / MISSING-BE | 있는 것: id, state, `duration`, `method`, `sources.length`. 없는 것: 이름(업로드 파일명), created/updated. 선택: `Job.name`, `Job.created` 추가 `[C]` 또는 사이드카 `meta.json`을 `store.py`가 쓰고 별도 요약 엔드포인트로 노출(contracts 변경 없음) |
| 프로젝트 열기 | 다른 job id를 따라가기(`follow`, `index.html:1453`) | AS-IS | App 상태가 `jobId`를 가짐. URL hash로 deep link 가능 |
| 프로젝트 삭제 | 없음 | MISSING-BE | `DELETE /api/jobs/{id}` + `JobStore.delete`(api.py/store.py, contracts 변경 없음, 실행 중이면 409) |
| Clean workspace / Reset+rerun soundtrack / Download edited JSON / Discard timeline edits | 대응 없음 | 불필요 | 삭제. "Discard edits"는 pending span 편집 폐기로 유지 |
| Download video (MP4) | `render` 후 `files/out/video.mp4` 또는 `/export` zip | AS-IS | `Job.outputs`가 있으면 직접 링크 |
| Stage + 재생 + 프레임 슬라이더 | `files/<video_path>` + Web Audio mix | SHAPE | 프레임 대신 초 단위 슬라이더(`step=0.01`). 영상 fps가 Job에 없으므로(4절 6번) |
| Stage mask 강조(SAM3 tracking) | `SourcePlan.visual_hint`(시각 1점의 정규화 박스) | MISSING-UI | 선택한 source의 hint 박스를 `hint.time` 근처(±0.5초 등)에 그림. 시각 정보가 없는 source는 "No on-screen location"으로 표시. mask 윤곽선/전 구간 tracking은 불가 |
| 모든 object를 색별로 표시(선택 없을 때) | 대응 없음 | MISSING-UI | 모든 source의 hint 박스를 색별로 표시하는 정도로 대체 |
| Objects lane(접이식) | 대응 없음 | MISSING-UI | hint 시각 표식 한 줄로 대체하거나 삭제 |
| 눈금자 scrub, playhead | `scrub` input, `seek`(`index.html:560, 653`) | AS-IS | 동작은 같고 단위만 초 |
| lane별 Play | 대응 없음 | MISSING-UI | Web Audio로 단일 source만 재생하는 함수 추가(엔진 확장) |
| Solo | 대응 없음 | MISSING-UI | 같은 엔진에서 다른 gain node를 0으로. 백엔드 변경 없음 |
| waveform dB 스케일 | `peaks()`가 RMS + 0.7승 정규화(`index.html:841-858`), `Job.peaks_path`는 원본 전체의 선형 peak(`media.py:94-101`) | MISSING-UI | 디코드된 AudioBuffer에서 `-60..0 dBFS` 매핑으로 계산하는 TS 함수를 추가. 서버 변경 불필요 |
| span 박스 이동/resize/삭제(pending) | `SourcePlan.spans[]`(초) | SHAPE | 이벤트 id를 `${sourceId}#${index}`로 합성. pending은 source별 span 목록 초안으로 단순화 가능 |
| span 편집 반영 = "Regenerate with new spans" | `reseparate{source_id, spans, description?}` | AS-IS (분리 source만) | 생성 source에는 적용 불가: `reseparate`가 생성 source를 거절하고(`graph.py:760`) `generate` 명령은 spans를 받지 않으며 real 생성기는 plan spans를 쓰지 않음(`docs/architecture.md` 용어표 "생성 트랙") |
| Edit audio: clip trim/move | 없음 | MISSING-BE `[C]` | `Source.clip_start/clip_end/clip_offset`(float|None), 새 명령 `SetClip`, `render.py`에서 clamp와 5 ms fade 적용 후 믹스. 브라우저 미리듣기는 Web Audio `start(when, offset, duration)`으로 즉시 가능 |
| Trim to spans / Undo trim | 없음 | MISSING-BE `[C]` | `Source.trim_to_spans: bool`(또는 `clip_segments`), 새 명령 `TrimToSpans(source_id, enabled)`, `render.py` 게이팅. 생성 source에서 span의 유일한 의미가 되므로 가치가 큼 |
| 음량 0-400% | `set_gain` 0..2 | SHAPE | 즉시 가능한 범위는 0-200%(UI 상한). 400%는 `Source.gain`, `Residual.gain`, `SetGain.gain`의 `le` 변경 `[C]` + `tests/test_audyssey_contracts.py` 수정 |
| 음량 미리듣기와 commit | `range` input -> gain node 즉시 + 놓을 때 `set_gain`(`index.html:723-732`) | AS-IS | 이미 같은 방식 |
| Selected track 패널: 상태, method 배지, Seed/Attempt | `Source.status`, `origin`, `attempts` | SHAPE | "Attempt N"만 표시. seed는 `gen_seed + attempts - 1`이지만 설정값을 UI에 알려주는 경로가 없음(`/api/system`에 없음, UNVERIFIED로 표시) |
| 실패 표시 + "Previous audio kept." | `Source.status=="failed"`, `StepStatus.message` | SHAPE | 분리/생성이 실패하면 `track_path=None`이 되므로(`graph.py:183-184, 281-283`) 이전 오디오가 유지되지 않음. "kept" 문구는 쓰면 안 됨 |
| Description 편집 + 재생성 | `reseparate.description`, `generate.description` | AS-IS | - |
| Model select(SelSync/ElevenLabs/TTS/Separate) | 방식 2개(분리 / 생성) | SHAPE | 4절 4번 |
| event별 설명/Spoken text, "Regenerate this span" | 없음(source당 설명 1개, 대사는 생성하지 않음) | 불필요 | 삭제 |
| Delete track + 확인 대화상자 | `drop`(끄기, 되돌릴 수 있음)만 있음 | MISSING-BE `[C]` (삭제를 원할 때) | 새 명령 `RemoveSource(source_id)`와 `graph.handle_command` 분기, 짝 source(`replaces`) 처리, 파일 삭제, residual 재계산. 대안: UI에서 "Remove from mix" = `drop`으로 이름 붙이고 확인창 재사용(변경 없음) |
| "Include rest of original audio" | `keep`/`drop` `source_id="residual"` (`handle_command` `graph.py:831-832`) | AS-IS (분리 모드만) | `Job.method=="generate"`이면 `residual.path`가 없어(`graph.py:326-328`) 스위치를 숨김. SoundPilot은 생성 모드에서도 원본 오디오 포함 여부를 다룸(UNVERIFIED) -> 동등 기능은 없음. 편집본/원본 토글(`index.html:407-408`)로 부분 대체 |
| Add track(draft lane, 다중 span, 이름/설명/모델) | `add_source{plan{name, kind, description, spans[], visual_hint?}, method}` | SHAPE | 양식에 `kind`(sfx/music/ambience/dialogue) 선택 추가(SoundPilot에는 없음). 모델 -> method. dialogue는 separate만, 무음 영상은 generate만. 이름 중복은 422 |
| Analysis 패널(scene/object/visual event) | 없음 | MISSING-UI | "Plan" 패널로 교체: source별 kind/설명/spans(눌러서 이동), `plan_issues`, 건너뛴 source 안내(`index.html:665-673`) |
| 키보드: Delete로 span 삭제, 슬라이더 더블클릭 100% | - | AS-IS | 그대로. Audyssey의 Space 재생, Esc 닫기 유지 |
| 파이프라인 board, edge popover, inspector drawer, trace | 있음 | Audyssey 고유 | 새 레이아웃에 배치(5절, 6.3). 변경 없음 |
| NL 편집 바 | 있음 | Audyssey 고유 | 새 레이아웃에서 타임라인 위에 유지 |
| keep 스위치, 피치 스텝퍼, 필터 점수/미통과 표시, 분리/생성 짝 비교 | 있음 | Audyssey 고유 | 선택 패널/행에 유지 |

### `contracts.py` 변경 목록 (전부 선택 사항이며 1단계에서는 하지 않아도 됩니다)

1. `Source.clip_start`, `clip_end`, `clip_offset` + 명령 `SetClip` (clip trim/move)
2. `Source.trim_to_spans`(또는 `clip_segments`) + 명령 `TrimToSpans` (trim to spans)
3. 명령 `RemoveSource` (track 삭제)
4. `Source.gain`, `Residual.gain`, `SetGain.gain` 상한 2 -> 4 (400%)
5. `Job.name`, `Job.created`(선택), 필요하면 `Job.fps/width/height`(선택)
6. (선택) `Generate.spans`: 생성 source에 span을 입력으로 주려면 생성기(`tools/generation`)도 span을 쓰도록 바뀌어야 하며 UI와 무관한 별도 작업입니다.

contracts 변경은 모두 `graph.py`(`handle_command`, `check_command`)와 `render.py`/`tests`를 함께 건드립니다. `graph.py`, `api.py`, `settings.py`도 CODEOWNERS 대상입니다.

---

## 4. 1:1로 대응되지 않는 개념과 제안

1. **VideoAsset / sound_timeline / track / event vs Job / Source**
   - 대응: `VideoAsset` ≈ `Job`, `SoundTrack`+`SoundSource` ≈ `Source`, `SoundEvent` ≈ `Span`(source 1개에 span 여러 개, 설명은 source당 1개), `SoundSource.visual_object` ≈ `VisualHint`.
   - 제안: `web/src/lib/adapter.ts`에 `jobToView(job)`를 만들어 SoundPilot 컴포넌트가 기대하는 모양(`soundTracks`, `events/timelineRows`, `audioTracks`)을 합성합니다. 이벤트 id는 `${source.id}#${index}`, track 상태는 `Source.status`에서 변환(`skipped`는 숨기고 안내). 분리/생성 짝은 SoundPilot처럼 한 lane에서 모델을 바꾸는 대신 Audyssey처럼 인접한 두 행으로 두어 A/B 비교(`replaces`, `index.html:603-612`)를 유지합니다.

2. **generate vs separate 모드 vs source별 `origin` + 무음 감지**
   - SoundPilot은 전역 `audio_mode`와 모드별 timeline 2개를 보관하고 언제든 전환합니다. Audyssey는 `Job.method`가 `/start`에서 한 번 정해지고(`api.py:90`) 이후에는 source마다 `origin`이 다릅니다. 무음 영상은 자동으로 generate입니다(`graph.py:366`, `Job.silent`).
   - 제안: 상단 바의 Generate/Separate 라디오는 `state=="new"`일 때만 활성화해 `/start`에 연결합니다. 시작 후에는 `Job.method`를 읽기 전용 배지로 보여주고, 전환은 track 단위 "Generate instead"/"Re-separate"로 대체합니다. 시작 후 전체 방식 전환은 `/start`의 409 규칙, graph, 계약을 바꿔야 하므로 범위에서 제외하길 권합니다.

3. **SAM3 tracking mask vs VisualHint 박스**
   - Audyssey에는 frame별 mask가 없고 plan당 박스 1개(`time`, 정규화 `box`)뿐이며 위치가 없는 source는 `visual_hint=null`입니다(`tools/planning/prompts.py:11-13`). SAM3는 `AUDYSSEY_VISUAL_PROMPT=true`일 때만 분리 입력용 마스킹에 쓰입니다(`graph.py:223`, 기본 false).
   - 제안: `TrackingOverlay`는 박스 그리기만 남깁니다. 선택한 source의 박스를 `hint.time` 근처에 표시하고, 없으면 "No on-screen location"을 칩에 표시합니다. 박스 정규화 좌표는 영상 해상도를 몰라도 `<video>` 크기에서 계산됩니다. `rle.ts`/mask painter(약 120줄)는 이식하지 않습니다. 전 구간 tracking이나 마스크 윤곽이 필요하면 별도 백엔드 작업입니다.

4. **모델 선택(SelSync/ElevenLabs/TTS) vs 단일 내부 생성기**
   - Audyssey의 생성 경로는 `settings.generator` 하나(`internal-model`)이고 TTS/ElevenLabs가 없으며 대사는 생성하지 않습니다(`graph.py:92-103`, `check_command`).
   - 제안: Model select를 "Method: Separate (SAM Audio) / Generate (internal model)" 두 선택지로 줄이고, 모델 이름은 `/api/system` lane의 `models[]`에서 읽어 표시합니다. 대사 source에서는 Generate를 비활성화하고 이유를 보여줍니다(기존 `rowActions`의 "대사는 생성을 지원하지 않습니다" 동작을 영어로 유지). Kokoro/TTS, Spoken text 입력은 삭제합니다.

5. **단일 전역 asset vs 여러 job**
   - SoundPilot의 서버에는 "현재 asset"이 있고 새 run이 이전 것을 비웁니다. Audyssey는 job이 병렬로 존재하고 SSE도 job별입니다.
   - 제안: `App`이 `jobId`를 상태로 갖고(URL hash 권장), `EventSource(/api/jobs/{id}/events)`를 job 전환 시 다시 엽니다. SSE 메시지가 `Job` 전체이므로 summary 재조회가 필요 없습니다(버전이 낮은 메시지는 버림: `index.html:1469`). SoundPilot의 요청 카운터 패턴(`App.tsx:59-66`)은 그대로 쓸 수 있습니다.

6. **프레임 vs 초**
   - SoundPilot UI 전체가 프레임 정수 기준입니다(`Timeline.tsx`, `lib/span.ts`, `pendingEdits.ts`, `newTrack.ts`). Audyssey `Span`과 `Job.duration`은 초 단위이고 fps/frame_count가 `Job`에 없습니다.
   - 제안: 초 단위로 변환합니다(최소 span 0.1초는 이미 `lib/span.ts:8-10`의 정의와 같음). 프레임 정밀도가 필요하면 `Job.fps` 추가 `[C]`가 필요하지만 이식에는 불필요하다고 판단합니다.

7. **재생 엔진**
   - SoundPilot: 서버가 mix한 mp4를 재생하고 stem 미리듣기는 HTMLAudio 요소를 따로 돌립니다(`VideoEditor.tsx:391-478`). Audyssey: 영상은 mute, AudioContext로 stem 전체를 즉시 mix하므로 keep/gain/solo가 서버 왕복 없이 반영됩니다(`index.html:510-590`). 피치만 render가 필요합니다.
   - 제안: Audyssey 엔진을 `lib/audioEngine.ts`로 옮겨 쓰고 Play/Solo/clip 미리듣기를 그 위에 구현합니다. SoundPilot의 `playSyncedAudio`와 서버 preview 방식은 가져오지 않습니다. 단 `transportAction`, `soloToggleAction`(`lib/selection.ts:92-105`) 순수 함수와 테스트는 의미가 같아 재사용합니다.

8. **큐(비동기) vs 동기 명령**
   - SoundPilot mutation은 `queued`를 돌려주고 상태는 SSE로만 옵니다. Audyssey의 `reseparate/generate/add_source/render`는 끝날 때까지 응답을 막고, 그 사이 SSE로 `steps`와 `Source.status`가 갱신됩니다(`graph.py` `update_step`이 매번 저장).
   - 제안: 명령 호출은 `busy` 상태 + SSE 진행 표시를 같이 사용(`index.html:870-887`의 `send` 패턴). `regenerateBlockedReason`(`VideoEditor.tsx:71-86`)은 `job.state==="running"`, 진행 중 명령, 409 응답 기준으로 다시 씁니다.

9. **삭제 vs 끄기, 음량 범위, residual 의미, 짝 비교**
   - 위 대응표의 항목을 사용자가 결정해야 합니다(7절).

---

## 5. 프론트엔드 재사용 추정

SoundPilot `web/`의 규모: components 3,317줄(Timeline 894, VideoEditor 1,086, SelectedTrackPanel 345, OpenVideoDialog 224, TrackingOverlay 186, TopBar 151, Stage 144, NewTrackPanel 125, AnalysisPanel 65, DeleteTrackDialog 53, Icon 44), App 303, api 281, types 229, lib 599, styles 274(긴 줄), tests 약 1,300줄. Audyssey 기존 UI는 단일 파일 1,528줄(CSS 약 350줄, JS 약 1,070줄, board+inspector 약 380줄).

| 구분 | 파일 | 비고 |
|---|---|---|
| **거의 그대로** | `Icon.tsx`, `DeleteTrackDialog.tsx`(문구만 "its audio"로 조정), `lib/errors.ts`, `lib/clip.ts`(clip 기능을 넣을 때만), `lib/gain.ts`(`GAIN_MAX_PERCENT`만 200 또는 400), `Stage.tsx`(video src와 overlay props만), `main.tsx`, `index.html`, `vite.config.ts`(proxy 대상 포트만 8501 -> 8600), `tsconfig.json`, `package.json` | `errors.ts`의 "Audyssey tools server unreachable" 문구는 그대로 적합 |
| **Audyssey API에 맞춰 수정** | `types.ts`(대부분 새로 작성: `Job`, `Source`, `Command` 타입을 contracts에서 옮김), `api.ts`(함수 약 10개를 `command()` 래퍼로 재작성), `App.tsx`(job 상태, job별 SSE, 핸들러 수는 절반 이하), `TopBar.tsx`(status/모드/버튼), `OpenVideoDialog.tsx`(업로드 1폼 + 프로젝트 목록만), `Timeline.tsx`(초 단위, 행 어댑터, Web Audio Play/Solo, 음량 상한, 분리/생성 짝 행, objects lane 제거), `VideoEditor.tsx`(전면 재작성 수준: asset 왕복/draftAsset/preview URL 로직 제거, 엔진 연결), `SelectedTrackPanel.tsx`(Model -> Method, 명령 매핑, keep/pitch/filter 점수 추가, "Previous audio kept" 제거), `NewTrackPanel.tsx`(kind 추가, 모델 -> method), `lib/span.ts`(프레임 -> 초), `lib/pendingEdits.ts`(이벤트 id -> source별 span 목록으로 단순화), `lib/selection.ts`(`reconcileSelection`, `transportAction`, `soloToggleAction`, `objectColor`, `statusView`는 유지. `methodLabel`, `generationLabel`, `trackActions`는 재작성), `lib/newTrack.ts`(모델 목록 교체), `lib/projects.ts`, `TrackingOverlay.tsx`(mask 경로 삭제, 박스 경로만), `styles.css`(어두운 SoundPilot 토큰을 기준으로 board/drawer/NL 바/edge popover 스타일을 이식하고 Audyssey의 `--video/--audio/--text` edge 색과 board SVG 색을 어두운 배경에 맞게 재조정) |
| **새로 작성(Audyssey 고유 이식)** | `lib/audioEngine.ts`(`index.html:510-590, 616-639` 이식), `components/PipelineBoard.tsx`(`index.html:1097-1235` + edge popover `1237-1344`), `components/Inspector.tsx`(drawer, `1277-1420`), `components/NlBar.tsx`(`901-1036`), `lib/adapter.ts`, `lib/waveform.ts`(dB 스케일) | board는 명령형 SVG 코드이므로 JSX로 다시 쓰거나 `useEffect`+ref로 감싸는 두 가지 방법이 있고, 후자가 빠르지만 TS 타입/테스트 이득이 적음 |
| **불필요** | `rle.ts`, `TrackingOverlay`의 mask painter, `lib/objects.ts`, `lib/analysis.ts`(Plan 패널로 대체), `lib/trackWindow.ts`, `AnalysisPanel.tsx`(Plan 패널로 대체), event별 설명/Spoken text(`EventRow`), bundle/reset/clean/mode 전환 대화상자 항목 | - |

**테스트 재사용** (`web/tests/*.test.mjs`, `node --test` + vite `ssrLoadModule`로 TSX를 SSR 렌더하는 방식이므로 vitest 등 새 의존성이 필요 없음):
- 그대로 또는 거의 그대로: `clip`, `gain`, `errors`, `transport`, `selection`(`methodLabel` 관련 단언만 수정), `new-track`(모델 목록 단언 수정).
- 수정 후 재사용: `pending-edits`, `projects`, `timeline-order`, `timeline-lanes`, `stage`, `topbar`, `selected-panel`(213줄), `regenerate-guard`, `track-edit-ui`.
- 삭제: `rle`, `objects`, `analysis`, `track-window`.

---

## 6. 빌드와 서빙 통합

### 6.1 현재 상태 (Audyssey)

- 루트 라우트가 `files("audyssey.ui") / "index.html"`을 읽어 `HTMLResponse`로 반환합니다(`api.py:258-262`), `/dev`는 `audyssey.devui`(`api.py:264-268`). 정적 파일 mount가 없습니다.
- `docker/app.Dockerfile`은 `COPY src/` 후 `uv sync --locked --no-dev --extra ui --extra llm`을 실행합니다. `uv sync`는 프로젝트를 editable로 설치하므로 이미지 안에서 패키지 경로는 `/app/src/audyssey`입니다(editable 여부는 UNVERIFIED, uv 기본 동작 기준).
- `pyproject.toml`의 `[tool.uv-build] include = ["src/audyssey/devui/*.html", "src/audyssey/ui/*.html"]`. 표 이름이 uv 문서의 `[tool.uv.build-backend]`와 달라 실제로 적용되는지는 UNVERIFIED입니다. 휠에 `webui/**`가 들어가는지는 `uv build` 후 `unzip -l`로 확인해야 합니다.
- CI(`.github/workflows/ci-lint.yaml`): `lint-and-format-check`(ruff, ty, `unittest discover tests`), `numpy-1x`, `docker-build`(app 이미지, tools는 변경 시에만). `ruff`/`ty`는 `src/`만 검사하므로 TS는 영향받지 않습니다. `publish-images.yaml`의 `paths`는 `src/**, pyproject.toml, uv.lock, gpu/**, docker/**`이고 `web/**`가 없어 UI만 바꾼 머지는 이미지를 다시 만들지 않습니다.
- `.dockerignore`는 `tests`, `docs`, `work`, `samples` 등을 제외하지만 `web/node_modules`, `web/dist`는 제외하지 않습니다.

### 6.2 제안

1. **소스 위치**: 저장소 루트의 `web/` (SoundPilot과 같은 구조, `web/package.json`, `package-lock.json`, `vite.config.ts`, `tsconfig.json`, `src/`, `tests/`).
2. **빌드 산출물 위치**: `web/vite.config.ts`의 `build.outDir`를 `../src/audyssey/webui`로 지정(gitignore 대상). Python 패키지 안에 두면 editable/설치 방식 모두 `files("audyssey.webui")`로 찾을 수 있습니다. 빈 `src/audyssey/webui/__init__.py`가 필요한지는 UNVERIFIED(`ui/__init__.py`가 있는 현 구조를 따라 두는 것을 권장).
3. **FastAPI** (`api.py`, core 파일):
   - `/assets`를 `StaticFiles(directory=webui/assets)`로 mount하고 `/`는 `webui/index.html`을 `FileResponse`로 반환.
   - **webui가 없으면 기존 `ui/index.html`로 fallback**: SoundPilot도 같은 방식을 씁니다(`src/v2a_inspect/ui/app.py:27-32`). 이렇게 하면 Node가 없는 CI의 `unittest`(`tests/test_audyssey_api.py:233-238`)가 수정 없이 통과합니다. 새 UI가 있을 때의 응답 검증은 별도 테스트(예: dist를 임시 폴더로 만들고 확인)로 추가합니다.
   - 기존 UI는 `/legacy`로 계속 제공하면 전환 기간 비교와 롤백이 쉽습니다. `/dev`(소스 추가/설명 수정 화면, `docs/status.md`의 "`/dev`에만 있습니다")는 새 UI가 add track/regenerate를 모두 포함하기 전까지 유지합니다.
4. **`.gitignore`** (필수): `!/web/**/*.json` 또는 `!web/package.json`, `!web/package-lock.json`, `!web/tsconfig.json`; `!/web/src/lib/`(Python 템플릿의 `lib/`가 `web/src/lib/`를 무시함); `web/node_modules/`(현재 없음); `/src/audyssey/webui/`.
5. **`.dockerignore`**: `web/node_modules`, `web/dist` 추가.
6. **`docker/app.Dockerfile`**: SoundPilot의 `Dockerfile:18-26`을 따라 앞에 `FROM node:22-bookworm-slim AS frontend` 단계를 추가합니다(`COPY web/package.json web/package-lock.json ./` -> `npm ci` -> `COPY web ./` -> `npm run build`). 최종 단계에서 `COPY src/ src/` 뒤에 `COPY --from=frontend <outDir> src/audyssey/webui`. Vite `outDir`가 `web/` 밖을 가리키면 frontend 단계에서 경로를 맞춰야 하므로, 단계 안에서는 `/app/src/audyssey/webui`로 빌드되도록 `WORKDIR` 구조를 같게 두는 것이 간단합니다. Node 20.19+ 또는 22.12+ 필요(`docs/usage.md`).
7. **CI** (`.github/`는 @gwpark0741만 승인): SoundPilot `ci-lint.yaml:60-75`의 `web` job(setup-node 22, npm cache, `npm ci`, `npm test`, `npm run build`, timeout 10분)을 추가하고 `docker-build`에서 app 이미지를 이미 빌드하므로 node 단계가 함께 검증됩니다. `publish-images.yaml`의 `paths`에 `web/**` 추가.
8. **`pyproject.toml`**: 6.1의 include가 실제로 적용되는지 확인한 뒤(`uv build`) 필요하면 `src/audyssey/webui/**`를 추가. CODEOWNERS 대상.
9. **개발 흐름**: `audyssey serve`(8600) + `npm run dev`(Vite proxy `/api` -> `127.0.0.1:8600`; job별 SSE도 `/api` 아래이므로 `/events` proxy는 불필요).
10. **문서/테스트**: `README.md:115`, `docs/status.md`, `docs/running.md`에 UI 빌드 방법과 `/legacy` 설명 추가, CODEOWNERS에 `/web/` 추가 여부는 팀 결정.

---

## 7. 리스크와 사용자에게 물어볼 점

1. **범위 결정(가장 큰 질문)**: clip trim/move, trim-to-spans, track 삭제, 400% 음량은 `contracts.py`와 `graph.py`/`render.py` 변경이 필요하고 팀 합의가 필요합니다. 1단계(백엔드 변경 없음: 레이아웃/상태/타임라인/add track/재분리/음량 0-200%/residual/export/board/inspector/NL)와 2단계(위 기능)로 나눌지, 처음부터 포함할지 정해야 합니다.
2. **"삭제"의 의미**: Audyssey에는 삭제가 없고 `drop`(끄기, 되돌릴 수 있음)만 있습니다. UI에서 "Delete track"을 `drop`으로 대체해도 되는지, 진짜 삭제 명령(`RemoveSource`)을 추가할지.
3. **생성 track의 span 편집**: 현재 생성기는 span을 입력으로 쓰지 않으므로, 생성 track에서 span을 끌어도 소리가 바뀌지 않습니다(`docs/architecture.md` 용어표). 생성 track의 span은 읽기 전용으로 두거나 trim-to-spans(2단계)와 묶어야 사용자 혼란이 없습니다.
4. **테마**: SoundPilot의 어두운 테마를 따를지(권장: "look" 이식이 목표) 기존 밝은 테마를 유지할지. board의 edge/상태 색과 inspector 스타일을 어두운 배경에 맞게 다시 잡아야 합니다.
5. **board/inspector 배치**: board는 viewBox 폭이 약 1,000(`index.html:1112-1116`)이라 SoundPilot의 우측 열(360-440px)에는 들어가지 않습니다. 제안: 상단 바 아래에 접이식 전폭 패널(진행 중 펼침, 완료 후 접힘)을 두고 inspector는 우측 drawer(모달)를 유지. 대안은 별도 "Pipeline" 탭. 어느 쪽을 쓸지 선택이 필요합니다.
6. **프로젝트 이름과 이력**: `Job`에 이름/날짜가 없어 이력 목록이 id 앞 6자와 상태 정도만 보여줍니다(`index.html:1483`). 이름과 날짜를 원하면 `Job.name/created` `[C]` 또는 사이드카를 추가해야 합니다. 프로젝트 삭제와 bundle도 같은 결정에 묶입니다.
7. **NL 바 위치와 SoundPilot에 없는 Audyssey 고유 기능 유지 범위**: NL 바, 피치, 필터 점수, 분리/생성 짝 비교를 새 레이아웃의 어디에 둘지.
8. **기존 한국어 UI 폐기 범위**: 영어 UI로 교체하면 `tests/test_audyssey_api.py:233-238`의 "내보내기" 단언을 고쳐야 하고, 기존 UI를 `/legacy`로 둘지 삭제할지 정해야 합니다. `/dev` 화면의 한국어도 그대로 둘지.
9. **확인하지 못한 것(UNVERIFIED)**: (a) `uv_build`가 `[tool.uv-build] include`를 인식하는지와 휠에 `webui`가 포함되는지, (b) `files/` 엔드포인트의 HTTP Range 지원(영상 seek에 필요, 현재 UI가 `files/<video_path>`를 seek하고 있어 동작은 하는 것으로 보임), (c) 생성 모드에서 SoundPilot "Include rest of original audio"의 정확한 의미, (d) seed를 UI에 노출할 방법, (e) Docker 이미지 안에서 editable 설치가 `/app/src` 경로를 쓰는지, (f) 외부 CDN 폰트(Instrument Sans, Pretendard)를 새 UI에서도 쓸지(SoundPilot은 시스템 폰트, 오프라인 시연 환경에서는 영향).
10. **동기 명령과 UI 멈춤**: `add_source`, `reseparate`, `generate`는 완료까지 응답을 막고 서버 잠금(409 "job is busy")이 있어 두 명령을 동시에 보낼 수 없습니다. SoundPilot처럼 여러 track을 연달아 만들 수 있다고 가정한 UX(예: add track 직후 다른 track 편집)는 직렬화해야 합니다.
