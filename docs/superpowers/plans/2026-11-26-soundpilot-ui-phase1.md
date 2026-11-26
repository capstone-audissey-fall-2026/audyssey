# SoundPilot UI for Audyssey, Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Audyssey's single-file UI with SoundPilot's React UI and features, adapted to Audyssey's job/command API, without changing `contracts.py`.

**Architecture:** A Vite/React app in `web/` builds into `src/audyssey/webui/`, which FastAPI serves at `/` (falling back to the old `ui/index.html` when no build exists). The app follows one job over SSE, adapts `Job` to view rows with `jobToView`, plays every track through the Web Audio engine ported from `ui/index.html`, and keeps Audyssey's pipeline board, inspector and edit bar as React components.

**Tech Stack:** React 19, Vite 7, TypeScript 5.9, `node --test` with Vite `ssrLoadModule` (as in SoundPilot), FastAPI `StaticFiles`, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-26-soundpilot-ui-design.md` (feature map, layout, Phase 2 list). Source mapping with line references: `docs/superpowers/plans/2026-11-26-soundpilot-ui-mapping.md`.

**Sources to copy from:** SoundPilot `web/` at `git -C ~/v2a_inspect show fork/main:web/<path>` (commit 0838ad7). Audyssey's current UI: `src/audyssey/ui/index.html` in this worktree.

## Global Constraints

- No change to `src/audyssey/contracts.py` or to command semantics in `graph.py`.
- UI copy in English, sentence case, verb-first buttons; no "Previous audio kept" (a failed source has `track_path = null`).
- Dark theme from SoundPilot `web/src/styles.css` tokens (`--bg #101114`, `--panel #17191f`, `--accent #d6a94a`, …); system font stack, no external font CDN.
- Seconds, not frames, in every helper and API payload.
- Volume slider range 0–200 % in Phase 1 (`set_gain` accepts 0–2).
- Spans of generated sources are read-only (the generator does not use spans).
- One mutating request at a time; controls disabled while a command runs or `job.state === "running"`; HTTP 409 shown as "Another change is still running."
- Keep keyboard behaviour from the old UI: Space plays/pauses (not inside inputs or dialogs), Esc closes the drawer, popover, menu or dialog. Respect `prefers-reduced-motion`.
- Node ≥ 20.19 locally, `node:22-bookworm-slim` in Docker. No dependency beyond `react`, `react-dom` and SoundPilot's dev dependencies.
- `/legacy` serves the old `ui/index.html`; `/dev` unchanged.
- Commit style: `<type>(<scope>): <summary>` (see `docs/contributing.md`); scopes `ui`, `api`, `docker`, `ci`.

## Review Focus

- Switching jobs while audio plays: playback stops, buffers of the old job are released, SSE messages from the old job are ignored.
- A second edit while a command is still running: buttons disabled; if a 409 still arrives, the message says another change is running and nothing is half-applied in the view.
- Silent video: Separate disabled with its reason, no residual lane, every span read-only.
- A source whose separation or generation failed: lane shows "Failed" and the step message, no waveform, Play disabled, no stale audio played.
- Upload rejected (too long, too large, not a video): the dialog shows the server's `detail` and keeps the chosen file.

---

### Task 1: Build, serve and ship the web app

**Files:**
- Create: `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx` (placeholder "Audyssey" heading), `web/src/styles.css` (SoundPilot tokens and base rules), `web/tests/smoke.test.mjs`
- Modify: `src/audyssey/api.py` (root, `/assets`, `/legacy`), `.gitignore`, `.dockerignore`, `docker/app.Dockerfile`, `.github/workflows/ci-lint.yaml`, `.github/workflows/publish-images.yaml`, `pyproject.toml` (include `src/audyssey/webui/**` if the wheel check needs it)
- Test: `tests/test_audyssey_api.py`

**Interfaces:**
- Produces: `npm run build` writes `src/audyssey/webui/index.html` and `src/audyssey/webui/assets/*`; `npm test` runs `node --test --test-concurrency=1 tests/*.test.mjs`; Vite dev proxy `/api` → `http://127.0.0.1:8600`.
- Produces: `create_app(..., webui_dir: Path | None = None)` — when `webui_dir/index.html` exists, `/` returns it and `/assets` serves `webui_dir/assets`; otherwise `/` returns `ui/index.html`. Default `webui_dir` = `files("audyssey") / "webui"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_audyssey_api.py`:
  - `test_root_falls_back_to_single_file_ui`: with `webui_dir` pointing to an empty temp dir, `GET /` is 200 and contains `id="board"`.
  - `test_root_serves_built_web_ui`: temp dir with `index.html` containing `<div id="root"></div>` and `assets/app.js`; `GET /` contains `id="root"`, `GET /assets/app.js` is 200.
  - `test_legacy_serves_single_file_ui`: `GET /legacy` contains `id="board"`.
- [ ] **Step 2: Run** `uv run python -m unittest tests.test_audyssey_api -k root -k legacy` — expect FAIL.
- [ ] **Step 3: Implement** the serving logic in `api.py`; copy SoundPilot's `package.json` (rename to `audyssey-web`), `tsconfig.json`, `vite.config.ts` (set `build.outDir: "../src/audyssey/webui"`, `emptyOutDir: true`, proxy target 8600), `index.html` (title "Audyssey"), `main.tsx`.
- [ ] **Step 4: Ignore rules** — `.gitignore`: add `!/web/package.json`, `!/web/package-lock.json`, `!/web/tsconfig.json`, `!/web/src/lib/`, `web/node_modules/`, `/src/audyssey/webui/`. Verify with `git check-ignore -v web/package.json web/src/lib/x.ts` (expect no match) and `git check-ignore -v src/audyssey/webui/index.html` (expect a match). `.dockerignore`: add `web/node_modules`, `web/dist`.
- [ ] **Step 5: Docker** — `docker/app.Dockerfile`: first stage `FROM node:22-bookworm-slim AS frontend`, `WORKDIR /app/web`, copy `web/package.json web/package-lock.json`, `npm ci`, copy `web/`, `npm run build` (outDir resolves to `/app/src/audyssey/webui`); final stage `COPY --from=frontend /app/src/audyssey/webui src/audyssey/webui` after `COPY src/ src/`.
- [ ] **Step 6: CI** — `ci-lint.yaml`: add job `web` (setup-node 22 with npm cache on `web/package-lock.json`, `npm ci`, `npm test`, `npm run build`, `timeout-minutes: 10`, working-directory `web`), copied from SoundPilot `ci-lint.yaml`. `publish-images.yaml`: add `web/**` to `paths`.
- [ ] **Step 7: Verify** — `uv run python -m unittest discover tests` PASS; `cd web && npm ci && npm test && npm run build` PASS; `uv build --wheel` then `unzip -l dist/*.whl | grep webui/index.html` finds the file (add the include to `pyproject.toml` only if it does not); `docker buildx build --builder audyssey-builder -f docker/app.Dockerfile -t audyssey-app:sp-ui --load .` succeeds and `docker run --rm audyssey-app:sp-ui ls /app/src/audyssey/webui/index.html` prints the path.
- [ ] **Step 8: Commit** — `build(ui): serve a Vite web app with a fallback to the single-file UI` (split into `ci` / `docker` commits if the diff reads better).

### Task 2: Types, API client and the Job adapter

**Files:**
- Create: `web/src/types.ts`, `web/src/api.ts`, `web/src/lib/adapter.ts`, `web/src/lib/span.ts`, `web/src/lib/errors.ts` (copy from SoundPilot)
- Test: `web/tests/adapter.test.mjs`, `web/tests/span.test.mjs`, `web/tests/errors.test.mjs` (copy)

**Interfaces:**
- Produces in `types.ts`: TypeScript mirrors of `Job`, `Source`, `SourcePlan`, `Span`, `VisualHint`, `FilterResult`, `Residual`, `StepStatus`, `RenderOutput`, `PlanIssue` and the command union `Command` (fields exactly as in `src/audyssey/contracts.py`), plus `Lane` (shape of `/api/system` items) and `TraceCall` (one `trace.jsonl` record).
- Produces in `api.ts`: `listJobs(): Promise<Job[]>`, `getJob(id): Promise<Job>`, `uploadVideo(file: File): Promise<Job>`, `startJob(id, method: "separate" | "generate"): Promise<Job>`, `sendCommand(id, cmd: Command): Promise<Job>`, `getTrace(id): Promise<TraceCall[]>`, `getSystem(): Promise<Lane[]>`, `routeRequest(id, text: string): Promise<RouteResult>` (shape from `api.py` `/route`), `exportUrl(id): string`, `fileUrl(id, path): string`, `jobEvents(id): EventSource`. Non-2xx throws `ApiError { status: number; detail: string }`.
- Produces in `adapter.ts`: `jobToView(job: Job): JobView` where `JobView = { rows: TrackRow[]; residual: ResidualRow | null; skipped: Source[]; duration: number }`, `TrackRow = { id; name; kind; origin: "separated" | "generated"; status; keep; gain; pitch; trackPath: string | null; spans: SpanBox[]; spansEditable: boolean; pairOf: string | null; filter: FilterResult | null; attempts: number; color: string }`, `SpanBox = { id: string /* `${sourceId}#${index}` */; start: number; end: number }`.
- Produces in `span.ts`: seconds-based `clampSpan(s, duration)`, `moveSpan`, `resizeSpan`, `MIN_SPAN = 0.1`.

- [ ] **Step 1: Write failing tests** — `adapter.test.mjs`:
  - a generated source with `replaces: "s1"` is placed right after `s1` and both carry `pairOf`;
  - sources with `status: "skipped"` go to `skipped`, not `rows`;
  - `residual` is null when `job.residual.path` is null;
  - `spansEditable` is false for generated sources and for every source when `job.silent`;
  - span ids are `s2#0`, `s2#1`.
  `span.test.mjs`: moving a span past the end clamps to `duration`; resizing below 0.1 s keeps 0.1 s.
- [ ] **Step 2: Run** `cd web && npm test` — expect FAIL.
- [ ] **Step 3: Implement** the three modules; colours from a fixed palette indexed by row order (reuse SoundPilot `objectColor` from `lib/selection.ts`).
- [ ] **Step 4: Run** `npm test` — PASS.
- [ ] **Step 5: Commit** — `feat(ui): job types, API client and job-to-view adapter`.

### Task 3: Audio engine and waveform

**Files:**
- Create: `web/src/lib/audioEngine.ts` (port of `ui/index.html` engine: `play`, `pause`, `seek`, `tick`, `useMix`, track buffers keyed by URL), `web/src/lib/waveform.ts`, `web/src/lib/selection.ts` (copy SoundPilot, keep `transportAction`, `soloToggleAction`, `reconcileSelection`, `objectColor`, `statusView`; drop model labels), `web/src/lib/gain.ts` (copy, `GAIN_MAX_PERCENT = 200`)
- Test: `web/tests/waveform.test.mjs`, `web/tests/engine.test.mjs`, `web/tests/transport.test.mjs`, `web/tests/selection.test.mjs`, `web/tests/gain.test.mjs` (copy and adjust)

**Interfaces:**
- Produces: `class AudioEngine { constructor(video: HTMLVideoElement, ctx?: BaseAudioContext); setTracks(tracks: { id: string; url: string | null }[]): Promise<void>; play(): void; pause(): void; seek(t: number): void; now(): number; playOnly(id: string | null): void; setSolo(id: string | null): void; setGain(id: string, gain: number): void; setKeep(id: string, keep: boolean): void; setMode(mode: "edit" | "original"): void; dispose(): void; onTime(cb: (t: number) => void): () => void }`.
- Produces: `effectiveGain(track: { gain: number; keep: boolean }, solo: string | null, id: string): number` (pure), `peaksDb(samples: Float32Array, buckets: number): Float32Array` mapping −60…0 dBFS to 0…1.

- [ ] **Step 1: Write failing tests** — `effectiveGain` returns 0 for a dropped track, 0 for a non-solo track while another is soloed, `gain` otherwise; `peaksDb` maps a full-scale sine to ≈1, −60 dBFS to 0, silence to 0; `engine.test.mjs` with a fake `AudioContext` (object with `currentTime`, `createGain`, `createBufferSource`) checks that `seek(3)` while playing restarts sources at offset 3 and that `dispose()` stops every source.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `feat(ui): Web Audio engine with solo and dB waveforms`.

### Task 4: App shell, top bar and Open video dialog

**Files:**
- Create: `web/src/App.tsx` (replace placeholder), `web/src/components/TopBar.tsx`, `web/src/components/OpenVideoDialog.tsx`, `web/src/components/Icon.tsx` (copy), `web/src/lib/status.ts`, `web/src/lib/projects.ts`
- Test: `web/tests/status.test.mjs`, `web/tests/topbar.test.mjs`, `web/tests/projects.test.mjs`, `web/tests/app-follow.test.mjs`

**Interfaces:**
- Consumes: Task 2 `api.ts`, Task 3 `AudioEngine`.
- Produces: `statusLine(job: Job | null, busy: string | null): { tone: "idle" | "run" | "done" | "fail"; text: string; progress: number | null }`; `projectRow(job: Job): { id: string; label: string; detail: string }`; `useJob(): { job: Job | null; follow(id: string): void; busy: string | null; run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined>; error: string | null }` exported from `App.tsx` module scope or `lib/useJob.ts`.

- [ ] **Step 1: Write failing tests** —
  - `statusLine`: `state "new"` → "Choose Separate or Generate to start."; a running `separate:s2` step with 1 of 3 sources done → text "Separating 2 of 3", progress ≈ 0.33; `failed` → tone "fail" and `job.error`; busy "export" → "Exporting…".
  - TopBar SSR: silent job in state "new" renders the Separate radio disabled with text "No original audio to separate."; state "ready" renders the method as a badge, no radio.
  - `projectRow`: label is the first 6 chars of the id; detail lists state, duration "7.1 s", method and track count.
  - `app-follow`: a message whose `id` differs from the followed job or whose `version` is lower than the last one is ignored.
  - `run()` with a command that rejects with `ApiError { status: 409 }` sets `error` to "Another change is still running." and clears `busy`.
  - OpenVideoDialog SSR with `uploadError = "video is 40.0s; maximum is 30s"` shows that text next to the file input.
- [ ] **Step 2–4:** run FAIL → implement → PASS. The dialog is a native `<dialog>`: file input, Upload button, recent projects list (newest first, open on click). Upload errors show `ApiError.detail` and keep the file. Primary button: "Separate audio" / "Generate audio" → `startJob`; Export button → `render` then download `exportUrl`.
- [ ] **Step 5: Commit** — `feat(ui): app shell, status line and Open video dialog`.

### Task 5: Stage and highlight box

**Files:**
- Create: `web/src/components/Stage.tsx` (copy, seconds slider, `x.xx s / y.yy s`), `web/src/components/HighlightOverlay.tsx`, `web/src/lib/highlight.ts`
- Test: `web/tests/highlight.test.mjs`, `web/tests/stage.test.mjs`

**Interfaces:**
- Produces: `visibleBoxes(rows: TrackRow[], sources: Source[], selected: string | null, t: number): { id: string; box: [number, number, number, number]; color: string }[]` — selected source only when selected, all when not; a box is visible when `|t − hint.time| ≤ 0.5`; `highlightChip(row, source, t): string | null` → "Highlighting {name}" / "{name} has no on-screen location".

- [ ] **Step 1: Failing tests** for the 0.5 s window, the no-hint chip, and the "nothing selected" case.
- [ ] **Step 2–4:** FAIL → implement (absolute-positioned boxes over the `<video>` content rect, computed from the element size and `videoWidth/videoHeight`) → PASS.
- [ ] **Step 5: Commit** — `feat(ui): stage with visual-hint highlight`.

### Task 6: Timeline

**Files:**
- Create: `web/src/components/Timeline.tsx` (adapted from SoundPilot: ruler + scrub, lanes, Play/Solo, waveform, span boxes, volume slider, keep switch, residual lane, draft lane hook-in), `web/src/lib/pendingEdits.ts` (per-source span drafts)
- Test: `web/tests/timeline-order.test.mjs`, `web/tests/timeline-lanes.test.mjs`, `web/tests/pending-edits.test.mjs`, `web/tests/track-edit-ui.test.mjs`

**Interfaces:**
- Consumes: `JobView` (Task 2), `AudioEngine`, `effectiveGain`, `peaksDb` (Task 3).
- Produces: `pendingEdits` API `{ get(sourceId): Span[] | null; set(sourceId, spans: Span[]): void; discard(sourceId?): void; dirty(): string[] }`; Timeline props `{ view; engine; selected; onSelect(id); onSpansChange(id, spans); onGainCommit(id, gain); onKeepChange(id, keep); disabled: string | null }`.

- [ ] **Step 1: Failing tests** — lanes appear in `rows` order with the residual lane last; a generated lane renders spans without drag handles and a title "Spans of generated tracks cannot be edited."; deleting the only span of a source is refused; a failed source renders "Failed", no waveform, Play disabled; volume slider max is 200 and double-click restores 100; keep switch for one side of a pair sends `keep` for it and `drop` for its pair (as `ui/index.html` does).
- [ ] **Step 2–4:** FAIL → implement → PASS. Span box drag: move by body, resize by edges, Delete/Backspace removes a selected box. Volume: `engine.setGain` while dragging, `onGainCommit` on release.
- [ ] **Step 5: Commit** — `feat(ui): timeline with solo, dB waveforms and span editing`.

### Task 7: Selected track, new track and plan panels

**Files:**
- Create: `web/src/components/SelectedTrackPanel.tsx`, `web/src/components/NewTrackPanel.tsx`, `web/src/components/PlanPanel.tsx`, `web/src/components/VideoEditor.tsx` (layout glue: stage | side panel, timeline below), `web/src/lib/trackActions.ts`, `web/src/lib/newTrack.ts`
- Test: `web/tests/track-actions.test.mjs`, `web/tests/selected-panel.test.mjs`, `web/tests/new-track.test.mjs`, `web/tests/plan-panel.test.mjs`, `web/tests/regenerate-guard.test.mjs`

**Interfaces:**
- Produces: `primaryAction(row: TrackRow, method: "separate" | "generate", pendingSpans: Span[] | null, job: Job): { label: string; command: Command } | { label: string; disabledReason: string }` with labels "Re-separate", "Regenerate", "Generate instead", "Regenerate with new spans"; `newTrackCommand(form, spans, job): Command` building `add_source`.

- [ ] **Step 1: Failing tests** —
  - separated row, method separate, pending spans → "Regenerate with new spans" with `reseparate {spans}`;
  - separated row, method generate → "Generate instead" with `generate`;
  - dialogue row, method generate → disabled "Speech is not generated.";
  - silent job, method separate → disabled "No original audio to separate.";
  - `newTrackCommand` for a silent job forces `method: "generate"`; dialogue + generate is refused with "Speech is not generated.";
  - regenerate guard: disabled while `job.state === "running"` or `busy !== null`;
  - plan panel lists `plan_issues` and skipped sources, and clicking a span calls `onSeek(start)`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Pitch stepper (±1 semitone, −12…12) sends `set_pitch` then `render`; description edits are sent with the primary command; the panel shows attempt count and the judge/score `reason` and scores.
- [ ] **Step 5: Commit** — `feat(ui): selected-track, new-track and plan panels`.

### Task 8: Pipeline board, inspector and edit bar

**Files:**
- Create: `web/src/components/PipelineBoard.tsx`, `web/src/components/EdgePopover.tsx`, `web/src/components/Inspector.tsx`, `web/src/components/EditBar.tsx`, `web/src/lib/board.ts` (pure layout: node positions, edge list, node state)
- Test: `web/tests/board.test.mjs`, `web/tests/inspector.test.mjs`, `web/tests/edit-bar.test.mjs`

**Interfaces:**
- Consumes: `getTrace`, `getSystem`, `routeRequest`, `sendCommand` (Task 2).
- Produces: `nodeState(job: Job, step: string): { status; sub: string }`, `boardLayout(lanes: Lane[], job: Job | null)` returning nodes and edges (ported from `ui/index.html` `drawBoard`, `FLOW`, `LINKS`).

- [ ] **Step 1: Failing tests** — `nodeState` for a validation round 2 returns sub "Round 2"; separate step with 2 of 4 done returns "2/4"; generate/score nodes are idle for a job without generated sources; inspector renders frames, clips, prompt and response for a `TraceCall` with `requests`; edit bar renders a command card with Run / Edit / Cancel for a `set_gain` result and clarify chips for a `clarify` result.
- [ ] **Step 2–4:** FAIL → implement → PASS. Board sits in a collapsible full-width panel: open while `job.state === "running"`, closed when ready (user toggle wins). Recolour board edges for the dark background (video `#8ab4ff`, audio `#d6a94a`, text `#6fdc9a`).
- [ ] **Step 5: Commit** — `feat(ui): pipeline board, inspector and edit bar`.

### Task 9: End-to-end check and docs

**Files:**
- Modify: `README.md`, `docs/running.md`, `docs/status.md`, `docs/architecture.md` (web app location, build, `/legacy`)
- Create: `web/tests/e2e/README.md` only if a Playwright script is kept (otherwise no file)

- [ ] **Step 1: Stub stack** — `cd web && npm run build`; `AUDYSSEY_PLANNER=stub AUDYSSEY_SEPARATOR=stub AUDYSSEY_FILTER=stub AUDYSSEY_GROUNDER=stub AUDYSSEY_GENERATOR=stub AUDYSSEY_WORK_DIR=<scratch> uv run audyssey serve --port 8611`.
- [ ] **Step 2: Headless browser walk** (Playwright with the cached `chrome-headless-shell`, 1440×900 and 390×844): upload `samples/sample.mp4` → start Separate → board runs → tracks appear → Play/Solo → drag a span and "Regenerate with new spans" → volume and keep → new track with two spans → Export downloads a zip; silent copy of the sample → Generate → Separate radio disabled, residual lane absent. Expect no page errors and no horizontal overflow at 390 px.
- [ ] **Step 3: Review Focus walk** — switch jobs while playing; click a second edit during a running command; upload a 40 s video (expect the duration error in the dialog).
- [ ] **Step 4: Docs** — describe `web/`, `npm run build`, dev proxy, `/legacy`, and the Phase 2 list.
- [ ] **Step 5: Commit** — `docs(ui): web app build and the SoundPilot layout`.
