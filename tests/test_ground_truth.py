"""Tests for SD3 Ground Truth extractor against synthetic Core and SDX library fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from sd3_forge.extract_gt import (
    build_inventory,
    inspect_installed_obws,
    parse_installer_config,
    parse_instrumentgroups,
    parse_micconf,
    parse_padconf,
    parse_uberconf,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_inventory_extraction_and_privacy(mock_inventory_path: Path) -> None:
    inv = json.loads(mock_inventory_path.read_text(encoding="utf-8"))
    assert "source_path" not in inv
    assert inv["schema_version"] == "2.0.0"
    assert "Pearl Masterworks" in inv["base_kits"]
    assert len(inv["positions"]["KickR"]["pieces"]) >= 2
    snare_names = {p["name"] for p in inv["positions"]["Snare"]["pieces"]}
    assert '6.5x14" Tama Bell Brass' in snare_names
    assert '6.5x14" Ludwig Black Beauty' in snare_names
    assert inv["microphones"]["channel_map"]["Kick In"] == ["Kick-In"]
    assert inv["microphones"]["channel_map"]["OH Dyn"] == ["Oh-Beyer", "Oh-BeyerR"]
    assert "padconf" in inv
    assert "instrument_groups" in inv


def test_part1_mic_and_bleed_constraints(mock_inventory_path: Path) -> None:
    inv = json.loads(mock_inventory_path.read_text(encoding="utf-8"))
    avail = set(inv["microphones"]["available_channels"])
    forb = set(inv["microphones"]["forbidden_channels"])
    bleed = set(inv["microphones"]["available_bleed_channels"])

    assert len(avail) == 13
    assert len(forb) == 9
    assert avail.isdisjoint(forb)
    assert bleed == {"Snare Bottom", "OH Dyn", "Amb Ribbon"}
    assert "OH Cond" in forb
    assert "Amb Mid" in forb


def test_native_fx_and_stackpack(mock_inventory_path: Path) -> None:
    inv = json.loads(mock_inventory_path.read_text(encoding="utf-8"))
    assert len(inv["native_fx_names"]) == 35
    assert "Comp 76" in inv["native_fx_names"]
    assert "EQ84" in inv["native_fx_names"]
    assert "Tape Simulator" in inv["native_fx_names"]
    assert "Room Reverb" in inv["native_fx_names"]
    assert "Dimension T" in inv["native_fx_names"]
    assert "Fat Muff" in inv["native_fx_names"]
    assert len(inv["stack_pack"]) >= 5


def test_sdx_multi_library_and_macro_extraction() -> None:
    sdx_dir = FIXTURES_DIR / "mock_sdx_library"
    inv = build_inventory(sdx_dir)

    assert "source_path" not in inv
    assert inv["library"]["lib_id"] == "SL-SYNTH_ROCK_SDX"
    assert "Synth Rock Kit" in inv["base_kits"]
    # Macro-expanded pads inside uberconf Cymbal1
    cym1_pads = inv["positions"]["Cymbal1"]["pads"]
    assert any(p["id"] == "crash1CS" and p["label"] == "Crescendo" for p in cym1_pads)

    # Dynamic mics & paired stereo channels from micconf
    avail = set(inv["microphones"]["available_channels"])
    assert avail == {"Kick Sub", "Snare Top", "OH Wide", "Room A"}
    assert inv["microphones"]["forbidden_channels"] == []
    assert inv["microphones"]["channel_map"]["OH Wide"] == ["OH-Wide", "OH-WideR"]
    assert inv["microphones"]["channel_map"]["Room A"] == ["Room-A", "Room-AR"]
    assert set(inv["microphones"]["available_bleed_channels"]) == {"OH Wide", "Room A"}

    # Padconf & Instrumentgroups
    assert "SnareTop" in inv["padconf"]["defaultpad"]["usemic"]
    assert inv["instrument_groups"]["Shaker Pad"] == [2, 4]


def test_installer_config_pack_detection(tmp_path: Path) -> None:
    ic_text = """
    TEMPLATE OBW-File
      File {
        FileName "SL-TEST/Sounds/soundb$1.obw"
      }
    END
    Option {
      Name "Basic Setup - Sticks Only"
      USE OBW-File 1
      USE OBW-File 2
    }
    Option {
      Name "Stereo Room Setup"
      USE OBW-File 24
    }
    Option {
      Name "All tools, mics and bleed"
      USE OBW-File 114
    }
    """
    opts = parse_installer_config(ic_text)
    assert len(opts) == 3
    assert opts[1]["obw_numbers"] == [24]

    (tmp_path / "Sounds").mkdir()
    (tmp_path / "Sounds" / "soundb1.obw").write_bytes(b"")
    (tmp_path / "Sounds" / "soundb2.obw").write_bytes(b"")
    (tmp_path / "Sounds" / "soundb24.obw").write_bytes(b"")

    obw = inspect_installed_obws(tmp_path, installer_options=opts)
    assert "Basic Setup - Sticks Only" in obw["installed_packs"]
    assert "Stereo Room Setup" in obw["installed_packs"]
    assert "All tools, mics and bleed" in obw["missing_packs"]


def test_parse_padconf_micconf_instrumentgroups_helpers() -> None:
    mc = parse_micconf(
        """
        mic {
          name OH-L
          mixname "OH Pair"
          stereo
          bleedcontrol
        }
        mic {
          name OH-R
          stereo
        }
        mic {
          name dummy
          dummy
        }
        """
    )
    assert len(mc) == 1
    assert mc[0]["internal_name"] == "OH-L"
    assert mc[0]["right_internal_name"] == "OH-R"
    assert mc[0]["bleedcontrol"] is True

    pc = parse_padconf(
        """
        TEMPLATE DefBleed
          usemic OH-L OH-R
        END
        defaultpad {
          USE DefBleed
        }
        pad kickR {
          usemic Kick-In OH-L OH-R
        }
        """
    )
    assert pc["defaultpad"]["usemic"] == ["OH-L", "OH-R"]
    assert pc["pads"]["kickR"]["usemic"] == ["Kick-In", "OH-L", "OH-R"]

    ig = parse_instrumentgroups(
        """
        name "Kick Zone"
        {
          prio 1
          note 36
          note 35
        }
        """
    )
    assert ig == {"Kick Zone": [35, 36]}

    uc = parse_uberconf(
        """
        TEMPLATE StdCym
          close OH-L
          pads {
            crash$1 CR "Crash"
          }
        END
        positions {
          Cymbal1 9 {
            USE StdCym 1
            c1 CR "18^ Crash"
          }
        }
        drumsets {
          "Kit A" {
            Cymbal1 c1
          }
        }
        """
    )
    assert uc["positions"]["Cymbal1"]["close_mics"] == ["OH-L"]
    assert uc["positions"]["Cymbal1"]["pads"] == [{"id": "crash1", "code": "CR", "label": "Crash"}]
