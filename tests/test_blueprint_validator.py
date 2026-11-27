"""Tests for anti-hallucination and topology blueprint validator."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from sd3_forge.validate_blueprint import validate_blueprint


def _sample_valid_blueprint() -> dict:
    return {
        "metadata": {
            "preset_id": "test-kit",
            "genre": "nu-metal",
            "reference": "Test Reference",
        },
        "mix_mode": "internal_sd3",
        "preflight_audit": {
            "envelope_ahdsr_checked": True,
            "fx_bands_checked": True,
            "unused_slots_resolved": True,
            "part1_mics_only": True,
            "raw_baseline_planned": True,
        },
        "kit": {
            "base_kit": "Pearl Masterworks",
            "unload_slots": [
                "Tom2",
                "Tom3",
                "Tom4",
                "Tom5",
                "Cymbal1",
                "Cymbal2",
                "Cymbal3",
                "Cymbal4",
                "Cymbal5",
                "Cymbal6",
            ],
            "pieces": [
                {
                    "slot": "KickR",
                    "name": '18x22" Pearl Masterworks',
                    "pitch_semitones": 0.0,
                    "envelope": {"attack_ms": 0, "decay_ms": 350},
                },
                {
                    "slot": "Snare",
                    "name": '6.5x14" Tama Bell Brass',
                    "pitch_semitones": 1.5,
                    "envelope": {"attack_ms": 0, "decay_ms": 480},
                },
                {"slot": "Hats", "name": '15" Paiste 2002 Extra Heavy', "pitch_semitones": 0.0},
                {"slot": "Tom1", "name": '8x10" Pearl Masterworks', "pitch_semitones": 0.0},
            ],
        },
        "mics": [
            {"channel": "Kick In", "fader_db": 0.0, "inserts": [{"fx": "EQ", "params": {"HPF": "30 Hz"}}]},
            {"channel": "Snare Top", "fader_db": 0.0, "inserts": [{"fx": "Comp 76", "params": {"Ratio": "8:1", "Attack": "5"}}]},
            {"channel": "OH Dyn", "fader_db": -3.0, "inserts": []},
            {"channel": "Amb Ribbon", "fader_db": -6.0, "inserts": [{"fx": "Tape Simulator", "params": {"Drive": 3}}]},
        ],
        "bleed": {
            "channels": [
                {"channel": "Snare Bottom", "enabled": True, "level_db": -8.0, "sources": ["Kick"]},
                {"channel": "OH Dyn", "enabled": True, "level_db": 0.0, "sources": ["All"]},
            ]
        },
        "buses": [
            {
                "name": "Parallel Slam",
                "fader_db": -8.0,
                "route_to": "Output 1/2",
                "inserts": [{"fx": "Comp 76", "params": {"Ratio": "All"}}],
            }
        ],
        "master_bus": {
            "channel": "Output 1/2",
            "fader_db": 0.0,
            "inserts": [{"fx": "Comp 670", "params": {"Threshold": -12}}],
        },
    }


def _write_bp(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "bp.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


def test_valid_blueprint_passes(tmp_path: Path, mock_inventory_path: Path) -> None:
    res = validate_blueprint(_write_bp(tmp_path, _sample_valid_blueprint()), inventory_path=mock_inventory_path)
    assert res.ok, res.errors
    assert not res.warnings, res.warnings


def test_hallucinated_snare_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["kit"]["pieces"][1]["name"] = '6.5x14" DW Collector Brass'
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Snare" in e for e in res.errors)


def test_forbidden_part2_mic_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["mics"].append({"channel": "Amb Mid", "fader_db": -4.0, "inserts": []})
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("FORBIDDEN" in e and "Amb Mid" in e for e in res.errors)


def test_forbidden_bleed_channel_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["bleed"]["channels"].append({"channel": "Kick In", "enabled": True, "level_db": -6.0, "sources": ["Snare"]})
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Bleed enabled" in e and "Kick In" in e for e in res.errors)


def test_non_native_fx_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["master_bus"]["inserts"].append({"fx": "FabFilter Pro-Q 3", "params": {}})
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Non-native FX" in e and "FabFilter Pro-Q 3" in e for e in res.errors)


def test_bogus_transient_envelope_in_drums_tab_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["kit"]["pieces"][0]["envelope"] = {"attack": 12, "sustain": -15}
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("schema error" in e.lower() for e in res.errors)


def test_eq84_four_band_hallucination_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["mics"][1]["inserts"].append(
        {"fx": "EQ84", "params": {"LowMid": "225 Hz, +2 dB", "HighMid": "3.2 kHz, +3 dB"}}
    )
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("EQ84 topology error" in e for e in res.errors)


def test_orphan_base_kit_slot_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["kit"]["unload_slots"].remove("Tom3")
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Orphan base_kit slots" in e and "Tom3" in e for e in res.errors)


def test_transient_percent_unit_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["mics"][0]["inserts"].append({"fx": "Transient", "params": {"Attack": "+18%", "Sustain": "-10%"}})
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Transient UI unit error" in e for e in res.errors)


def test_transient_out_of_db_range_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["mics"][0]["inserts"].append({"fx": "Transient", "params": {"Attack": "+20.0 dB", "Sustain": "-30.0 dB"}})
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Transient range error" in e and "Attack" in e for e in res.errors)
    assert any("Transient range error" in e and "Sustain" in e for e in res.errors)


def test_bus_index_out_of_range_and_duplicate_fails(tmp_path: Path, mock_inventory_path: Path) -> None:
    bp = copy.deepcopy(_sample_valid_blueprint())
    bp["buses"] = [
        {"name": "Bus 33 (Too High)", "fader_db": 0.0, "inserts": []},
        {"name": "Bus 1 (A)", "fader_db": 0.0, "inserts": []},
        {"name": "Bus 1 (Dup)", "fader_db": -2.0, "inserts": []},
    ]
    res = validate_blueprint(_write_bp(tmp_path, bp), inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("Bus 33" in e or "range" in e.lower() for e in res.errors)
    assert any("duplicate" in e.lower() for e in res.errors)
