"""TDD tests for the bounded 2-stage analytical calibrator & `.forge-history/` rollback."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import yaml

from sd3_forge.fx_catalog import parse_band_spec


def _extract_eq_cuts(inserts: list[dict[str, Any]]) -> list[tuple[float, float]]:
    cuts: list[tuple[float, float]] = []
    for ins in inserts:
        if ins.get("fx") == "EQ":
            for k, v in (ins.get("params") or {}).items():
                if str(k).lower().startswith("cut"):
                    hz, db, _q = parse_band_spec(v)
                    cuts.append((hz, db))
    return cuts


def _setup_test_preset(tmp_path: Path) -> Path:
    preset_dir = tmp_path / "test-preset"
    shutil.copytree("presets/nu-metal/deftones-around-the-fur", preset_dir)
    # Remove any copied test-report or bounces wavs so test is isolated
    for f in preset_dir.glob("test-report.*"):
        f.unlink()
    if (preset_dir / "diagnostic-plots.png").exists():
        (preset_dir / "diagnostic-plots.png").unlink()
    for wav in (preset_dir / "bounces").glob("*.wav"):
        wav.unlink()

    bp = yaml.safe_load((preset_dir / "03-sd3-blueprint.yaml").read_text(encoding="utf-8"))
    # Sabotage pitch, snare ring notch, harshness, and master fader so calibrator has real work
    for pc in bp["kit"]["pieces"]:
        if pc["slot"] == "KickR":
            pc["pitch_semitones"] = -0.5  # off from +2.0 st target
        elif pc["slot"] == "Snare":
            pc["pitch_semitones"] = 0.0  # off from +2.7 st target
    for m in bp["mics"]:
        if m["channel"] == "Snare Top":
            m["inserts"] = [ins for ins in m.get("inserts", []) if ins.get("fx") != "EQ"]
        if m["channel"] == "OH Dyn":
            m["inserts"] = [{"fx": "EQ", "params": {"HPF": "250 Hz", "HighShelf": "7.0 kHz, +4.0 dB"}}]
    for b in bp["buses"]:
        if b["name"] == "Bus 2 (Snare Bus)":
            b["inserts"] = [ins for ins in b.get("inserts", []) if ins.get("fx") != "EQ"]
    bp["master_bus"]["fader_db"] = 5.5  # artificially hot peak
    (preset_dir / "03-sd3-blueprint.yaml").write_text(
        yaml.safe_dump(bp, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return preset_dir


def _synth_from_blueprint(
    preset_dir: Path,
    manifest_path: Path,
    out_wav: Path,
    *,
    force_fail_if_notched: bool = False,
) -> dict[str, Any]:
    """Deterministic acoustic synth tied to blueprint pitch, EQ cuts, OH harshness, and master fader."""
    bp = yaml.safe_load((preset_dir / "03-sd3-blueprint.yaml").read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sr = 44100
    dur = float(manifest.get("total_seconds", 12.0)) + 2.0
    n = int(round(dur * sr))
    audio = np.zeros((n, 2), dtype=np.float64)

    pieces = {p["slot"]: p for p in bp["kit"]["pieces"]}
    kick_pitch = float(pieces["KickR"].get("pitch_semitones", 0.0))
    snare_pitch = float(pieces["Snare"].get("pitch_semitones", 0.0))
    # Slight realistic nonlinearity so Secant method refines iter 2+
    kick_f0 = 51.8 * (2.0 ** (kick_pitch / 12.0))
    snare_f0 = 192.5 * (2.0 ** (snare_pitch / 12.0))

    mics = {m["channel"]: m for m in bp["mics"]}
    buses = {b["name"]: b for b in bp.get("buses", [])}
    snare_cuts = _extract_eq_cuts(mics["Snare Top"].get("inserts", [])) + _extract_eq_cuts(
        buses.get("Bus 2 (Snare Bus)", {}).get("inserts", [])
    )
    ring_gain_db = sum(db for hz, db in snare_cuts if abs(hz - 475.0) <= 45.0)
    ring_amp = 0.24 * (10.0 ** (max(-18.0, ring_gain_db) / 20.0))
    if force_fail_if_notched and ring_gain_db < -1.0:
        # Inject hard-fail phase inversion on kick if mutated (used to test auto-rollback!)
        inject_phase_fail = True
    else:
        inject_phase_fail = False

    oh_cuts = _extract_eq_cuts(mics["OH Dyn"].get("inserts", []))
    oh_4k_db = sum(db for hz, db in oh_cuts if 3000.0 <= hz <= 6000.0)
    harsh_amp = 0.28 * (10.0 ** (max(-18.0, oh_4k_db) / 20.0))

    master_db = float(bp["master_bus"].get("fader_db", 0.0))
    master_lin = 10.0 ** ((master_db - 2.5) / 20.0)

    def add_tone(t_s: float, dur_s: float, freq: float, amp: float, pan_r: float = 0.5, tau: float = 12.0) -> None:
        i0 = int(t_s * sr)
        length = min(n - i0, int(dur_s * sr))
        if i0 < 0 or length <= 8:
            return
        tv = np.arange(length, dtype=np.float64) / sr
        sig = amp * np.exp(-tau * tv) * np.sin(2.0 * np.pi * freq * tv)
        audio[i0 : i0 + length, 0] += sig * (1.0 - pan_r) * 1.414
        audio[i0 : i0 + length, 1] += (-sig if inject_phase_fail else sig) * pan_r * 1.414

    windows = manifest.get("windows", {})
    for key in ("kick_isolated", "kick_velocity_ladder", "double_kick_burst"):
        if key in windows:
            win = windows[key]
            vels = win.get("velocities", [120] * len(win["hit_times_s"]))
            for t, v in zip(win["hit_times_s"], vels, strict=False):
                sc = 0.25 + 0.75 * (float(v) / 127.0)
                # Fast beater attack (sharp crest & clear double-kick gap) + 58 Hz body + 92 Hz punch
                add_tone(float(t), 0.35, kick_f0, 0.75 * sc, tau=14.0)
                add_tone(float(t), 0.22, 92.0, 0.50 * sc, tau=18.0)
                add_tone(float(t), 0.04, 4200.0, 0.55 * sc, tau=90.0)

    for key in ("snare_center_isolated", "snare_rimshot_isolated", "snare_velocity_ladder", "snare_flam_isolated"):
        if key in windows:
            win = windows[key]
            vels = win.get("velocities", [120] * len(win["hit_times_s"]))
            for t, v in zip(win["hit_times_s"], vels, strict=False):
                sc = 0.25 + 0.75 * (float(v) / 127.0)
                add_tone(float(t), 0.40, snare_f0, 0.30 * sc, pan_r=0.45, tau=9.0)
                add_tone(float(t), 0.38, 475.0, ring_amp * sc, pan_r=0.52, tau=5.0)
                add_tone(float(t), 0.08, 3200.0, 0.14 * sc, pan_r=0.48, tau=45.0)

    for idx, (wk, hz, pan_r) in enumerate(
        [
            ("racktom1_isolated", 155.0, 0.25),
            ("racktom2_isolated", 130.0, 0.40),
            ("racktom3_isolated", 110.0, 0.50),
            ("floortom1_isolated", 92.0, 0.65),
            ("floortom2_isolated", 72.0, 0.85),
        ]
    ):
        _ = idx
        if wk in windows:
            for t in windows[wk]["hit_times_s"]:
                add_tone(float(t), 0.5, hz, 0.25, pan_r=pan_r, tau=6.0)

    if "cymbals_isolated" in windows:
        for t in windows["cymbals_isolated"].get("hit_times_s", []):
            add_tone(float(t), 0.8, 4300.0, harsh_amp, pan_r=0.35, tau=4.0)
            add_tone(float(t), 0.8, 10500.0, 0.08, pan_r=0.65, tau=4.0)
    if "cymbal_choke" in windows:
        ck = windows["cymbal_choke"]
        ht = float(ck["hit_time_s"])
        add_tone(ht, 0.35, 6500.0, 0.22, pan_r=0.4, tau=3.0)
    if "groove_all" in windows:
        gs = float(windows["groove_all"]["start_s"])
        ge = float(windows["groove_all"]["end_s"])
        t = gs
        while t < ge - 0.5:
            add_tone(t, 0.30, kick_f0, 0.45, tau=12.0)
            add_tone(t, 0.20, 92.0, 0.28, tau=16.0)
            add_tone(t + 0.5, 0.30, snare_f0, 0.32, pan_r=0.45, tau=10.0)
            add_tone(t + 0.25, 0.25, 7500.0, 0.18, pan_r=0.20, tau=12.0)
            add_tone(t + 0.75, 0.25, 9200.0, 0.18, pan_r=0.80, tau=12.0)
            t += 1.0

    audio = np.clip(audio * master_lin, -0.999, 0.999)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), audio, sr, subtype="PCM_24")
    peak = float(np.max(np.abs(audio)))
    return {
        "out_wav": str(out_wav),
        "sample_rate": sr,
        "duration_s": dur,
        "peak_linear": peak,
        "peak_dbfs": float(20.0 * np.log10(max(peak, 1e-12))),
        "render_time_s": 0.01,
        "via_daemon": False,
    }


def test_calibration_history_and_rollback(tmp_path: Path) -> None:
    from sd3_forge.calibrate import CalibrationHistory

    preset_dir = tmp_path / "p"
    preset_dir.mkdir()
    bp_path = preset_dir / "03-sd3-blueprint.yaml"
    bp0 = {"schema_version": "2.0", "marker": "baseline"}
    bp1 = {"schema_version": "2.0", "marker": "better"}
    bp2 = {"schema_version": "2.0", "marker": "worse"}

    hist = CalibrationHistory(preset_dir)
    rep0 = {"summary": {"hard_failures": 2, "warnings": 2}, "scalar_loss": 220.0}
    rep1 = {"summary": {"hard_failures": 0, "warnings": 1}, "scalar_loss": 3.5}
    rep2 = {"summary": {"hard_failures": 1, "warnings": 0}, "scalar_loss": 102.0}

    hist.record_baseline(bp0, rep0)
    assert (preset_dir / ".forge-history" / "iter_000.yaml").exists()
    assert hist.is_better(rep1, rep0) is True
    hist.record_candidate("stage1", "pitch", bp1, rep1, accepted=True)
    assert hist.is_better(rep2, rep1) is False
    hist.record_candidate("stage2", "regressed", bp2, rep2, accepted=False)

    bp_path.write_text(yaml.safe_dump(bp2), encoding="utf-8")
    hist.restore_best(bp_path)
    restored = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    assert restored["marker"] == "better"
    log = json.loads((preset_dir / ".forge-history" / "history.json").read_text(encoding="utf-8"))
    assert len(log["iterations"]) == 3


def test_calibrate_stage1_secant_and_stage2_causal_notch(
    tmp_path: Path, mock_inventory_path: Path, synthetic_base_sd3p_path: Path
) -> None:
    from sd3_forge.calibrate import run_calibration
    from sd3_forge.generate_test_midi import generate_midi_and_manifest

    preset_dir = _setup_test_preset(tmp_path)
    _, full_manifest = generate_midi_and_manifest(tmp_path / "full-suite", scope="full")

    def fake_render(
        sd3p_path: Path,
        out_wav: Path,
        *,
        midi_path: Path | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        # Derive matching manifest next to midi_path
        if midi_path and midi_path.stem.startswith("probe-"):
            mpath = midi_path.with_name(f"{midi_path.stem}-manifest.json")
        else:
            mpath = full_manifest
        if not mpath.exists():
            mpath = full_manifest
        return _synth_from_blueprint(preset_dir, mpath, out_wav)

    res = run_calibration(
        preset_dir,
        max_pitch_iters=3,
        max_mix_iters=4,
        inventory_path=mock_inventory_path,
        template_path=synthetic_base_sd3p_path,
        full_manifest_path=full_manifest,
        full_midi_path=tmp_path / "full-suite" / "standard-test-groove.mid",
        use_daemon=False,
        run_canary=True,
        canary_fn=lambda *_a, **_kw: {"ok": True, "silent_slots": []},
        render_fn=fake_render,
    )

    assert (preset_dir / ".forge-history" / "best.yaml").exists()
    final_bp = yaml.safe_load((preset_dir / "03-sd3-blueprint.yaml").read_text(encoding="utf-8"))
    pieces = {p["slot"]: p for p in final_bp["kit"]["pieces"]}
    # Kick (~58 Hz from 51.8 Hz -> ~+1.9 st) & Snare (~225 Hz from 192.5 Hz -> ~+2.7 st)
    assert abs(float(pieces["KickR"]["pitch_semitones"]) - 1.9) <= 0.4
    assert abs(float(pieces["Snare"]["pitch_semitones"]) - 2.7) <= 0.4

    # Check Stage 2 inserted/adjusted notch near 475 Hz without exceeding 5 bands/EQ or 5 inserts
    snare_top = next(m for m in final_bp["mics"] if m["channel"] == "Snare Top")
    assert len(snare_top["inserts"]) <= 5
    cuts = _extract_eq_cuts(snare_top["inserts"])
    assert any(abs(hz - 475.0) <= 30.0 and db < -1.0 for hz, db in cuts)
    for ins in snare_top["inserts"]:
        if ins["fx"] == "EQ":
            band_keys = [k for k in ins["params"] if re.match(r"^(cut|boost|bell|hpf|lpf|lowshelf|highshelf)", str(k), re.I)]
            assert len(band_keys) <= 5

    # Check OH Dyn cut & master fader trimmed
    oh_dyn = next(m for m in final_bp["mics"] if m["channel"] == "OH Dyn")
    assert any(3500.0 <= hz <= 5000.0 and db < 0.0 for hz, db in _extract_eq_cuts(oh_dyn["inserts"]))
    assert float(final_bp["master_bus"]["fader_db"]) < 5.5
    assert res["final_report"]["summary"]["hard_failures"] == 0


def test_calibrate_rolls_back_on_regression(
    tmp_path: Path, mock_inventory_path: Path, synthetic_base_sd3p_path: Path
) -> None:
    from sd3_forge.calibrate import run_calibration
    from sd3_forge.generate_test_midi import generate_midi_and_manifest

    preset_dir = _setup_test_preset(tmp_path)
    # Give baseline valid pitches so it reaches Stage 2 directly and tests Stage 2 rollback
    bp = yaml.safe_load((preset_dir / "03-sd3-blueprint.yaml").read_text(encoding="utf-8"))
    for pc in bp["kit"]["pieces"]:
        if pc["slot"] == "KickR":
            pc["pitch_semitones"] = 1.9
        elif pc["slot"] == "Snare":
            pc["pitch_semitones"] = 2.7
    # Keep baseline peak safe so Stage 2 mutation is guaranteed to strictly worsen hard_failures
    bp["master_bus"]["fader_db"] = 2.5
    (preset_dir / "03-sd3-blueprint.yaml").write_text(yaml.safe_dump(bp, sort_keys=False), encoding="utf-8")

    _, full_manifest = generate_midi_and_manifest(tmp_path / "full-suite", scope="full")

    def regressing_render(
        sd3p_path: Path,
        out_wav: Path,
        *,
        midi_path: Path | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if midi_path and midi_path.stem.startswith("probe-"):
            mpath = midi_path.with_name(f"{midi_path.stem}-manifest.json")
        else:
            mpath = full_manifest
        if not mpath.exists():
            mpath = full_manifest
        return _synth_from_blueprint(preset_dir, mpath, out_wav, force_fail_if_notched=True)

    res = run_calibration(
        preset_dir,
        max_pitch_iters=2,
        max_mix_iters=2,
        inventory_path=mock_inventory_path,
        template_path=synthetic_base_sd3p_path,
        full_manifest_path=full_manifest,
        full_midi_path=tmp_path / "full-suite" / "standard-test-groove.mid",
        use_daemon=False,
        run_canary=False,
        render_fn=regressing_render,
    )

    assert res["rolled_back"] is True
    final_bp = yaml.safe_load((preset_dir / "03-sd3-blueprint.yaml").read_text(encoding="utf-8"))
    best_bp = yaml.safe_load((preset_dir / ".forge-history" / "best.yaml").read_text(encoding="utf-8"))
    assert final_bp == best_bp
