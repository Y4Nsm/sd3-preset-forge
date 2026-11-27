"""Tests for lightweight reference drum stem profiler (`profile_ref.py`)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from sd3_forge.profile_ref import profile_reference_wav
from tests.test_analyze_bounce import _add_hit, _synth_cymbal, _synth_kick, _synth_snare

SR = 44100


def _write_synthetic_stem(wav_path: Path) -> None:
    buf = np.zeros((int(8.0 * SR), 2), dtype=np.float64)
    kick = _synth_kick(SR, f0=55.0, dur=0.45)
    snare = _synth_snare(SR, f0=215.0, dur=0.45, ring_amp=0.07)
    cym = _synth_cymbal(SR, dur=0.35)

    # 4 bars @ 120 BPM (0..8s): alternating kick (0, 1, 2...) and snare (0.5, 1.5...)
    for step in range(16):
        ts = step * 0.5
        if step % 2 == 0:
            _add_hit(buf, kick, ts, SR, gain=0.9)
        else:
            _add_hit(buf, snare, ts, SR, gain=0.95)
        if step % 4 == 0:
            _add_hit(buf, cym, ts, SR, gain=0.3)

    pk = float(np.max(np.abs(buf)))
    if pk > 0:
        buf *= 0.85 / pk
    sf.write(str(wav_path), buf, SR, subtype="PCM_24")


def test_profile_reference_wav_extracts_priors_and_disclaimer(tmp_path: Path) -> None:
    wav_path = tmp_path / "ref_stem.wav"
    _write_synthetic_stem(wav_path)

    profile = profile_reference_wav(wav_path)
    assert profile["advisory_only"] is True
    assert profile["schema_version"] == "2.0"

    assert profile["loudness"]["integrated_lufs"] > -35.0
    assert profile["loudness"]["true_peak_dbfs"] < 0.0
    assert "spectral_tilt_db_per_oct" in profile["spectral_balance"]
    assert "sub_20_60_db" in profile["spectral_balance"]

    priors = profile["transient_priors"]
    assert priors["candidate_counts"]["kick"] >= 3
    assert priors["candidate_counts"]["snare"] >= 3
    assert abs(priors["kick_fundamental_hz"] - 55.0) <= 3.5
    assert abs(priors["snare_fundamental_hz"] - 215.0) <= 5.0
    assert priors["confidence"] in {"high", "medium"}

    spec_priors = profile["suggested_spec_priors"]
    assert "disclaimer" in spec_priors
    assert "kick" in spec_priors and "snare_center" in spec_priors


def test_cli_profile_ref_json_output(tmp_path: Path) -> None:
    wav_path = tmp_path / "ref_stem.wav"
    out_json = tmp_path / "ref_profile.json"
    _write_synthetic_stem(wav_path)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sd3_forge.cli",
            "profile-ref",
            str(wav_path),
            "--out",
            str(out_json),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["advisory_only"] is True
    assert out_json.exists()
