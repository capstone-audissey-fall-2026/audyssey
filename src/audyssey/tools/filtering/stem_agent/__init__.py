"""3-stage stem filter (presence -> purity -> completeness) judged by Qwen3-Omni.

Vendored from the capstone stem_filter_agent (stem_filter/ package, 2026-11-21 version). The stage
logic, prompts and thresholds are unchanged; only I/O was adapted (scipy instead of soundfile, one
OpenAI-compatible backend, no CLI/batch runner). Measured on 625 human-labelled StemFoley stems with
Qwen3-Omni-30B-A3B-Instruct: ACCEPT precision 0.837 (all of S1/S2/S3 good), see docs/filtering_agent.md.
"""

from .agent import ACCEPT, HOLD, REJECT, FilterResult, StemFilterAgent
from .config import AgentConfig, load_config
from .stages import StemCase

__all__ = [
    "ACCEPT",
    "HOLD",
    "REJECT",
    "AgentConfig",
    "FilterResult",
    "StemCase",
    "StemFilterAgent",
    "load_config",
]
