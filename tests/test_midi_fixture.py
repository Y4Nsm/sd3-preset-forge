"""Tests for MIDI v2 test suite (`standard-test-groove.mid`, `midi-manifest.json`, and `--scope` probes)."""

from __future__ import annotations

import json
from pathlib import Path

import mido

from sd3_forge.generate_test_midi import VALID_SCOPES, generate_midi_and_manifest

MIDI_PATH = Path("test-suite/standard-test-groove.mid")
MANIFEST_PATH = Path("test-suite/midi-manifest.json")


def test_midi_and_manifest_exist() -> None:
    assert MIDI_PATH.exists()
    assert MANIFEST_PATH.exists()


def test_midi_v2_layout_velocities_chokes_and_cymbal_buffer(
    tmp_path: Path, mock_inventory_path: Path
) -> None:
    midi_p, man_p = generate_midi_and_manifest(tmp_path)
    mid = mido.MidiFile(str(midi_p))
    manifest = json.loads(man_p.read_text(encoding="utf-8"))
    inv = json.loads(mock_inventory_path.read_text(encoding="utf-8"))
    valid_notes = {row["note"] for row in inv["midi_keymap"]}

    assert manifest["schema_version"] == "2.0.0"
    assert manifest["bpm"] == 120
    assert abs(mid.length - 108.0) < 0.3

    win = manifest["windows"]
    for req_key in (
        "kick_isolated",
        "kick_velocity_ladder",
        "double_kick_burst",
        "snare_center_isolated",
        "snare_rimshot_isolated",
        "snare_velocity_ladder",
        "snare_flam_isolated",
        "racktom1_isolated",
        "racktom2_isolated",
        "racktom3_isolated",
        "floortom1_isolated",
        "floortom2_isolated",
        "hihat_isolated",
        "cymbals_isolated",
        "cymbal_choke",
        "bleed_stress",
        "groove_heavy",
        "groove_dynamic_fill",
        "groove_all",
        "tail_release",
    ):
        assert req_key in win, f"Missing MIDI v2 window: {req_key}"

    assert win["kick_velocity_ladder"]["velocities"] == [35, 65, 95, 125]
    assert win["snare_velocity_ladder"]["velocities"] == [35, 65, 95, 125]
    assert "per_cymbal" in win["cymbals_isolated"]
    assert set(win["cymbals_isolated"]["per_cymbal"].keys()) >= {"crash1", "crash2", "splash", "ride_bow", "ride_bell", "crash5"}

    # Mandatory >= 4.0 s buffer between last cymbal choke/hit and bleed_stress/groove
    last_cymbal_event = max(win["cymbals_isolated"]["hit_times_s"] + [win["cymbal_choke"]["choke_time_s"]])
    assert win["bleed_stress"]["start_s"] - last_cymbal_event >= 4.0

    played_notes = {
        msg.note
        for tr in mid.tracks
        for msg in tr
        if msg.type == "note_on" and msg.velocity > 0
    }
    assert {36, 38, 40, 69, 48, 47, 45, 43, 41, 42, 44, 46, 86, 49, 50, 55, 51, 53, 52}.issubset(played_notes)
    assert played_notes.issubset(valid_notes)


def test_scoped_midi_probes_shift_to_zero(tmp_path: Path) -> None:
    for scope in VALID_SCOPES:
        if scope == "full":
            continue
        midi_p, man_p = generate_midi_and_manifest(tmp_path, scope=scope)
        assert midi_p.name == f"probe-{scope}.mid"
        assert man_p.name == f"probe-{scope}-manifest.json"
        manifest = json.loads(man_p.read_text(encoding="utf-8"))
        assert manifest["scope"] == scope
        assert 0.5 < manifest["total_seconds"] < 40.0
        assert manifest["event_count"] > 0
