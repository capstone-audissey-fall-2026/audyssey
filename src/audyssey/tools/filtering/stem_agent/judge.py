"""Turns backend yes/no answers into calibrated stage verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .backend import JudgeBackend, Part, YesNo
from .prompts import ANSWER_FORMAT, SYSTEM

PASS, FAIL, UNCERTAIN = "PASS", "FAIL", "UNCERTAIN"


@dataclass
class Probe:
    """One counterfactual question pair answered by the judge."""

    name: str
    p_true: Optional[float]  # P(property in POSITIVE phrasing holds)
    p_pos: Optional[float]
    p_neg_inverted: Optional[float]
    evidence: str
    method: str

    def to_dict(self) -> Dict[str, Any]:
        def r(x: Optional[float]) -> Optional[float]:
            return None if x is None else round(x, 4)

        return {
            "name": self.name,
            "p_true": r(self.p_true),
            "p_pos": r(self.p_pos),
            "p_neg_inverted": r(self.p_neg_inverted),
            "evidence": self.evidence,
            "method": self.method,
        }


def ask(
    backend: JudgeBackend,
    name: str,
    audios: List[Part],
    pos: str,
    neg: Optional[str],
    max_tokens: int,
) -> Probe:
    """Ask POSITIVE (and optionally NEGATED) phrasing; return averaged P(property)."""
    a = backend.yes_no(SYSTEM, audios + [pos + ANSWER_FORMAT], max_tokens)
    b: Optional[YesNo] = None
    if neg is not None:
        b = backend.yes_no(SYSTEM, audios + [neg + ANSWER_FORMAT], max_tokens)
    p_pos = a.p_yes
    p_neg = None if (b is None or b.p_yes is None) else 1.0 - b.p_yes
    vals = [p for p in (p_pos, p_neg) if p is not None]
    p = sum(vals) / len(vals) if vals else None
    return Probe(name, p, p_pos, p_neg, a.evidence, a.method)


def band(p: Optional[float], pass_if_low: bool, pass_at: float, fail_at: float) -> str:
    """Map a probability onto PASS / FAIL / UNCERTAIN.

    pass_if_low=False: high p is good (presence). pass_if_low=True: low p is good
    (purity: P(other sound), completeness: P(missing)).
    """
    if p is None:
        return UNCERTAIN
    if pass_if_low:
        if p <= pass_at:
            return PASS
        if p >= fail_at:
            return FAIL
        return UNCERTAIN
    if p >= pass_at:
        return PASS
    if p <= fail_at:
        return FAIL
    return UNCERTAIN


@dataclass
class StageResult:
    stage: str
    verdict: str  # PASS | FAIL | UNCERTAIN
    score: Optional[float]  # stage's key probability (see `score_meaning`)
    score_meaning: str
    reason: str
    probes: List[Probe] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    deterministic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "verdict": self.verdict,
            "score": None if self.score is None else round(self.score, 4),
            "score_meaning": self.score_meaning,
            "reason": self.reason,
            "deterministic": self.deterministic,
            "probes": [p.to_dict() for p in self.probes],
            "details": self.details,
        }
