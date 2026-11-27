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
    audio: np.ndarray,
    plans: list[SourcePlan],
    attempt: int,
    video: Path | None = None,
) -> list[np.ndarray]:
    torch, model, processor = _load()
    tf32 = settings.sam_audio_allow_tf32 and settings.sam_audio_device.startswith(
        "cuda"
    )
    anchor_lists = [
        [["+", span.start, span.end] for span in plan.spans] for plan in plans
    ]
    waveform = torch.from_numpy(audio.T)
    previous_precision = torch.get_float32_matmul_precision() if tf32 else None
    if tf32:
        torch.set_float32_matmul_precision("high")
    try:
        batch = processor(
            descriptions=[plan.description for plan in plans],
            audios=[waveform] * len(plans),
            anchors=anchor_lists if any(anchor_lists) else None,
            **({"masked_videos": [str(video)]} if video is not None else {}),
        ).to(settings.sam_audio_device)
        with torch.inference_mode():
            torch.manual_seed(attempt)
            result = model.separate(
                batch,
                reranking_candidates=settings.sam_audio_reranking_candidates,
                predict_spans=settings.sam_audio_predict_spans,
            )
        if len(result.target) != len(plans):
            raise RuntimeError("SAM Audio returned the wrong number of tracks")
        return [
            target.detach().cpu().float().numpy().reshape(-1, 1)
            for target in result.target
        ]
    finally:
        if previous_precision is not None:
            torch.set_float32_matmul_precision(previous_precision)


def _write_track(out: Path, target: np.ndarray, samples: int) -> Path:
    track = np.zeros((samples, 1), dtype=np.float32)
    length = min(samples, len(target))
    track[:length] = target[:length]
    return write_wav(out, track)


def separate_batch(
    mono: Path, plans: list[SourcePlan], outs: list[Path], attempt: int
) -> list[Path]:
    if not plans or len(plans) != len(outs):
        raise ValueError("expected one output path per source plan")
    settings = Settings()
    audio = read_wav(mono)
    jobs = list(zip(plans, outs, strict=True))
    # SAM Audio predicts spans only if the whole batch has no supplied anchors.
    groups = (
        [
            [job for job in jobs if bool(job[0].spans) == anchored]
            for anchored in (True, False)
        ]
        if settings.sam_audio_predict_spans
        else [jobs]
    )
    with _model_lock:
        torch, _, _ = _load()
        batch_size = settings.sam_audio_batch_size
        for group in groups:
            offset = 0
            while offset < len(group):
                batch = group[offset : offset + batch_size]
                try:
                    targets = _infer(
                        settings, audio, [plan for plan, _ in batch], attempt
                    )
                except torch.cuda.OutOfMemoryError:
                    if len(batch) == 1:
                        raise
                    batch_size = len(batch) // 2
                else:
                    for (_, out), target in zip(batch, targets, strict=True):
                        _write_track(out, target, len(audio))
                    offset += len(batch)
                    continue
                # Release cached allocations after the failed frame has unwound.
                torch.cuda.empty_cache()
    return outs


def separate(
    mono: Path, plan: SourcePlan, video: Path | None, out: Path, attempt: int
) -> Path:
    settings = Settings()
    audio = read_wav(mono)
    with _model_lock:
        target = _infer(settings, audio, [plan], attempt, video)[0]
    return _write_track(out, target, len(audio))
