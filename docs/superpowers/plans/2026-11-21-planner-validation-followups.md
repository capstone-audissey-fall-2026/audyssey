# Planner Validation Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support audio and visual plan validation as equal modes, make plan/validate per-source (accepted sources are kept, only failing ones are replanned), and stop dropping sources for non-validation reasons.

**Architecture:** `real.validate_plan` picks audio or visual mode per source from a new `validator_audio` setting (falling back to the current video+audio rule) and from the inline size limit. The graph keeps a list of accepted source names in `AnalysisState`; the planner receives accepted plans through `planning_scope` and only new sources are validated. Issue kinds are split into informational, skip-blocking and replan-triggering sets in `graph.py`.

**Tech Stack:** Python 3.13, LangGraph, pydantic-settings, numpy/scipy, unittest; vanilla JS UI.

**Spec:** `docs/superpowers/specs/2026-11-21-planner-validation-followups-design.md`

## Global Constraints

- No paid API calls, no GPU. Verify with unit tests and stub runs only.
- Do not change tool signatures `plan(video, audio, duration, feedback)` / `validate_plan(video, audio, plans)`. Pass per-request data through `planning_scope` (ContextVar).
- Do not change `src/audyssey/contracts.py`.
- New setting: `validator_audio: bool | None = None` (env `AUDYSSEY_VALIDATOR_AUDIO`). `None` → use `_hears(endpoint)` (`input == "video" and video_audio`). A set value is authoritative: when true, WAV is sent regardless of `input`.
- Validation WAV is 16000 Hz, stereo kept (`scipy.signal.resample_poly(data, 1, 3, axis=0)`), PCM16.
- Prompt version string becomes `"planning-evidence-v3"`.
- Informational issue kind: `"not_validated"`. Kinds that do not skip separation: `"visual_hint_not_found"`, `"not_validated"`. Every non-informational kind triggers replanning and blocks acceptance.
- Validate step and round-limit plan warning use `"warning"` only when a non-informational issue exists.
- Empty plan: plan step `status="warning"`, `message="No sources proposed"`; job still ends `ready`.
- Never run `ruff format` on `tests/`. Run `ruff check` and `ruff format` on `src/` only.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. The planner re-emits an accepted source name with a changed description → the new copy is dropped, the accepted `Source` (and its user edits) stays unchanged. Test in Task 4.
2. Visual mode on an endpoint whose `video_audio` is true but `validator_audio=false` → clips are cut without audio. Test in Task 1.
3. All sources pass in round 1 → no replanning; plan step stays at round 1. Test in Task 4.
4. Oversize audio for a music source → falls back to visual mode → `not_validated`, no request sent. Test in Task 2.
5. A round with a format issue on one source still validates the other new sources in the same round. Test in Task 4.

---

### Task 1: Audio/visual validation modes

**Files:**
- Modify: `src/audyssey/settings.py` (validator fields, ~line 80)
- Modify: `src/audyssey/tools/planning/prompts.py` (`VERSION`, `validator_prompt`)
- Modify: `src/audyssey/tools/planning/real.py` (`validate_plan`, ~lines 440–550)
- Modify: `src/audyssey/planning_eval.py` (config dict, ~line 173)
- Test: `tests/test_audyssey_planner_real.py`, `tests/test_audyssey_settings.py`

**Interfaces:**
- Produces: `Settings.validator_audio: bool | None`; `prompts.validator_prompt(purpose, hears)` with a visual separation branch; `PlanIssue(kind="not_validated")` from `validate_plan`.

- [ ] **Step 1: Write the failing tests** (in `PlannerRealTests`; default env in `setUp` has no validator input → visual mode)

```python
def test_separation_visual_mode_validates_visible_producer(self):
    self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "a person talks on screen"})]
    issues = real.validate_plan(self.video, self.audio, [self.visible()])
    self.assertEqual(issues, [])
    system = self.requests[0]["messages"][0]["content"]
    self.assertIn("producer", system)
    self.assertIn("cannot hear", system)

def test_separation_visual_mode_passes_music_ambience_and_offscreen_without_call(self):
    plans = [SourcePlan(**self.source(name="wind", kind="ambience")),
             SourcePlan(**self.source(name="score", kind="music")),
             SourcePlan(**self.source(name="narrator"))]  # no visual_hint → offscreen
    issues = real.validate_plan(self.video, self.audio, plans)
    self.assertEqual([(i.source_name, i.kind) for i in issues],
                     [("wind", "not_validated"), ("score", "not_validated"), ("narrator", "not_validated")])
    self.assertEqual(self.requests, [])

def test_validator_audio_false_strips_audio_from_clips(self):
    calls = self.clip()
    self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "person visible"})]
    env = {"AUDYSSEY_VALIDATOR_INPUT": "video", "AUDYSSEY_VALIDATOR_VIDEO_AUDIO": "true",
           "AUDYSSEY_VALIDATOR_AUDIO": "false"}
    with patch.dict(os.environ, env):
        self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
    self.assertEqual(calls, [False])
    self.assertNotIn("mm_processor_kwargs", self.requests[0])

def test_validator_audio_true_sends_wav_even_with_frames_input(self):
    self.responses = [json.dumps({"status": "supported", "evidence": "audio", "reason": "speech heard"})]
    with patch.dict(os.environ, {"AUDYSSEY_VALIDATOR_AUDIO": "true"}):
        self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
    types = [p["type"] for p in self.requests[0]["messages"][1]["content"]]
    self.assertIn("input_audio", types)
    self.assertNotIn("image_url", types)
```

In `tests/test_audyssey_settings.py`, extend `test_validator_context_bounds_and_environment` (or add a sibling test): `Settings().validator_audio is None`; with `AUDYSSEY_VALIDATOR_AUDIO=true` it is `True`.

Update these existing tests to the new behavior:
- `test_separation_music_and_ambience_also_require_audio` → expect `not_validated` for both, no requests (rename to `..._pass_without_audio`).
- `test_separation_without_audio_is_unverified_without_model_call` → delete (covered by the new visual-mode test).
- `test_visual_evidence_does_not_approve_separation` → keep as is (it runs in audio mode: `INPUT=video`, `VIDEO_AUDIO=true`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_audyssey_planner_real.py tests/test_audyssey_settings.py -q`
Expected: the four new tests fail (`validation_unavailable` instead of a model call / `not_validated`; unknown setting).

- [ ] **Step 3: Implement**

- `settings.py`: add `validator_audio: bool | None = None` with a one-line comment (declares the validator accepts audio input; unset → video+audio rule).
- `prompts.py`: `VERSION = "planning-evidence-v3"`. In `validator_prompt`, when `purpose == "separate" and not hears`, use a visual policy carrying the pre-PR-#40 criterion: judge by the sound's producer; name what is visible; supported only if the specific producer named in the source (same kind of person, creature or object, or the action causing it) is visible in the TARGET intervals; a sound with no visual trace (voice, grunt) is supported if its producer is shown; unsupported if the producer is a different or absent thing; put what was seen in the reason; evidence must be `visual` or `none`.
- `real.py` `validate_plan`:
  - `audio_capable = settings.validator_audio if settings.validator_audio is not None else _hears(endpoint)`; `hears = request.audio_available and audio_capable`.
  - Keep `validation_unavailable` only for `purpose == "separate" and not request.audio_available`.
  - Visual mode for separation: music/ambience/`visual_hint is None` → append `PlanIssue(source_name, "not_validated", f"{name}: not validated (no visual evidence possible)")` and `continue` before any request.
  - Visual mode uses `visual = endpoint.model_copy(update={"video_audio": False})` for both `_media(video, visual, windows, tmp)` and `_request(visual, ...)`, so clips carry no audio and `_chat` adds no `mm_processor_kwargs`.
  - Audio mode media: WAV (`_audio_media`) when `settings.validator_audio_only or not _hears(endpoint)`; otherwise `_media(video, endpoint, ...)` (clip with audio).
  - Judgement: in visual mode, `evidence in {"audio","audio_visual"}` → `validation_uncertain`; `visual` evidence may approve separation. In audio mode keep the PR #40 rules.
- `planning_eval.py`: add `"validator_audio": settings.validator_audio` to the config dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_audyssey_planner_real.py tests/test_audyssey_settings.py tests/test_audyssey_planning_eval.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/audyssey/settings.py src/audyssey/tools/planning/prompts.py src/audyssey/tools/planning/real.py src/audyssey/planning_eval.py tests/test_audyssey_planner_real.py tests/test_audyssey_settings.py
git commit -m "feat(planning): support audio and visual validation modes"
```

---

### Task 2: 16 kHz validation audio and oversize fallback

**Files:**
- Modify: `src/audyssey/tools/planning/real.py` (`_audio_media` ~line 106, audio branch of `validate_plan`)
- Test: `tests/test_audyssey_planner_real.py`

**Interfaces:**
- Consumes: Task 1's per-source mode flow.
- Produces: `_audio_media(samples, windows)` emitting 16000 Hz PCM16 WAV parts.

- [ ] **Step 1: Write the failing tests**

```python
def test_oversize_audio_falls_back_to_visual_validation(self):
    self.responses = [json.dumps({"status": "supported", "evidence": "visual", "reason": "person visible"})]
    env = {"AUDYSSEY_VALIDATOR_AUDIO": "true", "AUDYSSEY_VALIDATOR_CONTEXT_S": "0"}
    with patch.dict(os.environ, env), patch.object(real, "_MAX_INLINE_B64", 10):
        self.assertEqual(real.validate_plan(self.video, self.audio, [self.visible()]), [])
    types = [p["type"] for p in self.requests[0]["messages"][1]["content"]]
    self.assertNotIn("input_audio", types)
    self.assertIn("cannot hear", self.requests[0]["messages"][0]["content"])

def test_oversize_audio_music_is_not_validated_without_call(self):
    env = {"AUDYSSEY_VALIDATOR_AUDIO": "true"}
    with patch.dict(os.environ, env), patch.object(real, "_MAX_INLINE_B64", 10):
        issues = real.validate_plan(self.video, self.audio, [SourcePlan(**self.source(name="score", kind="music"))])
    self.assertEqual([(i.source_name, i.kind) for i in issues], [("score", "not_validated")])
    self.assertEqual(self.requests, [])
```

Update `test_audio_only_validator_sends_pcm_wav_without_video_or_vllm_flags`: expected header `(16000, 2, 32000)`; keep the channel-sum-zero assertion.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_audyssey_planner_real.py -q -k "oversize or pcm_wav"`
Expected: FAIL (48000 header; audio still sent).

- [ ] **Step 3: Implement**

- `_audio_media`: resample each window with `resample_poly(data, 1, 3, axis=0)`, write WAV at 16000 Hz, 2-byte samples, same channel count.
- In audio mode, after building WAV parts: if `sum(len(v) for k, v in parts if k == "audio") > _MAX_INLINE_B64`, switch this source to visual mode (same rules as Task 1: prompt, `audio_available` payload field, evidence check, music/ambience/offscreen pass-through). Add `# ponytail: oversize audio (~3.5 min at 16 kHz stereo) falls back to visual validation; split windows if long sources matter.`
- Read `_MAX_INLINE_B64` at call time (module attribute) so the test patch applies.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_audyssey_planner_real.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/audyssey/tools/planning/real.py tests/test_audyssey_planner_real.py
git commit -m "fix(planning): send 16 kHz validation audio and fall back to visual when oversize"
```

---

### Task 3: Planner receives accepted sources

**Files:**
- Modify: `src/audyssey/tools/planning/__init__.py` (`PlanningRequest`, `planning_scope`)
- Modify: `src/audyssey/tools/planning/prompts.py` (`_COMMON` or `planner_prompt`)
- Modify: `src/audyssey/tools/planning/real.py` (`plan`, request context JSON ~line 400)
- Test: `tests/test_audyssey_planner_real.py`

**Interfaces:**
- Produces: `PlanningRequest.accepted: tuple[SourcePlan, ...] = ()`; `planning_scope(purpose, audio_available, accepted: tuple[SourcePlan, ...] = ())`. Existing two-argument calls keep working.

- [ ] **Step 1: Write the failing test**

```python
def test_planner_sees_accepted_sources_and_instruction(self):
    from audyssey.tools.planning import planning_scope
    accepted = (SourcePlan(**self.source(name="door", kind="sfx", description="a door slams")),)
    with planning_scope("separate", True, accepted):
        self.plan([self.source()])
    request = self.requests[0]
    context = request["messages"][1]["content"][0]["text"]
    self.assertIn('"accepted_sources": [{"name": "door"', context)
    self.assertIn("accepted_sources", request["messages"][0]["content"])
    self.assertIn("do not return them again", request["messages"][0]["content"].lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_audyssey_planner_real.py -q -k accepted`
Expected: FAIL (`planning_scope` takes 2 positional arguments).

- [ ] **Step 3: Implement**

- `PlanningRequest`: add `accepted: tuple[SourcePlan, ...] = ()`; `planning_scope` gains `accepted=()`. Import `SourcePlan` from `audyssey.contracts` (check for import cycles; `contracts` does not import planning).
- `real.plan`: add `"accepted_sources": [p.model_dump(include={"name","kind","description","spans"}) for p in request.accepted]` to the request-context JSON.
- `prompts._COMMON`: add: "Request context may list accepted_sources. They are final: do not return them again. Return only corrected replacements for sources named in feedback and sources still missing. An empty sources list is valid."

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_audyssey_planner_real.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/audyssey/tools/planning/__init__.py src/audyssey/tools/planning/prompts.py src/audyssey/tools/planning/real.py tests/test_audyssey_planner_real.py
git commit -m "feat(planning): tell the planner which sources are already accepted"
```

---

### Task 4: Per-source plan/validate flow in the graph

**Files:**
- Modify: `src/audyssey/graph.py` (`AnalysisState` ~line 312, `prepare`, `plan` ~line 409, `validate` ~line 465, `separate` ~line 530, routing ~line 611)
- Test: `tests/test_audyssey_graph.py`

**Interfaces:**
- Consumes: `planning_scope(purpose, audio_available, accepted)` from Task 3; `"not_validated"` kind from Task 1.
- Produces: `AnalysisState.accepted: list[str]`; module constants `INFO_KINDS = {"not_validated"}`, `NON_SKIP_KINDS = {"visual_hint_not_found", "not_validated"}`.

- [ ] **Step 1: Write the failing tests** (use `replace(self.ctx.tools, plan=..., validate_plan=...)` fakes like the existing tests)

```python
def test_accepted_sources_are_not_revalidated_or_replaced(self):
    rounds, validated = [], []
    def plan(video, audio, duration, issues):
        rounds.append(issues)
        if not issues:
            return [SourcePlan(name="door", kind="sfx", description="door"),
                    SourcePlan(name="dog", kind="sfx", description="dog")]
        return [SourcePlan(name="door", kind="sfx", description="changed door"),
                SourcePlan(name="dog2", kind="sfx", description="real dog")]
    def validate(video, audio, plans):
        validated.append([p.name for p in plans])
        return [PlanIssue(source_name="dog", kind="not_found", message="dog: silent")] if any(p.name == "dog" for p in plans) else []
    self.ctx.tools = replace(self.ctx.tools, plan=plan, validate_plan=validate)
    job = graph.analyze(self.job, self.ctx)
    self.assertEqual(validated, [["door", "dog"], ["dog2"]])
    self.assertEqual([s.plan.name for s in job.sources], ["door", "dog2"])
    self.assertEqual(job.sources[0].plan.description, "door")

def test_format_issue_does_not_block_validation_of_other_sources(self):
    self.ctx.settings.max_plan_rounds = 1
    validated = []
    def validate(video, audio, plans):
        validated.append([p.name for p in plans])
        return [PlanIssue(source_name="dog", kind="not_found", message="dog: silent")]
    self.ctx.tools = replace(self.ctx.tools,
        plan=lambda *a: [SourcePlan(name="blank", kind="sfx", description=" "),
                         SourcePlan(name="dog", kind="sfx", description="dog")],
        validate_plan=validate)
    job = graph.analyze(self.job, self.ctx)
    self.assertEqual(validated, [["dog"]])
    self.assertTrue(all(s.status == "skipped" for s in job.sources))

def test_all_pass_in_first_round_needs_no_replan(self):
    calls = []
    self.ctx.tools = replace(self.ctx.tools,
        plan=lambda *a: calls.append(1) or [SourcePlan(name="door", kind="sfx", description="door")],
        validate_plan=lambda *a: [])
    job = graph.analyze(self.job, self.ctx)
    self.assertEqual(len(calls), 1)
    self.assertEqual(next(s for s in job.steps if s.key == "plan").round, 1)

def test_hint_not_found_source_is_still_separated_on_last_round(self):
    # max_plan_rounds=1, visual_prompt on, locate finds nothing, validator passes
    # → job.plan_issues has visual_hint_not_found, but the source status is "done".

def test_not_validated_is_informational(self):
    # validate returns [PlanIssue(name, "not_validated", ...)] for one source
    # → plan called once, source separated ("done"), validate_plan step status "done",
    #   step message contains "not validated".

def test_empty_plan_warns(self):
    # extend test_empty_plan_preserves_original_as_residual:
    # plan step status == "warning" and message == "No sources proposed".
```

Write the three commented tests as full code in the same style as the first three. Existing tests that must still pass unchanged: `test_analyze_runs_both_validation_loops`, `test_plan_round_limit_warns`, `test_hint_not_found_triggers_replan`, `test_edit_during_planning_survives_replan`, `test_unverified_plan_never_reaches_gpu_tools`, `test_planner_scope_follows_job_mode_and_restores_after_use`, `test_locate_exception_becomes_issue`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_audyssey_graph.py -q`
Expected: the new tests fail; existing ones pass.

- [ ] **Step 3: Implement**

- `AnalysisState.accepted: list[str] = Field(default_factory=list)`; `prepare` returns `"accepted": []`.
- `plan` node:
  1. `accepted = [s for s in job.sources if s.plan.name in state.accepted]`.
  2. Call `ctx.tools.plan(..., [i for i in state.issues if i.kind not in INFO_KINDS])` inside `planning_scope(method, not job.silent, tuple(s.plan for s in accepted))`.
  3. Drop planner outputs whose name is in `state.accepted`, then `check_plans` the rest (its issues become the returned `issues`).
  4. Build new `Source`s exactly as today (reuse a same-named previous `Source`, origin reset logic unchanged); `job.sources = accepted + new`; renumber ids `s1..` over the whole list as today.
  5. Plan step: `status="warning", message="No sources proposed"` when `job.sources` is empty, else `"done"`.
- `validate` node:
  1. `fresh = [s for s in job.sources if s.plan.name not in state.accepted]`; `bad = {i.source_name for i in state.issues}`; `candidates = [s.plan for s in fresh if s.plan.name not in bad]`.
  2. `issues = list(state.issues) + (ctx.tools.validate_plan(..., candidates) if candidates else [])` inside `planning_scope(method, not job.silent)`. Remove `state.issues or ...`.
  3. Run the locate check only over `candidates`.
  4. `blocking = {i.source_name for i in issues if i.kind not in INFO_KINDS}`; `accepted = state.accepted + [p.name for p in candidates if p.name not in blocking]`.
  5. Step status `"warning"` iff any non-informational issue; message joins all issue messages. Round-limit plan warning uses the same condition.
  6. Return `{"job": job, "issues": issues, "accepted": accepted}`.
- Routing: replan iff any `i.kind not in INFO_KINDS` and `state.round < max_plan_rounds`.
- `separate` node: `unresolved` excludes `NON_SKIP_KINDS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_audyssey_graph.py tests/test_audyssey_graph_factory.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/audyssey/graph.py tests/test_audyssey_graph.py
git commit -m "fix(graph): accept validated sources and replan only failing ones"
```

---

### Task 5: Skipped-source notice and docs

**Files:**
- Modify: `src/audyssey/ui/index.html` (markup before `.grid.thead` ~line 418, `drawRows` ~line 663, a small CSS rule near `.empty-row` ~line 254)
- Modify: `.env.example` (validator block ~line 35), `docs/planning.md` (validator section ~line 46)

**Interfaces:**
- Consumes: `job.sources[].status == "skipped"`, `job.plan_issues[]` (`source_name`, `message`).

- [ ] **Step 1: Implement the notice**

- Add `<div id="skip-note" class="skip-note" role="status" hidden></div>` right above `<div class="grid thead">`.
- In `drawRows`, before returning: collect skipped sources whose name appears in `S.job.plan_issues` (`source_name`); when there are any, show `검수를 통과하지 못해 건너뛴 소스 N개: ` followed by `name — message` entries joined by `, `; otherwise set `hidden`. Use `textContent`/`el()` only (no `innerHTML`). Reuse `--warn` for the text or border color.

- [ ] **Step 2: Update docs**

- `.env.example`: add `# AUDYSSEY_VALIDATOR_AUDIO=true` with a Korean comment: 검수 모델이 오디오 입력을 받으면 true(오디오 검수), 받지 못하면 false(시각 검수); 비워 두면 INPUT=video + VIDEO_AUDIO=true일 때만 오디오 검수.
- `docs/planning.md`: replace the "validator must support audio" requirement with the two modes, the music/ambience/offscreen pass-through in visual mode, the oversize fallback, and the accepted-source replanning.

- [ ] **Step 3: Verify in the app**

Run the app in stub mode (see `docs/running.md`), upload `tests` sample video or any short mp4 with sound, set `AUDYSSEY_MAX_PLAN_ROUNDS=1` so the stub `ghost_sound` stays rejected, and confirm the notice shows `ghost_sound` with its reason and the other tracks render. Capture a screenshot.

- [ ] **Step 4: Full checks**

Run: `python -m pytest -q && ruff check src tests && ruff format --check src`
Expected: all tests pass, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add src/audyssey/ui/index.html .env.example docs/planning.md
git commit -m "feat(ui): show sources skipped by validation; document validator modes"
```
