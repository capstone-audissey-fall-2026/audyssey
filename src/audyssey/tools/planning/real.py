"""플래닝 담당 모듈의 기본 구현. 성능이 아니라 연결 확인용. 교체 가능."""

import base64
import io
import json
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypeVar, cast

import numpy as np
from scipy.signal import resample_poly
from google import genai
from google.genai import errors, types
from langsmith import trace
from langsmith.run_helpers import tracing_context
from openai.types.chat import ChatCompletionContentPartParam, ChatCompletionMessageParam
from pydantic import TypeAdapter, ValidationError

from audyssey import media
from audyssey import trace as job_trace
from audyssey.contracts import Model, PlanIssue, SourcePlan, Span, VisualHint
from audyssey.settings import LLMEndpoint, Settings
from audyssey.tools.planning import llm
from audyssey.tools.planning import current_request, prompts


class _Sources(Model):
    sources: list[object]


class _Check(Model):
    status: Literal["supported", "unsupported", "uncertain"]
    evidence: Literal["audio", "visual", "audio_visual", "none"]
    reason: str = ""


class _Span(Model):
    start: float
    end: float


class _Hint(Model):
    time: float
    box: tuple[float, float, float, float]
    description: str


_Response = TypeVar("_Response", bound=Model)


class _InvalidJSON(RuntimeError):
    pass


_RETRY = "Return valid JSON matching the schema."
# Inline requests cap at 20 MB (Gemini uploads instead); 512 px clips of a 30 s video are far below.
_MAX_INLINE_B64 = 19_000_000

# Provider-neutral request media: labels, base64 JPEG frames, base64 mp4 clips.
_Part = tuple[Literal["text", "image", "video", "audio"], str]
_Usage = dict[str, int]
_Send = Callable[[bool], tuple[str | None, _Usage]]


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _media(
    video: Path, endpoint: LLMEndpoint, windows: list[tuple[float, float]], tmp: Path
) -> list[_Part]:
    """Frames sampled at endpoint.fps, or one clip per time window."""
    parts: list[_Part] = []
    left = endpoint.max_frames
    for i, (start, end) in enumerate(windows):
        if endpoint.input == "video":
            clip = media.planner_clip(
                video,
                tmp / f"clip-{i}.mp4",
                endpoint.video_audio and current_request().audio_available,
                start,
                end,
            )
            parts += [
                ("text", f"Video from {start:g} to {end:g} seconds"),
                ("video", _b64(clip)),
            ]
            continue
        if left == 0:
            # ponytail: frames past max_frames are dropped, later windows unseen.
            break
        count = max(1, min(round((end - start) * endpoint.fps), left))
        left -= count
        for time, path in media.extract_frames(
            video, count, tmp / f"frames-{i}", start, end
        ):
            parts += [("text", f"Frame at {time:g} seconds"), ("image", _b64(path))]
    inline = endpoint.api != "gemini"
    if inline and sum(len(v) for k, v in parts if k == "video") > _MAX_INLINE_B64:
        raise RuntimeError("planner video is too large to send inline")
    return parts


def _audio_media(
    samples: np.ndarray, windows: list[tuple[float, float]]
) -> list[_Part]:
    """Encode context windows as PCM16 WAV; retain stereo to avoid cancellation."""
    parts: list[_Part] = []
    for start, end in windows:
        data = resample_poly(
            samples[round(start * 48000) : round(end * 48000)], 1, 3, axis=0
        )
        output = io.BytesIO()
        with wave.open(output, "wb") as stream:
            stream.setnchannels(data.shape[1])
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())
        parts.extend(
            [
                ("text", f"Audio from {start:g} to {end:g} seconds"),
                ("audio", base64.b64encode(output.getvalue()).decode("ascii")),
            ]
        )
    return parts


@contextmanager
def _chat(
    endpoint: LLMEndpoint, system: str, text: str, parts: list[_Part]
) -> Iterator[_Send]:
    content: list[ChatCompletionContentPartParam] = [{"type": "text", "text": text}]
    for kind, value in parts:
        if kind == "text":
            content.append({"type": "text", "text": value})
        elif kind == "image":
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{value}"},
                }
            )
        elif kind == "audio":
            content.append(
                {
                    "type": "input_audio",
                    "input_audio": {"data": value, "format": "wav"},
                }
            )
        else:
            # video_url (vLLM, OpenRouter); not in the OpenAI SDK types.
            content.append(
                cast(
                    ChatCompletionContentPartParam,
                    {
                        "type": "video_url",
                        "video_url": {"url": f"data:video/mp4;base64,{value}"},
                    },
                )
            )
    extra: dict[str, object] = {}
    if endpoint.api == "openai" and any(kind == "video" for kind, _ in parts):
        # vLLM-only fields; OpenRouter takes no fps and Gemini hears the clip's audio.
        # num_frames=-1 lifts vLLM's 32-frame default so fps decides; needs
        # --trust-request-mm-kwargs on the server.
        extra["media_io_kwargs"] = {"video": {"fps": endpoint.fps, "num_frames": -1}}
        if endpoint.video_audio and current_request().audio_available:
            extra["mm_processor_kwargs"] = {"use_audio_in_video": True}
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]

    def send(retry: bool) -> tuple[str | None, _Usage]:
        if retry:
            messages.append({"role": "user", "content": _RETRY})
        with llm.chat_client(endpoint) as client:
            response = client.chat.completions.create(
                model=endpoint.model,
                messages=messages,
                response_format={"type": "json_object"},
                extra_body=extra or None,
            )
        usage = response.usage
        return (
            response.choices[0].message.content if response.choices else None,
            {
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
            if usage
            else {},
        )

    yield send


@contextmanager
def _gemini(
    endpoint: LLMEndpoint, system: str, text: str, parts: list[_Part]
) -> Iterator[_Send]:
    """Upload clips through the Files API, send their URIs, delete them after."""
    uploaded: list[str] = []
    with llm.gemini_client(endpoint) as client:
        try:
            contents: list[types.Part] = []
            for kind, value in parts:
                if kind == "text":
                    contents.append(types.Part(text=value))
                elif kind == "image":
                    contents.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(value), mime_type="image/jpeg"
                        )
                    )
                elif kind == "audio":
                    contents.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(value), mime_type="audio/wav"
                        )
                    )
                else:
                    file = llm.gemini_upload(
                        client, base64.b64decode(value), "video/mp4"
                    )
                    uploaded.append(file.name or "")
                    contents.append(
                        types.Part(
                            file_data=types.FileData(
                                file_uri=file.uri, mime_type="video/mp4"
                            ),
                            video_metadata=types.VideoMetadata(fps=endpoint.fps),
                        )
                    )
            yield _gemini_send(client, endpoint, system, text, contents)
        except errors.APIError as exc:
            message = f"gemini request failed: {exc}"
            raise RuntimeError(
                message.replace(endpoint.api_key or "\0", "***")
            ) from None
        finally:
            for name in filter(None, uploaded):
                # Files expire after 48 h anyway; a failed delete must not hide the result.
                with suppress(errors.APIError):
                    client.files.delete(name=name)


def _gemini_send(
    client: genai.Client,
    endpoint: LLMEndpoint,
    system: str,
    text: str,
    contents: list[types.Part],
) -> _Send:
    contents.append(types.Part(text=text))
    config = types.GenerateContentConfig(
        system_instruction=system, response_mime_type="application/json"
    )

    def send(retry: bool) -> tuple[str | None, _Usage]:
        if retry:
            contents.append(types.Part(text=_RETRY))
        response = client.models.generate_content(
            model=endpoint.model,
            contents=types.Content(role="user", parts=contents),
            config=config,
        )
        meta = response.usage_metadata
        return response.text or None, {
            "input_tokens": meta.prompt_token_count or 0,
            "output_tokens": meta.candidates_token_count or 0,
            "total_tokens": meta.total_token_count or 0,
        } if meta else {}

    return send


def _request(
    endpoint: LLMEndpoint,
    system: str,
    text: str,
    parts: list[_Part],
    response_type: type[_Response],
) -> _Response:
    backend = _gemini if endpoint.api == "gemini" else _chat
    record = job_trace.current()
    sent = _keep_media(record, parts) if record else []
    raw = None
    with backend(endpoint, system, text, parts) as send:
        for attempt in range(2):
            # Record model/usage only: the SDK wrapper would also trace media bytes.
            with trace(
                "planner_completion",
                run_type="llm",
                inputs={"model": endpoint.model},
                metadata={"ls_model_name": endpoint.model, "ls_model_type": "chat"},
            ) as run:
                with tracing_context(enabled=False, parent=False):
                    raw, usage = send(attempt > 0)
                run.end(outputs={"usage_metadata": usage} if usage else {})
            if record:
                record.requests.append(
                    {
                        "model": endpoint.model,
                        "api": endpoint.api,
                        "input": "audio"
                        if any(kind == "audio" for kind, _ in parts)
                        else endpoint.input,
                        "fps": endpoint.fps,
                        "audio": _hears(endpoint) and current_request().audio_available,
                        "purpose": current_request().purpose,
                        "prompt_version": prompts.VERSION,
                        "attempt": attempt + 1,
                        "system": system,
                        "text": text + ("\n" + _RETRY if attempt else ""),
                        "media": sent,
                        "raw": raw,
                        "usage": usage,
                    }
                )
            try:
                data = json.loads(raw or "")
                if isinstance(data, list) and len(response_type.model_fields) == 1:
                    # Gemini sometimes drops the {"sources": [...]} wrapper.
                    (field,) = response_type.model_fields
                    data = {field: data}
                return response_type.model_validate(data)
            except (json.JSONDecodeError, ValidationError):
                continue
    excerpt = raw or ""
    if endpoint.api_key:
        excerpt = excerpt.replace(endpoint.api_key, "***")
    raise _InvalidJSON(f"planner returned invalid JSON: {excerpt[:500]}") from None


def _keep_media(record: job_trace.Call, parts: list[_Part]) -> list[dict[str, str]]:
    """Save the frames and clips a request sends, labelled by their time."""
    kept, label = [], ""
    batch = len(record.requests)
    for i, (kind, value) in enumerate(parts):
        if kind == "text":
            label = value
            continue
        suffix = {"image": "jpg", "video": "mp4", "audio": "wav"}[kind]
        name = f"{batch}-{i}.{suffix}"
        file = record.save(name, base64.b64decode(value))
        kept.append({"kind": kind, "label": label, "file": file})
    return kept


def _hears(endpoint: LLMEndpoint) -> bool:
    return endpoint.input == "video" and endpoint.video_audio


def _source(item: object, duration: float) -> SourcePlan:
    data = TypeAdapter(dict[str, object]).validate_python(item)
    if "spans" in data:
        if not isinstance(data["spans"], list):
            raise ValueError("spans must be a list")
        spans = []
        for value in data["spans"]:
            span = _Span.model_validate(value)
            start, end = (
                max(0, min(duration, span.start)),
                max(0, min(duration, span.end)),
            )
            if start < end:
                spans.append(Span(start=start, end=end))
        data["spans"] = spans
    if data.get("visual_hint") is not None:
        hint = _Hint.model_validate(data["visual_hint"])
        box = tuple(max(0, min(1, x)) for x in hint.box)
        data["visual_hint"] = (
            VisualHint(
                time=max(0, min(duration, hint.time)),
                box=(box[0], box[1], box[2], box[3]),
                description=hint.description,
            )
            if box[0] < box[2] and box[1] < box[3]
            else None
        )
    return SourcePlan.model_validate(data)


def plan(
    video: Path, audio: Path, duration: float, feedback: list[PlanIssue]
) -> list[SourcePlan]:
    endpoint = Settings().planner_endpoint()
    request = current_request()
    with TemporaryDirectory() as tmp:
        parts = _media(video, endpoint, [(0.0, duration)], Path(tmp))
    response = _request(
        endpoint,
        prompts.planner_prompt(
            request.purpose,
            request.audio_available and _hears(endpoint),
            json.dumps(SourcePlan.model_json_schema()),
        ),
        f"Video duration: {duration:g} seconds. Feedback: "
        + json.dumps([issue.model_dump() for issue in feedback])
        + "\nRequest context: "
        + json.dumps(
            {
                "purpose": request.purpose,
                "audio_available": request.audio_available,
                "audio_in_request": request.audio_available and _hears(endpoint),
                "accepted_sources": [
                    p.model_dump(include={"name", "kind", "description", "spans"})
                    for p in request.accepted
                ],
            }
        ),
        parts,
        _Sources,
    )
    sources = []
    for item in response.sources:
        try:
            sources.append(_source(item, duration))
        except ValueError:
            continue
    if response.sources and not sources:
        raise RuntimeError("planner returned no valid sources")
    return sources


def validation_windows(
    source: SourcePlan, duration: float, padding: float
) -> list[tuple[float, float]]:
    """Bound context to the video and avoid sending overlapping clips twice."""
    targets = [(s.start, s.end) for s in source.spans] or [(0.0, duration)]
    merged: list[tuple[float, float]] = []
    for start, end in sorted(targets):
        start, end = max(0.0, start - padding), min(duration, end + padding)
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def validate_plan(video: Path, audio: Path, plans: list[SourcePlan]) -> list[PlanIssue]:
    """Validate purpose-specific evidence; errors and uncertainty never approve."""
    if not plans:
        return []
    settings = Settings()
    endpoint = settings.validator_endpoint()
    request = current_request()
    audio_capable = (
        settings.validator_audio
        if settings.validator_audio is not None
        else _hears(endpoint)
    )
    hears = request.audio_available and audio_capable
    # Visual mode: the validator judges separation from what it sees alone.
    visual_mode = (
        request.purpose == "separate" and request.audio_available and not hears
    )
    visual = endpoint.model_copy(update={"video_audio": False})
    duration, _ = media.probe(video)
    samples = media.read_wav(audio) if request.purpose == "separate" and hears else None
    issues = []

    def not_validated(source: SourcePlan) -> bool:
        if source.kind in {"music", "ambience"} or source.visual_hint is None:
            issues.append(
                PlanIssue(
                    source_name=source.name,
                    kind="not_validated",
                    message=f"{source.name}: not validated (no visual evidence possible)",
                )
            )
            return True
        return False

    for source in plans:
        source_visual = visual_mode
        source_hears = hears
        if request.purpose == "separate" and not request.audio_available:
            issues.append(
                PlanIssue(
                    source_name=source.name,
                    kind="validation_unavailable",
                    message=f"{source.name}: separation requires audio-enabled video validation",
                )
            )
            continue
        if source_visual and not_validated(source):
            continue
        if request.purpose == "generate" and source.kind == "dialogue":
            issues.append(
                PlanIssue(
                    source_name=source.name,
                    kind="unsupported_source",
                    message=f"{source.name}: dialogue is not generated",
                )
            )
            continue
        windows = validation_windows(source, duration, settings.validator_context_s)
        if not windows or any(
            s.end > duration or s.start >= duration for s in source.spans
        ):
            issues.append(
                PlanIssue(
                    source_name=source.name,
                    kind="span_out_of_range",
                    message=f"{source.name}: no valid validation interval",
                )
            )
            continue
        if samples is not None:
            targets = [(s.start, s.end) for s in source.spans] or [(0.0, duration)]
            if not any(
                np.max(
                    np.abs(samples[round(start * 48000) : round(end * 48000)]),
                    initial=0,
                )
                > np.finfo(np.float32).eps
                for start, end in targets
            ):
                issues.append(
                    PlanIssue(
                        source_name=source.name,
                        kind="not_found",
                        message=f"{source.name}: target intervals are digitally silent",
                    )
                )
                continue
        parts = None
        if samples is not None and (
            settings.validator_audio_only or not _hears(endpoint)
        ):
            parts = _audio_media(samples, windows)
            # ponytail: oversize audio (~3.5 min at 16 kHz stereo) falls back to visual validation; split windows if long sources matter.
            if sum(len(v) for k, v in parts if k == "audio") > _MAX_INLINE_B64:
                parts = None
                source_hears, source_visual = False, True
                if not_validated(source):
                    continue
        target = endpoint if source_hears else visual
        if parts is None:
            with TemporaryDirectory() as tmp:
                parts = _media(video, target, windows, Path(tmp))
        system = prompts.validator_prompt(request.purpose, source_hears)
        text = json.dumps(
            {
                "source": source.model_dump(include={"name", "kind", "description"}),
                "purpose": request.purpose,
                "audio_available": source_hears,
                "target_intervals": [(s.start, s.end) for s in source.spans]
                or [(0.0, duration)],
                "context_intervals": windows,
            }
        )
        try:
            check = _request(target, system, text, parts, _Check)
        except _InvalidJSON:
            issues.append(
                PlanIssue(
                    source_name=source.name,
                    kind="validation_error",
                    message=f"{source.name}: validator returned invalid JSON twice; plan is not validated",
                )
            )
            continue
        kind = None
        if not source_hears and check.evidence in {"audio", "audio_visual"}:
            kind = "validation_uncertain"
        elif check.status == "unsupported":
            kind = "not_found"
        elif (
            check.status == "uncertain"
            or check.evidence == "none"
            or (
                request.purpose == "separate"
                and not source_visual
                and check.evidence not in {"audio", "audio_visual"}
            )
        ):
            kind = "validation_uncertain"
        if kind:
            issues.append(
                PlanIssue(
                    source_name=source.name,
                    kind=kind,
                    message=f"{source.name}: "
                    + (check.reason or "insufficient evidence in target intervals"),
                )
            )
    return issues
