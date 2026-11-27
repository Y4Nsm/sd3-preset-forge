"""Bounded 2-stage analytical calibrator with `.forge-history/` checkpointing & auto-rollback."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from sd3_forge.analyze_bounce import evaluate_against_spec, measure_bounce, run_analysis
from sd3_forge.compile_sd3p import compile_blueprint_to_sd3p
from sd3_forge.daemon import render_via_daemon_or_direct, run_canary_via_daemon_or_direct
from sd3_forge.fx_catalog import parse_band_spec
from sd3_forge.generate_test_midi import generate_midi_and_manifest
from sd3_forge.models import BlueprintV2
from sd3_forge.paths import default_manifest_path, default_midi_path
from sd3_forge.validate_blueprint import validate_preset_dir

_EQ_BAND_RE = re.compile(r"^(hpf|lpf|lowshelf|low_shelf|highshelf|high_shelf|cut|boost|bell)", re.I)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(val)))


def _score_tuple(report: dict[str, Any]) -> tuple[int, int, float]:
    s = report["summary"]
    return (
        int(s.get("hard_failures", 0)),
        int(s.get("warnings", 0)),
        round(float(report.get("scalar_loss", 0.0)), 4),
    )


class CalibrationHistory:
    """Checkpoint manager storing candidate snapshots and `best.yaml` under `.forge-history/`."""

    def __init__(self, preset_dir: Path) -> None:
        self.preset_dir = preset_dir
        self.history_dir = preset_dir / ".forge-history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.best_path = self.history_dir / "best.yaml"
        self.log_path = self.history_dir / "history.json"
        self.best_report: dict[str, Any] | None = None
        self.iterations: list[dict[str, Any]] = []

    @staticmethod
    def is_better(candidate_report: dict[str, Any], best_report: dict[str, Any] | None) -> bool:
        if best_report is None:
            return True
        return _score_tuple(candidate_report) < _score_tuple(best_report)

    def _dump_yaml(self, path: Path, bp_dict: dict[str, Any]) -> None:
        path.write_text(yaml.safe_dump(bp_dict, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def _save_log(self) -> None:
        self.log_path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now(UTC).isoformat(),
                    "best_score": _score_tuple(self.best_report) if self.best_report else None,
                    "iterations": self.iterations,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _append_entry(
        self, stage: str, note: str, bp_dict: dict[str, Any], report: dict[str, Any], *, accepted: bool
    ) -> Path:
        idx = len(self.iterations)
        snap = self.history_dir / f"iter_{idx:03d}.yaml"
        self._dump_yaml(snap, bp_dict)
        if accepted:
            self._dump_yaml(self.best_path, bp_dict)
            self.best_report = copy.deepcopy(report)
        s = report["summary"]
        self.iterations.append(
            {
                "iter": idx,
                "stage": stage,
                "note": note,
                "snapshot": snap.name,
                "accepted": accepted,
                "overall_status": report.get("overall_status"),
                "hard_failures": int(s.get("hard_failures", 0)),
                "warnings": int(s.get("warnings", 0)),
                "scalar_loss": float(report.get("scalar_loss", 0.0)),
            }
        )
        self._save_log()
        return snap

    def record_baseline(self, bp_dict: dict[str, Any], report: dict[str, Any]) -> Path:
        return self._append_entry("baseline", "initial baseline", bp_dict, report, accepted=True)

    def record_candidate(
        self, stage: str, note: str, bp_dict: dict[str, Any], report: dict[str, Any], *, accepted: bool
    ) -> Path:
        return self._append_entry(stage, note, bp_dict, report, accepted=accepted)

    def restore_best(self, target_yaml_path: Path) -> dict[str, Any]:
        if not self.best_path.exists():
            raise FileNotFoundError(f"Best snapshot not found: {self.best_path}")
        raw = self.best_path.read_text(encoding="utf-8")
        target_yaml_path.write_text(raw, encoding="utf-8")
        return yaml.safe_load(raw)


def _load_bp(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _save_bp(path: Path, bp_dict: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(bp_dict, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _get_piece_pitch(bp_dict: dict[str, Any], slot: str) -> float:
    for pc in bp_dict.get("kit", {}).get("pieces", []):
        if pc.get("slot") == slot:
            return float(pc.get("pitch_semitones", 0.0))
    return 0.0


def _set_piece_pitch(bp_dict: dict[str, Any], slot: str, new_pitch_st: float) -> bool:
    clamped = round(_clamp(new_pitch_st, -6.0, 6.0), 2)
    for pc in bp_dict.get("kit", {}).get("pieces", []):
        if pc.get("slot") == slot:
            pc["pitch_semitones"] = clamped
            return True
    return False


def _format_hz(hz: float) -> str:
    return f"{hz / 1000.0:.2f} kHz" if hz >= 1000.0 else f"{int(round(hz))} Hz"


def _upsert_eq_band(
    inserts: list[dict[str, Any]],
    freq_hz: float,
    delta_db: float,
    *,
    q: float = 5.0,
    max_cut_db: float = -14.0,
    max_boost_db: float = 12.0,
) -> bool:
    """Safely insert or adjust a bounded bell band without exceeding 5 bands/EQ or 5 inserts/channel."""
    step_db = _clamp(delta_db, -3.5, 3.5)
    if abs(step_db) < 0.25:
        return False

    freq_hz = _clamp(freq_hz, 25.0, 18000.0)
    prefix = "Cut" if step_db < 0 else "Boost"

    # 1. Try updating an existing nearby Cut/Boost band
    for ins in inserts:
        if ins.get("fx") != "EQ":
            continue
        params = ins.setdefault("params", {})
        for key, val in list(params.items()):
            if not str(key).lower().startswith(("cut", "boost", "bell")):
                continue
            try:
                cur_hz, cur_db, cur_q = parse_band_spec(val)
            except ValueError:
                continue
            if abs(cur_hz - freq_hz) <= max(20.0, 0.15 * freq_hz):
                new_db = round(_clamp(cur_db + step_db, max_cut_db, max_boost_db), 1)
                if abs(new_db - cur_db) < 0.1:
                    return False
                new_q = round(max(cur_q, q) if step_db < 0 and q >= 3.0 else cur_q, 2)
                params[key] = f"{_format_hz(freq_hz)}, {new_db:+.1f} dB, Q {new_q}"
                return True

    # 2. Add new band to existing EQ with < 5 active bands
    for ins in inserts:
        if ins.get("fx") != "EQ":
            continue
        params = ins.setdefault("params", {})
        band_keys = [k for k in params if _EQ_BAND_RE.match(str(k))]
        if len(band_keys) < 5:
            idx = 1
            while f"{prefix}_{idx}" in params:
                idx += 1
            new_db = round(_clamp(step_db, max_cut_db, max_boost_db), 1)
            params[f"{prefix}_{idx}"] = f"{_format_hz(freq_hz)}, {new_db:+.1f} dB, Q {q:.1f}"
            return True

    # 3. Append a fresh EQ insert if total inserts < 5
    if len(inserts) < 5:
        new_db = round(_clamp(step_db, max_cut_db, max_boost_db), 1)
        inserts.append(
            {
                "fx": "EQ",
                "purpose": f"Causal trim around {_format_hz(freq_hz)}",
                "params": {f"{prefix}_1": f"{_format_hz(freq_hz)}, {new_db:+.1f} dB, Q {q:.1f}"},
            }
        )
        return True

    return False


def _adjust_fader(
    bp_dict: dict[str, Any],
    target_type: str,
    name: str,
    delta_db: float,
    *,
    max_step_db: float = 3.0,
    min_db: float = -24.0,
    max_db: float = 6.0,
) -> bool:
    step = _clamp(delta_db, -max_step_db, max_step_db)
    if abs(step) < 0.1:
        return False

    if target_type == "master_bus":
        mb = bp_dict.get("master_bus", {})
        cur = float(mb.get("fader_db", 0.0))
        nxt = round(_clamp(cur + step, min_db, max_db), 2)
        if abs(nxt - cur) < 0.05:
            return False
        mb["fader_db"] = nxt
        return True

    items = bp_dict.get("buses" if target_type == "buses" else "mics", [])
    key_field = "name" if target_type == "buses" else "channel"
    for item in items:
        if item.get(key_field) == name:
            cur = float(item.get("fader_db", 0.0))
            nxt = round(_clamp(cur + step, min_db, max_db), 2)
            if abs(nxt - cur) < 0.05:
                return False
            item["fader_db"] = nxt
            return True
    return False


def _find_channel_inserts(bp_dict: dict[str, Any], kind: str, name: str) -> list[dict[str, Any]] | None:
    if kind == "master_bus":
        return bp_dict.get("master_bus", {}).setdefault("inserts", [])
    key_field = "name" if kind == "buses" else "channel"
    for entry in bp_dict.get(kind, []):
        if entry.get(key_field) == name:
            return entry.setdefault("inserts", [])
    return None


def _propose_stage2_mutations(bp_dict: dict[str, Any], report: dict[str, Any], step_scale: float) -> list[str]:
    actions: list[str] = []
    checks = {c["metric"]: c for c in report.get("checks", [])}
    metrics = report.get("metrics", {})

    # 1. Master peak / clipping safety
    tp = checks.get("safety.true_peak_dbfs")
    clip = checks.get("safety.clipping_samples")
    if (tp and tp["status"] != "PASS") or (clip and clip["status"] != "PASS"):
        val = float(tp["measured"]) if tp and isinstance(tp.get("measured"), (int, float)) else 0.0
        ideal = float(tp.get("ideal", -1.5)) if tp else -1.5
        if _adjust_fader(bp_dict, "master_bus", "Output 1/2", (ideal - val) * step_scale, max_step_db=3.5):
            actions.append(f"master_bus.fader_db trim ({ideal - val:+.2f} dB)")

    # 2. Snare ring resonance (causal notch using exact ring_peaks_hz)
    for grp in ("snare_center", "snare_rimshot"):
        chk = checks.get(f"{grp}.ring_prominence_db")
        if chk and chk["status"] != "PASS":
            peaks = metrics.get(grp, {}).get("ring_peaks_hz") or [450.0]
            freq_hz = float(peaks[0])
            for ch_kind, ch_name in (("mics", "Snare Top"), ("buses", "Bus 2 (Snare Bus)"), ("mics", "Snare Bottom")):
                ins = _find_channel_inserts(bp_dict, ch_kind, ch_name)
                if ins is not None and _upsert_eq_band(ins, freq_hz, -3.5 * step_scale, q=5.0):
                    actions.append(f"{ch_name} EQ notch @ {freq_hz:.0f} Hz")
                    break
            break  # One snare ring cut target per step

    # 3. Cymbal harshness (3-6 kHz cut on OH Dyn / Amb Ribbon)
    cym_chk = checks.get("cymbals.harshness_ratio_db")
    if cym_chk and cym_chk["status"] != "PASS" and isinstance(cym_chk.get("measured"), (int, float)):
        val = float(cym_chk["measured"])
        mx = float(cym_chk.get("max", 3.0))
        direction = -2.5 * step_scale if val > mx else +2.0 * step_scale
        for ch_name in ("OH Dyn", "Amb Ribbon", "Hi-Hat"):
            ins = _find_channel_inserts(bp_dict, "mics", ch_name)
            if ins is not None and _upsert_eq_band(ins, 4200.0, direction, q=1.3):
                actions.append(f"{ch_name} 4.2 kHz ({direction:+.1f} dB)")
                break

    # 4. Kick-to-Snare balance
    k2s = checks.get("groove.kick_to_snare_peak_diff_db")
    if k2s and k2s["status"] != "PASS" and isinstance(k2s.get("measured"), (int, float)):
        ideal = float(k2s.get("ideal", -0.5))
        delta = (ideal - float(k2s["measured"])) * 0.5 * step_scale
        if _adjust_fader(bp_dict, "buses", "Bus 1 (Kick Bus)", delta, max_step_db=2.5):
            actions.append(f"Bus 1 (Kick Bus) fader ({delta:+.2f} dB)")

    # 5. Low-mid mud / kick boxiness
    mud = checks.get("groove.low_mid_150_500_db")
    box = checks.get("kick.boxiness_250_550_db")
    target_chk = None
    if mud and mud["status"] != "PASS" and isinstance(mud.get("measured"), (int, float)):
        target_chk = mud
    elif box and box["status"] != "PASS" and isinstance(box.get("measured"), (int, float)):
        target_chk = box
    if target_chk is not None:
        val = float(target_chk["measured"])
        mx = float(target_chk.get("max", -6.5))
        if val > mx:
            ins = _find_channel_inserts(bp_dict, "master_bus", "Output 1/2")
            if ins is not None and _upsert_eq_band(ins, 320.0, -2.5 * step_scale, q=1.4):
                actions.append(f"Output 1/2 320 Hz ({-2.5 * step_scale:+.1f} dB)")

    return actions


def run_calibration(
    preset_dir: Path,
    *,
    max_pitch_iters: int = 3,
    max_mix_iters: int = 4,
    inventory_path: Path | None = None,
    template_path: Path | None = None,
    vst3_path: Path | None = None,
    full_midi_path: Path | None = None,
    full_manifest_path: Path | None = None,
    use_daemon: bool = True,
    run_canary: bool = True,
    render_fn: Callable[..., dict[str, Any]] | None = None,
    canary_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run bounded 2-stage analytical calibration with `.forge-history/` checkpointing & rollback."""
    preset_dir = Path(preset_dir)
    bp_path = preset_dir / "03-sd3-blueprint.yaml"
    spec_path = preset_dir / "02-spec-targets.yaml"

    init_val = validate_preset_dir(preset_dir, inventory_path=inventory_path)
    if not init_val.ok:
        raise ValueError(f"Initial blueprint failed validation: {'; '.join(init_val.errors)}")

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    resolved_full_midi = full_midi_path or default_midi_path()
    resolved_full_manifest = full_manifest_path or default_manifest_path()
    full_manifest = json.loads(resolved_full_manifest.read_text(encoding="utf-8"))

    history = CalibrationHistory(preset_dir)
    probes_dir = history.history_dir / "probes"
    probes_dir.mkdir(parents=True, exist_ok=True)
    bounces_dir = preset_dir / "bounces"
    bounces_dir.mkdir(parents=True, exist_ok=True)

    active_render = render_fn or render_via_daemon_or_direct
    active_canary = canary_fn or run_canary_via_daemon_or_direct

    def _compile_current() -> Path:
        return compile_blueprint_to_sd3p(
            preset_dir,
            template_path=template_path,
            inventory_path=inventory_path,
            install_to_sd3=False,
        )

    def _run_full_eval(tag: str) -> tuple[Path, dict[str, Any]]:
        sd3p = _compile_current()
        wav = bounces_dir / f"cal-{tag}.wav"
        active_render(
            sd3p,
            wav,
            midi_path=resolved_full_midi,
            vst3_path=vst3_path,
            use_daemon=use_daemon,
        )
        rep = run_analysis(preset_dir, wav, manifest_path=resolved_full_manifest, align=True)
        return wav, rep

    # 1. Pre-flight multi-slot canary
    bp_curr = _load_bp(bp_path)
    unload_slots = bp_curr.get("kit", {}).get("unload_slots", [])
    canary_result: dict[str, Any] = {"skipped": True, "ok": True}
    if run_canary:
        sd3p0 = _compile_current()
        canary_result = active_canary(
            sd3p0,
            unload_slots=unload_slots,
            vst3_path=vst3_path,
            use_daemon=use_daemon,
        )
        if not canary_result.get("ok"):
            raise RuntimeError(
                f"Pre-flight canary detected silent kit slot(s): {canary_result.get('silent_slots')}. "
                "Check kit pieces or `unload_slots` before calibrating."
            )

    # 2. Baseline full evaluation
    _, base_report = _run_full_eval("iter-000")
    history.record_baseline(bp_curr, base_report)
    last_rendered_is_best = True
    rolled_back = False

    max_warnings = int(spec.get("metadata", {}).get("max_warnings") or 0)
    if (
        base_report["overall_status"] == "PASS"
        and base_report["summary"]["warnings"] == 0
        and float(base_report["scalar_loss"]) <= 1.0
    ):
        return {
            "preset_id": base_report["preset_id"],
            "overall_status": base_report["overall_status"],
            "rolled_back": False,
            "canary": canary_result,
            "history_dir": str(history.history_dir),
            "iterations": history.iterations,
            "final_report": base_report,
        }

    # 3. Stage 1 — Bounded Secant Pitch Calibration (Kick & Snare via fast scoped probes)
    bp_work = copy.deepcopy(bp_curr)
    pitch_changed = False
    for grp_key, slot, probe_scope in (("kick", "KickR", "kick"), ("snare_center", "Snare", "snare")):
        chk = next((c for c in base_report["checks"] if c["metric"] == f"{grp_key}.fundamental_hz"), None)
        if not chk or not isinstance(chk.get("ideal"), (int, float)) or not isinstance(chk.get("measured"), (int, float)):
            continue
        ideal_hz = float(chk["ideal"])
        f_curr = float(chk["measured"])
        if chk["status"] == "PASS" and abs(f_curr - ideal_hz) <= 1.5:
            continue

        scope_dir = probes_dir / probe_scope
        probe_midi, probe_manifest_path = generate_midi_and_manifest(scope_dir, scope=probe_scope)
        p_best = _get_piece_pitch(bp_work, slot)
        f_best = f_curr
        p_prev = p_best
        f_prev = f_curr
        p_curr = p_best

        for it in range(1, max(1, max_pitch_iters) + 1):
            if it == 1 or abs(f_curr - f_prev) < 0.2 or abs(p_curr - p_prev) < 1e-3:
                delta_st = _clamp(12.0 * math.log2(max(ideal_hz, 1.0) / max(f_curr, 1.0)), -4.0, 4.0)
                p_cand = _clamp(p_curr + delta_st, -6.0, 6.0)
            else:
                slope = (p_curr - p_prev) / (f_curr - f_prev)
                p_cand = _clamp(p_curr + _clamp((ideal_hz - f_curr) * slope, -3.5, 3.5), -6.0, 6.0)

            p_cand = round(p_cand, 2)
            if abs(p_cand - p_curr) < 0.05:
                break

            cand_bp = copy.deepcopy(bp_work)
            _set_piece_pitch(cand_bp, slot, p_cand)
            BlueprintV2.model_validate(cand_bp)
            _save_bp(bp_path, cand_bp)

            sd3p_probe = _compile_current()
            probe_wav = probes_dir / f"{slot}-p{it}.wav"
            active_render(
                sd3p_probe,
                probe_wav,
                midi_path=probe_midi,
                vst3_path=vst3_path,
                use_daemon=use_daemon,
            )
            probe_metrics = measure_bounce(
                probe_wav,
                manifest_path=probe_manifest_path,
                align=True,
                unload_slots=set(unload_slots),
            )
            f_new = float(probe_metrics.get(grp_key, {}).get("fundamental_hz", f_curr))

            p_prev, f_prev = p_curr, f_curr
            p_curr, f_curr = p_cand, f_new
            if abs(f_new - ideal_hz) < abs(f_best - ideal_hz):
                p_best = p_cand
                f_best = f_new
                bp_work = cand_bp
                pitch_changed = True
            if abs(f_best - ideal_hz) <= 1.0:
                break

        _set_piece_pitch(bp_work, slot, p_best)

    best_report = base_report
    if pitch_changed:
        _save_bp(bp_path, bp_work)
        val_s1 = validate_preset_dir(preset_dir, inventory_path=inventory_path)
        if val_s1.ok:
            _, s1_report = _run_full_eval("stage1-pitch")
            accepted = history.is_better(s1_report, best_report)
            history.record_candidate("stage1", "secant pitch update", bp_work, s1_report, accepted=accepted)
            if accepted:
                best_report = s1_report
                last_rendered_is_best = True
            else:
                rolled_back = True
                bp_work = history.restore_best(bp_path)
                last_rendered_is_best = False
        else:
            rolled_back = True
            bp_work = history.restore_best(bp_path)
            last_rendered_is_best = False

    # 4. Stage 2 — Bounded Causal Spectral / Ring / Balance Trim
    step_scale = 1.0
    for mix_it in range(1, max(0, max_mix_iters) + 1):
        if (
            best_report["overall_status"] == "PASS"
            and best_report["summary"]["warnings"] <= min(0, max_warnings)
            and float(best_report["scalar_loss"]) <= 1.2
        ):
            break

        cand_bp = copy.deepcopy(bp_work)
        actions = _propose_stage2_mutations(cand_bp, best_report, step_scale)
        if not actions:
            break

        try:
            BlueprintV2.model_validate(cand_bp)
        except Exception:
            break

        _save_bp(bp_path, cand_bp)
        val_cand = validate_preset_dir(preset_dir, inventory_path=inventory_path)
        if not val_cand.ok:
            history.restore_best(bp_path)
            break

        _, cand_report = _run_full_eval(f"stage2-{mix_it:02d}")
        accepted = history.is_better(cand_report, best_report)
        history.record_candidate("stage2", "; ".join(actions), cand_bp, cand_report, accepted=accepted)

        if accepted:
            bp_work = cand_bp
            best_report = cand_report
            last_rendered_is_best = True
            if best_report["overall_status"] == "PASS" and best_report["summary"]["warnings"] <= max_warnings:
                if best_report["summary"]["warnings"] == 0 or float(best_report["scalar_loss"]) < 1.5:
                    break
        else:
            rolled_back = True
            bp_work = history.restore_best(bp_path)
            last_rendered_is_best = False
            step_scale *= 0.5
            if step_scale < 0.25:
                break

    # 5. Final Full Gate: ensure blueprint + reports reflect `best.yaml`
    history.restore_best(bp_path)
    if not last_rendered_is_best:
        _, best_report = _run_full_eval("final")

    assert full_manifest is not None
    return {
        "preset_id": best_report["preset_id"],
        "overall_status": best_report["overall_status"],
        "rolled_back": rolled_back,
        "canary": canary_result,
        "history_dir": str(history.history_dir),
        "iterations": history.iterations,
        "final_report": best_report,
    }


def calibrate_evaluate_stub(metrics: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Exposed thin helper around `evaluate_against_spec` for calibrator diagnostics."""
    return evaluate_against_spec(metrics, spec)
