# SoundPilot UI for Audyssey: design

2026-11-26. Port the SoundPilot web UI (`gwpark0741/soundpilot`, `web/`, commit 0838ad7) to Audyssey, including its features, in English.
Feature mapping with file and line references: `docs/superpowers/plans/2026-11-26-soundpilot-ui-mapping.md`.

## Decisions (user, 2026-11-26)

- Port the features, not only the look. UI copy in English.
- Two phases.
  - **Phase 1**: no change to `contracts.py`; everything the current API already supports.
  - **Phase 2** (separate PR, team agreement for `contracts.py`): clip trim/move, trim to spans, a real track delete command (`RemoveSource`), volume up to 400%, project name and creation time on `Job`.
- Projects: show name and date (Phase 2, `Job.name`, `Job.created`). No project delete, no bundle import/export.
- Theme: SoundPilot's dark tokens. Audyssey's pipeline board and inspector are kept and recolored.
- The current single-file UI stays at `/legacy` during the transition; `/dev` stays.

## Architecture

- `web/`: React 19 + Vite + TypeScript app, copied from SoundPilot and adapted. No new runtime dependency beyond `react`, `react-dom`.
- Build output: `src/audyssey/webui/` (git-ignored). FastAPI serves `webui/index.html` at `/` and `webui/assets` at `/assets`; when `webui/` is absent it falls back to `ui/index.html`, so Python-only CI keeps working.
- State: the app follows one job (`jobId` in the URL hash) through `GET /api/jobs/{id}/events` (SSE, full `Job` JSON); stale messages (lower `version`, other job) are dropped.
- Playback: Audyssey's Web Audio engine (video muted, `AudioContext` as the master clock, every track mixed live). Play one track, Solo, keep and gain apply without a server round trip; pitch needs a server render.
- Units: seconds everywhere (`Span`, `Job.duration`); SoundPilot's frame-based helpers are converted.
- Adapter: `jobToView(job)` turns `Job` into the rows the components draw (track rows, span boxes, residual row, pairs of a separated source and its generated replacement kept on adjacent rows).

## Layout (desktop)

```
Top bar:  Audyssey [Original audio|Silent video] [Open video]  status line + progress   (Generate|Separate) [Separate audio]  [Export]
Pipeline: collapsible full-width board (open while running, closed when ready); click a step -> inspector drawer
Main:     Stage (video, highlight box, transport)          | Side: Selected track panel / New track panel / Plan panel
Bottom:   Edit bar (natural-language request) above the timeline: ruler + track lanes + residual lane + draft lane
```

## Feature map, Phase 1

| SoundPilot feature | Audyssey behaviour |
|---|---|
| Status line + progress | From `Job.state`, `Job.steps` (running step label, `round/max_rounds`, done/total per-source steps) |
| Input badge | `Job.silent` → "Silent video", else "Original audio" |
| Generate / Separate radio + primary button | Enabled only when `state == "new"`; the button calls `POST /api/jobs/{id}/start {method}`. Separate disabled for silent videos ("No original audio to separate."). After start: read-only badge from `Job.method` |
| Open video dialog | Upload form (`POST /api/jobs`) and recent projects (`GET /api/jobs`): short id, state, duration, method, track count. Upload errors show the server `detail` |
| Stage + highlight | `<video>` of `job.video_path`; the selected source's `visual_hint` box drawn within ±0.5 s of `hint.time`; chip "Highlighting {name}" or "{name} has no on-screen location"; nothing selected → every hint box in its track colour |
| Ruler scrub, playhead | Seconds |
| Lane Play / Solo | Web Audio engine: play one source from the playhead; Solo mutes the others |
| Waveform | Computed in the browser from the decoded track, dB scale −60…0 dBFS → 0…1, times gain |
| Span boxes | Move, resize, delete (at least one span per source); edits pending until "Regenerate with new spans" (`reseparate {spans}`). Separated sources only; spans of generated sources are read-only with the reason shown |
| Volume | Slider 0–200 %, live gain while dragging, `set_gain` on release, double-click resets to 100 % |
| Keep | Switch → `keep` / `drop` (for a pair, one side at a time as today) |
| Include rest of original audio | `keep`/`drop` with `source_id: "residual"`; hidden when there is no residual |
| Selected track panel | Status, origin badge, attempt, judge/score result, description edit, method select "Separate (SAM Audio)" / "Generate (internal model)", primary button "Re-separate" / "Regenerate" / "Generate instead" / "Regenerate with new spans", pitch stepper (`set_pitch` then `render`), failure message from the step |
| New track | Draft lane with one 2 s span at the playhead, drag on empty lane to add spans, double-click to remove; form: name, kind (sfx, ambience, music, dialogue), description, method → `add_source` |
| Plan panel (replaces Analysis) | Sources with kind, description, spans (click to seek), `plan_issues`, sources skipped by validation |
| Pipeline board, edge popover, inspector | Ported from `ui/index.html` as React components |
| Edit bar | Ported natural-language request bar (`/route`) with command cards |
| Export | `render`, then download `/api/jobs/{id}/export` |
| Busy handling | Audyssey commands block until done and return 409 "job is busy"; one command at a time, controls disabled while a command or the job runs, 409 shown as "Another change is still running." |

Not ported: SAM3 masks and RLE decoding, objects lane, analysis panel, model picker entries other than separate/generate, TTS and spoken text, per-event regenerate, bundle, clean workspace, reset/rerun, advanced run options.

## Phase 2 (separate plan)

`contracts.py`: `Source.clip_start/clip_end/clip_offset` + `SetClip`; `Source.trim_to_spans` + `TrimToSpans`; `RemoveSource`; gain upper bound 2 → 4 (`Source.gain`, `Residual.gain`, `SetGain.gain`); `Job.name`, `Job.created`. Matching changes in `graph.py`, `tools/editing/render.py`, the UI (Edit audio mode, trim, delete dialog, 400 % slider, project names and dates).

## Risks

- `.gitignore` ignores `*.json` and `lib/`; `web/package.json`, `package-lock.json`, `tsconfig.json` and `web/src/lib/` need exceptions.
- Core files touched in Phase 1: `api.py`, `docker/app.Dockerfile`, `pyproject.toml` (approval from @gwpark0741 or @Zero-woo), `.github/` (@gwpark0741).
- The app image gains a Node build stage.
