"""Unit tests verifying mathematical ground truth for DSP Engine v2 (`dsp_metrics.py`)."""

from __future__ import annotations

import math

import numpy as np

from sd3_forge.dsp_metrics import (
    active_crest_factor_db,
    asymmetric_tukey_window,
    attack_body_tail_metrics,
    band_energy_ratio_db,
    band_rms_dbfs,
    detect_onset_offset_xcorr,
    detect_ring_peaks,
    direct_to_reverberant_ratio_db,
    estimate_fundamental_hz,
    measure_lufs_and_lra,
    schroeder_decay_ms,
)

SR = 44100


def test_asymmetric_tukey_preserves_early_transient_unlike_hann() -> None:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    # Sharp 3 ms click burst peaking at t = 2 ms
    click = np.exp(-0.5 * ((t - 0.002) / 0.001) ** 2) * np.sin(2.0 * np.pi * 3500.0 * t)
    hann = np.hanning(n)
    tukey = asymmetric_tukey_window(n, SR, attack_taper_ms=0.5, release_taper_ms=25.0)

    ref_energy = float(np.sum(click**2))
    tukey_loss_db = 10.0 * math.log10(ref_energy / float(np.sum((click * tukey) ** 2)))
    hann_loss_db = 10.0 * math.log10(ref_energy / float(np.sum((click * hann) ** 2)))

    assert abs(tukey_loss_db) < 0.5
    assert hann_loss_db > 15.0


def test_parseval_exact_band_rms_and_ratio() -> None:
    dur = 0.5
    n = int(dur * SR)
    t = np.arange(n) / SR
    # Target RMS = -6.0 dBFS => peak amplitude = sqrt(2) * 10^(-6/20)
    target_rms = 10.0 ** (-6.0 / 20.0)
    x = math.sqrt(2.0) * target_rms * np.sin(2.0 * np.pi * 1000.0 * t)

    rms_band_db = band_rms_dbfs(x, SR, 800.0, 1200.0)
    assert abs(rms_band_db - (-6.0)) <= 0.15

    full_ratio_db = band_energy_ratio_db(x, SR, 10.0, SR * 0.49)
    assert abs(full_ratio_db) <= 0.05


def test_attack_body_tail_separation() -> None:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    # Onset at 2 ms: bright 4 kHz transient + 25 ms 220 Hz body + quiet tail
    atk = 0.8 * np.sin(2.0 * np.pi * 4000.0 * t) * np.exp(-np.maximum(0.0, t - 0.002) / 0.004)
    atk[t < 0.002] = 0.0
    body = 0.2 * np.sin(2.0 * np.pi * 220.0 * t) * np.exp(-np.maximum(0.0, t - 0.002) / 0.025)
    body[t < 0.002] = 0.0
    res = attack_body_tail_metrics(atk + body, SR, onset_offset_in_slice_ms=2.0)
    assert res["attack_to_body_db"] > 6.0
    assert res["body_to_tail_db"] > 9.0


def test_schroeder_edc_matches_analytical_decay_constants() -> None:
    # x(t) = exp(-t / tau) * sin(2*pi*f*t): energy decays as exp(-2t/tau).
    # Time for -20 dB energy drop: 20 = 20*log10(e) * (t/tau) => t = tau * ln(10) = 230.2585 ms (for tau=0.10 s)
    # Time for -30 dB drop: 30 * ln(10)/20? Wait: exp(-t/tau) amplitude => -20 dB when exp(-t/tau)=0.1 => t=tau*ln(10)=230.26 ms; -30 dB => t=tau*ln(10)*1.5=345.39 ms
    tau = 0.10
    n = int(1.0 * SR)
    t = np.arange(n) / SR
    x = np.exp(-t / tau) * np.sin(2.0 * np.pi * 120.0 * t)

    t20 = schroeder_decay_ms(x, SR, drop_db=20.0)
    t30 = schroeder_decay_ms(x, SR, drop_db=30.0)
    assert abs(t20["decay_ms"] - 230.26) <= 5.0
    assert t20["r2"] > 0.99
    assert t20["drop_guard_triggered"] is False
    assert abs(t30["decay_ms"] - 345.39) <= 5.0
    assert t30["r2"] > 0.99


def test_schroeder_drop_guard_when_tail_does_not_reach_full_drop() -> None:
    tau = 0.25
    n = int(0.35 * SR)  # Only drops ~12 dB in 350 ms!
    t = np.arange(n) / SR
    x = np.exp(-t / tau) * np.sin(2.0 * np.pi * 150.0 * t)
    res = schroeder_decay_ms(x, SR, drop_db=30.0)
    assert res["drop_guard_triggered"] is True
    assert res["achieved_drop_db"] < 20.0


def test_direct_to_reverberant_ratio_accuracy() -> None:
    n = int(0.5 * SR)
    x = np.zeros(n, dtype=np.float64)
    # Direct burst inside [5 ms, 25 ms] with energy = E_d, reverb inside [50 ms, 300 ms] with energy = E_d / 10 (-10 dB => DRR = +10.0 dB)
    t = np.arange(n) / SR
    direct_mask = (t >= 0.005) & (t < 0.025)
    reverb_mask = (t >= 0.050) & (t < 0.300)
    x[direct_mask] = 0.8 * np.sin(2.0 * np.pi * 500.0 * t[direct_mask])
    e_direct = float(np.sum(x[direct_mask] ** 2))
    raw_rev = np.sin(2.0 * np.pi * 500.0 * t[reverb_mask])
    scale = math.sqrt((e_direct / 10.0) / float(np.sum(raw_rev**2)))
    x[reverb_mask] = scale * raw_rev

    drr = direct_to_reverberant_ratio_db(x, SR, direct_ms=30.0, tail_end_ms=450.0)
    assert abs(drr - 10.0) <= 0.2


def test_log_parabolic_pitch_accuracy_and_noise_prominence_guard() -> None:
    for freq in (58.3, 144.8, 225.4):
        n = int(0.25 * SR)
        t = np.arange(n) / SR
        tone = np.sin(2.0 * np.pi * freq * t) * np.exp(-t / 0.12)
        est = estimate_fundamental_hz(tone, SR, f_min=max(30.0, freq * 0.6), f_max=min(400.0, freq * 1.5))
        assert abs(est["hz"] - freq) <= 0.5
        assert est["prominent"] is True
        assert est["prominence_db"] > 12.0

    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 0.2, int(0.2 * SR))
    noise_est = estimate_fundamental_hz(noise, SR, f_min=35.0, f_max=100.0, min_prominence_db=10.0)
    assert noise_est["prominent"] is False


def test_sliding_median_ring_detector_finds_exact_peaks() -> None:
    rng = np.random.default_rng(11)
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    tail = (
        0.04 * rng.normal(0.0, 1.0, n)
        + 0.18 * np.sin(2.0 * np.pi * 462.5 * t) * np.exp(-t / 0.14)
        + 0.12 * np.sin(2.0 * np.pi * 1124.0 * t) * np.exp(-t / 0.11)
    )
    res = detect_ring_peaks(tail, SR, f_min=280.0, f_max=1600.0, min_prominence_db=6.0)
    assert res["ring_prominence_db"] > 10.0
    assert len(res["ring_peaks_hz"]) >= 2
    assert any(abs(hz - 462.5) <= 2.0 for hz in res["ring_peaks_hz"])
    assert any(abs(hz - 1124.0) <= 2.0 for hz in res["ring_peaks_hz"])


def test_active_crest_t95_invariant_to_trailing_silence() -> None:
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    hit = np.sin(2.0 * np.pi * 180.0 * t) * np.exp(-t / 0.05)
    padded = np.concatenate([hit, np.zeros(int(2.0 * SR), dtype=np.float64)])

    cf_short = active_crest_factor_db(hit, energy_fraction=0.95)
    cf_padded = active_crest_factor_db(padded, energy_fraction=0.95)
    assert abs(cf_short - cf_padded) < 0.1


def test_itu_bs1770_lufs_and_lra_calibration() -> None:
    n = int(4.0 * SR)
    t = np.arange(n) / SR
    # 1 kHz stereo sine with amplitude 0.1 on both L & R => exact -20.00 +- 0.2 LUFS
    s_1k = 0.1 * np.sin(2.0 * np.pi * 1000.0 * t)
    m_1k = measure_lufs_and_lra(np.column_stack([s_1k, s_1k]), SR)
    assert abs(m_1k["integrated_lufs"] - (-20.0)) <= 0.25

    # 4 kHz stereo sine gets ~+3.27 dB net K-weighting gain relative to 1 kHz (+3.96 dB vs +0.69 dB)
    s_4k = 0.1 * np.sin(2.0 * np.pi * 4000.0 * t)
    m_4k = measure_lufs_and_lra(np.column_stack([s_4k, s_4k]), SR)
    diff = m_4k["integrated_lufs"] - m_1k["integrated_lufs"]
    assert 3.1 <= diff <= 3.5

    # Dual-level track (2s quiet @ -18 dB + 2s loud @ 0 dB) => positive LRA > 4 LU
    quiet = 0.02 * np.sin(2.0 * np.pi * 440.0 * np.arange(int(3.5 * SR)) / SR)
    loud = 0.25 * np.sin(2.0 * np.pi * 440.0 * np.arange(int(3.5 * SR)) / SR)
    dual = np.concatenate([quiet, loud])
    m_dual = measure_lufs_and_lra(np.column_stack([dual, dual]), SR)
    assert m_dual["lra_lu"] > 5.0


def test_xcorr_onset_alignment_under_prenoise() -> None:
    rng = np.random.default_rng(19)
    total = int(8.5 * SR)
    audio = rng.normal(0.0, 0.015, (total, 2))  # ~ -36 dBFS continuous noise
    true_offset_s = 0.150
    hit_times = [0.0, 2.0, 4.0, 6.0]
    t_hit = np.arange(int(0.2 * SR)) / SR
    pulse = 0.7 * np.sin(2.0 * np.pi * 80.0 * t_hit) * np.exp(-t_hit / 0.04)
    for ht in hit_times:
        idx = int((ht + true_offset_s) * SR)
        audio[idx : idx + len(pulse), 0] += pulse
        audio[idx : idx + len(pulse), 1] += pulse

    est_samples = detect_onset_offset_xcorr(audio, SR, hit_times_s=hit_times, max_search_s=2.0)
    est_ms = est_samples / SR * 1000.0
    assert abs(est_ms - 148.0) <= 4.0  # 150 ms minus 2 ms pre-roll
