"""Lightweight advisory profiler for reference drum stems (`numpy`/`scipy` only, zero PyTorch)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy import signal

from sd3_forge.dsp_metrics import (
    EPS,
    active_crest_factor_db,
    band_energy_ratio_db,
    detect_ring_peaks,
    direct_to_reverberant_ratio_db,
    estimate_fundamental_hz,
    measure_lufs_and_lra,
    rms,
    schroeder_decay_ms,
    to_db,
)


def _true_peak_dbfs(audio: np.ndarray) -> float:
    peaks = []
    for ch in range(audio.shape[1]):
        up = signal.resample_poly(audio[:, ch], up=4, down=1)
        peaks.append(float(np.max(np.abs(up))))
    return to_db(max(peaks) if peaks else 0.0)


def _stereo_correlation(audio: np.ndarray) -> float:
    if audio.ndim < 2 or audio.shape[1] < 2 or len(audio) < 16:
        return 1.0
    l_std = float(np.std(audio[:, 0]))
    r_std = float(np.std(audio[:, 1]))
    if l_std < EPS or r_std < EPS:
        return 1.0 if (l_std < EPS and r_std < EPS) else 0.0
    return float(np.corrcoef(audio[:, 0], audio[:, 1])[0, 1])


def _detect_onsets(mono: np.ndarray, sr: int, *, min_spacing_s: float = 0.12) -> list[int]:
    hop = max(1, int(round(0.002 * sr)))
    win = max(hop * 2, int(round(0.006 * sr)))
    if len(mono) < win + hop:
        return []
    env = np.array([rms(mono[i : i + win]) for i in range(0, len(mono) - win + 1, hop)], dtype=np.float64)
    flux = np.maximum(0.0, np.diff(env, prepend=0.0))
    max_flux = float(np.max(flux))
    if max_flux < 1e-4:
        return []
    dist = max(1, int(round(min_spacing_s / (hop / sr))))
    peaks, _ = signal.find_peaks(flux, height=max(0.015, 0.18 * max_flux), distance=dist)
    pre = int(round(0.002 * sr))
    return [max(0, int(p * hop) - pre) for p in peaks]


def profile_reference_wav(wav_path: Path) -> dict[str, Any]:
    """Extract lightweight acoustic priors from a reference WAV (purely advisory)."""
    if not wav_path.exists():
        raise FileNotFoundError(f"Reference WAV not found: {wav_path}")

    audio, sr_raw = sf.read(str(wav_path), always_2d=True, dtype="float64")
    sr = int(sr_raw)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    mono = np.mean(audio, axis=1)
    lufs = measure_lufs_and_lra(audio, sr)
    corr = _stereo_correlation(audio)
    lr_bal = to_db(rms(audio[:, 0]) + EPS) - to_db(rms(audio[:, 1]) + EPS)
    pk_db = to_db(float(np.max(np.abs(mono))) if len(mono) else 0.0)
    crest_db = float(pk_db - to_db(rms(mono)))

    band_defs = [
        ("sub_20_60_db", 20.0, 60.0, 38.0),
        ("low_60_150_db", 60.0, 150.0, 95.0),
        ("low_mid_150_500_db", 150.0, 500.0, 275.0),
        ("mid_500_2000_db", 500.0, 2000.0, 1000.0),
        ("high_mid_2000_6000_db", 2000.0, 6000.0, 3500.0),
        ("air_6000_16000_db", 6000.0, 16000.0, 9800.0),
    ]
    spectral_balance: dict[str, float] = {}
    band_vals: list[float] = []
    log2_fc: list[float] = []
    for name, f_lo, f_hi, fc in band_defs:
        val = round(band_energy_ratio_db(mono, sr, f_lo, f_hi), 3)
        spectral_balance[name] = val
        band_vals.append(val)
        log2_fc.append(math.log2(fc))
    tilt, _ = np.polyfit(np.array(log2_fc), np.array(band_vals), 1)
    spectral_balance["spectral_tilt_db_per_oct"] = round(float(tilt), 3)

    onsets = _detect_onsets(mono, sr)
    k_funds, k_decays = [], []
    s_funds, s_decays, s_drrs, s_rings = [], [], [], []
    slice_n = int(0.300 * sr)

    for idx in onsets:
        seg = mono[idx : min(len(mono), idx + slice_n)]
        if len(seg) < int(0.080 * sr):
            continue
        e_low = band_energy_ratio_db(seg, sr, 35.0, 115.0)
        e_mid = band_energy_ratio_db(seg, sr, 140.0, 350.0)
        e_crack = band_energy_ratio_db(seg, sr, 1800.0, 8000.0)

        if e_low > e_mid + 2.0:
            k_body = seg[int(0.020 * sr) : min(len(seg), int(0.220 * sr))]
            f_est = estimate_fundamental_hz(k_body if len(k_body) >= 64 else seg, sr, 35.0, 100.0, min_prominence_db=6.0)
            if f_est["prominent"]:
                k_funds.append(f_est["hz"])
            k_decays.append(schroeder_decay_ms(seg, sr, 20.0)["decay_ms"])
        elif e_mid >= e_low or e_crack > -20.0:
            s_body = seg[int(0.005 * sr) : min(len(seg), int(0.120 * sr))]
            f_est = estimate_fundamental_hz(s_body if len(s_body) >= 64 else seg, sr, 120.0, 320.0, min_prominence_db=6.0)
            if f_est["prominent"]:
                s_funds.append(f_est["hz"])
            s_tail = seg[int(0.025 * sr) : min(len(seg), int(0.240 * sr))]
            if len(s_tail) >= 64:
                ring = detect_ring_peaks(s_tail, sr, f_min=280.0, f_max=1600.0, min_prominence_db=6.0)
                s_rings.extend(ring["ring_peaks_hz"])
            s_decays.append(schroeder_decay_ms(seg, sr, 30.0)["decay_ms"])
            s_drrs.append(direct_to_reverberant_ratio_db(seg, sr, direct_ms=30.0, tail_end_ms=280.0))

    k_cnt = len(k_funds)
    s_cnt = len(s_funds)
    confidence = "high" if (k_cnt >= 3 and s_cnt >= 3) else ("medium" if (k_cnt >= 1 or s_cnt >= 1) else "low")

    kick_f0 = round(float(np.median(k_funds)), 1) if k_funds else 58.0
    kick_t20 = round(float(np.median(k_decays)), 1) if k_decays else 175.0
    snare_f0 = round(float(np.median(s_funds)), 1) if s_funds else 215.0
    snare_t30 = round(float(np.median(s_decays)), 1) if s_decays else 340.0
    snare_drr = round(float(np.median(s_drrs)), 2) if s_drrs else 6.0

    # Cluster top ring peaks cleanly
    ring_clusters: list[float] = []
    for hz in s_rings:
        if not any(abs(hz - r) <= 15.0 for r in ring_clusters):
            ring_clusters.append(round(hz, 1))
        if len(ring_clusters) >= 3:
            break

    return {
        "schema_version": "2.0",
        "advisory_only": True,
        "file_name": wav_path.name,
        "sample_rate": sr,
        "duration_s": round(float(len(audio) / sr), 3),
        "loudness": {
            "integrated_lufs": round(lufs["integrated_lufs"], 2),
            "lra_lu": round(lufs["lra_lu"], 2),
            "true_peak_dbfs": round(_true_peak_dbfs(audio), 2),
            "crest_factor_db": round(crest_db, 2),
            "active_crest_factor_db": round(active_crest_factor_db(mono), 2),
            "stereo_correlation": round(corr, 3),
            "stereo_width": round(1.0 - corr, 3),
            "lr_balance_db": round(lr_bal, 2),
        },
        "spectral_balance": spectral_balance,
        "transient_priors": {
            "kick_fundamental_hz": kick_f0,
            "kick_decay_t20_ms": kick_t20,
            "snare_fundamental_hz": snare_f0,
            "snare_decay_t30_ms": snare_t30,
            "snare_drr_db": snare_drr,
            "snare_ring_peaks_hz": ring_clusters,
            "candidate_counts": {"onsets": len(onsets), "kick": k_cnt, "snare": s_cnt},
            "confidence": confidence,
        },
        "suggested_spec_priors": {
            "disclaimer": "Advisory priors extracted from reference stem; verify bleed, cymbals, and mastering compression manually.",
            "kick": {
                "fundamental_hz": {"min": round(max(35.0, kick_f0 - 6.0), 1), "ideal": kick_f0, "max": round(min(100.0, kick_f0 + 6.0), 1), "unit": "Hz"},
            },
            "snare_center": {
                "fundamental_hz": {"min": round(max(120.0, snare_f0 - 15.0), 1), "ideal": snare_f0, "max": round(min(320.0, snare_f0 + 15.0), 1), "unit": "Hz"},
                "drr_db": {"min": round(snare_drr - 4.0, 1), "ideal": snare_drr, "max": round(snare_drr + 4.0, 1), "unit": "dB"},
            },
            "groove": {
                "integrated_lufs": {"min": round(lufs["integrated_lufs"] - 4.0, 1), "ideal": round(lufs["integrated_lufs"], 1), "max": round(lufs["integrated_lufs"] + 3.0, 1), "unit": "LUFS"},
            },
        },
    }
