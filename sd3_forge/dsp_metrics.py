"""Exact mathematical DSP primitives for SD3 Preset Forge v2 (anti-Goodhart metrics)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage, signal

EPS = 1e-12


def to_db(val: float) -> float:
    return float(20.0 * np.log10(max(val, EPS)))


def rms(x: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def asymmetric_tukey_window(
    n: int,
    sr: int,
    attack_taper_ms: float = 0.5,
    release_taper_ms: float = 25.0,
) -> np.ndarray:
    """Asymmetric cosine taper preserving early transients (0.5 ms rise) while smoothing tail cutoff."""
    if n <= 0:
        return np.array([], dtype=np.float64)
    if n < 8:
        return np.ones(n, dtype=np.float64)

    win = np.ones(n, dtype=np.float64)
    n_a = min(max(0, int(round(attack_taper_ms * sr / 1000.0))), n // 4)
    n_r = min(max(0, int(round(release_taper_ms * sr / 1000.0))), n // 2)

    if n_a > 0:
        t = np.linspace(0.0, np.pi, n_a, endpoint=False)
        win[:n_a] = 0.5 * (1.0 - np.cos(t))
    if n_r > 0:
        t = np.linspace(0.0, np.pi, n_r, endpoint=False)
        win[-n_r:] = 0.5 * (1.0 + np.cos(t))
    return win


def _one_sided_power_spectrum(
    x: np.ndarray,
    sr: int,
    *,
    win: np.ndarray | None = None,
    n_fft: int | None = None,
) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Return `(freqs, one_sided_weighted_mag2, win_energy, n_fft)` obeying Parseval's theorem."""
    n = len(x)
    w = win if win is not None else asymmetric_tukey_window(n, sr)
    nf = n_fft or max(4096, 1 << int(np.ceil(np.log2(max(n, 16)))))
    spec = np.fft.rfft(x.astype(np.float64) * w, n=nf)
    freqs = np.fft.rfftfreq(nf, d=1.0 / sr)
    mag2 = np.abs(spec) ** 2
    if len(mag2) > 2:
        if nf % 2 == 0:
            mag2[1:-1] *= 2.0
        else:
            mag2[1:] *= 2.0
    win_energy = float(np.sum(w**2)) + EPS
    return freqs, mag2, win_energy, nf


def band_energy_ratio_db(
    x: np.ndarray,
    sr: int,
    f_low: float,
    f_high: float,
    *,
    attack_taper_ms: float = 0.5,
    release_taper_ms: float = 25.0,
) -> float:
    """Parseval-exact band energy relative to total signal energy (dB)."""
    if len(x) < 16:
        return -120.0
    win = asymmetric_tukey_window(len(x), sr, attack_taper_ms=attack_taper_ms, release_taper_ms=release_taper_ms)
    freqs, mag2, _, _ = _one_sided_power_spectrum(x, sr, win=win)
    mask = (freqs >= f_low) & (freqs <= min(f_high, sr * 0.495))
    total_pow = float(np.sum(mag2)) + EPS
    band_pow = float(np.sum(mag2[mask]))
    return float(10.0 * np.log10(max(band_pow / total_pow, EPS)))


def band_rms_dbfs(
    x: np.ndarray,
    sr: int,
    f_low: float,
    f_high: float,
    *,
    attack_taper_ms: float = 0.5,
    release_taper_ms: float = 25.0,
) -> float:
    """Parseval-exact in-band RMS level in dBFS."""
    if len(x) < 16:
        return -120.0
    win = asymmetric_tukey_window(len(x), sr, attack_taper_ms=attack_taper_ms, release_taper_ms=release_taper_ms)
    freqs, mag2, win_energy, n_fft = _one_sided_power_spectrum(x, sr, win=win)
    mask = (freqs >= f_low) & (freqs <= min(f_high, sr * 0.495))
    band_mean_sq = float(np.sum(mag2[mask])) / (n_fft * win_energy)
    return float(10.0 * np.log10(max(band_mean_sq, EPS)))


def attack_body_tail_metrics(
    mono: np.ndarray,
    sr: int,
    *,
    onset_offset_in_slice_ms: float = 2.0,
) -> dict[str, float]:
    """Compute time-windowed Attack (`[-2,+20 ms]`), Body (`[+10,+150 ms]`), and Tail (`[+30,+350 ms]`) levels."""

    def _slice(ms0: float, ms1: float) -> np.ndarray:
        i0 = max(0, min(len(mono), int((onset_offset_in_slice_ms + ms0) * sr / 1000.0)))
        i1 = max(i0, min(len(mono), int((onset_offset_in_slice_ms + ms1) * sr / 1000.0)))
        return mono[i0:i1]

    atk_seg = _slice(-2.0, 20.0)
    body_seg = _slice(10.0, 150.0)
    tail_seg = _slice(30.0, 350.0)
    atk_db = to_db(rms(atk_seg))
    body_db = to_db(rms(body_seg))
    tail_db = to_db(rms(tail_seg))
    return {
        "attack_rms_dbfs": atk_db,
        "body_rms_dbfs": body_db,
        "tail_rms_dbfs": tail_db,
        "attack_to_body_db": float(atk_db - body_db),
        "body_to_tail_db": float(body_db - tail_db),
    }


def schroeder_decay_ms(x: np.ndarray, sr: int, drop_db: float = 20.0) -> dict[str, Any]:
    """ISO 3382 Schroeder backward Energy Decay Curve (EDC) with R^2 quality & drop guard."""
    if len(x) < max(64, int(0.025 * sr)):
        return {"decay_ms": 0.0, "r2": 0.0, "achieved_drop_db": 0.0, "drop_guard_triggered": True}

    hop = max(1, int(0.002 * sr))
    env_win = max(hop, int(0.006 * sr))
    env = np.array([rms(x[i : i + env_win]) for i in range(0, len(x) - env_win + 1, hop)], dtype=np.float64)
    if len(env) < 4 or float(np.max(env)) < 1e-6:
        return {"decay_ms": 0.0, "r2": 0.0, "achieved_drop_db": 0.0, "drop_guard_triggered": True}

    pk_frame = int(np.argmax(env))
    i0 = min(len(x) - 16, pk_frame * hop)
    y = x[i0:].astype(np.float64)

    # Physical envelope decay depth (distinguishes finite buffer truncation from genuine full decay)
    tail_rms_db = 20.0 * np.log10(np.maximum(env[pk_frame:], EPS) / (env[pk_frame] + EPS))
    last_decile_start = min(len(tail_rms_db) - 1, max(0, int(len(tail_rms_db) * 0.9)))
    achieved_drop_db = float(-np.median(tail_rms_db[last_decile_start:]))

    # Lundeby-inspired noise-floor cutoff when late noise plateau is elevated
    edc = np.cumsum(y[::-1] ** 2)[::-1]
    edc_db = 10.0 * np.log10(np.maximum(edc, EPS) / (edc[0] + EPS))
    noise_tail_start = int(len(y) * 0.9)
    noise_floor_rms = rms(y[noise_tail_start:])
    peak_rms = float(env[pk_frame])
    noise_rel_db = 20.0 * np.log10(max(noise_floor_rms, EPS) / max(peak_rms, EPS))

    cutoff = len(edc_db) - max(1, int(0.015 * sr))
    if noise_rel_db > -45.0:
        bad = np.where(edc_db <= noise_rel_db + 8.0)[0]
        if len(bad) > 0:
            cutoff = min(cutoff, int(bad[0]))
    cutoff = max(16, cutoff)
    edc_fit = edc_db[:cutoff]

    # ISO 3382 fit range: [-5 dB, -(5 + drop_db) dB]
    drop_guard = achieved_drop_db < (abs(drop_db) - 2.0)
    hi_bound = -5.0
    lo_bound = -(5.0 + abs(drop_db)) if not drop_guard else max(float(np.min(edc_fit)) + 3.0, -(5.0 + abs(drop_db)))
    lo_bound = min(hi_bound - 3.0, lo_bound)

    idx_mask = (edc_fit <= hi_bound) & (edc_fit >= lo_bound)
    fit_idx = np.where(idx_mask)[0]
    if len(fit_idx) < 8:
        fit_idx = np.arange(0, max(8, len(edc_fit) // 2))
        drop_guard = True

    t_sec = fit_idx / float(sr)
    y_db = edc_fit[fit_idx]
    slope, intercept = np.polyfit(t_sec, y_db, 1)
    y_pred = slope * t_sec + intercept
    ss_res = float(np.sum((y_db - y_pred) ** 2))
    ss_tot = float(np.sum((y_db - np.mean(y_db)) ** 2)) + EPS
    r2 = float(max(0.0, 1.0 - ss_res / ss_tot))

    if slope >= -1e-6:
        return {"decay_ms": float(len(y) / sr * 1000.0), "r2": r2, "achieved_drop_db": achieved_drop_db, "drop_guard_triggered": True}

    decay_ms = float((abs(drop_db) / (-slope)) * 1000.0)
    return {
        "decay_ms": decay_ms,
        "r2": r2,
        "achieved_drop_db": achieved_drop_db,
        "drop_guard_triggered": bool(drop_guard),
    }


def direct_to_reverberant_ratio_db(
    x: np.ndarray,
    sr: int,
    *,
    direct_ms: float = 35.0,
    tail_end_ms: float = 450.0,
) -> float:
    """Ratio (dB) of direct hit energy (`[-2ms, +direct_ms]`) to reverberant tail (`[+direct_ms, +tail_end_ms]`)."""
    if len(x) < 32:
        return 0.0
    head = np.abs(x[: min(len(x), int(0.08 * sr))])
    pk = float(np.max(head))
    if pk <= EPS:
        return 0.0
    above = np.where(head >= 0.25 * pk)[0]
    i_onset = int(above[0]) if len(above) > 0 else int(np.argmax(head))
    pre = int(0.002 * sr)
    d_start = max(0, i_onset - pre)
    d_end = min(len(x), i_onset + int(direct_ms * sr / 1000.0))
    r_end = min(len(x), i_onset + int(tail_end_ms * sr / 1000.0))
    e_direct = float(np.sum(np.square(x[d_start:d_end], dtype=np.float64)))
    e_reverb = float(np.sum(np.square(x[d_end:r_end], dtype=np.float64)))
    return float(10.0 * np.log10((e_direct + EPS) / (e_reverb + EPS)))


def _log_parabolic_refine(log_mag: np.ndarray, peak_idx: int, sr: int, n_fft: int) -> float:
    bin_hz = float(sr) / float(n_fft)
    if 0 < peak_idx < len(log_mag) - 1:
        y0, y1, y2 = float(log_mag[peak_idx - 1]), float(log_mag[peak_idx]), float(log_mag[peak_idx + 1])
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > EPS:
            delta = float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5))
            return float((peak_idx + delta) * bin_hz)
    return float(peak_idx * bin_hz)


def estimate_fundamental_hz(
    x: np.ndarray,
    sr: int,
    f_min: float,
    f_max: float,
    *,
    min_prominence_db: float = 9.5,
) -> dict[str, Any]:
    """Log-magnitude parabolic pitch estimate with spectral prominence & sub-100 Hz centroid guard."""
    if len(x) < 64:
        return {"hz": 0.0, "prominence_db": 0.0, "prominent": False, "centroid_hz": 0.0}

    win = asymmetric_tukey_window(len(x), sr, attack_taper_ms=0.5, release_taper_ms=25.0)
    n_fft = max(32768, 1 << int(np.ceil(np.log2(len(x) * 4))))
    mag = np.abs(np.fft.rfft(x.astype(np.float64) * win, n=n_fft))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    mask = (freqs >= f_min) & (freqs <= f_max)
    idxs = np.where(mask)[0]
    if len(idxs) < 3:
        return {"hz": 0.0, "prominence_db": 0.0, "prominent": False, "centroid_hz": 0.0}

    band_mag = mag[idxs]
    band_freqs = freqs[idxs]
    band_pow = band_mag**2
    centroid_hz = float(np.sum(band_freqs * band_pow) / (np.sum(band_pow) + EPS))

    log_mag = np.log(mag + EPS)
    band_db = 20.0 * np.log10(band_mag + EPS)
    floor_db = float(np.median(band_db))

    peaks, _ = signal.find_peaks(band_db, prominence=min(3.0, min_prominence_db * 0.5))
    if len(peaks) > 0:
        best_rel = int(peaks[int(np.argmax(band_db[peaks]))])
    else:
        best_rel = int(np.argmax(band_db))

    peak_idx = int(idxs[best_rel])
    prominence_db = float(band_db[best_rel] - floor_db)
    hz = _log_parabolic_refine(log_mag, peak_idx, sr, n_fft)

    at_boundary = best_rel == 0 or best_rel == len(idxs) - 1
    prominent = bool((prominence_db >= min_prominence_db) and not at_boundary)

    if f_max <= 120.0 and (at_boundary or prominence_db < 4.0):
        hz = centroid_hz
        prominent = False

    return {
        "hz": float(hz),
        "prominence_db": prominence_db,
        "prominent": prominent,
        "centroid_hz": centroid_hz,
    }


def detect_ring_peaks(
    mono_tail: np.ndarray,
    sr: int,
    *,
    f_min: float = 280.0,
    f_max: float = 1600.0,
    median_bw_hz: float = 120.0,
    min_prominence_db: float = 6.0,
    max_peaks: int = 3,
) -> dict[str, Any]:
    """Sliding-median ring detector over `f_min..f_max` returning prominence & exact peak frequencies."""
    if len(mono_tail) < 64:
        return {"ring_prominence_db": 0.0, "ring_peaks_hz": [], "ring_peaks": []}

    win = asymmetric_tukey_window(len(mono_tail), sr, attack_taper_ms=1.0, release_taper_ms=25.0)
    n_fft = max(16384, 1 << int(np.ceil(np.log2(len(mono_tail) * 2))))
    mag = np.abs(np.fft.rfft(mono_tail.astype(np.float64) * win, n=n_fft))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    log_mag = np.log(mag + EPS)
    bin_hz = float(sr) / float(n_fft)

    pad_lo = max(20.0, f_min - median_bw_hz)
    pad_hi = min(sr * 0.49, f_max + median_bw_hz)
    pad_mask = (freqs >= pad_lo) & (freqs <= pad_hi)
    pad_idxs = np.where(pad_mask)[0]
    if len(pad_idxs) < 8:
        return {"ring_prominence_db": 0.0, "ring_peaks_hz": [], "ring_peaks": []}

    pad_db = 20.0 * np.log10(mag[pad_idxs] + EPS)
    k_bins = max(5, int(round(median_bw_hz / bin_hz)) | 1)
    floor_db = ndimage.median_filter(pad_db, size=k_bins, mode="nearest")

    band_sub_mask = (freqs[pad_idxs] >= f_min) & (freqs[pad_idxs] <= f_max)
    band_sub_idxs = np.where(band_sub_mask)[0]
    if len(band_sub_idxs) < 3:
        return {"ring_prominence_db": 0.0, "ring_peaks_hz": [], "ring_peaks": []}

    excess = pad_db[band_sub_idxs] - floor_db[band_sub_idxs]
    ring_prom = float(np.max(excess))

    min_dist = max(1, int(round(25.0 / bin_hz)))
    peaks, _ = signal.find_peaks(excess, height=min_prominence_db, prominence=min_prominence_db * 0.75, distance=min_dist)

    found: list[dict[str, float]] = []
    for rel_i in peaks:
        global_idx = int(pad_idxs[band_sub_idxs[rel_i]])
        hz = _log_parabolic_refine(log_mag, global_idx, sr, n_fft)
        found.append({"hz": round(hz, 1), "prominence_db": round(float(excess[rel_i]), 2)})

    found.sort(key=lambda item: item["prominence_db"], reverse=True)
    found = found[:max_peaks]
    return {
        "ring_prominence_db": ring_prom,
        "ring_peaks_hz": [p["hz"] for p in found],
        "ring_peaks": found,
    }


def active_crest_factor_db(x: np.ndarray, *, energy_fraction: float = 0.95) -> float:
    """Crest factor evaluated strictly across active onset..T95 energy span (invariant to silence padding)."""
    if len(x) < 8:
        return 0.0
    e = np.square(x, dtype=np.float64)
    total_e = float(np.sum(e))
    if total_e <= EPS:
        return 0.0
    cum_e = np.cumsum(e) / total_e
    i_start = int(np.searchsorted(cum_e, 0.002, side="left"))
    i_end = int(np.searchsorted(cum_e, energy_fraction, side="left")) + 1
    i_end = max(i_start + 4, min(len(x), i_end))
    active_seg = x[i_start:i_end]
    pk = float(np.max(np.abs(active_seg)))
    r = rms(active_seg)
    return to_db(pk / (r + EPS))


def _bs1770_k_weight_coeffs(sr: int) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """Exact bilinear ITU-R BS.1770-4 Stage 1 shelf + Stage 2 RLB high-pass for sample rate `sr`."""
    # Stage 1: pre-filter +4 dB high-shelf
    db = 3.999843853973347
    f0_1 = 1681.974450955533
    q_1 = 0.7071752369554196
    k1 = math.tan(math.pi * f0_1 / sr)
    vh = 10.0 ** (db / 20.0)
    vb = vh**0.4996667741545416
    a0_1 = 1.0 + k1 / q_1 + k1 * k1
    b_1 = np.array([(vh + vb * k1 / q_1 + k1 * k1) / a0_1, 2.0 * (k1 * k1 - vh) / a0_1, (vh - vb * k1 / q_1 + k1 * k1) / a0_1])
    a_1 = np.array([1.0, 2.0 * (k1 * k1 - 1.0) / a0_1, (1.0 - k1 / q_1 + k1 * k1) / a0_1])

    # Stage 2: RLB high-pass filter
    f0_2 = 38.13547087602444
    q_2 = 0.5003270373238773
    k2 = math.tan(math.pi * f0_2 / sr)
    a0_2 = 1.0 + k2 / q_2 + k2 * k2
    b_2 = np.array([1.0 / a0_2, -2.0 / a0_2, 1.0 / a0_2])
    a_2 = np.array([1.0, 2.0 * (k2 * k2 - 1.0) / a0_2, (1.0 - k2 / q_2 + k2 * k2) / a0_2])
    return (b_1, a_1), (b_2, a_2)


def measure_lufs_and_lra(stereo_audio: np.ndarray, sr: int) -> dict[str, float]:
    """Measure ITU-R BS.1770-4 integrated LUFS and EBU R128 LRA on stereo/mono audio."""
    if len(stereo_audio) < int(0.45 * sr):
        return {"integrated_lufs": -70.0, "lra_lu": 0.0}

    arr = stereo_audio if stereo_audio.ndim == 2 else stereo_audio[:, None]
    n_ch = min(2, arr.shape[1])
    (b1, a1), (b2, a2) = _bs1770_k_weight_coeffs(sr)
    filtered = np.zeros((arr.shape[0], n_ch), dtype=np.float64)
    for ch in range(n_ch):
        y = signal.lfilter(b1, a1, arr[:, ch].astype(np.float64))
        filtered[:, ch] = signal.lfilter(b2, a2, y)

    # Momentary 400 ms blocks @ 100 ms hop
    win_400 = max(1, int(round(0.400 * sr)))
    hop_100 = max(1, int(round(0.100 * sr)))
    sq = np.sum(np.square(filtered), axis=1)  # equal L/R channel weight = 1.0

    # Cumulative sum for O(N) sliding block mean power
    csum = np.concatenate([[0.0], np.cumsum(sq)])
    starts = np.arange(0, len(sq) - win_400 + 1, hop_100)
    if len(starts) == 0:
        return {"integrated_lufs": -70.0, "lra_lu": 0.0}
    block_powers = (csum[starts + win_400] - csum[starts]) / float(win_400)
    block_lufs = -0.691 + 10.0 * np.log10(np.maximum(block_powers, EPS))

    abs_mask = block_lufs > -70.0
    if not np.any(abs_mask):
        return {"integrated_lufs": -70.0, "lra_lu": 0.0}
    z_abs = float(np.mean(block_powers[abs_mask]))
    gamma_r = -0.691 + 10.0 * math.log10(max(z_abs, EPS)) - 10.0

    rel_mask = block_lufs > gamma_r
    if not np.any(rel_mask):
        integrated = -0.691 + 10.0 * math.log10(max(z_abs, EPS))
    else:
        z_rel = float(np.mean(block_powers[rel_mask]))
        integrated = -0.691 + 10.0 * math.log10(max(z_rel, EPS))

    # Short-term 3.0 s blocks (fallback >= 0.8s on very short clips) for EBU R128 LRA
    win_3s = min(len(sq), max(win_400, int(round(3.0 * sr))))
    starts_3s = np.arange(0, len(sq) - win_3s + 1, hop_100)
    if len(starts_3s) < 2:
        lra_lu = 0.0
    else:
        st_powers = (csum[starts_3s + win_3s] - csum[starts_3s]) / float(win_3s)
        st_lufs = -0.691 + 10.0 * np.log10(np.maximum(st_powers, EPS))
        st_abs = st_lufs[st_lufs > -70.0]
        if len(st_abs) < 2:
            lra_lu = 0.0
        else:
            st_mean_pow = float(np.mean(st_powers[st_lufs > -70.0]))
            lra_rel_thresh = -0.691 + 10.0 * math.log10(max(st_mean_pow, EPS)) - 20.0
            gated_st = st_lufs[st_lufs >= lra_rel_thresh]
            if len(gated_st) < 2:
                lra_lu = 0.0
            else:
                lra_lu = float(np.percentile(gated_st, 95) - np.percentile(gated_st, 10))

    return {"integrated_lufs": float(integrated), "lra_lu": float(lra_lu)}


def detect_onset_offset_xcorr(
    audio: np.ndarray,
    sr: int,
    *,
    hit_times_s: list[float] | None = None,
    max_search_s: float = 3.0,
) -> int:
    """Align rendered audio to MIDI grid using rectified-envelope cross-correlation + leading-edge snap."""
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    max_lag_samples = min(len(mono), int(max_search_s * sr))
    if max_lag_samples < 32:
        return 0

    if hit_times_s:
        subset_hits = [float(t) for t in hit_times_s if 0.0 <= float(t) <= 30.0][:16]
    else:
        subset_hits = []

    if not subset_hits:
        seg = np.abs(mono[:max_lag_samples])
        pk = float(np.max(seg)) if len(seg) else 0.0
        if pk < 1e-4:
            return 0
        above = np.where(seg >= max(0.03, 0.12 * pk))[0]
        if len(above) == 0:
            return 0
        return max(0, int(above[0]) - int(0.002 * sr))

    # Downsample rectified energy into 1 ms frames
    hop = max(1, int(round(0.001 * sr)))
    tpl_span_s = min(len(mono) / sr - max_search_s - 0.05, subset_hits[-1] + 0.15)
    tpl_hits = [t for t in subset_hits if t < tpl_span_s]
    if not tpl_hits:
        tpl_hits = [subset_hits[0]]

    tpl_frames = max(32, int(round((tpl_hits[-1] + 0.15) * sr / hop)))
    max_lag_frames = int(round(max_search_s * sr / hop))
    total_frames = min(len(mono) // hop, tpl_frames + max_lag_frames)
    if total_frames <= tpl_frames:
        return 0

    trimmed = mono[: total_frames * hop].reshape(total_frames, hop)
    env = np.sqrt(np.mean(trimmed**2, axis=1))
    # Subtract noise floor so steady pre-roll noise does not skew correlation
    noise_est = float(np.percentile(env, 25))
    env_clean = np.maximum(0.0, env - 2.0 * noise_est)

    tpl = np.zeros(tpl_frames, dtype=np.float64)
    decay_frames = max(5, int(round(0.060 / (hop / sr))))
    kern = np.exp(-np.arange(decay_frames) / (decay_frames / 3.0))
    for ht in tpl_hits:
        idx = int(round(ht * sr / hop))
        end_k = min(tpl_frames, idx + len(kern))
        if idx < tpl_frames:
            tpl[idx:end_k] += kern[: end_k - idx]

    corr = signal.correlate(env_clean, tpl, mode="valid")
    if len(corr) == 0 or float(np.max(corr)) <= EPS:
        return 0
    best_frame = int(np.argmax(corr))
    coarse_sample = best_frame * hop

    # Snap precisely to leading edge around the first MIDI hit within +-25 ms
    first_center = coarse_sample + int(round(tpl_hits[0] * sr))
    pad = int(0.025 * sr)
    w0 = max(0, first_center - pad)
    w1 = min(len(mono), first_center + pad)
    seg = np.abs(mono[w0:w1])
    pk = float(np.max(seg)) if len(seg) else 0.0
    if pk > 1e-4:
        above = np.where(seg >= max(0.03, 0.25 * pk))[0]
        if len(above) > 0:
            edge_sample = w0 + int(above[0])
            return max(0, edge_sample - int(0.002 * sr) - int(round(tpl_hits[0] * sr)))
    return max(0, coarse_sample)
