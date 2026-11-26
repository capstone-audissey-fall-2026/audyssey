"""The three filtering stages: presence (존재성), purity (순수성), completeness (완전성).

Each stage is independent of the others, so the agent can run them in either order.
Cheap deterministic signal checks run first; the audio LLM is only asked when needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .audio import Clip, compute_residual, silent_ratio, windows
from .backend import JudgeBackend
from .config import AgentConfig, COMPLETENESS, PRESENCE, PURITY
from . import prompts as P
from .judge import FAIL, PASS, UNCERTAIN, StageResult, ask, band
from .prompts import SYSTEM


@dataclass
class StemCase:
    """Everything the filter knows about one candidate stem."""

    stem_id: str
    target: str  # natural-language description of the target sound
    stem: Clip
    original: Optional[Clip] = None  # needed for completeness
    residual: Optional[Clip] = None  # optional; computed from original-stem if absent
    group_id: Optional[str] = None  # candidates for the same target share a group
    segments: List[Tuple[float, float]] = field(
        default_factory=list
    )  # planner intervals
    # Other sources the planner found in the same clip (used by purity mode "named").
    other_sources: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


def _prep(clip: Clip, cfg: AgentConfig) -> Clip:
    return (
        clip.normalized(cfg.audio.normalize_peak_dbfs) if cfg.audio.normalize else clip
    )


def _parse_json(text: str) -> Any:
    m = re.search(r"\[.*\]", text or "", flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------------------- presence
def run_presence(
    case: StemCase, cfg: AgentConfig, backend: JudgeBackend
) -> StageResult:
    c = cfg.presence
    peak = case.stem.peak_dbfs()
    if peak < cfg.audio.silence_peak_dbfs:
        return StageResult(
            PRESENCE,
            FAIL,
            0.0,
            "P(target present)",
            f"stem is digitally silent (peak {peak:.1f} dBFS)",
            deterministic=True,
            details={"peak_dbfs": round(peak, 1)},
        )
    stem = _prep(case.stem, cfg)
    probe = ask(
        backend,
        "presence",
        [stem],
        P.PRESENCE_POS.format(target=case.target),
        P.PRESENCE_NEG.format(target=case.target) if c.dual_polarity else None,
        cfg.backend.max_evidence_tokens,
    )
    verdict = band(probe.p_true, False, c.pass_at, c.fail_at)
    reason = {
        PASS: "target sound is audible in the stem",
        FAIL: "target sound not audible in the stem",
        UNCERTAIN: "judge is unsure whether the target is audible",
    }[verdict]
    return StageResult(
        PRESENCE,
        verdict,
        probe.p_true,
        "P(target present)",
        reason,
        [probe],
        {"peak_dbfs": round(peak, 1)},
    )


# ------------------------------------------------------------------------- purity
def _named_sources(
    case: StemCase, cfg: AgentConfig, backend: JudgeBackend
) -> List[str]:
    names: List[str] = []
    if case.original is not None:
        heard = _parse_json(
            backend.generate(
                SYSTEM,
                [
                    _prep(case.original, cfg),
                    P.PURITY_NAMED_ENUMERATE.format(target=case.target),
                ],
                128,
            )
        )
        if isinstance(heard, list):
            names += [str(h) for h in heard]
    names += list(case.other_sources)
    seen, out = set(), []
    tgt = case.target.lower()
    for n in names:
        k = n.strip().strip('"“”').lower()
        if k and k not in seen and k != tgt:
            seen.add(k)
            out.append(n.strip().strip('"“”'))
    return out[: cfg.purity.max_named_sources]


def run_purity(
    case: StemCase,
    cfg: AgentConfig,
    backend: JudgeBackend,
    second: Optional[JudgeBackend] = None,
) -> StageResult:
    c = cfg.purity
    normalize = c.normalize if c.normalize is not None else (c.mode == "strict")
    stem = (
        case.stem.normalized(cfg.audio.normalize_peak_dbfs) if normalize else case.stem
    )
    details: Dict[str, Any] = {"mode": c.mode, "normalized": normalize}
    tmpl = (
        (P.PURITY_POS, P.PURITY_NEG)
        if c.mode == "strict"
        else (P.PURITY_AUDIBLE_POS, P.PURITY_AUDIBLE_NEG)
    )
    probe = ask(
        backend,
        "purity",
        [stem],
        tmpl[0].format(target=case.target),
        tmpl[1].format(target=case.target) if c.dual_polarity else None,
        cfg.backend.max_evidence_tokens,
    )
    probes = [probe]
    score = probe.p_true
    if c.mode == "named":
        details["audible_p"] = None if probe.p_true is None else round(probe.p_true, 4)
        per_source = {}
        for src in _named_sources(case, cfg, backend):
            pr = ask(
                backend,
                f"purity[{src}]",
                [stem],
                P.PURITY_NAMED_POS.format(source=src, target=case.target),
                P.PURITY_NAMED_NEG.format(source=src, target=case.target)
                if c.dual_polarity
                else None,
                cfg.backend.max_evidence_tokens,
            )
            probes.append(pr)
            if pr.p_true is not None:
                per_source[src] = round(pr.p_true, 4)
        details["named_sources"] = per_source
        named_max = max(per_source.values()) if per_source else 0.0
        details["named_max"] = named_max
        score = max(named_max, probe.p_true if probe.p_true is not None else 0.0)
        if per_source:
            details["heard_sources"] = [
                s for s, p in per_source.items() if p >= c.fail_at
            ]
    if c.segment_s > 0 and case.stem.duration > c.segment_s + 0.5:
        seg = []
        for a, b in windows(case.stem.duration, c.segment_s, c.segment_hop_s):
            piece = case.stem.crop(a, b)
            if piece.peak_dbfs() < c.segment_skip_dbfs:
                continue
            if normalize:
                piece = piece.normalized(cfg.audio.normalize_peak_dbfs)
            pr = ask(
                backend,
                f"purity[{a:.1f}-{b:.1f}]",
                [piece],
                tmpl[0].format(target=case.target),
                tmpl[1].format(target=case.target) if c.dual_polarity else None,
                cfg.backend.max_evidence_tokens,
            )
            probes.append(pr)
            if pr.p_true is not None:
                seg.append(((a, b), pr.p_true))
        details["segments"] = [
            {"start": round(a, 2), "end": round(b, 2), "p_other": round(p, 4)}
            for (a, b), p in seg
        ]
        if seg:
            ps = sorted((p for _, p in seg), reverse=True)
            combined = (
                ps[0]
                if c.segment_combine == "max" or len(ps) < 2
                else (ps[0] + ps[1]) / 2
            )
            details["whole_p"] = None if score is None else round(score, 4)
            details["segment_p"] = round(combined, 4)
            score = max(combined, score if score is not None else 0.0)
            worst = max(seg, key=lambda x: x[1])[0]
            if worst and combined >= c.fail_at:
                details["intrusion_window"] = [round(worst[0], 2), round(worst[1], 2)]
    if second is not None:
        pr2 = ask(
            second,
            "purity[second]",
            [stem],
            tmpl[0].format(target=case.target),
            tmpl[1].format(target=case.target) if c.dual_polarity else None,
            cfg.backend.max_evidence_tokens,
        )
        probes.append(pr2)
        details["primary_p"] = None if score is None else round(score, 4)
        details["second_p"] = None if pr2.p_true is None else round(pr2.p_true, 4)
        if pr2.p_true is None:
            score = max(
                score or 0.0, c.fail_at
            )  # second judge unavailable: never auto-pass
        elif c.second_combine == "mean":
            score = ((score or 0.0) + pr2.p_true) / 2
        else:
            score = max(score or 0.0, pr2.p_true)
    verdict = band(score, True, c.pass_at, c.fail_at)
    if c.enumerate_sources and verdict != PASS and c.mode != "named":
        heard = _parse_json(backend.generate(SYSTEM, [stem, P.PURITY_ENUMERATE], 128))
        if isinstance(heard, list):
            details["heard_sources"] = [str(h) for h in heard][:12]
    reason = {
        PASS: "only the target sound is audible",
        FAIL: "non-target sound audible in the stem",
        UNCERTAIN: "judge is unsure whether other sounds are present",
    }[verdict]
    if details.get("heard_sources"):
        reason += f" (heard: {', '.join(details['heard_sources'])})"
    return StageResult(
        PURITY, verdict, score, "P(other sound audible)", reason, probes, details
    )


# ------------------------------------------------------------------------- completeness
def _planned_segment_misses(
    case: StemCase, cfg: AgentConfig
) -> List[Tuple[float, float]]:
    c = cfg.completeness
    misses = []
    for a, b in case.segments:
        if b - a < 0.05:
            continue
        seg = case.stem.crop(a, b)
        if silent_ratio(seg, c.segment_silence_dbfs) >= c.segment_min_silent_ratio:
            misses.append((round(a, 2), round(b, 2)))
    return misses


def run_completeness(
    case: StemCase, cfg: AgentConfig, backend: JudgeBackend
) -> StageResult:
    c = cfg.completeness
    meaning = "P(part of target missing)"
    if case.original is None:
        return StageResult(
            COMPLETENESS,
            UNCERTAIN,
            None,
            meaning,
            "no original mixture given; completeness cannot be judged",
        )

    details: Dict[str, Any] = {}
    # 1) deterministic: planner said the target is active here, but the stem is silent there
    seg_misses = _planned_segment_misses(case, cfg) if c.segment_check != "off" else []
    if seg_misses:
        details["silent_in_planned_segments"] = seg_misses
    if c.segment_check != "hard":
        seg_misses_evidence, seg_misses = seg_misses, []
    else:
        seg_misses_evidence = seg_misses

    # 2) windowed ORIGINAL vs STEM comparison
    probes, window_verdicts = [], []
    for a, b in windows(
        max(case.original.duration, case.stem.duration), c.window_s, c.hop_s
    ):
        o = _prep(case.original.crop(a, b), cfg)
        s = _prep(case.stem.crop(a, b), cfg)
        span = (
            ""
            if (a == 0.0 and b >= case.original.duration - 1e-3)
            else P.SPAN_NOTE.format(start=a, end=b)
        )
        pr = ask(
            backend,
            f"completeness[{a:.1f}-{b:.1f}]",
            ["Audio 1 (ORIGINAL):", o, "Audio 2 (STEM):", s],
            P.COMPLETENESS_POS.format(target=case.target, span=span),
            P.COMPLETENESS_NEG.format(target=case.target, span=span)
            if c.dual_polarity
            else None,
            cfg.backend.max_evidence_tokens,
        )
        probes.append(pr)
        window_verdicts.append(
            ((a, b), band(pr.p_true, True, c.pass_at, c.fail_at), pr.p_true)
        )
    details["windows"] = [
        {
            "start": round(a, 2),
            "end": round(b, 2),
            "verdict": v,
            "p_missing": None if p is None else round(p, 4),
        }
        for (a, b), v, p in window_verdicts
    ]

    # 3) residual check: target still clearly audible in what was left behind
    residual_verdict = PASS
    if c.use_residual:
        res = case.residual
        if res is None and c.compute_residual_if_missing:
            res = compute_residual(case.original, case.stem)
        if res is not None and res.peak_dbfs() > cfg.audio.silence_peak_dbfs:
            rp = ask(
                backend,
                "residual",
                [_prep(res, cfg)],
                P.RESIDUAL_POS.format(target=case.target),
                P.RESIDUAL_NEG.format(target=case.target) if c.dual_polarity else None,
                cfg.backend.max_evidence_tokens,
            )
            probes.append(rp)
            if rp.p_true is not None and rp.p_true >= c.residual_fail_at:
                residual_verdict = FAIL
            elif rp.p_true is None or rp.p_true >= c.residual_uncertain_at:
                residual_verdict = UNCERTAIN
            details["residual_p_target"] = (
                None if rp.p_true is None else round(rp.p_true, 4)
            )

    verdicts = [v for _, v, _ in window_verdicts] + [residual_verdict]
    scores = [p for _, _, p in window_verdicts if p is not None]
    score = max(scores) if scores else None
    if seg_misses or FAIL in verdicts:
        verdict = FAIL
    elif UNCERTAIN in verdicts:
        verdict = UNCERTAIN
    else:
        verdict = PASS

    if verdict == FAIL:
        parts = []
        if seg_misses:
            parts.append(f"stem silent in planned target interval(s) {seg_misses}")
        bad = [(a, b) for (a, b), v, _ in window_verdicts if v == FAIL]
        if bad:
            parts.append(
                "target missing/attenuated vs original in window(s) "
                + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in bad)
            )
        if residual_verdict == FAIL:
            parts.append("target still clearly audible in the residual")
        reason = "; ".join(parts)
        loc = _parse_json(
            backend.generate(
                SYSTEM,
                [
                    "Audio 1 (ORIGINAL):",
                    _prep(case.original, cfg),
                    "Audio 2 (STEM):",
                    _prep(case.stem, cfg),
                    P.COMPLETENESS_LOCALIZE.format(
                        target=case.target, duration=case.original.duration
                    ),
                ],
                128,
            )
        )
        ranges = []
        if isinstance(loc, list):
            for r in loc:
                if isinstance(r, (list, tuple)) and len(r) == 2:
                    try:
                        ranges.append([round(float(r[0]), 2), round(float(r[1]), 2)])
                    except (TypeError, ValueError):
                        pass
        details["missing_ranges"] = ranges or [list(m) for m in seg_misses_evidence]
    elif verdict == UNCERTAIN:
        reason = "judge is unsure whether every occurrence of the target is preserved"
    else:
        reason = "all occurrences of the target in the original are preserved"
    return StageResult(
        COMPLETENESS,
        verdict,
        score,
        meaning,
        reason,
        probes,
        details,
        deterministic=bool(seg_misses) and FAIL not in verdicts,
    )


STAGES = {PRESENCE: run_presence, PURITY: run_purity, COMPLETENESS: run_completeness}
