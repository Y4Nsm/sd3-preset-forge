"""Deterministic DSP Bounce Analyzer v2 for SD3 Preset Forge (Anti-Goodhart Evaluator)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import yaml
from scipy import signal

from sd3_forge.dsp_metrics import (
    EPS,
    active_crest_factor_db,
    attack_body_tail_metrics,
    band_energy_ratio_db,
    detect_onset_offset_xcorr,
    detect_ring_peaks,
    direct_to_reverberant_ratio_db,
    estimate_fundamental_hz,
    measure_lufs_and_lra,
    rms,
    schroeder_decay_ms,
    to_db,
)
from sd3_forge.paths import default_manifest_path

_TOM_WINDOW_TO_SLOT = [
    ("racktom1", "racktom1_isolated", "Tom1", 95.0, 240.0),
    ("racktom2", "racktom2_isolated", "Tom2", 75.0, 200.0),
    ("racktom3", "racktom3_isolated", "Tom3", 65.0, 175.0),
    ("floortom1", "floortom1_isolated", "Tom4", 55.0, 160.0),
    ("floortom2", "floortom2_isolated", "Tom5", 40.0, 130.0),
]


def _crest_factor_db(x: np.ndarray) -> float:
    pk = float(np.max(np.abs(x))) if len(x) else 0.0
    return to_db(pk / (rms(x) + EPS))


def _stereo_correlation(stereo_seg: np.ndarray) -> float:
    if stereo_seg.ndim < 2 or stereo_seg.shape[1] < 2 or len(stereo_seg) < 16:
        return 1.0
    l_ch = stereo_seg[:, 0]
    r_ch = stereo_seg[:, 1]
    l_std = float(np.std(l_ch))
    r_std = float(np.std(r_ch))
    if l_std < EPS or r_std < EPS:
        return 1.0 if (l_std < EPS and r_std < EPS) else 0.0
    return float(np.corrcoef(l_ch, r_ch)[0, 1])


def _true_peak_dbfs(audio: np.ndarray) -> float:
    peaks = []
    for ch in range(audio.shape[1]):
        up = signal.resample_poly(audio[:, ch], up=4, down=1)
        peaks.append(float(np.max(np.abs(up))))
    return to_db(max(peaks) if peaks else 0.0)


def detect_onset_offset_samples(audio: np.ndarray, sr: int, max_search_s: float = 3.0) -> int:
    """Compatibility wrapper around onset offset detection."""
    return detect_onset_offset_xcorr(audio, sr, hit_times_s=None, max_search_s=max_search_s)


def _slice_hit(audio: np.ndarray, sr: int, offset: int, t_s: float, start_ms: float, end_ms: float) -> np.ndarray:
    s_idx = offset + int((t_s + start_ms / 1000.0) * sr)
    e_idx = offset + int((t_s + end_ms / 1000.0) * sr)
    s_idx = max(0, min(len(audio), s_idx))
    e_idx = max(s_idx, min(len(audio), e_idx))
    return audio[s_idx:e_idx]


def _load_stereo_audio(wav_path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(wav_path), always_2d=True, dtype="float64")
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]
    return audio, int(sr)


def _merge_ring_peaks(per_hit_peaks: list[list[dict[str, float]]], max_peaks: int = 3) -> list[float]:
    clusters: list[dict[str, float]] = []
    for hit_list in per_hit_peaks:
        for pk in hit_list:
            hz = pk["hz"]
            prom = pk["prominence_db"]
            matched = next((c for c in clusters if abs(c["hz"] - hz) <= 12.0), None)
            if matched:
                w_old = matched["weight"]
                w_new = prom
                matched["hz"] = (matched["hz"] * w_old + hz * w_new) / (w_old + w_new)
                matched["weight"] = w_old + w_new
                matched["max_prom"] = max(matched["max_prom"], prom)
            else:
                clusters.append({"hz": hz, "weight": prom, "max_prom": prom})
    clusters.sort(key=lambda c: c["weight"], reverse=True)
    return [round(c["hz"], 1) for c in clusters[:max_peaks]]


def _measure_double_kick_clarity(audio: np.ndarray, sr: int, offset: int, hit_times: list[float]) -> float:
    if len(hit_times) < 2:
        return 0.0
    pks_db: list[float] = []
    vals_db: list[float] = []
    for i in range(len(hit_times) - 1):
        t0, t1 = hit_times[i], hit_times[i + 1]
        hit_seg = np.mean(_slice_hit(audio, sr, offset, t0, 0.0, 25.0), axis=1)
        mid_ms = (t1 - t0) * 1000.0 * 0.65
        val_seg = np.mean(_slice_hit(audio, sr, offset, t0, max(20.0, mid_ms - 10.0), max(30.0, mid_ms + 5.0)), axis=1)
        if len(hit_seg) > 8 and len(val_seg) > 8:
            pks_db.append(to_db(rms(hit_seg)))
            vals_db.append(to_db(rms(val_seg)))
    if not pks_db:
        return 0.0
    return float(np.median(np.array(pks_db) - np.array(vals_db)))


def _measure_audio_array(
    audio: np.ndarray,
    sr: int,
    wav_label: str,
    manifest: dict[str, Any],
    align: bool = True,
    unload_slots: set[str] | None = None,
) -> dict[str, Any]:
    windows = manifest.get("windows", {})
    scope = manifest.get("scope", "full")
    unloaded = set(unload_slots or ())

    cal_hits: list[float] = []
    for key in ("kick_isolated", "kick_velocity_ladder", "snare_center_isolated", "racktom1_isolated", "hihat_isolated"):
        if key in windows and windows[key].get("hit_times_s"):
            cal_hits.extend(float(t) for t in windows[key]["hit_times_s"])
            break
    offset = detect_onset_offset_xcorr(audio, sr, hit_times_s=cal_hits or None) if align else 0

    tp_db = _true_peak_dbfs(audio)
    clip_samples = int(np.sum(np.abs(audio) >= 0.999))
    l_rms = rms(audio[:, 0])
    r_rms = rms(audio[:, 1])
    lr_balance_db = to_db(l_rms + EPS) - to_db(r_rms + EPS)

    # --- Kick analysis ---
    kick_metrics: dict[str, Any] = {}
    k_corr: list[float] = []
    k_peaks: list[float] = []
    if "kick_isolated" in windows:
        k_funds, k_sub, k_punch, k_box, k_click, k_cf, k_acf, k_dec, k_r2, k_drr, k_a2b = ([] for _ in range(11))
        for t in windows["kick_isolated"]["hit_times_s"]:
            seg = _slice_hit(audio, sr, offset, t, 0.0, 500.0)
            mono = np.mean(seg, axis=1)
            attack_mono = np.mean(_slice_hit(audio, sr, offset, t, 0.0, 150.0), axis=1)
            kick_body = np.mean(_slice_hit(audio, sr, offset, t, 20.0, 220.0), axis=1)
            f_est = estimate_fundamental_hz(kick_body, sr, 35.0, 100.0)
            k_funds.append(f_est["hz"])
            k_sub.append(band_energy_ratio_db(mono, sr, 30.0, 70.0))
            k_punch.append(band_energy_ratio_db(mono, sr, 70.0, 130.0))
            k_box.append(band_energy_ratio_db(mono, sr, 250.0, 550.0))
            k_click.append(band_energy_ratio_db(attack_mono, sr, 3000.0, 6000.0))
            k_cf.append(_crest_factor_db(mono))
            k_acf.append(active_crest_factor_db(mono))
            edc = schroeder_decay_ms(mono, sr, 20.0)
            k_dec.append(edc["decay_ms"])
            k_r2.append(edc["r2"])
            k_drr.append(direct_to_reverberant_ratio_db(mono, sr, direct_ms=35.0, tail_end_ms=450.0))
            abt = attack_body_tail_metrics(mono, sr)
            k_a2b.append(abt["attack_to_body_db"])
            k_corr.append(_stereo_correlation(seg))
            k_peaks.append(float(np.max(np.abs(mono))) if len(mono) else 0.0)

        kick_metrics = {
            "fundamental_hz": float(np.median(k_funds)),
            "sub_30_70_db": float(np.mean(k_sub)),
            "punch_70_130_db": float(np.mean(k_punch)),
            "boxiness_250_550_db": float(np.mean(k_box)),
            "click_3000_6000_db": float(np.mean(k_click)),
            "crest_factor_db": float(np.mean(k_cf)),
            "active_crest_factor_db": float(np.mean(k_acf)),
            "decay_t20_ms": float(np.mean(k_dec)),
            "decay_t20_r2": float(np.mean(k_r2)),
            "drr_db": float(np.mean(k_drr)),
            "attack_to_body_db": float(np.mean(k_a2b)),
        }
        if "kick_velocity_ladder" in windows:
            v_rms = [
                to_db(rms(np.mean(_slice_hit(audio, sr, offset, vt, 0.0, 250.0), axis=1)))
                for vt in windows["kick_velocity_ladder"]["hit_times_s"]
            ]
            if len(v_rms) >= 2:
                kick_metrics["velocity_dynamic_range_db"] = float(max(v_rms) - min(v_rms))
        if "double_kick_burst" in windows:
            kick_metrics["double_kick_clarity_db"] = _measure_double_kick_clarity(
                audio, sr, offset, windows["double_kick_burst"]["hit_times_s"]
            )

    # --- Snare analysis ---
    def analyze_snare_group(times: list[float]) -> dict[str, Any]:
        funds, ring_proms, per_hit_rings, cracks, wires, cfs, acfs, decs, r2s, drrs, corrs, peaks = (
            [] for _ in range(12)
        )
        for t in times:
            seg = _slice_hit(audio, sr, offset, t, 0.0, 550.0)
            mono = np.mean(seg, axis=1)
            body = np.mean(_slice_hit(audio, sr, offset, t, 5.0, 120.0), axis=1)
            tail = np.mean(_slice_hit(audio, sr, offset, t, 25.0, 250.0), axis=1)
            atk = np.mean(_slice_hit(audio, sr, offset, t, 0.0, 80.0), axis=1)
            f_est = estimate_fundamental_hz(body, sr, 120.0, 320.0)
            funds.append(f_est["hz"])
            ring_res = detect_ring_peaks(tail, sr, f_min=280.0, f_max=1600.0, median_bw_hz=120.0, min_prominence_db=6.0)
            ring_proms.append(ring_res["ring_prominence_db"])
            per_hit_rings.append(ring_res["ring_peaks"])
            cracks.append(band_energy_ratio_db(atk, sr, 2000.0, 5000.0))
            wires.append(band_energy_ratio_db(mono, sr, 7000.0, 14000.0))
            cfs.append(_crest_factor_db(mono))
            acfs.append(active_crest_factor_db(mono))
            edc = schroeder_decay_ms(mono, sr, 30.0)
            decs.append(edc["decay_ms"])
            r2s.append(edc["r2"])
            drrs.append(direct_to_reverberant_ratio_db(mono, sr, direct_ms=30.0, tail_end_ms=450.0))
            corrs.append(_stereo_correlation(seg))
            peaks.append(float(np.max(np.abs(mono))) if len(mono) else 0.0)

        return {
            "fundamental_hz": float(np.median(funds)),
            "ring_prominence_db": float(np.mean(ring_proms)),
            "ring_peaks_hz": _merge_ring_peaks(per_hit_rings),
            "crack_2000_5000_db": float(np.mean(cracks)),
            "wire_sizzle_7000_14000_db": float(np.mean(wires)),
            "crest_factor_db": float(np.mean(cfs)),
            "active_crest_factor_db": float(np.mean(acfs)),
            "decay_t30_ms": float(np.mean(decs)),
            "decay_t30_r2": float(np.mean(r2s)),
            "drr_db": float(np.mean(drrs)),
            "_corr": float(np.mean(corrs)),
            "_peak_db": to_db(float(np.mean(peaks))),
        }

    snare_c_raw: dict[str, Any] = (
        analyze_snare_group(windows["snare_center_isolated"]["hit_times_s"])
        if "snare_center_isolated" in windows
        else {}
    )
    snare_r_raw: dict[str, Any] = (
        analyze_snare_group(windows["snare_rimshot_isolated"]["hit_times_s"])
        if "snare_rimshot_isolated" in windows
        else {}
    )

    if snare_c_raw and "snare_velocity_ladder" in windows:
        v_rms = [
            to_db(rms(np.mean(_slice_hit(audio, sr, offset, vt, 0.0, 250.0), axis=1)))
            for vt in windows["snare_velocity_ladder"]["hit_times_s"]
        ]
        if len(v_rms) >= 2:
            snare_c_raw["velocity_dynamic_range_db"] = float(max(v_rms) - min(v_rms))
            snare_c_raw["ghost_to_backbeat_db"] = float(v_rms[-1] - v_rms[0])

    # --- Dynamic Unloaded-Tom Handling & Pan Azimuth Check ---
    ref_peak_lin = float(np.mean(k_peaks)) if k_peaks else float(np.max(np.abs(audio)))
    ref_peak_db = to_db(ref_peak_lin)
    tom_metrics: dict[str, Any] = {}
    loaded_toms: list[str] = []
    unloaded_toms: list[str] = []
    loaded_freqs: list[float] = []
    loaded_pans: list[float] = []
    saw_tom_window = False

    for t_key, win_name, slot_id, f_lo, f_hi in _TOM_WINDOW_TO_SLOT:
        if win_name not in windows:
            continue
        saw_tom_window = True
        if slot_id in unloaded:
            unloaded_toms.append(t_key)
            continue

        hit_hzs: list[float] = []
        hit_pans: list[float] = []
        hit_peaks_db: list[float] = []
        for t in windows[win_name]["hit_times_s"]:
            seg = _slice_hit(audio, sr, offset, t, 0.0, 250.0)
            body = np.mean(seg, axis=1)
            hit_peaks_db.append(to_db(float(np.max(np.abs(body))) if len(body) else 0.0))
            f_est = estimate_fundamental_hz(body, sr, f_lo, f_hi, min_prominence_db=5.0)
            hit_hzs.append(f_est["hz"])
            hit_pans.append(to_db(rms(seg[:, 0])) - to_db(rms(seg[:, 1])))

        avg_pk_db = float(np.mean(hit_peaks_db)) if hit_peaks_db else -120.0
        if avg_pk_db < -50.0 or avg_pk_db < ref_peak_db - 28.0:
            unloaded_toms.append(t_key)
            continue

        hz_val = float(np.median(hit_hzs))
        pan_val = float(np.mean(hit_pans))
        loaded_toms.append(t_key)
        loaded_freqs.append(hz_val)
        loaded_pans.append(pan_val)
        tom_metrics[f"{t_key}_hz"] = hz_val
        tom_metrics[f"{t_key}_pan_lr_db"] = pan_val

    if saw_tom_window:
        pitch_order_valid = len(loaded_freqs) >= 2 and all(a > b for a, b in zip(loaded_freqs, loaded_freqs[1:], strict=False))
        if len(loaded_pans) >= 2:
            dec_pan = all(a >= b - 0.5 for a, b in zip(loaded_pans, loaded_pans[1:], strict=False))
            inc_pan = all(a <= b + 0.5 for a, b in zip(loaded_pans, loaded_pans[1:], strict=False))
            pan_spread = max(loaded_pans) - min(loaded_pans)
            pan_order_valid = bool((dec_pan or inc_pan) and pan_spread >= 2.0)
        else:
            pan_order_valid = True
        tom_metrics["loaded_toms"] = loaded_toms
        tom_metrics["unloaded_toms"] = unloaded_toms
        tom_metrics["pitch_order_valid"] = bool(pitch_order_valid)
        tom_metrics["pan_order_valid"] = pan_order_valid

    # --- Per-Cymbal Evaluation & Choke Gate ---
    cym_metrics: dict[str, Any] = {}
    cym_segs: list[np.ndarray] = []
    if "hihat_isolated" in windows:
        for t in windows["hihat_isolated"].get("closed_times_s", []) + windows["hihat_isolated"].get("open_times_s", []):
            cym_segs.append(_slice_hit(audio, sr, offset, t, 0.0, 500.0))

    per_cym_out: dict[str, dict[str, float]] = {}
    if "cymbals_isolated" in windows:
        cym_win = windows["cymbals_isolated"]
        if isinstance(cym_win.get("per_cymbal"), dict):
            for cname, cinfo in cym_win["per_cymbal"].items():
                segs = [_slice_hit(audio, sr, offset, t, 0.0, 800.0) for t in cinfo.get("hit_times_s", [])]
                if not segs:
                    continue
                cat = np.vstack(segs)
                pk_db = to_db(float(np.max(np.abs(cat))) if len(cat) else 0.0)
                if pk_db < -50.0:
                    continue
                c_mono = np.mean(cat, axis=1)
                e_3_6 = band_energy_ratio_db(c_mono, sr, 3000.0, 6000.0)
                e_8_16 = band_energy_ratio_db(c_mono, sr, 8000.0, 16000.0)
                per_cym_out[cname] = {
                    "harshness_ratio_db": round(float(e_3_6 - e_8_16), 3),
                    "air_8_16k_db": round(float(e_8_16), 3),
                    "stereo_width": round(float(1.0 - _stereo_correlation(cat)), 3),
                    "peak_dbfs": round(pk_db, 2),
                }
                cym_segs.append(cat)
        else:
            for t in cym_win.get("hit_times_s", []):
                cym_segs.append(_slice_hit(audio, sr, offset, t, 0.0, 800.0))

    if cym_segs:
        cym_cat = np.vstack(cym_segs)
        cym_mono = np.mean(cym_cat, axis=1)
        e_3_6k = band_energy_ratio_db(cym_mono, sr, 3000.0, 6000.0)
        e_8_16k = band_energy_ratio_db(cym_mono, sr, 8000.0, 16000.0)
        cym_metrics = {
            "harshness_ratio_db": float(e_3_6k - e_8_16k),
            "cymbals_stereo_width": float(1.0 - _stereo_correlation(cym_cat)),
        }
        if per_cym_out:
            cym_metrics["per_cymbal"] = per_cym_out
            cym_metrics["worst_cymbal_harshness_db"] = max(v["harshness_ratio_db"] for v in per_cym_out.values())
        if "cymbal_choke" in windows:
            ck = windows["cymbal_choke"]
            ht = float(ck["hit_time_s"])
            ct = float(ck["choke_time_s"])
            ring_seg = np.mean(_slice_hit(audio, sr, offset, ht, 0.0, (ct - ht) * 1000.0), axis=1)
            post_seg = np.mean(_slice_hit(audio, sr, offset, ct, 120.0, 600.0), axis=1)
            cym_metrics["choke_attenuation_db"] = float(to_db(rms(ring_seg)) - to_db(rms(post_seg)))

    # --- Groove & LUFS/LRA ---
    groove_metrics: dict[str, Any] = {}
    groove_corr = 1.0
    if "groove_all" in windows:
        g_start = offset + int(windows["groove_all"]["start_s"] * sr)
        g_end = min(len(audio), offset + int(windows["groove_all"]["end_s"] * sr))
        groove_seg = audio[g_start:g_end]
        if len(groove_seg) >= 32:
            groove_mono = np.mean(groove_seg, axis=1)
            groove_corr = _stereo_correlation(groove_seg)
            lufs_info = measure_lufs_and_lra(groove_seg, sr)
            groove_metrics = {
                "sub_20_60_db": band_energy_ratio_db(groove_mono, sr, 20.0, 60.0),
                "low_60_150_db": band_energy_ratio_db(groove_mono, sr, 60.0, 150.0),
                "low_mid_150_500_db": band_energy_ratio_db(groove_mono, sr, 150.0, 500.0),
                "mid_500_2000_db": band_energy_ratio_db(groove_mono, sr, 500.0, 2000.0),
                "high_mid_2000_6000_db": band_energy_ratio_db(groove_mono, sr, 2000.0, 6000.0),
                "air_6000_16000_db": band_energy_ratio_db(groove_mono, sr, 6000.0, 16000.0),
                "groove_crest_factor_db": _crest_factor_db(groove_mono),
                "active_crest_factor_db": active_crest_factor_db(groove_mono),
                "groove_rms_dbfs": to_db(rms(groove_mono)),
                "integrated_lufs": lufs_info["integrated_lufs"],
                "lra_lu": lufs_info["lra_lu"],
            }
            if k_peaks and snare_r_raw:
                kick_peak_db = to_db(float(np.mean(k_peaks)))
                groove_metrics["kick_to_snare_peak_diff_db"] = float(kick_peak_db - snare_r_raw["_peak_db"])

    safety_metrics: dict[str, Any] = {
        "true_peak_dbfs": tp_db,
        "clipping_samples": clip_samples,
        "lr_balance_db": lr_balance_db,
        "groove_stereo_correlation": groove_corr if "groove_all" in windows else _stereo_correlation(audio),
    }
    if k_corr:
        safety_metrics["kick_stereo_correlation"] = float(np.mean(k_corr))
    if snare_c_raw:
        safety_metrics["snare_stereo_correlation"] = float(snare_c_raw["_corr"])

    return {
        "file": wav_label,
        "scope": scope,
        "sample_rate": int(sr),
        "duration_s": float(len(audio) / sr),
        "alignment_offset_ms": float(offset / sr * 1000.0),
        "safety": safety_metrics,
        "kick": kick_metrics,
        "snare_center": {k: v for k, v in snare_c_raw.items() if not k.startswith("_")},
        "snare_rimshot": {k: v for k, v in snare_r_raw.items() if not k.startswith("_")},
        "toms": tom_metrics,
        "cymbals": cym_metrics,
        "groove": groove_metrics,
    }


def measure_bounce(
    wav_path: Path,
    manifest_path: Path | None = None,
    align: bool = True,
    unload_slots: set[str] | None = None,
) -> dict[str, Any]:
    resolved_manifest = manifest_path or default_manifest_path()
    audio, sr = _load_stereo_audio(wav_path)
    manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    return _measure_audio_array(audio, sr, str(wav_path), manifest, align=align, unload_slots=unload_slots)


def _generate_causal_patch(
    group: str,
    key: str,
    status: str,
    val: Any,
    bound: dict[str, Any],
    metrics: dict[str, Any],
    extra: dict[str, Any],
) -> dict[str, Any] | None:
    if status == "PASS":
        return None
    if key == "fundamental_hz" and "pitch_delta_semitones" in extra:
        slot = "KickR" if group == "kick" else "Snare"
        return {
            "target": f"kit.pieces[{slot}].pitch_semitones",
            "delta_semitones": extra["pitch_delta_semitones"],
            "metric": f"{group}.{key}",
        }
    if key == "ring_prominence_db" and group.startswith("snare"):
        peaks = metrics.get(group, {}).get("ring_peaks_hz") or [450.0]
        return {
            "target": "snare_eq_notch",
            "channel": "Snare Top",
            "freq_hz": peaks[0],
            "gain_db": -3.5,
            "q": 5.0,
            "metric": f"{group}.{key}",
        }
    if key in {"true_peak_dbfs", "clipping_samples"}:
        delta_db = round(float(bound.get("ideal", -1.5) - float(val)), 2) if isinstance(val, (int, float)) else -1.5
        return {"target": "master_bus.fader_db", "delta_db": max(-6.0, min(6.0, delta_db)), "metric": f"{group}.{key}"}
    if key == "kick_to_snare_peak_diff_db" and isinstance(val, (int, float)):
        ideal = float(bound.get("ideal", 0.0))
        return {"target": "Bus 1 (Kick Bus).fader_db", "delta_db": round(ideal - float(val), 2), "metric": f"{group}.{key}"}
    if key == "harshness_ratio_db":
        return {"target": "mic[OH Dyn].eq_cut", "freq_hz": 4200.0, "delta_db": -2.0, "metric": f"{group}.{key}"}
    return None


def evaluate_against_spec(metrics: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    hard_fails = 0
    warns = 0
    loss_terms: list[float] = []
    causal_patches: list[dict[str, Any]] = []
    is_scoped = metrics.get("scope", "full") != "full"

    for group in ("safety", "kick", "snare_center", "snare_rimshot", "toms", "cymbals", "groove"):
        spec_group = spec.get(group, {})
        meas_group = metrics.get(group, {})
        if is_scoped and not meas_group:
            continue
        for key, bound in spec_group.items():
            if is_scoped and key not in meas_group:
                continue
            val = meas_group.get(key)
            severity = bound.get("severity", "hard")
            unit = bound.get("unit", "")
            ideal = bound.get("ideal")
            mn = bound.get("min")
            mx = bound.get("max")

            status = "PASS"
            delta: float | None = None
            guidance = ""

            if val is None:
                status = "FAIL" if severity == "hard" else "WARN"
                guidance = f"Métrica ausente: {group}.{key}."
            elif isinstance(val, bool) or isinstance(ideal, bool):
                expected = ideal if isinstance(ideal, bool) else mn
                if val != expected:
                    status = "FAIL" if severity == "hard" else "WARN"
                    guidance = bound.get("hint_low", f"Ajustar {group}.{key} para {expected}")
                    loss_terms.append(4.0)
            elif isinstance(val, (int, float)):
                if mn is not None and val < mn:
                    status = "FAIL" if severity == "hard" else "WARN"
                    delta = round(float(val - mn), 3)
                    guidance = bound.get("hint_low", f"Abaixo do mínimo ({mn} {unit}).")
                elif mx is not None and val > mx:
                    status = "FAIL" if severity == "hard" else "WARN"
                    delta = round(float(val - mx), 3)
                    guidance = bound.get("hint_high", f"Acima do máximo ({mx} {unit}).")
                elif isinstance(ideal, (int, float)):
                    delta = round(float(val - ideal), 3)

                if isinstance(ideal, (int, float)):
                    span = max(1.0, (float(mx) - float(mn)) * 0.5) if (mn is not None and mx is not None) else max(1.0, abs(float(ideal)) * 0.25)
                    loss_terms.append(min(25.0, ((float(val) - float(ideal)) / span) ** 2))

            extra: dict[str, Any] = {}
            if key == "fundamental_hz" and isinstance(val, (int, float)) and val > 0 and isinstance(ideal, (int, float)) and ideal > 0:
                semis = 12.0 * math.log2(ideal / val)
                extra["pitch_delta_semitones"] = round(semis, 2)
                if status != "PASS":
                    guidance = f"{guidance} (Delta de afinação: {semis:+.2f} semitons no knob Pitch do SD3)."

            if key == "ring_prominence_db" and group.startswith("snare") and meas_group.get("ring_peaks_hz"):
                peaks_str = ", ".join(f"{hz:.0f} Hz" for hz in meas_group["ring_peaks_hz"])
                extra["ring_peaks_hz"] = meas_group["ring_peaks_hz"]
                if status != "PASS":
                    guidance = f"{guidance} [Picos de ring detectados: {peaks_str}]"

            patch = _generate_causal_patch(group, key, status, val, bound, metrics, extra)
            if patch is not None:
                causal_patches.append(patch)

            if status == "FAIL":
                hard_fails += 1
            elif status == "WARN":
                warns += 1

            checks.append(
                {
                    "metric": f"{group}.{key}",
                    "measured": round(val, 3) if isinstance(val, float) else val,
                    "min": mn,
                    "max": mx,
                    "ideal": ideal,
                    "unit": unit,
                    "severity": severity,
                    "status": status,
                    "delta": delta,
                    "guidance": guidance,
                    **extra,
                }
            )

    max_warnings = spec.get("metadata", {}).get("max_warnings")
    warn_budget_exceeded = bool(max_warnings is not None and warns > int(max_warnings))
    overall = "PASS" if (hard_fails == 0 and not warn_budget_exceeded) else "FAIL"
    scalar_loss = round(
        sum(loss_terms) / max(1, len(loss_terms))
        + 100.0 * hard_fails
        + (15.0 * max(0, warns - int(max_warnings)) if max_warnings is not None else 2.0 * warns),
        4,
    )

    return {
        "preset_id": spec["metadata"]["preset_id"],
        "overall_status": overall,
        "warn_budget_exceeded": warn_budget_exceeded,
        "max_warnings": max_warnings,
        "scalar_loss": scalar_loss,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(1 for c in checks if c["status"] == "PASS"),
            "warnings": warns,
            "hard_failures": hard_fails,
        },
        "causal_patches": causal_patches,
        "metrics": metrics,
        "checks": checks,
    }


def save_diagnostic_plots(
    wav_path: Path | None,
    report: dict[str, Any],
    out_png: Path,
    manifest_path: Path | None = None,
    *,
    audio: np.ndarray | None = None,
    sr: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if audio is None or sr is None:
        if wav_path is None:
            raise ValueError("Provide either `wav_path` or `(audio, sr)` to save_diagnostic_plots")
        audio, sr = _load_stereo_audio(wav_path)
    if manifest is None:
        resolved_manifest = manifest_path or default_manifest_path()
        manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))

    offset = int(report["metrics"]["alignment_offset_ms"] / 1000.0 * sr)
    windows = manifest.get("windows", {})

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle(f"SD3 Preset Forge Diagnostic — {report['preset_id']} [{report['overall_status']}]", fontsize=13)

    ax = axes[0, 0]
    if "groove_all" in windows:
        gs = offset + int(windows["groove_all"]["start_s"] * sr)
        ge = min(len(audio), offset + int(windows["groove_all"]["end_s"] * sr))
        g_mono = np.mean(audio[gs:ge], axis=1)
    else:
        g_mono = np.mean(audio, axis=1)
    if len(g_mono) >= 256:
        freqs, psd = signal.welch(g_mono, fs=sr, nperseg=min(16384, len(g_mono)))
        psd_db = 10.0 * np.log10(psd + EPS)
        ax.semilogx(freqs[1:], psd_db[1:], color="#2b6cb0")
    ax.set_xlim(25, 18000)
    ax.set_title("Power Spectrum (25 Hz - 18 kHz)")
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB")
    ax.grid(True, which="both", alpha=0.3)

    ax = axes[0, 1]
    sn_seg = np.array([], dtype=np.float64)
    if "snare_rimshot_isolated" in windows:
        t_sn = windows["snare_rimshot_isolated"]["hit_times_s"][0]
        sn_seg = np.mean(_slice_hit(audio, sr, offset, t_sn, 0.0, 220.0), axis=1)
    elif "snare_center_isolated" in windows:
        t_sn = windows["snare_center_isolated"]["hit_times_s"][0]
        sn_seg = np.mean(_slice_hit(audio, sr, offset, t_sn, 0.0, 220.0), axis=1)
    if len(sn_seg) >= 64:
        nf = 16384
        sp = 20.0 * np.log10(np.abs(np.fft.rfft(sn_seg * np.hanning(len(sn_seg)), n=nf)) + EPS)
        fr = np.fft.rfftfreq(nf, d=1.0 / sr)
        ax.plot(fr, sp, color="#c53030")
    ax.set_xlim(80, 1600)
    ax.set_title("Snare Fundamental & Ring (80 - 1600 Hz)")
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB")
    ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    k_seg = np.array([], dtype=np.float64)
    if "kick_isolated" in windows:
        t_k = windows["kick_isolated"]["hit_times_s"][0]
        k_seg = np.mean(_slice_hit(audio, sr, offset, t_k, 0.0, 450.0), axis=1)
    for label, seg, col in [("Kick", k_seg, "#2f855a"), ("Snare", sn_seg, "#c53030")]:
        if len(seg) > 10:
            t_ms = np.arange(len(seg)) / sr * 1000.0
            env = 20.0 * np.log10(np.maximum(np.abs(seg), 1e-5) / (np.max(np.abs(seg)) + EPS))
            ax.plot(t_ms, env, label=label, alpha=0.75, color=col)
    ax.set_ylim(-60, 3)
    ax.set_title("Transient & Decay Envelope")
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("dB rel Peak")
    if len(k_seg) > 10 or len(sn_seg) > 10:
        ax.legend()
    ax.grid(True, alpha=0.3)

    ax = axes[1, 1]
    ax.axis("off")
    s = report["summary"]
    m = report["metrics"]
    lines = [
        f"Overall: {report['overall_status']} (loss={report.get('scalar_loss', 0):.2f})",
        f"Passed: {s['passed']}/{s['total_checks']} | Warns: {s['warnings']} | Fails: {s['hard_failures']}",
    ]
    if "fundamental_hz" in m.get("kick", {}):
        lines.append(f"Kick f0: {m['kick']['fundamental_hz']:.1f} Hz")
    if "fundamental_hz" in m.get("snare_center", {}):
        lines.append(f"Snare Center f0: {m['snare_center']['fundamental_hz']:.1f} Hz")
    if m.get("snare_center", {}).get("ring_peaks_hz"):
        lines.append(f"Snare Ring Peaks: {m['snare_center']['ring_peaks_hz']}")
    lines.append(f"True Peak: {m['safety']['true_peak_dbfs']:.2f} dBFS")
    if "integrated_lufs" in m.get("groove", {}):
        lines.append(f"LUFS: {m['groove']['integrated_lufs']:.1f} | LRA: {m['groove']['lra_lu']:.1f} LU")
    lines.append("")
    lines.append("Failures / Warnings:")
    fails = [c for c in report["checks"] if c["status"] != "PASS"][:6]
    if not fails:
        lines.append("  None — ALL GREEN!")
    for c in fails:
        lines.append(f"  [{c['status']}] {c['metric']}: {c['measured']} ({c['guidance'][:45]})")
    ax.text(0.02, 0.95, "\n".join(lines), va="top", family="monospace", fontsize=9)

    fig.tight_layout()
    fig.savefig(str(out_png), dpi=130)
    plt.close(fig)


def render_report_md(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Relatório TDD de Áudio — `{report['preset_id']}`",
        "",
        f"- **Status Geral:** **{report['overall_status']}** (`scalar_loss = {report.get('scalar_loss', 0.0)}`)",
        f"- **Resumo:** {s['passed']}/{s['total_checks']} PASS | {s['warnings']} WARN | {s['hard_failures']} FAIL",
        f"- **Arquivo Analisado:** `{report['metrics']['file']}` (offset alinhado: `{report['metrics']['alignment_offset_ms']:.1f} ms`)",
        "",
        "| Métrica | Medido | Alvo (Min / Ideal / Max) | Status | Delta / Ação SD3 |",
        "| :--- | :---: | :---: | :---: | :--- |",
    ]
    for c in report["checks"]:
        target_str = f"{c.get('min', '-')} / {c.get('ideal', '-')} / {c.get('max', '-')}"
        action = c.get("guidance") or (f"delta {c['delta']}" if c.get("delta") is not None else "-")
        lines.append(
            f"| `{c['metric']}` | `{c['measured']} {c['unit']}` | `{target_str}` | **{c['status']}** | {action} |"
        )
    return "\n".join(lines) + "\n"


def _load_unload_slots(preset_dir: Path) -> set[str]:
    bp_path = preset_dir / "03-sd3-blueprint.yaml"
    if not bp_path.exists():
        return set()
    try:
        bp = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
        return set(bp.get("kit", {}).get("unload_slots", []))
    except Exception:
        return set()


def run_analysis(
    preset_dir: Path,
    wav_path: Path,
    manifest_path: Path | None = None,
    align: bool = True,
) -> dict[str, Any]:
    resolved_manifest = manifest_path or default_manifest_path()
    spec = yaml.safe_load((preset_dir / "02-spec-targets.yaml").read_text(encoding="utf-8"))
    audio, sr = _load_stereo_audio(wav_path)
    manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    unload_slots = _load_unload_slots(preset_dir)

    metrics = _measure_audio_array(audio, sr, str(wav_path), manifest, align=align, unload_slots=unload_slots)
    report = evaluate_against_spec(metrics, spec)

    (preset_dir / "test-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (preset_dir / "test-report.md").write_text(
        render_report_md(report), encoding="utf-8"
    )
    save_diagnostic_plots(
        None,
        report,
        preset_dir / "diagnostic-plots.png",
        audio=audio,
        sr=sr,
        manifest=manifest,
    )
    return report
