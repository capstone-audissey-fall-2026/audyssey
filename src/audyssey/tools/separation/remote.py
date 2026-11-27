from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from pydantic import TypeAdapter

from audyssey.contracts import SourcePlan
from audyssey.tools.remote import post, remote_settings


def separate(
    mono: Path, plan: SourcePlan, video: Path | None, out: Path, attempt: int
) -> Path:
    settings = remote_settings()
    files = {"mono": ("mono.wav", mono.read_bytes(), "audio/wav")}
    if video is not None:
        files["video"] = ("video.mp4", video.read_bytes(), "video/mp4")
    response = post(
        settings.separator_url,
        "/separate",
        files,
        {"plan": plan.model_dump_json(), "attempt": str(attempt)},
        settings.tool_token,
        settings.remote_timeout_s,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.content)
    return out


def separate_batch(
    mono: Path, plans: list[SourcePlan], outs: list[Path], attempt: int
) -> list[Path]:
    if len(plans) != len(outs):
        raise ValueError("expected one output path per source plan")
    settings = Settings()
    response = post(
        settings.separator_url,
        "/separate_batch",
        {"mono": ("mono.wav", mono.read_bytes(), "audio/wav")},
        {
            "plans": TypeAdapter(list[SourcePlan]).dump_json(plans).decode(),
            "attempt": str(attempt),
        },
        settings.tool_token,
        settings.remote_timeout_s,
    )
    names = [f"{index}.wav" for index in range(len(outs))]
    with ZipFile(BytesIO(response.content)) as archive:
        if archive.namelist() != names:
            raise RuntimeError("invalid separation batch response")
        for name, out in zip(names, outs, strict=True):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(name))
    return outs
