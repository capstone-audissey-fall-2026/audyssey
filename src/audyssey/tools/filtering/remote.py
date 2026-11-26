from pathlib import Path

from audyssey.contracts import FilterResult, SourcePlan
from audyssey.tools.remote import post, remote_settings


def judge(mono: Path, track: Path, plan: SourcePlan) -> FilterResult:
    settings = remote_settings()
    response = post(
        settings.filter_url,
        "/judge",
        {
            "mono": ("mono.wav", mono.read_bytes(), "audio/wav"),
            "track": ("track.wav", track.read_bytes(), "audio/wav"),
        },
        {"plan": plan.model_dump_json()},
        settings.tool_token,
        settings.remote_timeout_s,
    )
    return FilterResult.model_validate(response.json())
