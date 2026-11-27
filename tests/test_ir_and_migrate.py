"""Tests for Pydantic v2 Typed IR, v1->v2 migration, and strict validator v2 checks."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from sd3_forge.migrate import migrate_blueprint_file, migrate_v1_dict_to_v2
from sd3_forge.models import BlueprintV2, load_blueprint_ir
from sd3_forge.validate_blueprint import validate_blueprint


def _sample_v2_blueprint() -> dict:
    return {
        "schema_version": "2.0",
        "metadata": {
            "preset_id": "test-v2-kit",
            "genre": "grunge",
            "reference": "Test V2 Reference",
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
            "unload_slots": ["Tom2", "Tom3", "Tom4", "Tom5", "Cymbal1", "Cymbal2", "Cymbal3", "Cymbal4", "Cymbal5", "Cymbal6"],
            "pieces": [
                {
                    "slot": "KickR",
                    "name": '18x22" Pearl Masterworks',
                    "pitch_semitones": 0.0,
                    "level_db": 0.0,
                    "envelope": {"attack_ms": 0, "hold_ms": 10, "decay_ms": 350, "sustain_db": -3.0, "release_ms": 200},
                },
                {
                    "slot": "Snare",
                    "name": '6.5x14" Tama Bell Brass',
                    "pitch_semitones": 1.5,
                    "stacks": [{"category": "Snares", "name": "Synthetic Clap Stack", "library_id": "SP-SUPERIOR_DRUMMER_3", "level_db": -6.0, "pitch_semitones": 0.0}],
                },
                {"slot": "Hats", "name": '15" Paiste 2002 Extra Heavy', "pitch_semitones": 0.0},
                {"slot": "Tom1", "name": '8x10" Pearl Masterworks', "pitch_semitones": 0.0},
            ],
        },
        "mics": [
            {
                "channel": "Kick In",
                "fader_db": 0.0,
                "sends": [{"bus": "Bus 1 (Room Bus)", "level_db": -10.0, "pre_fader": True}],
                "inserts": [{"fx": "EQ", "params": {"HPF": "35 Hz"}}],
            },
            {
                "channel": "Snare Top",
                "fader_db": 0.0,
                "inserts": [
                    {
                        "fx": "Comp 76",
                        "params": {"Ratio": "4:1", "Attack": "5", "Release": "2", "Input": "0.9"},
                        "calibration_targets": {"target_gr_db": [3.0, 5.0]},
                    }
                ],
            },
            {"channel": "OH Dyn", "fader_db": -3.0, "pan": "L60/R60", "inserts": []},
            {"channel": "Amb Ribbon", "fader_db": -6.0, "pan": "L100/R100", "inserts": []},
        ],
        "bleed": {
            "channels": [
                {"channel": "Snare Bottom", "enabled": True, "level_db": -8.0, "sources": ["Kick", "Toms"], "source_levels_db": {"Kick": -6.0}},
                {"channel": "OH Dyn", "enabled": True, "level_db": 0.0, "sources": ["All"]},
            ]
        },
        "buses": [
            {
                "name": "Bus 1 (Room Bus)",
                "fader_db": -4.0,
                "route_to": "Output 1/2",
                "inserts": [{"fx": "Plate Reverb", "params": {"Size": "60%", "PreDelay": "20 ms", "DryWet": "100%"}}],
            }
        ],
        "master_bus": {
            "channel": "Output 1/2",
            "fader_db": 0.0,
            "inserts": [
                {
                    "fx": "Comp 670",
                    "params": {"Threshold": 0.125, "TimeConstant": "Fast"},
                    "calibration_targets": {"target_gr_db": 1.5},
                }
            ],
        },
    }


def test_v2_ir_rejects_extra_keys_and_gr_in_params(tmp_path: Path, mock_inventory_path: Path) -> None:
    v2 = _sample_v2_blueprint()
    ir = BlueprintV2.model_validate(v2)
    assert ir.schema_version == "2.0"

    bad = copy.deepcopy(v2)
    bad["unknown_top_field"] = 123
    with pytest.raises(ValidationError):
        BlueprintV2.model_validate(bad)

    bad_gr = copy.deepcopy(v2)
    bad_gr["mics"][1]["inserts"][0]["params"]["GR"] = "3-5 dB"
    p = tmp_path / "bad_gr.yaml"
    p.write_text(yaml.safe_dump(bad_gr, sort_keys=False), encoding="utf-8")
    res = validate_blueprint(p, inventory_path=mock_inventory_path)
    assert not res.ok
    assert any("calibration_targets" in e for e in res.errors)


def test_v1_to_v2_migration_from_v1_fixture_and_deftones_preset(
    tmp_path: Path, mock_inventory_path: Path
) -> None:
    # 1. Legacy v1 fixture with GR + prose knob commentary migrates cleanly to strict v2
    v1_raw = copy.deepcopy(_sample_v2_blueprint())
    del v1_raw["schema_version"]
    v1_raw["mics"][1]["inserts"] = [
        {"fx": "Comp 76", "params": {"Ratio": "4:1", "Attack": "5 (médio-lento)", "Release": "2 (rápido)", "GR": "3-5 dB"}}
    ]
    v1_raw["master_bus"]["inserts"] = [
        {"fx": "Comp 670", "params": {"Threshold": "Suave (1.5 dB GR)", "TimeConstant": "Fast/Auto"}}
    ]

    ir_from_v1, warnings, is_v2 = load_blueprint_ir(v1_raw)
    assert is_v2 is False
    assert ir_from_v1.schema_version == "2.0"
    assert any("migrate" in w.lower() or "schema_version" in w.lower() for w in warnings)

    v2_dict = migrate_v1_dict_to_v2(v1_raw)
    assert v2_dict["schema_version"] == "2.0"
    assert "GR" not in v2_dict["mics"][1]["inserts"][0]["params"]
    assert v2_dict["mics"][1]["inserts"][0]["calibration_targets"]["target_gr_db"] == [3.0, 5.0]
    BlueprintV2.model_validate(v2_dict)

    v1_path = tmp_path / "legacy_v1.yaml"
    v1_path.write_text(yaml.safe_dump(v1_raw, sort_keys=False), encoding="utf-8")
    out_yaml = tmp_path / "migrated_v2.yaml"
    migrate_blueprint_file(v1_path, out_path=out_yaml)
    res = validate_blueprint(out_yaml, inventory_path=mock_inventory_path)
    assert res.ok, res.errors
    assert not any("migrate" in w.lower() for w in res.warnings)

    # 2. The committed deftones-around-the-fur blueprint is already strict schema_version '2.0'
    deftones_bp = Path("presets/nu-metal/deftones-around-the-fur/03-sd3-blueprint.yaml")
    res_deftones = validate_blueprint(deftones_bp, inventory_path=mock_inventory_path)
    assert res_deftones.ok, res_deftones.errors
    assert not any("migrate" in w.lower() for w in res_deftones.warnings)


def test_validator_catches_bus_cycles_bad_bleed_sources_and_unknown_fx_param(
    tmp_path: Path, mock_inventory_path: Path
) -> None:
    # Bus cycle: Bus 1 -> Bus 2 -> Bus 1
    cyc = copy.deepcopy(_sample_v2_blueprint())
    cyc["buses"] = [
        {"name": "Bus 1 (A)", "fader_db": 0.0, "route_to": "Bus 2 (B)", "inserts": []},
        {"name": "Bus 2 (B)", "fader_db": 0.0, "route_to": "Bus 1 (A)", "inserts": []},
    ]
    p_cyc = tmp_path / "cyc.yaml"
    p_cyc.write_text(yaml.safe_dump(cyc, sort_keys=False), encoding="utf-8")
    res_cyc = validate_blueprint(p_cyc, inventory_path=mock_inventory_path)
    assert not res_cyc.ok
    assert any("cycle" in e.lower() for e in res_cyc.errors)

    # Unknown bleed source
    bleed_bad = copy.deepcopy(_sample_v2_blueprint())
    bleed_bad["bleed"]["channels"][0]["sources"] = ["Cowbell"]
    p_bleed = tmp_path / "bleed.yaml"
    p_bleed.write_text(yaml.safe_dump(bleed_bad, sort_keys=False), encoding="utf-8")
    res_bleed = validate_blueprint(p_bleed, inventory_path=mock_inventory_path)
    assert not res_bleed.ok
    assert any("Cowbell" in e for e in res_bleed.errors)

    # Unknown FX param rejected by validator (single contract)
    fx_bad = copy.deepcopy(_sample_v2_blueprint())
    fx_bad["mics"][1]["inserts"][0]["params"]["FooKnob"] = "5"
    p_fx = tmp_path / "fx.yaml"
    p_fx.write_text(yaml.safe_dump(fx_bad, sort_keys=False), encoding="utf-8")
    res_fx = validate_blueprint(p_fx, inventory_path=mock_inventory_path)
    assert not res_fx.ok
    assert any("FooKnob" in e for e in res_fx.errors)


def test_cli_migrate_json_roundtrip(tmp_path: Path, mock_inventory_path: Path) -> None:
    out_path = tmp_path / "migrated.yaml"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sd3_forge.cli",
            "migrate",
            "presets/nu-metal/deftones-around-the-fur",
            "--out",
            str(out_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert Path(payload["out_path"]).exists()
    res = validate_blueprint(out_path, inventory_path=mock_inventory_path)
    assert res.ok, res.errors
