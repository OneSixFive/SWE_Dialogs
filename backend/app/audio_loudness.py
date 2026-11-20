"""Integrated loudness (ITU-R BS.1770-4, mono) and gain-only level matching for 16-bit PCM.

Used to bring each dialog speaker to the same loudness: a constant gain per speaker, then a lookahead peak limiter
that only touches the rare peaks above the ceiling.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import lfilter

BLOCK_SECONDS = 0.4
BLOCK_OVERLAP = 0.75
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0


def _k_weighting(sample_rate: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """BS.1770 pre-filter (high shelf) and RLB (high pass) biquads for any sample rate."""
    w0 = 2 * math.pi * 1500.0 / sample_rate
    a = 10 ** (4.0 / 40)
    alpha = math.sin(w0) / (2 * (1 / math.sqrt(2)))
    cos, root = math.cos(w0), 2 * math.sqrt(a) * alpha
    shelf = (
        np.array([a * ((a + 1) + (a - 1) * cos + root), -2 * a * ((a - 1) + (a + 1) * cos),
                  a * ((a + 1) + (a - 1) * cos - root)]),
        np.array([(a + 1) - (a - 1) * cos + root, 2 * ((a - 1) - (a + 1) * cos), (a + 1) - (a - 1) * cos - root]),
    )
    w0 = 2 * math.pi * 38.0 / sample_rate
    alpha, cos = math.sin(w0) / (2 * 0.5), math.cos(w0)
    high_pass = (
        np.array([(1 + cos) / 2, -(1 + cos), (1 + cos) / 2]),
        np.array([1 + alpha, -2 * cos, 1 - alpha]),
    )
    return [shelf, high_pass]


def integrated_loudness(samples: np.ndarray, sample_rate: int) -> float | None:
    """Gated integrated loudness in LUFS of float samples in [-1, 1]; None when shorter than one block or silent."""
    block = int(BLOCK_SECONDS * sample_rate)
    if len(samples) < block:
        return None
    filtered = samples
    for b, a in _k_weighting(sample_rate):
        filtered = lfilter(b, a, filtered)
    step = int(block * (1 - BLOCK_OVERLAP))
    cumulative = np.concatenate(([0.0], np.cumsum(filtered * filtered)))
    starts = np.arange(0, len(filtered) - block + 1, step)
    power = (cumulative[starts + block] - cumulative[starts]) / block
    power = power[power > 10 ** ((ABSOLUTE_GATE_LUFS + 0.691) / 10)]
    if power.size == 0:
        return None
    relative_gate = -0.691 + 10 * math.log10(power.mean()) + RELATIVE_GATE_LU
    power = power[power > 10 ** ((relative_gate + 0.691) / 10)]
    if power.size == 0:
        return None
    return -0.691 + 10 * math.log10(power.mean())


def measure(chunks: list[bytes], sample_rate: int) -> tuple[float | None, float | None]:
    """(integrated LUFS, peak dBFS) of s16le mono chunks taken together; None where unmeasurable."""
    joined = np.concatenate([np.frombuffer(chunk, dtype="<i2") for chunk in chunks]).astype(np.float64) / 32768.0
    peak = float(np.abs(joined).max()) if joined.size else 0.0
    return integrated_loudness(joined, sample_rate), (20 * math.log10(peak) if peak > 0 else None)


def limit_peaks(samples: np.ndarray, sample_rate: int, *, ceiling_dbfs: float, lookahead_seconds: float) -> np.ndarray:
    """Lookahead peak limiter for float samples: no sample ends above the ceiling, and the gain eases down and back up
    over +/- the lookahead around each peak instead of clipping.

    The needed gain is spread to every sample within the lookahead by a minimum filter, then smoothed with a Hann
    window of the same span. Every sample inside that window already carries a gain at or below the one the peak
    needs, so the smoothed curve can never let a peak through.
    """
    ceiling = 10 ** (ceiling_dbfs / 20)
    magnitude = np.abs(samples)
    if magnitude.size == 0 or magnitude.max() <= ceiling:
        return samples
    needed = np.minimum(1.0, ceiling / np.maximum(magnitude, 1e-12))
    half = max(1, int(lookahead_seconds * sample_rate))
    held = minimum_filter1d(needed, size=2 * half + 1, mode="nearest")
    window = np.hanning(2 * half + 3)[1:-1]
    smoothed = np.convolve(np.pad(held, half, mode="edge"), window / window.sum(), mode="valid")
    return samples * np.minimum(smoothed, needed)


def apply_gain(
    chunks: list[bytes],
    gain_db: float,
    sample_rate: int,
    *,
    ceiling_dbfs: float | None = None,
    lookahead_seconds: float = 0.005,
) -> list[bytes]:
    """Constant gain for s16le mono chunks, then (when a ceiling is given) the peak limiter per chunk."""
    if abs(gain_db) < 0.05 and ceiling_dbfs is None:
        return chunks
    gain = 10 ** (gain_db / 20)
    leveled = []
    for chunk in chunks:
        samples = np.frombuffer(chunk, dtype="<i2").astype(np.float64) / 32768.0 * gain
        if ceiling_dbfs is not None:
            samples = limit_peaks(
                samples, sample_rate, ceiling_dbfs=ceiling_dbfs, lookahead_seconds=lookahead_seconds
            )
        leveled.append(np.clip(np.rint(samples * 32768.0), -32768, 32767).astype("<i2").tobytes())
    return leveled


def shared_level_gains(
    levels: dict[str, tuple[float | None, float | None]], *, target_lufs: float, peak_ceiling_dbfs: float
) -> tuple[float | None, dict[str, float]]:
    """Gains that put every group at one common loudness: the target, or lower when some group cannot reach it
    without its peak passing the ceiling. Unmeasurable groups get 0 dB. Returns (common LUFS, gain dB per group)."""
    reachable = [
        min(target_lufs, lufs + (peak_ceiling_dbfs - peak))
        for lufs, peak in levels.values()
        if lufs is not None and peak is not None
    ]
    if not reachable:
        return None, {key: 0.0 for key in levels}
    common = min(reachable)
    return common, {
        key: (common - lufs if lufs is not None and peak is not None else 0.0) for key, (lufs, peak) in levels.items()
    }
