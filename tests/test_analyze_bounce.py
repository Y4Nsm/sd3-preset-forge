"""Integration tests for DSP bounce analyzer using deterministic synthetic WAVs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from sd3_forge.analyze_bounce import evaluate_against_spec, measure_bounce

MANIFEST_PATH = Path("test-suite/midi-manifest.json")
SR = 44100


def _synth_kick(sr: int, f0: float = 58.0, dur: float = 0.45) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    # Pitch envelope dropping to f0 + 4kHz beater click
    freq_t = f0 + 55.0 * np.exp(-t / 0.015)
    phase = 2.0 * np.pi * np.cumsum(freq_t) / sr
    body = 0.65 * np.sin(phase) * np.exp(-t / 0.095)
    click = 0.16 * np.sin(2.0 * np.pi * 4100.0 * t) * np.exp(-t / 0.004)
    hit = body + click
    return np.column_stack([hit, hit])


def _synth_snare(sr: int, f0: float = 225.0, dur: float = 0.45, ring_amp: float = 0.06) -> np.ndarray:
    rng = np.random.default_rng(42)
    n = int(dur * sr)
    t = np.arange(n) / sr
    body = 0.50 * np.sin(2.0 * np.pi * f0 * t) * np.exp(-t / 0.065)
    ring = ring_amp * np.sin(2.0 * np.pi * 460.0 * t) * np.exp(-t / 0.11)
    crack = 0.24 * np.sin(2.0 * np.pi * 3100.0 * t) * np.exp(-t / 0.008)
    noise = rng.normal(0.0, 1.0, n)
    b, a = signal.butter(2, 6500.0 / (sr / 2.0), btype="high")
    wires = 0.14 * signal.lfilter(b, a, noise) * np.exp(-t / 0.085)
    mono = body + ring + crack + wires
    return np.column_stack([mono, mono * 0.98])


def _synth_tom(sr: int, f0: float, dur: float = 0.5) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    hit = 0.55 * np.sin(2.0 * np.pi * f0 * t) * np.exp(-t / 0.14)
    return np.column_stack([hit, hit])


def _synth_cymbal(sr: int, dur: float = 0.7, seed: int = 99) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    t = np.arange(n) / sr
    b, a = signal.butter(3, 7800.0 / (sr / 2.0), btype="high")
    l_ch = signal.lfilter(b, a, rng.normal(0.0, 1.0, n)) * np.exp(-t / 0.25)
    r_ch = signal.lfilter(b, a, rng.normal(0.0, 1.0, n)) * np.exp(-t / 0.25)
    return 0.22 * np.column_stack([l_ch, r_ch])


def _add_hit(buf: np.ndarray, hit: np.ndarray, t_s: float, sr: int, gain: float = 1.0) -> None:
    idx = int(t_s * sr)
    end = min(len(buf), idx + len(hit))
    if idx < len(buf):
        buf[idx:end] += gain * hit[: end - idx]


def _build_synthetic_kit_wav(
    out_wav: Path,
    kick_hz: float = 58.0,
    snare_hz: float = 225.0,
    leading_silence_s: float = 0.0,
    clip_audio: bool = False,
    invert_groove_phase: bool = False,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    win = manifest["windows"]
    total_n = int((manifest["total_seconds"] + leading_silence_s + 0.5) * SR)
    buf = np.zeros((total_n, 2), dtype=np.float64)

    kick = _synth_kick(SR, f0=kick_hz)
    snare = _synth_snare(SR, f0=snare_hz)

    def _panned(hit: np.ndarray, l_gain: float, r_gain: float) -> np.ndarray:
        out = hit.copy()
        out[:, 0] *= l_gain
        out[:, 1] *= r_gain
        return out

    rt1 = _panned(_synth_tom(SR, 145.0), 0.9, 0.4)
    rt2 = _panned(_synth_tom(SR, 115.0), 0.75, 0.65)
    ft1 = _panned(_synth_tom(SR, 85.0), 0.6, 0.85)
    ft2 = _panned(_synth_tom(SR, 62.0), 0.4, 0.95)
    cym = _synth_cymbal(SR)

    off = leading_silence_s
    for t in win["kick_isolated"]["hit_times_s"]:
        _add_hit(buf, kick, t + off, SR)
    if "kick_velocity_ladder" in win:
        for t, v in zip(win["kick_velocity_ladder"]["hit_times_s"], win["kick_velocity_ladder"]["velocities"], strict=True):
            _add_hit(buf, kick, t + off, SR, gain=v / 127.0)
    if "double_kick_burst" in win:
        for t in win["double_kick_burst"]["hit_times_s"]:
            _add_hit(buf, kick, t + off, SR, gain=0.85)
    for t in win["snare_center_isolated"]["hit_times_s"]:
        _add_hit(buf, snare, t + off, SR, gain=0.9)
    for t in win["snare_rimshot_isolated"]["hit_times_s"]:
        _add_hit(buf, snare, t + off, SR, gain=1.05)
    if "snare_velocity_ladder" in win:
        for t, v in zip(win["snare_velocity_ladder"]["hit_times_s"], win["snare_velocity_ladder"]["velocities"], strict=True):
            _add_hit(buf, snare, t + off, SR, gain=(v / 127.0) ** 1.2)
    for t in win["racktom1_isolated"]["hit_times_s"]:
        _add_hit(buf, rt1, t + off, SR)
    for t in win["racktom2_isolated"]["hit_times_s"]:
        _add_hit(buf, rt2, t + off, SR)
    # Intentionally leave racktom3 silent (mimics unloaded slot in kit!)
    for t in win["floortom1_isolated"]["hit_times_s"]:
        _add_hit(buf, ft1, t + off, SR)
    for t in win["floortom2_isolated"]["hit_times_s"]:
        _add_hit(buf, ft2, t + off, SR)
    for t in win["hihat_isolated"]["closed_times_s"] + win["hihat_isolated"]["open_times_s"]:
        _add_hit(buf, cym, t + off, SR, gain=0.7)
    for t in win["cymbals_isolated"]["hit_times_s"]:
        _add_hit(buf, cym, t + off, SR, gain=0.9)
    if "cymbal_choke" in win:
        ch_t = win["cymbal_choke"]["hit_time_s"]
        ck_t = win["cymbal_choke"]["choke_time_s"]
        long_cym = _synth_cymbal(SR, dur=1.2, seed=77)
        mute_sample = int((ck_t - ch_t + 0.03) * SR)
        long_cym[mute_sample:] *= np.exp(-np.arange(len(long_cym) - mute_sample) / (0.015 * SR))[:, None]
        _add_hit(buf, long_cym, ch_t + off, SR, gain=0.9)

    # Groove bars
    g_start = win["groove_all"]["start_s"] + off
    for step in range(32):
        ts = g_start + step * 0.5
        if step % 2 == 0:
            _add_hit(buf, kick, ts, SR, gain=0.95)
        else:
            _add_hit(buf, snare, ts, SR, gain=0.95)
        _add_hit(buf, cym, ts, SR, gain=0.45)

    if invert_groove_phase:
        gs_i = int(g_start * SR)
        ge_i = int((win["groove_all"]["end_s"] + off) * SR)
        buf[gs_i:ge_i, 1] = -buf[gs_i:ge_i, 0]

    if clip_audio:
        buf *= 3.0
        buf = np.clip(buf, -1.0, 1.0)
    else:
        pk = np.max(np.abs(buf))
        if pk > 0:
            buf *= 0.80 / pk

    sf.write(str(out_wav), buf, SR, subtype="PCM_24")


def _synthetic_spec() -> dict:
    return {
        "metadata": {
            "preset_id": "synth-test",
            "genre": "nu-metal",
            "reference_artist": "Test",
            "reference_album": "Test",
            "mix_mode": "internal_sd3",
        },
        "safety": {
            "true_peak_dbfs": {"min": -12.0, "max": -0.5, "ideal": -1.5, "unit": "dBFS", "severity": "hard"},
            "clipping_samples": {"min": 0, "max": 0, "ideal": 0, "unit": "samples", "severity": "hard"},
            "groove_stereo_correlation": {"min": 0.1, "max": 1.0, "ideal": 0.65, "unit": "r", "severity": "hard"},
        },
        "kick": {
            "fundamental_hz": {"min": 50.0, "max": 66.0, "ideal": 58.0, "unit": "Hz", "severity": "hard"},
            "crest_factor_db": {"min": 9.0, "max": 22.0, "ideal": 14.0, "unit": "dB", "severity": "hard"},
        },
        "snare_center": {
            "fundamental_hz": {"min": 210.0, "max": 245.0, "ideal": 225.0, "unit": "Hz", "severity": "hard"},
        },
        "snare_rimshot": {
            "fundamental_hz": {"min": 210.0, "max": 245.0, "ideal": 225.0, "unit": "Hz", "severity": "hard"},
        },
        "toms": {
            "pitch_order_valid": {"ideal": True, "unit": "bool", "severity": "hard"},
        },
        "cymbals": {
            "harshness_ratio_db": {"min": -30.0, "max": 3.0, "ideal": -6.0, "unit": "dB", "severity": "hard"},
            "cymbals_stereo_width": {"min": 0.2, "max": 1.4, "ideal": 0.8, "unit": "w", "severity": "hard"},
        },
        "groove": {
            "groove_crest_factor_db": {"min": 7.0, "max": 22.0, "ideal": 12.0, "unit": "dB", "severity": "hard"},
        },
    }


def test_clean_synthetic_bounce_passes(tmp_path: Path) -> None:
    wav_path = tmp_path / "clean.wav"
    _build_synthetic_kit_wav(wav_path, kick_hz=58.0, snare_hz=225.0)
    metrics = measure_bounce(wav_path, MANIFEST_PATH)
    report = evaluate_against_spec(metrics, _synthetic_spec())

    assert abs(metrics["kick"]["fundamental_hz"] - 58.0) <= 2.5
    assert abs(metrics["snare_center"]["fundamental_hz"] - 225.0) <= 3.0
    assert metrics["toms"]["pitch_order_valid"] is True
    assert report["overall_status"] == "PASS", report["checks"]


def test_broken_bounce_with_offset_clipping_phase_and_low_snare_fails(tmp_path: Path) -> None:
    wav_path = tmp_path / "broken.wav"
    _build_synthetic_kit_wav(
        wav_path,
        kick_hz=58.0,
        snare_hz=175.0,
        leading_silence_s=0.15,
        clip_audio=True,
        invert_groove_phase=True,
    )
    metrics = measure_bounce(wav_path, MANIFEST_PATH, align=True)
    report = evaluate_against_spec(metrics, _synthetic_spec())

    assert 130.0 <= metrics["alignment_offset_ms"] <= 170.0
    assert abs(metrics["snare_center"]["fundamental_hz"] - 175.0) <= 4.0
    assert report["overall_status"] == "FAIL"

    by_metric = {c["metric"]: c for c in report["checks"]}
    assert by_metric["safety.clipping_samples"]["status"] == "FAIL"
    assert by_metric["safety.groove_stereo_correlation"]["status"] == "FAIL"
    assert by_metric["snare_center.fundamental_hz"]["status"] == "FAIL"
    assert by_metric["snare_center.fundamental_hz"]["pitch_delta_semitones"] > 3.5


def test_dsp_v2_ring_peaks_warn_budget_unloaded_toms_and_scoped_probe(tmp_path: Path) -> None:
    wav_path = tmp_path / "v2.wav"
    _build_synthetic_kit_wav(wav_path, kick_hz=58.0, snare_hz=225.0)
    metrics = measure_bounce(wav_path, MANIFEST_PATH, unload_slots={"Tom3"})

    # Exact ring peak detection & new v2 metrics
    assert any(abs(hz - 460.0) <= 3.0 for hz in metrics["snare_center"]["ring_peaks_hz"])
    assert "drr_db" in metrics["snare_center"]
    assert "active_crest_factor_db" in metrics["kick"]
    assert "decay_t20_r2" in metrics["kick"]
    assert "integrated_lufs" in metrics["groove"]
    assert "lra_lu" in metrics["groove"]
    assert "velocity_dynamic_range_db" in metrics["snare_center"]
    assert metrics["toms"]["unloaded_toms"] == ["racktom3"]
    assert metrics["toms"]["pan_order_valid"] is True
    assert metrics["cymbals"]["choke_attenuation_db"] > 12.0
    assert "per_cymbal" in metrics["cymbals"]

    # Strict max_warnings enforcement + causal patches
    spec = _synthetic_spec()
    spec["metadata"]["max_warnings"] = 1
    spec["snare_center"]["ring_prominence_db"] = {"min": 0.0, "max": 2.0, "ideal": 1.0, "unit": "dB", "severity": "warn"}
    spec["groove"]["integrated_lufs"] = {"min": -5.0, "max": -1.0, "ideal": -3.0, "unit": "LUFS", "severity": "warn"}
    rep = evaluate_against_spec(metrics, spec)
    assert rep["summary"]["warnings"] == 2
    assert rep["warn_budget_exceeded"] is True
    assert rep["overall_status"] == "FAIL"
    assert "scalar_loss" in rep
    assert any(p.get("target") == "snare_eq_notch" for p in rep["causal_patches"])

    # Scoped probe analysis works cleanly when only kick_isolated exists
    from sd3_forge.generate_test_midi import generate_midi_and_manifest

    _, scoped_man = generate_midi_and_manifest(tmp_path / "scoped", scope="kick")
    scoped_wav = tmp_path / "kick_only.wav"
    buf = np.zeros((int(18.0 * SR), 2), dtype=np.float64)
    k = _synth_kick(SR, f0=59.5)
    man_data = json.loads(scoped_man.read_text(encoding="utf-8"))
    for t in man_data["windows"]["kick_isolated"]["hit_times_s"]:
        _add_hit(buf, k, t, SR)
    sf.write(str(scoped_wav), buf, SR, subtype="PCM_24")

    m_scoped = measure_bounce(scoped_wav, scoped_man, align=False)
    assert abs(m_scoped["kick"]["fundamental_hz"] - 59.5) <= 1.0
