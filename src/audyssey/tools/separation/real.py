from functools import cache
from importlib import import_module
from pathlib import Path
from threading import Lock

import numpy as np

from audyssey.contracts import SourcePlan
from audyssey.media import read_wav, write_wav
from audyssey.settings import Settings

# shortcut: one GPU model per process, one call at a time; batch or queue if throughput matters
_model_lock = Lock()


@cache
def _load():
    settings = Settings()
    try:
        torch = import_module("torch")
        sam = import_module("sam_audio")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "SAM Audio is not installed: install the gpu/ environment"
        ) from exc
    # Rankers and the span predictor are ~4.4B of small's 5.8B params and are built in
    # SAMAudio.__init__ (the stock Judge ranker loads facebook/sam-audio-judge). Skip or
    # rebuild them via config overrides; they are not in the checkpoint, so loading
    # stays strict.
    overrides: dict[str, object] = {}
    if settings.sam_audio_reranking_candidates == 1:
        overrides.update(visual_ranker=None, text_ranker=None)
    else:
        # Same ensemble as the released configs, but the Judge ranker uses our
        # configured Judge (official or mirror) instead of the hardcoded official repo.
        clap = settings.sam_audio_clap_checkpoint or None
        imagebind = settings.sam_audio_imagebind_checkpoint
        overrides["text_ranker"] = {
            "kind": "ensemble",
            "rankers": {
                "clap": [{"kind": "clap", "checkpoint": clap}, 5.0],
                "judge": [
                    {
                        "kind": "judge",
                        "checkpoint_or_model_id": settings.sam_audio_judge_model,
                    },
                    1.0,
                ],
            },
        }
        overrides["visual_ranker"] = (
            {"kind": "imagebind", "checkpoint": imagebind} if imagebind else None
        )
    if not settings.sam_audio_predict_spans:
        overrides["span_predictor"] = None
    model = sam.SAMAudio.from_pretrained(settings.sam_audio_model, **overrides)
    model = model.to(settings.sam_audio_device).eval()
    processor = sam.SAMAudioProcessor.from_pretrained(settings.sam_audio_model)
    return torch, model, processor


def _infer(
    settings: Settings,
    audios: list[np.ndarray],
    descriptions: list[str],
    attempt: int,
    *,
    anchors: list[list[list[str | float]]] | None = None,
    video: Path | None = None,
    predict_spans: bool = False,
) -> list[np.ndarray]:
    torch, model, processor = _load()
    tf32 = settings.sam_audio_allow_tf32 and settings.sam_audio_device.startswith(
        "cuda"
    )
    previous_precision = torch.get_float32_matmul_precision() if tf32 else None
    if tf32:
        torch.set_float32_matmul_precision("high")
    try:
        batch = processor(
            descriptions=descriptions,
            audios=[torch.from_numpy(audio.T) for audio in audios],
            anchors=anchors,
            **({"masked_videos": [str(video)]} if video is not None else {}),
        ).to(settings.sam_audio_device)
        with torch.inference_mode():
            torch.manual_seed(attempt)
            result = model.separate(
                batch,
                reranking_candidates=settings.sam_audio_reranking_candidates,
                predict_spans=predict_spans,
            )
        if len(result.target) != len(audios):
            raise RuntimeError("SAM Audio returned the wrong number of tracks")
        return [
            target.detach().cpu().float().numpy().reshape(-1, 1)
            for target in result.target
        ]
    finally:
        if previous_precision is not None:
            torch.set_float32_matmul_precision(previous_precision)


def _windows(plan: SourcePlan, samples: int, padding: float) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    duration = samples / 48000
    for span in sorted(plan.spans, key=lambda span: span.start):
        start = round(min(duration, max(0, span.start - padding)) * 48000)
        end = round(min(duration, span.end + padding) * 48000)
        if start >= end:
            continue
        if windows and start <= windows[-1][1]:
            windows[-1] = windows[-1][0], max(end, windows[-1][1])
        else:
            windows.append((start, end))
    return windows


def _infer_crops(
    settings: Settings, audios: list[np.ndarray], descriptions: list[str], attempt: int
) -> list[np.ndarray]:
    torch, _, _ = _load()
    try:
        return _infer(settings, audios, descriptions, attempt)
    except torch.cuda.OutOfMemoryError:
        if len(audios) == 1:
            raise
    # The failed call's frame has unwound, so unused GPU allocations can be released.
    torch.cuda.empty_cache()
    mid = len(audios) // 2
    return _infer_crops(
        settings, audios[:mid], descriptions[:mid], attempt
    ) + _infer_crops(settings, audios[mid:], descriptions[mid:], attempt)


def _crop_tracks(
    settings: Settings,
    mono: Path,
    plans: list[SourcePlan],
    attempt: int,
    padding: float,
) -> list[np.ndarray]:
    audio = read_wav(mono)
    tracks = [np.zeros((len(audio), 1), dtype=np.float32) for _ in plans]
    jobs = [
        (index, start, end)
        for index, plan in enumerate(plans)
        for start, end in (
            _windows(plan, len(audio), padding) if plan.spans else [(0, len(audio))]
        )
        if start < end
    ]
    for offset in range(0, len(jobs), settings.sam_audio_batch_size):
        group = jobs[offset : offset + settings.sam_audio_batch_size]
        targets = _infer_crops(
            settings,
            [audio[start:end] for _, start, end in group],
            [plans[index].description for index, _, _ in group],
            attempt,
        )
        for (index, start, end), target in zip(group, targets, strict=True):
            length = min(end - start, len(target))
            tracks[index][start : start + length] = target[:length]
    return tracks


def separate_batch(
    mono: Path, plans: list[SourcePlan], outs: list[Path], attempt: int
) -> list[Path]:
    settings = Settings()
    padding = settings.sam_audio_crop_padding_s
    if padding is None:
        raise ValueError("SAM Audio crop padding is required for batch separation")
    if len(plans) != len(outs):
        raise ValueError("expected one output path per source plan")
    with _model_lock:
        tracks = _crop_tracks(settings, mono, plans, attempt, padding)
    return [write_wav(out, track) for out, track in zip(outs, tracks, strict=True)]


def separate(
    mono: Path, plan: SourcePlan, video: Path | None, out: Path, attempt: int
) -> Path:
    settings = Settings()
    padding = settings.sam_audio_crop_padding_s
    if video is None and padding is not None:
        with _model_lock:
            track = _crop_tracks(settings, mono, [plan], attempt, padding)[0]
        return write_wav(out, track)

    audio = read_wav(mono)
    anchors = (
        [[["+", span.start, span.end] for span in plan.spans]] if plan.spans else None
    )
    with _model_lock:
        target = _infer(
            settings,
            [audio],
            [plan.description],
            attempt,
            anchors=anchors,
            video=video,
            predict_spans=settings.sam_audio_predict_spans,
        )[0]
    track = np.zeros((len(audio), 1), dtype=np.float32)
    length = min(len(audio), len(target))
    track[:length] = target[:length]
    return write_wav(out, track)
