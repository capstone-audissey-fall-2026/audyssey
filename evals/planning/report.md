# Planning validation smoke experiment (2026-11-21)

This is a development smoke experiment on synthetic controls, not a real-world accuracy benchmark. No GPU tools were invoked.

## Configuration

- Model: `google/gemini-2.5-flash` via `openrouter`.
- Prompt version: `planning-evidence-v2`.
- Context padding: 0.5 seconds; audio-only separation validation: `true`.
- Dataset SHA-256: `b2f48f4f93c9a2735fec16b46a7c4ce0e824bc53a8e8a5b82e8389f2795ef670`.
- Whole-video planning: disabled in this run. Actual validation LLM requests: 4.
- Two acoustic negatives are decided by numerical-silence checks; two policy cases require no model. Three scored cases exercise the LLM, and one unscored generation case exercises the LLM.
- Synthesized H.264/PCM inputs; candidate names are neutral. No reference labels were sent to the model.

## Results

| Case | Expected | Actual | Reference |
|---|---|---|---|
| audible-visible | accept | accept | synthetic |
| visible-silent | reject | reject | synthetic |
| audible-offscreen | accept | accept | synthetic |
| outside-target | reject | reject | synthetic |
| wrong-sound | reject | reject | synthetic |
| audio-unavailable | uncertain | uncertain | synthetic |
| generation-dialogue | reject | reject | synthetic |
| generation-blink | accept | accept | needs_review |

Scored controls: 7; matches: 7; false approvals: 0; execution errors: 0.

## Limits and next experiment

- The generation-plausibility case remains `needs_review` and is excluded from the score.
- The initial prompt-only iteration approved three acoustic negatives. The final iteration combines revised prompts, a digital-silence guard and audio-only input; this does not isolate the contribution of each change.
- The earlier iteration also ran whole-video planning, so its total runtime is not comparable. This report makes no speedup claim.
- These development cases were used while implementing the policy. They are not held out and cannot establish generalization.
- Add human-reviewed speech, overlapping sounds, quiet real backgrounds, offscreen sources and short transients. Measure source precision/recall and boundary error separately from validator decisions.
- The real whole-video planner still needs a real-world coverage evaluation. A source-count match does not establish source identity or timing correctness.
- Re-run after changing prompt/model/input settings; store config, media hashes and traces in a fresh output directory. Raw local artifacts for this run are in `.cache/planning-openrouter-v4/` and are intentionally untracked.

## Implementation checks

- Ruff lint/format, ty and UI JavaScript syntax checks passed.
- Related graph/planner/evaluation/settings/tool tests passed (120 tests).
- Windows full suite: 381 tests, 371 passed, 10 errors. The unchanged main baseline ran 358 tests and reproduced the exact same 10 errors: nine FFmpeg development-build `-vsync` incompatibilities and one Windows symlink privilege error. No tests were skipped or weakened to hide those errors.
