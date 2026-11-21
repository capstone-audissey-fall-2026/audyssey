# Planning and validation: evidence-based baseline

This baseline separates two tasks: identifying existing sounds for separation,
and proposing scene-appropriate sounds for generation. All model instructions are
English and versioned in `src/audyssey/tools/planning/prompts.py`.

## Runtime behavior

- The app and Studio pass the job method and audio availability through
  `planning_scope`. It uses ContextVar and resets after each tool call. Existing
  tool signatures, SourcePlan and stored Job JSON stay compatible.
- Separation requires audible evidence. A visible silent object is insufficient;
  audible offscreen sources remain valid.
- Validation has two modes, chosen by `AUDYSSEY_VALIDATOR_AUDIO`. Unset, audio
  mode is used only when `INPUT=video` and `VIDEO_AUDIO=true`. `true` sends the
  WAV even with frames input; `false` forces visual mode.
- Audio mode sends 16 kHz stereo PCM16 WAV windows from the original audio. If
  the audio exceeds the inline limit (about 3.5 minutes), that source falls back
  to visual validation. `AUDYSSEY_VALIDATOR_AUDIO_ONLY=true` (default) omits
  visual cues; `false` compares video-plus-audio. Generation keeps using
  video/frames.
- Visual mode judges separation from frames. Music, ambience and offscreen
  sources cannot be seen, so they pass as informational `not_validated` issues
  and do not block or skip the source. `visual_hint_not_found` is likewise
  informational.
- Digitally silent target intervals are rejected locally before any model call.
  This only checks numerical silence near float32 precision; it is not VAD or a
  calibrated audibility threshold. Stereo is retained to avoid phase cancellation.
- Generation checks scene appropriateness and does not require a proposed sound
  to exist in the original audio. Dialogue generation remains unsupported.
- A genuinely empty `sources` list is valid. A non-empty list containing only
  malformed sources remains an error.
- Validators return `status: supported|unsupported|uncertain`,
  `evidence: audio|visual|audio_visual|none`, and a short English `reason`.
  Visual-only evidence cannot approve separation. An unavailable audio input
  cannot be reported as audio evidence.
- Invalid JSON is retried once and then becomes `validation_error`, never an
  approval. Transport/provider failures still fail the graph's validation step.
- The existing plan-round limit applies. After the last round, sources with
  unresolved issues are marked `skipped` with a warning and do not invoke GPU
  tools. Valid sources continue. A global issue affects all sources.
- Replanning is per source: sources that pass validation are accepted and passed
  to the planner as `accepted_sources`; only failing sources are replanned. The
  UI lists skipped sources with their reasons above the track table.
- `ready` means graph processing ended, not that every source was approved.
  Inspect `plan_issues`, source status and step warnings. If every source in a
  separation job is skipped, residual retains the original soundtrack.

For the existing OpenRouter configuration:

```dotenv
AUDYSSEY_PLANNER_API=openrouter
AUDYSSEY_PLANNER_INPUT=video
AUDYSSEY_PLANNER_VIDEO_AUDIO=true
# Unset validator overrides inherit the planner's settings.
AUDYSSEY_VALIDATOR_CONTEXT_S=0.5
AUDYSSEY_VALIDATOR_AUDIO_ONLY=true
```

Audio mode needs a validator model that actually accepts audio input. For a
vision-only model set `AUDYSSEY_VALIDATOR_AUDIO=false`. Stub behavior remains
deterministic for offline integration tests.

## Context and timestamps

Each target interval receives 0.5 seconds of context on both sides by default.
Set `AUDYSSEY_VALIDATOR_CONTEXT_S` between 0 and 5 seconds. Context is bounded to
the video; overlapping or touching context intervals are merged.

The request lists `target_intervals` and `context_intervals` independently. A sound
present only in the padding does not support the target interval. Video clips
start at zero internally, so the English instruction explicitly gives:

```text
original_time = clip_start + local_time
```

This improves the evidence given to the model; it is not a measured event-boundary
detector. VAD, ASR, sound-event detection and CLAP checks are future experiments.

## Small controlled evaluation set

`evals/planning/cases.jsonl` contains eight reproducible controls. FFmpeg and NumPy
produce three-second videos, two electronic beeps, and silent variants. The silent
and audible blinking-square variants copy the same encoded video stream.
Fixtures use H.264 video and lossless PCM audio in Matroska; the real input adapter
converts them to MP4 or PCM WAV. Candidate names are neutral and do not reveal labels.

Cases cover audible/visible beeps, a visible but silent square, offscreen beeps,
sound only outside the requested interval, an incorrect speech hypothesis, missing
audio evidence, unsupported generated dialogue, and a proposed sound for a silent
blinking scene.

Seven references follow the synthetic waveform or explicit application policy.
The generation-plausibility example is marked `needs_review` and excluded from
accuracy. These are synthetic controls, not a human-reviewed real-world benchmark.
Add reviewed speech, overlapping effects and actual project clips before claiming
general quality improvements. Keep clips from the same original in the same
evaluation split when adding train/dev/test data.

From the repository root, prepare fixtures without model calls:

```powershell
uv run --locked python -m audyssey.planning_eval prepare --out .cache/planning-fixtures-v1
```

Evaluate candidate validation using your configured LLM:

```powershell
uv run --locked --env-file .env --extra llm python -m audyssey.planning_eval run --fixtures .cache/planning-fixtures-v1 --out .cache/planning-run-v1 --yes
```

Add `--include-planning` to also generate a whole-video plan for each case. This
adds model calls; source-count matching is reported separately and does not measure
semantic correctness or temporal accuracy. Review the saved sources manually.
`run` requires `--yes`; no GPU tools are called. Output folders are never overwritten.

Each run saves:

- `config.json`: prompt version, model/input settings, dataset hash and media hashes;
  no API keys or endpoint credentials.
- `cases.jsonl`: decisions, issue kinds, source plans, errors and latency per case.
- `summary.json`: accuracy on scored references (errors count as misses), false
  approvals, error counts, review-required cases and optional source-count accuracy.
- Per-case traces containing actual prompts, media, responses and token usage.

Change one prompt/model/context setting per comparison. An experiment that returns
provider errors is not evidence of low semantic accuracy: report errors separately.
Do not tune on a held-out real-world test set.

The initial synthetic smoke result and its limits are recorded in
[`evals/planning/report.md`](../evals/planning/report.md).
