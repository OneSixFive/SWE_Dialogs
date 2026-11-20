"""Integrated loudness (ITU-R BS.1770-4, mono) and gain-only level matching for 16-bit PCM.

Used to bring each dialog speaker to the same loudness. Only a constant gain is applied: no compression or limiting.
"""

from __future__ import annotations

import math

import numpy as np
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


def match_loudness(
    chunks: list[bytes], sample_rate: int, *, target_lufs: float, peak_ceiling_dbfs: float
) -> tuple[list[bytes], float | None, float]:
    """One gain for all chunks (s16le mono) so their joint loudness hits the target, capped so peaks stay at or
    below the ceiling. Returns (chunks, measured LUFS, applied gain dB); unmeasurable audio is returned unchanged."""
    arrays = [np.frombuffer(chunk, dtype="<i2") for chunk in chunks]
    joined = np.concatenate(arrays).astype(np.float64) / 32768.0
    measured = integrated_loudness(joined, sample_rate)
    peak = float(np.abs(joined).max()) if joined.size else 0.0
    if measured is None or peak == 0.0:
        return chunks, measured, 0.0
    gain_db = min(target_lufs - measured, peak_ceiling_dbfs - 20 * math.log10(peak))
    if abs(gain_db) < 0.05:
        return chunks, measured, 0.0
    gain = 10 ** (gain_db / 20)
    scaled = [
        np.clip(np.rint(array.astype(np.float64) * gain), -32768, 32767).astype("<i2").tobytes() for array in arrays
    ]
    return scaled, measured, gain_db
