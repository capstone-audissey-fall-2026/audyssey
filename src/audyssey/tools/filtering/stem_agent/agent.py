"""StemFilterAgent: runs the 3-stage pipeline and returns an orchestrator-ready decision.

Decision rules
  ACCEPT : every stage PASS                               -> 최종 선별 (사용할 스템)
  REJECT : some stage FAIL (first FAIL in order is reported) -> 현재 스템 제외 → 다음 후보 평가
  HOLD   : no FAIL but some stage UNCERTAIN                -> 자동 선별 제외, 사람 검수용 별도 보관
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .backend import JudgeBackend, make_backend
from .config import COMPLETENESS, PRESENCE, PURITY, AgentConfig
from .judge import FAIL, UNCERTAIN, StageResult
from .stages import STAGES, StemCase, run_purity

ACCEPT, REJECT, HOLD = "ACCEPT", "REJECT", "HOLD"

STAGE_KO = {PRESENCE: "존재성", PURITY: "순수성", COMPLETENESS: "완전성"}

# What the orchestrator / planner should try next, per failed stage.
RETRY_HINTS = {
    PRESENCE: {
        "action": "replan_or_generate",
        "hint": "Target not heard in the stem: rephrase the target description or change the "
        "separation prompt/seed; if the target is not in the original either, route to "
        "selective V2A generation.",
    },
    PURITY: {
        "action": "reseparate_tighter",
        "hint": "Non-target sounds leaked in: make the description more specific, add the "
        "intruding sources as negatives, or try another seed/candidate.",
    },
    COMPLETENESS: {
        "action": "reseparate_wider",
        "hint": "Parts of the target are missing: broaden the description to cover all "
        "variants of the sound, pass the missing time ranges as span prompts, or "
        "try another seed/candidate.",
    },
}


@dataclass
class FilterResult:
    stem_id: str
    group_id: Optional[str]
    target: str
    order: List[str]
    decision: str
    failed_stage: Optional[str]
    uncertain_stages: List[str]
    stages: List[StageResult]
    skipped_stages: List[str]
    retry: Optional[Dict[str, Any]]
    elapsed_s: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stem_id": self.stem_id,
            "group_id": self.group_id,
            "target": self.target,
            "order": self.order,
            "decision": self.decision,
            "failed_stage": self.failed_stage,
            "failed_stage_ko": STAGE_KO.get(self.failed_stage)
            if self.failed_stage
            else None,
            "uncertain_stages": self.uncertain_stages,
            "skipped_stages": self.skipped_stages,
            "retry": self.retry,
            "stages": [s.to_dict() for s in self.stages],
            "elapsed_s": round(self.elapsed_s, 2),
            "meta": self.meta,
        }

    def stage(self, name: str) -> Optional[StageResult]:
        return next((s for s in self.stages if s.stage == name), None)


class StemFilterAgent:
    def __init__(self, cfg: AgentConfig, backend: Optional[JudgeBackend] = None):
        self.cfg = cfg
        self.backend = backend or make_backend(cfg.backend)
        sj = cfg.purity.second_judge
        self.second_backend = make_backend(sj) if sj is not None else None

    def evaluate(self, case: StemCase) -> FilterResult:
        t0 = time.time()
        order = self.cfg.stage_order
        results: List[StageResult] = []
        failed: Optional[str] = None
        for name in order:
            if name == PURITY and self.second_backend is not None:
                r = run_purity(case, self.cfg, self.backend, second=self.second_backend)
            else:
                r = STAGES[name](case, self.cfg, self.backend)
            results.append(r)
            if r.verdict == FAIL and failed is None:
                failed = name
                if self.cfg.early_exit:
                    break
        done = {r.stage for r in results}
        uncertain = [r.stage for r in results if r.verdict == UNCERTAIN]
        if failed:
            decision = REJECT
        elif uncertain:
            decision = HOLD
        else:
            decision = ACCEPT

        retry = None
        if failed:
            fr = next(r for r in results if r.stage == failed)
            retry = dict(RETRY_HINTS[failed])
            retry["reason"] = fr.reason
            if failed == COMPLETENESS and fr.details.get("missing_ranges"):
                retry["missing_ranges"] = fr.details["missing_ranges"]
            if failed == PURITY and fr.details.get("heard_sources"):
                retry["intruding_sources"] = fr.details["heard_sources"]
        elif decision == HOLD:
            retry = {
                "action": "human_review",
                "hint": "Judge was unsure; keep this stem out of automatic selection and "
                "store it for human review.",
                "uncertain_stages": uncertain,
            }

        return FilterResult(
            case.stem_id,
            case.group_id,
            case.target,
            order,
            decision,
            failed,
            uncertain,
            results,
            [s for s in order if s not in done],
            retry,
            time.time() - t0,
            dict(case.meta),
        )
