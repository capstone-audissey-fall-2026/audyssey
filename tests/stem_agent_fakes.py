"""Deterministic fake judge for the stem filter agent (ported from the stem_filter_agent mock).

It reads tags from the stem file name: `absent`, `mixed`, `missing`, `unsure`.
Never use it for real filtering.
"""

import json
from typing import Dict, List

from audyssey.tools.filtering.stem_agent.audio import Clip
from audyssey.tools.filtering.stem_agent.backend import JudgeBackend, Part, YesNo


class MockBackend(JudgeBackend):
    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _stem_name(parts: List[Part]) -> str:
        clips = [p for p in parts if isinstance(p, Clip)]
        return clips[-1].name.lower() if clips else ""

    def yes_no(self, system: str, parts: List[Part], max_tokens: int) -> YesNo:
        self.calls += 1
        q = " ".join(p for p in parts if isinstance(p, str))
        name = self._stem_name(parts)
        neg = (
            "completely free" in q
            or "perfectly clean" in q
            or "fully present" in q
            or "free of any recognisable" in q
            or "Does it contain only the target" in q
            or "Is it free of any" in q
        )
        if "residual" in name:
            truth = False
        elif "remained after" in q:
            truth = False
        elif "Audio 2 is a STEM" in q:  # completeness: truth = something missing
            truth = "missing" in name
        elif "Sound to check" in q:  # purity/named: truth = that source audible
            truth = "mixed" in name and "crowd" in q
        elif "supposed to contain ONLY" in q or "should contain only" in q:  # purity
            # `brief`: intrusion only inside 2-5 s, averaged away when the whole clip is judged
            truth = "mixed" in name or ("brief" in name and "[2.00-" in name)
        else:  # presence: truth = target present
            truth = "absent" not in name
        p = 0.9 if truth else 0.1
        if "unsure" in name:
            p = 0.45
        if neg:
            p = 1.0 - p
        return YesNo(p, ("YES" if p >= 0.5 else "NO") + "\nmock evidence", "mock")

    def generate(self, system: str, parts: List[Part], max_tokens: int) -> str:
        self.calls += 1
        q = " ".join(p for p in parts if isinstance(p, str))
        name = self._stem_name(parts)
        if "NOT the target" in q:
            return json.dumps(["crowd noise"])
        if "time ranges" in q:
            return json.dumps([[2.0, 3.0]] if "missing" in name else [])
        return json.dumps(["target", "crowd noise"] if "mixed" in name else ["target"])

    def info(self) -> Dict[str, str]:
        return {"backend": "mock"}
