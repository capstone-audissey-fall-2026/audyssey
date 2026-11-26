"""Configuration for the stem filtering agent.

All thresholds are probabilities produced by the judge (see judge.py).
Each stage maps a probability to PASS / FAIL / UNCERTAIN with two cut-offs,
and UNCERTAIN stems are never auto-selected (they go to the HOLD bucket for
human review, as in "판단이 불확실하면 자동 선별에서 제외").
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional

# Stage names (stable IDs written to results; the S1/S2/S3 labels depend on order).
PRESENCE = "presence"  # 존재성
PURITY = "purity"  # 순수성
COMPLETENESS = "completeness"  # 완전성

ORDERS: Dict[str, List[str]] = {
    # 방법 1 / 변경안: 존재성 → 순수성 → 완전성
    "method1": [PRESENCE, PURITY, COMPLETENESS],
    # 방법 2 / 기존안: 존재성 → 완전성 → 순수성
    "method2": [PRESENCE, COMPLETENESS, PURITY],
}


@dataclass
class BackendConfig:
    # "openai" = any OpenAI-compatible server (vLLM, DashScope compatible-mode)
    # "transformers" = load Qwen3-Omni locally on GPU
    # "mock" = deterministic fake judge for pipeline tests (no model)
    kind: str = "openai"
    model: str = "Qwen/Qwen3-Omni-30B-A3B-Instruct"
    base_url: str = "http://127.0.0.1:8901/v1"
    api_key_env: str = "OPENAI_API_KEY"  # env var name; key is never stored in config
    # How audio is attached in the chat message: "audio_url" (vLLM) or "input_audio" (DashScope)
    audio_part: str = "audio_url"
    timeout_s: float = 120.0
    max_evidence_tokens: int = 96
    # If the server returns no logprobs, sample this many times and use the vote share.
    fallback_samples: int = 3
    fallback_temperature: float = 0.7
    # transformers backend only
    device_map: str = "auto"
    attn_implementation: Optional[str] = None


@dataclass
class AudioConfig:
    sample_rate: int = 16000  # Qwen3-Omni audio encoder rate
    # A stem whose peak is below this is treated as digital silence (deterministic S1 FAIL).
    silence_peak_dbfs: float = -60.0
    # Peak-normalise clips before sending them to the judge so faint content is audible.
    normalize_peak_dbfs: float = -1.0
    normalize: bool = True


@dataclass
class PresenceConfig:
    # Precision-first ("what passes must be faultless"), tuned on StemFoley human labels with
    # Qwen3-Omni-30B-A3B (presence AUC 0.85). Balanced-accuracy cut would be 0.743; we demand more.
    pass_at: float = 0.85  # P(target present) >= pass_at  -> PASS
    fail_at: float = 0.70  # P(target present) <= fail_at  -> FAIL
    dual_polarity: bool = True


@dataclass
class PurityConfig:
    # Probability that ANY non-target sound is audible.
    # Mode "audible", strict precision-first ("통과된 스템은 결함이 없어야 한다"); tuned on only
    # 200 S3-labelled stems (AUC 0.79), so re-calibrate on a larger set before relying on it.
    # 0.36 -> 54 accepts at 85.2% precision; 0.25 -> 31 accepts at 90.3% (out-of-fold ~88%).
    # 0.25..0.40 lands in HOLD (kept for human review, never auto-selected).
    pass_at: float = 0.25  # P(other sound) <= pass_at -> PASS
    fail_at: float = 0.40  # P(other sound) >= fail_at -> FAIL
    dual_polarity: bool = True
    # "strict"  : even faint hiss/noise counts (the original spec)
    # "audible" : judged at normal playback level, steady noise floor ignored (human S3 rule)
    # "named"   : name the non-target sources of the ORIGINAL (+ planner's other sources) and
    #             ask about each in the stem; score = max(named, audible)
    # "audible" won the ablation (AUC 0.79 vs strict 0.69, named 0.69 on the same 200 stems).
    mode: str = "audible"
    # Peak-normalise the stem before the purity question. Amplifies the separation noise floor,
    # so it is turned off automatically for "audible"/"named" unless set to True explicitly.
    normalize: Optional[bool] = None
    max_named_sources: int = 6
    # Extra free-text call listing what was heard; used only for evidence / retry hints.
    enumerate_sources: bool = True
    # Segment-wise judging: also ask the purity question on short windows of the stem, so a
    # brief intrusion is not averaged away over the whole clip. 0 = off (default until the
    # thresholds are re-calibrated with it on; segment scores run higher than whole-clip ones).
    segment_s: float = 0.0
    segment_hop_s: float = 2.0
    # Windows whose stem peak is below this are skipped (nothing audible to judge).
    segment_skip_dbfs: float = -45.0
    # How window probabilities are combined: "max" or "top2" (mean of the two highest, less
    # sensitive to one noisy window). Final score = max(whole-clip, combined windows).
    segment_combine: str = "max"
    # Second, independent audio model asked the same "audible other sound?" question (an
    # ensemble against confident single-model mistakes). None = off. Combine:
    # "max"  = veto, both judges must hear nothing (precision-first), "mean" = average.
    second_judge: Optional[BackendConfig] = None
    second_combine: str = "max"


@dataclass
class CompletenessConfig:
    # Probability that some occurrence of the target in ORIGINAL is missing from STEM.
    # Qwen's P(missing) runs high (complete stems have a median of 0.55), and in the
    # precision-first tuning a looser completeness cut kept more good stems without letting
    # more faulty ones through (most bad accepts come from purity, not completeness).
    pass_at: float = 0.69
    fail_at: float = 0.75
    dual_polarity: bool = True
    # Long clips are judged window by window so a short dropout is not averaged away.
    window_s: float = 10.0
    hop_s: float = 8.0
    # If the planner gave target intervals, check whether the stem is (near) silent inside one.
    # "evidence" = record only (default; on the StemFoley human set this check had ~57%
    # precision because planner intervals overestimate), "hard" = FAIL, "off" = skip.
    segment_check: str = "evidence"
    segment_silence_dbfs: float = -50.0
    segment_min_silent_ratio: float = 0.9
    # Residual check: if the target is clearly audible in the residual (original - stem),
    # part of it was not extracted.
    # Off by default: on the human set the residual probe had AUC 0.48 (no signal), because
    # residuals carry target-like bleed whether or not anything is missing.
    use_residual: bool = False
    residual_fail_at: float = 0.75  # strict default: residuals often carry faint bleed
    residual_uncertain_at: float = 0.50
    compute_residual_if_missing: bool = True


@dataclass
class AgentConfig:
    order: str = "method1"
    # Run only these stages (for ablations); empty = all stages in `order`.
    only_stages: List[str] = field(default_factory=list)
    # Stop at the first definitive FAIL (operation mode). False = run every stage and
    # keep all verdicts (analysis mode, lets you compare method1 vs method2 offline).
    early_exit: bool = True
    # Per group of candidate stems for the same target: "all" judges every candidate,
    # "first" stops at the first ACCEPT ("현재 스템 제외 → 다음 후보 평가").
    select: str = "all"
    backend: BackendConfig = field(default_factory=BackendConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    purity: PurityConfig = field(default_factory=PurityConfig)
    completeness: CompletenessConfig = field(default_factory=CompletenessConfig)

    @property
    def stage_order(self) -> List[str]:
        if self.order not in ORDERS:
            raise ValueError(
                f"unknown order {self.order!r}; choose from {list(ORDERS)}"
            )
        if self.only_stages:
            return [s for s in ORDERS[self.order] if s in self.only_stages]
        return ORDERS[self.order]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _merge(dc: Any, data: Dict[str, Any]) -> Any:
    known = {f.name: f for f in fields(dc)}
    for key, value in data.items():
        if key not in known:
            raise KeyError(f"unknown config key {key!r} in {type(dc).__name__}")
        current = getattr(dc, key)
        if key == "second_judge" and isinstance(value, dict):
            current = BackendConfig()
            setattr(dc, key, current)
        if is_dataclass(current) and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(dc, key, value)
    return dc


def load_config(
    path: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None
) -> AgentConfig:
    cfg = AgentConfig()
    if path:
        with open(path, encoding="utf-8") as fh:
            _merge(cfg, json.load(fh))
    if overrides:
        _merge(cfg, overrides)
    cfg.stage_order  # validate
    return cfg
