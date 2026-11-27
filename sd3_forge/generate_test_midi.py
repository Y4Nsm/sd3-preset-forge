"""Generate deterministic MIDI v2 test suite (`standard-test-groove.mid`, `midi-manifest.json`, and `--scope` probes)."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import mido

from sd3_forge.paths import default_test_suite_dir

BPM = 120
PPQ = 480
DRUM_CHANNEL = 9  # MIDI channel 10 (0-indexed 9)
TOTAL_BARS = 54
TOTAL_SECONDS = TOTAL_BARS * 2.0  # At 120 BPM in 4/4, 1 bar = 2.0 seconds

VALID_SCOPES = ("full", "kick", "snare", "toms", "cymbals", "groove", "dynamics")

_SCOPE_EVENT_SECTIONS: dict[str, set[str]] = {
    "kick": {"kick_isolated", "kick_velocity_ladder", "double_kick_burst"},
    "snare": {"snare_center_isolated", "snare_rimshot_isolated", "snare_velocity_ladder", "snare_flam_isolated"},
    "toms": {"racktom1_isolated", "racktom2_isolated", "racktom3_isolated", "floortom1_isolated", "floortom2_isolated"},
    "cymbals": {
        "hihat_closed",
        "hihat_open",
        "hihat_pedal",
        "cymbal_crash1",
        "cymbal_crash2",
        "cymbal_splash",
        "cymbal_ride_bow",
        "cymbal_ride_bell",
        "cymbal_crash5",
        "cymbal_choke",
    },
    "groove": {"bleed_stress", "groove_heavy", "groove_dynamic_fill", "tail_release"},
    "dynamics": {"kick_velocity_ladder", "double_kick_burst", "snare_velocity_ladder", "snare_flam_isolated", "groove_dynamic_fill"},
}

_SCOPE_WINDOWS: dict[str, set[str]] = {
    "kick": {"kick_isolated", "kick_velocity_ladder", "double_kick_burst"},
    "snare": {"snare_center_isolated", "snare_rimshot_isolated", "snare_velocity_ladder", "snare_flam_isolated"},
    "toms": {"racktom1_isolated", "racktom2_isolated", "racktom3_isolated", "floortom1_isolated", "floortom2_isolated"},
    "cymbals": {"hihat_isolated", "cymbals_isolated", "cymbal_choke"},
    "groove": {"bleed_stress", "groove_heavy", "groove_dynamic_fill", "groove_all", "tail_release"},
    "dynamics": {"kick_velocity_ladder", "double_kick_burst", "snare_velocity_ladder", "snare_flam_isolated", "groove_dynamic_fill"},
}


def _sec_to_ticks(sec: float) -> int:
    return round(sec * 2.0 * PPQ)


def _shift_window_dict(w: Any, dt: float) -> Any:
    if isinstance(w, dict):
        out: dict[str, Any] = {}
        for k, v in w.items():
            if k in {"hit_times_s", "closed_times_s", "open_times_s", "pedal_times_s"} and isinstance(v, list):
                out[k] = [round(float(x) - dt, 4) for x in v]
            elif k in {"start_s", "end_s", "hit_time_s", "choke_time_s"} and isinstance(v, (int, float)):
                out[k] = round(float(v) - dt, 4)
            elif k == "per_cymbal" and isinstance(v, dict):
                out[k] = {ck: _shift_window_dict(cv, dt) for ck, cv in v.items()}
            else:
                out[k] = copy.deepcopy(v)
        return out
    return copy.deepcopy(w)


def build_test_events(scope: str = "full") -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    """Return `(events, windows, total_seconds)` for the requested test `scope`."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unsupported MIDI scope {scope!r}; expected one of {VALID_SCOPES}")

    events: list[dict[str, Any]] = []
    windows: dict[str, Any] = {}

    def add_isolated(
        section: str,
        note: int,
        times: list[float],
        velocities: list[int],
        analyze_win_ms: tuple[float, float],
        *,
        duration_s: float = 0.15,
    ) -> None:
        for t, v in zip(times, velocities, strict=True):
            events.append({"time_s": t, "note": note, "velocity": v, "duration_s": duration_s, "section": section})
        windows[section] = {
            "note": note,
            "hit_times_s": times,
            "velocities": velocities,
            "window_ms": list(analyze_win_ms),
        }

    # --- Block A: Isolated drums, velocity ladders & bursts (0..60s) ---
    add_isolated("kick_isolated", 36, [0.0, 2.0, 4.0, 6.0], [122, 126, 127, 120], (0.0, 600.0))
    add_isolated("kick_velocity_ladder", 36, [8.0, 9.5, 11.0, 12.5], [35, 65, 95, 125], (0.0, 500.0))

    dk_times = [round(14.0 + i * 0.125, 4) for i in range(8)]
    dk_vels = [124, 120, 125, 121, 126, 120, 125, 122]
    add_isolated("double_kick_burst", 36, dk_times, dk_vels, (0.0, 1200.0), duration_s=0.08)

    add_isolated("snare_center_isolated", 38, [16.0, 18.0, 20.0, 22.0], [122, 126, 127, 120], (0.0, 600.0))
    add_isolated("snare_rimshot_isolated", 40, [24.0, 26.0, 28.0, 30.0], [122, 126, 127, 120], (0.0, 600.0))
    add_isolated("snare_velocity_ladder", 38, [32.0, 33.5, 35.0, 36.5], [35, 65, 95, 125], (0.0, 550.0))

    flam_times = [38.0, 40.0]
    for ft in flam_times:
        events.append({"time_s": round(ft - 0.025, 4), "note": 38, "velocity": 52, "duration_s": 0.06, "section": "snare_flam_isolated"})
        events.append({"time_s": ft, "note": 69, "velocity": 122, "duration_s": 0.15, "section": "snare_flam_isolated"})
    windows["snare_flam_isolated"] = {"note": 69, "hit_times_s": flam_times, "velocities": [122, 122], "window_ms": [0.0, 600.0]}

    add_isolated("racktom1_isolated", 48, [42.0, 44.0], [124, 122], (0.0, 650.0))
    add_isolated("racktom2_isolated", 47, [46.0, 48.0], [124, 122], (0.0, 650.0))
    add_isolated("racktom3_isolated", 45, [50.0, 52.0], [124, 122], (0.0, 650.0))
    add_isolated("floortom1_isolated", 43, [54.0, 56.0], [124, 122], (0.0, 750.0))
    add_isolated("floortom2_isolated", 41, [58.0, 60.0], [124, 122], (0.0, 800.0))

    # --- Block B: Hi-Hat, Per-Cymbal Probes & Choke + >=4s Post-Cymbal Decay Buffer (62..84s) ---
    hh_closed = [62.0, 63.0]
    hh_open = [64.0, 65.0]
    hh_pedal = [66.0]
    for t in hh_closed:
        events.append({"time_s": t, "note": 42, "velocity": 115, "duration_s": 0.15, "section": "hihat_closed"})
    for t in hh_open:
        events.append({"time_s": t, "note": 46, "velocity": 118, "duration_s": 0.35, "section": "hihat_open"})
    for t in hh_pedal:
        events.append({"time_s": t, "note": 44, "velocity": 110, "duration_s": 0.12, "section": "hihat_pedal"})
    windows["hihat_isolated"] = {
        "notes": [42, 46, 44],
        "closed_times_s": hh_closed,
        "open_times_s": hh_open,
        "pedal_times_s": hh_pedal,
        "window_ms": [0.0, 600.0],
    }

    per_cymbal = {
        "crash1": {"note": 86, "hit_times_s": [68.0], "section": "cymbal_crash1", "vel": 124, "dur": 0.5},
        "crash2": {"note": 49, "hit_times_s": [70.0], "section": "cymbal_crash2", "vel": 124, "dur": 0.5},
        "splash": {"note": 55, "hit_times_s": [72.0], "section": "cymbal_splash", "vel": 120, "dur": 0.4},
        "ride_bow": {"note": 51, "hit_times_s": [74.0], "section": "cymbal_ride_bow", "vel": 118, "dur": 0.3},
        "ride_bell": {"note": 53, "hit_times_s": [75.5], "section": "cymbal_ride_bell", "vel": 122, "dur": 0.3},
        "crash5": {"note": 52, "hit_times_s": [77.0], "section": "cymbal_crash5", "vel": 122, "dur": 0.5},
    }
    cym_all_times: list[float] = []
    cym_notes: list[int] = []
    for info in per_cymbal.values():
        cym_notes.append(info["note"])
        for t in info["hit_times_s"]:
            cym_all_times.append(t)
            events.append({"time_s": t, "note": info["note"], "velocity": info["vel"], "duration_s": info["dur"], "section": info["section"]})

    windows["cymbals_isolated"] = {
        "notes": cym_notes,
        "hit_times_s": cym_all_times,
        "window_ms": [0.0, 800.0],
        "per_cymbal": {
            cname: {"note": info["note"], "hit_times_s": info["hit_times_s"], "window_ms": [0.0, 800.0]}
            for cname, info in per_cymbal.items()
        },
    }

    events.append({"time_s": 79.0, "note": 49, "velocity": 124, "duration_s": 0.35, "section": "cymbal_choke"})
    events.append({"time_s": 79.4, "note": 50, "velocity": 120, "duration_s": 0.15, "section": "cymbal_choke"})
    windows["cymbal_choke"] = {"hit_note": 49, "choke_note": 50, "hit_time_s": 79.0, "choke_time_s": 79.4, "window_ms": [0.0, 1000.0]}

    # --- Block C: >=4.6 s cymbal decay buffer followed by Bleed Stress (84..88s) ---
    for bar in range(2):
        b = 84.0 + bar * 2.0
        for off_t in (0.0, 1.0):
            events.append({"time_s": b + off_t, "note": 36, "velocity": 124, "duration_s": 0.12, "section": "bleed_stress"})
        events.append({"time_s": b + 0.5, "note": 43, "velocity": 122, "duration_s": 0.15, "section": "bleed_stress"})
        events.append({"time_s": b + 1.5, "note": 43, "velocity": 120, "duration_s": 0.15, "section": "bleed_stress"})
        for step in range(4):
            events.append({"time_s": b + step * 0.5 + 0.25, "note": 42, "velocity": 105, "duration_s": 0.10, "section": "bleed_stress"})
    windows["bleed_stress"] = {"start_s": 84.0, "end_s": 88.0}

    # --- Block D: Grooves & Dynamic Fill + Release Tail (88..108s) ---
    for bar_idx in range(4):
        b = 88.0 + bar_idx * 2.0
        if bar_idx == 0:
            events.append({"time_s": b + 0.0, "note": 49, "velocity": 124, "duration_s": 0.4, "section": "groove_heavy"})
        for k_off, k_vel in [(0.0, 125), (0.75, 118), (1.0, 124), (1.375, 116)]:
            events.append({"time_s": b + k_off, "note": 36, "velocity": k_vel, "duration_s": 0.12, "section": "groove_heavy"})
        for s_off in (0.5, 1.5):
            events.append({"time_s": b + s_off, "note": 40, "velocity": 124, "duration_s": 0.12, "section": "groove_heavy"})
        for step in range(8):
            note_hh = 46 if step % 2 == 0 else 42
            vel_hh = 112 if step % 2 == 0 else 96
            events.append({"time_s": b + step * 0.25, "note": note_hh, "velocity": vel_hh, "duration_s": 0.12, "section": "groove_heavy"})

    for bar_idx in range(4):
        b = 96.0 + bar_idx * 2.0
        if bar_idx < 3:
            for k_off, k_vel in [(0.0, 124), (0.25, 114), (0.875, 118), (1.0, 125), (1.75, 112)]:
                events.append({"time_s": b + k_off, "note": 36, "velocity": k_vel, "duration_s": 0.10, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 0.375, "note": 38, "velocity": 48, "duration_s": 0.08, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 0.5, "note": 40, "velocity": 126, "duration_s": 0.12, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 1.125, "note": 38, "velocity": 54, "duration_s": 0.08, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 1.5, "note": 40, "velocity": 126, "duration_s": 0.12, "section": "groove_dynamic_fill"})
            for step in range(8):
                n_ride = 53 if step in (0, 4) else 51
                events.append({"time_s": b + step * 0.25, "note": n_ride, "velocity": 108, "duration_s": 0.15, "section": "groove_dynamic_fill"})
        else:
            events.append({"time_s": b + 0.0, "note": 36, "velocity": 125, "duration_s": 0.12, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 0.25, "note": 40, "velocity": 125, "duration_s": 0.12, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 0.5, "note": 48, "velocity": 122, "duration_s": 0.15, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 0.75, "note": 48, "velocity": 118, "duration_s": 0.15, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 1.0, "note": 47, "velocity": 122, "duration_s": 0.15, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 1.25, "note": 43, "velocity": 124, "duration_s": 0.15, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 1.5, "note": 41, "velocity": 125, "duration_s": 0.18, "section": "groove_dynamic_fill"})
            events.append({"time_s": b + 1.75, "note": 36, "velocity": 126, "duration_s": 0.12, "section": "groove_dynamic_fill"})

    events.append({"time_s": 104.0, "note": 36, "velocity": 127, "duration_s": 0.2, "section": "tail_release"})
    events.append({"time_s": 104.0, "note": 49, "velocity": 127, "duration_s": 0.6, "section": "tail_release"})

    windows["groove_all"] = {"start_s": 88.0, "end_s": 104.0}
    windows["groove_heavy"] = {"start_s": 88.0, "end_s": 96.0}
    windows["groove_dynamic_fill"] = {"start_s": 96.0, "end_s": 104.0}
    windows["tail_release"] = {"start_s": 104.0, "end_s": 108.0}

    if scope == "full":
        return events, windows, TOTAL_SECONDS

    allowed_sec = _SCOPE_EVENT_SECTIONS[scope]
    allowed_win = _SCOPE_WINDOWS[scope]
    sub_events = [copy.deepcopy(ev) for ev in events if ev["section"] in allowed_sec]
    sub_windows = {wk: copy.deepcopy(wv) for wk, wv in windows.items() if wk in allowed_win}

    # Compact sparse time gaps (> 3.0s) so short diagnostic probes never render long dead silence
    sorted_times = sorted(ev["time_s"] for ev in sub_events)
    clusters: list[tuple[float, float]] = []
    c_start = sorted_times[0]
    c_end = sorted_times[0]
    for t in sorted_times[1:]:
        if t - c_end > 3.0:
            clusters.append((c_start, c_end + 1.0))
            c_start = t
        c_end = max(c_end, t)
    clusters.append((c_start, c_end + 1.0))

    shifts: list[tuple[float, float, float]] = []
    cursor = 0.0
    for cs, ce in clusters:
        shifts.append((cs, ce, cs - cursor))
        dur = math.ceil((ce - cs + 1.0) / 2.0) * 2.0
        cursor += dur

    def _remap_time(t: float) -> float:
        for cs, ce, delta in shifts:
            if cs - 0.1 <= t <= ce + 0.5:
                return round(t - delta, 4)
        return round(t - shifts[-1][2], 4)

    for ev in sub_events:
        ev["time_s"] = _remap_time(ev["time_s"])

    def _remap_win(w: Any) -> Any:
        if isinstance(w, dict):
            out: dict[str, Any] = {}
            for k, v in w.items():
                if k in {"hit_times_s", "closed_times_s", "open_times_s", "pedal_times_s"} and isinstance(v, list):
                    out[k] = [_remap_time(float(x)) for x in v]
                elif k in {"start_s", "end_s", "hit_time_s", "choke_time_s"} and isinstance(v, (int, float)):
                    out[k] = _remap_time(float(v))
                elif k == "per_cymbal" and isinstance(v, dict):
                    out[k] = {ck: _remap_win(cv) for ck, cv in v.items()}
                else:
                    out[k] = copy.deepcopy(v)
            return out
        return copy.deepcopy(w)

    sub_windows = {wk: _remap_win(wv) for wk, wv in sub_windows.items()}
    max_t = max(ev["time_s"] + ev["duration_s"] for ev in sub_events) + 1.2
    sub_total = float(math.ceil(max_t / 2.0) * 2.0)
    return sub_events, sub_windows, sub_total


def generate_midi_and_manifest(out_dir: Path | None = None, *, scope: str = "full") -> tuple[Path, Path]:
    resolved_dir = out_dir or default_test_suite_dir()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    events, windows, total_sec = build_test_events(scope=scope)

    mid = mido.MidiFile(ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage("track_name", name=f"SD3 Preset Forge Test ({scope})", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))

    raw_msgs: list[tuple[int, int, int, int]] = []
    for ev in events:
        on_tick = _sec_to_ticks(ev["time_s"])
        off_tick = _sec_to_ticks(ev["time_s"] + ev["duration_s"])
        raw_msgs.append((on_tick, 1, ev["note"], ev["velocity"]))
        raw_msgs.append((off_tick, 0, ev["note"], 0))

    raw_msgs.sort(key=lambda x: (x[0], x[1], x[2]))

    last_tick = 0
    for tick, is_on, note, vel in raw_msgs:
        delta = max(0, tick - last_tick)
        msg_type = "note_on" if is_on else "note_off"
        track.append(mido.Message(msg_type, channel=DRUM_CHANNEL, note=note, velocity=vel, time=delta))
        last_tick = tick

    end_tick = _sec_to_ticks(total_sec)
    track.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - last_tick)))

    if scope == "full":
        midi_path = resolved_dir / "standard-test-groove.mid"
        manifest_path = resolved_dir / "midi-manifest.json"
    else:
        midi_path = resolved_dir / f"probe-{scope}.mid"
        manifest_path = resolved_dir / f"probe-{scope}-manifest.json"

    mid.save(str(midi_path))
    manifest = {
        "schema_version": "2.0.0",
        "scope": scope,
        "bpm": BPM,
        "ppq": PPQ,
        "total_bars": int(round(total_sec / 2.0)),
        "total_seconds": total_sec,
        "midi_channel_1based": DRUM_CHANNEL + 1,
        "windows": windows,
        "event_count": len(events),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return midi_path, manifest_path
