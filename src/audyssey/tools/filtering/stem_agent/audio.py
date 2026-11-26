"""Audio utilities: loading, resampling, silence checks, windowing, residuals."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from math import gcd
from typing import List, Tuple

import numpy as np
from scipy.io import wavfile

EPS = 1e-12


@dataclass
class Clip:
    """Mono float32 audio at a fixed sample rate."""

    samples: np.ndarray
    sr: int
    name: str = ""

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.sr)

    def crop(self, start_s: float, end_s: float) -> "Clip":
        a = max(0, int(round(start_s * self.sr)))
        b = min(len(self.samples), int(round(end_s * self.sr)))
        return Clip(
            self.samples[a:b].copy(), self.sr, f"{self.name}[{start_s:.2f}-{end_s:.2f}]"
        )

    def peak_dbfs(self) -> float:
        return amp_to_db(
            float(np.max(np.abs(self.samples))) if len(self.samples) else 0.0
        )

    def normalized(self, peak_dbfs: float) -> "Clip":
        peak = float(np.max(np.abs(self.samples))) if len(self.samples) else 0.0
        if peak < EPS:
            return self
        gain = (10 ** (peak_dbfs / 20.0)) / peak
        return Clip((self.samples * gain).astype(np.float32), self.sr, self.name)

    def to_wav_bytes(self) -> bytes:
        buf = io.BytesIO()
        pcm = (np.clip(self.samples, -1.0, 1.0) * 32767.0).astype(np.int16)
        wavfile.write(buf, self.sr, pcm)
        return buf.getvalue()

    def to_data_uri(self) -> str:
        return "data:audio/wav;base64," + base64.b64encode(self.to_wav_bytes()).decode(
            "ascii"
        )

    def to_base64(self) -> str:
        return base64.b64encode(self.to_wav_bytes()).decode("ascii")


def amp_to_db(x: float) -> float:
    return 20.0 * np.log10(max(x, EPS))


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    from scipy.signal import resample_poly

    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def align(a: Clip, b: Clip) -> Tuple[Clip, Clip]:
    """Zero-pad the shorter clip so both have the same length."""
    n = max(len(a.samples), len(b.samples))
    pa = np.pad(a.samples, (0, n - len(a.samples)))
    pb = np.pad(b.samples, (0, n - len(b.samples)))
    return Clip(pa, a.sr, a.name), Clip(pb, b.sr, b.name)


def compute_residual(original: Clip, stem: Clip) -> Clip:
    o, s = align(original, stem)
    return Clip(
        (o.samples - s.samples).astype(np.float32), o.sr, "residual(original-stem)"
    )


def windows(
    duration: float, window_s: float, hop_s: float
) -> List[Tuple[float, float]]:
    """Cover [0, duration] with windows; one window if the clip is short."""
    if duration <= window_s:
        return [(0.0, duration)]
    out = []
    t = 0.0
    while t + window_s < duration:
        out.append((t, t + window_s))
        t += hop_s
    out.append((max(0.0, duration - window_s), duration))
    return out


def silent_ratio(clip: Clip, floor_dbfs: float, frame_s: float = 0.02) -> float:
    """Fraction of short frames whose RMS is below floor_dbfs."""
    n = max(1, int(frame_s * clip.sr))
    x = clip.samples
    if len(x) == 0:
        return 1.0
    frames = len(x) // n or 1
    x = np.pad(x, (0, max(0, frames * n - len(x))))[: frames * n].reshape(frames, n)
    rms = np.sqrt(np.mean(x**2, axis=1) + EPS)
    db = 20.0 * np.log10(rms + EPS)
    return float(np.mean(db < floor_dbfs))
