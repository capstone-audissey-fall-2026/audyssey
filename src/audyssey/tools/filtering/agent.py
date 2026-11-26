"""filter=agent: the 3-stage stem filter (presence -> purity -> completeness) as the judge.

An audio LLM (Qwen3-Omni-30B-A3B-Instruct on an OpenAI-compatible server such as vLLM) answers
counterfactual yes/no questions about the separated track and the original mix; see
docs/filtering_agent.md and tools/filtering/stem_agent/.

Mapping to FilterResult (the app re-derives `passed` from `overall`, see judge_verdict):
  ACCEPT -> overall 1.0     (every stage PASS)
  HOLD   -> overall 0.4     (no FAIL, some stage unsure; fails the default 0.5 threshold,
                             i.e. "unsure stems are not auto-selected")
  REJECT -> overall 0.0     (some stage FAIL)
Stage probabilities are kept in scores: p_present, p_other (non-target audible), p_missing,
plus recall = 1 - p_missing and precision = 1 - p_other in the SAM Audio Judge sense.
"""

from functools import cache
from pathlib import Path
from threading import Lock

import numpy as np

from audyssey.contracts import FilterResult, SourcePlan, Span
from audyssey.media import read_wav
from audyssey.settings import Settings
from audyssey.tools.filtering.stem_agent import (
    ACCEPT,
    HOLD,
    AgentConfig,
    StemCase,
    StemFilterAgent,
    load_config,
)
from audyssey.tools.filtering.stem_agent import FilterResult as AgentResult
from audyssey.tools.filtering.stem_agent.audio import Clip, resample
from audyssey.tools.filtering.stem_agent.backend import JudgeBackend, make_backend

OVERALL = {ACCEPT: 1.0, HOLD: 0.4}
_lock = Lock()


def agent_config(settings: Settings) -> AgentConfig:
    cfg = load_config(settings.stem_agent_config or None)
    cfg.backend.base_url = settings.stem_agent_url
    cfg.backend.model = settings.stem_agent_model
    cfg.backend.timeout_s = settings.stem_agent_timeout_s
    return cfg


@cache
def _agent() -> StemFilterAgent:
    settings = Settings()
    if not settings.stem_agent_url.strip():
        raise ValueError("AUDYSSEY_STEM_AGENT_URL is required for filter=agent")
    cfg = agent_config(settings)
    backend = make_backend(cfg.backend)
    _set_key(backend, settings.stem_agent_api_key)
    return StemFilterAgent(cfg, backend)


def _set_key(backend: JudgeBackend, key: str) -> None:
    # The vendored backend reads an env var by default; the app passes its own setting instead.
    if key and hasattr(backend, "api_key"):
        setattr(backend, "api_key", key)


def _clip(path: Path, sr: int, name: str) -> Clip:
    data = read_wav(path).mean(axis=1).astype(np.float32)
    return Clip(resample(data, 48000, sr), sr, name)


def to_filter_result(result: AgentResult, plan: SourcePlan) -> FilterResult:
    scores = {"overall": OVERALL.get(result.decision, 0.0)}
    for stage, key in (
        ("presence", "p_present"),
        ("purity", "p_other"),
        ("completeness", "p_missing"),
    ):
        stage_result = result.stage(stage)
        if stage_result is not None and stage_result.score is not None:
            scores[key] = round(float(stage_result.score), 4)
    if "p_missing" in scores:
        scores["recall"] = round(1 - scores["p_missing"], 4)
    if "p_other" in scores:
        scores["precision"] = round(1 - scores["p_other"], 4)

    if result.decision == ACCEPT:
        return FilterResult(passed=True, scores=scores)
    if result.decision == HOLD:
        reason = "agent HOLD: unsure about " + ", ".join(result.uncertain_stages)
        return FilterResult(passed=False, scores=scores, reason=reason)
    failed = result.stage(result.failed_stage or "")
    reason = f"agent REJECT at {result.failed_stage}: {failed.reason if failed else ''}"
    return FilterResult(
        passed=False,
        scores=scores,
        reason=reason.strip(),
        suggestion=_suggestion(result, plan),
    )


def _suggestion(result: AgentResult, plan: SourcePlan) -> SourcePlan | None:
    """Completeness FAIL with located gaps: re-separate with those ranges as span anchors."""
    retry = result.retry or {}
    ranges = retry.get("missing_ranges") or []
    spans = list(plan.spans)
    for item in ranges:
        try:
            start, end = max(0.0, float(item[0])), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if end > start and all(not (s.start <= start and end <= s.end) for s in spans):
            spans.append(Span(start=start, end=end))
    if len(spans) == len(plan.spans):
        return None
    return plan.model_copy(update={"spans": sorted(spans, key=lambda s: s.start)})


def judge(mono: Path, track: Path, plan: SourcePlan) -> FilterResult:
    with _lock:
        agent = _agent()
    sr = agent.cfg.audio.sample_rate
    case = StemCase(
        stem_id=track.stem,
        target=plan.description,
        stem=_clip(track, sr, track.name),
        original=_clip(mono, sr, mono.name),
        segments=[(s.start, s.end) for s in plan.spans],
    )
    return to_filter_result(agent.evaluate(case), plan)
