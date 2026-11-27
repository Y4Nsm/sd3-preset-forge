"""TDD tests for the compact `sd3-forge inventory` query CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sd3_forge.cli import main


def test_inventory_summary_json(mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["inventory", "summary", "--inventory", str(mock_inventory_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "library" in data
    assert data["counts"]["base_kits"] >= 1
    assert data["counts"]["installed_mics"] >= 4
    assert data["counts"]["native_fx"] == 35
    assert data["counts"]["midi_notes"] >= 1


def test_inventory_kits_list_and_detail(mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc_list = main(["inventory", "kits", "--inventory", str(mock_inventory_path), "--json"])
    assert rc_list == 0
    list_data = json.loads(capsys.readouterr().out)
    assert "Pearl Masterworks" in list_data["base_kits"]

    rc_detail = main(
        ["inventory", "kits", "--kit", "Pearl Masterworks", "--inventory", str(mock_inventory_path), "--json"]
    )
    assert rc_detail == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["kit"]["name"] == "Pearl Masterworks"
    assert "KickR" in detail["kit"]["pieces"]


def test_inventory_pieces_filter_and_unknown_slot(
    mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "inventory",
            "pieces",
            "--slot",
            "Snare",
            "--search",
            "Bell Brass",
            "--inventory",
            str(mock_inventory_path),
            "--json",
        ]
    )
    assert rc == 0
    raw = capsys.readouterr().out
    assert len(raw) < 4096
    data = json.loads(raw)
    names = [p["name"] for p in data["pieces"]]
    assert any("Bell Brass" in n for n in names)

    rc_bad = main(
        ["inventory", "pieces", "--slot", "NonExistentSlot", "--inventory", str(mock_inventory_path)]
    )
    assert rc_bad == 1
    assert "ERROR:" in capsys.readouterr().err


def test_inventory_mics_and_bleed_filter(mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["inventory", "mics", "--bleed-only", "--inventory", str(mock_inventory_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] >= 1
    assert all(m["bleed_installed"] is True for m in data["mics"])


def test_inventory_fx_filter_and_spec_detail(mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc_list = main(
        ["inventory", "fx", "--category", "Dynamics", "--inventory", str(mock_inventory_path), "--json"]
    )
    assert rc_list == 0
    fx_data = json.loads(capsys.readouterr().out)
    assert any(item["name"] == "Comp 76" for item in fx_data["fx"])

    rc_spec = main(
        ["inventory", "fx", "--name", "Comp 76", "--inventory", str(mock_inventory_path), "--json"]
    )
    assert rc_spec == 0
    spec_data = json.loads(capsys.readouterr().out)
    assert spec_data["effect"]["effect_id"] == 40
    assert any(p["name"] == "Ratio" and "All" in p["allowed_values"] for p in spec_data["params"])


def test_inventory_stacks_and_keymap(mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc_st = main(["inventory", "stacks", "--inventory", str(mock_inventory_path), "--json"])
    assert rc_st == 0
    st_data = json.loads(capsys.readouterr().out)
    assert st_data["total_items"] >= 1

    rc_km = main(["inventory", "keymap", "--group", "Kick", "--inventory", str(mock_inventory_path), "--json"])
    assert rc_km == 0
    km_data = json.loads(capsys.readouterr().out)
    assert any(entry["note"] == 36 for entry in km_data["keymap"])
