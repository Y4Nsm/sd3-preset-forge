"""Tests for packaging, lazy imports, cross-platform paths, and config-first `init`."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from sd3_forge.init_workspace import normalize_sd3p_to_neutral, run_init
from sd3_forge.paths import (
    detect_sd3_vst3_path,
    detect_user_presets_dir,
    load_package_json,
    load_package_text,
)


def test_package_resources_load_from_any_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    bp_schema = load_package_json("schemas/blueprint.schema.json")
    spec_schema = load_package_json("schemas/spec-targets.schema.json")
    cal_yaml = load_package_text("data/fx-ui-calibration.yaml")
    assert bp_schema["title"] == "SD3 Preset Forge Blueprint Schema"
    assert spec_schema["title"] == "SD3 Preset Forge Spec Targets Contract"
    assert "Transient" in cal_yaml


def test_cli_and_validator_work_without_pedalboard(
    tmp_path: Path, mock_inventory_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pedalboard", None)
    import sd3_forge.cli as cli_mod
    import sd3_forge.render_sd3 as render_mod

    importlib.reload(render_mod)
    importlib.reload(cli_mod)

    rc = cli_mod.main(
        ["validate", "presets/nu-metal/deftones-around-the-fur", "--inventory", str(mock_inventory_path)]
    )
    assert rc == 0

    dummy_sd3p = tmp_path / "x.sd3p"
    dummy_sd3p.write_bytes(b"PlugVersion 3.4.4\n\x00")
    with pytest.raises(RuntimeError, match="sd3-preset-forge\\[render\\]"):
        render_mod.render_sd3p_to_wav(dummy_sd3p, tmp_path / "out.wav", midi_path=Path("test-suite/standard-test-groove.mid"))


def test_cross_platform_path_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SD3_VST3_PATH", raising=False)
    monkeypatch.delenv("SD3_PRESETS_DIR", raising=False)
    monkeypatch.setenv("SD3_FORGE_HOME", str(tmp_path))

    vst_mac = detect_sd3_vst3_path(platform="darwin")
    assert vst_mac is not None
    assert "Library/Audio/Plug-Ins/VST3/Superior Drummer 3.vst3" in vst_mac.as_posix()

    vst_win = detect_sd3_vst3_path(platform="win32")
    assert vst_win is not None
    assert "Superior Drummer 3.vst3" in vst_win.name

    monkeypatch.setenv("SD3_PRESETS_DIR", str(tmp_path / "CustomPresets"))
    assert detect_user_presets_dir() == tmp_path / "CustomPresets"


def test_normalize_sd3p_strips_contaminated_state() -> None:
    dirty = """PlugVersion 3.4.4
BouncePrefix "v0-raw"
SAMPLER {
HQ {
soundlib "SL-SUPERIOR_DRUMMER_3"
}
instbox 0 {
xpad 0 SL-SUPERIOR_DRUMMER_3 {
pos "KickR"
drum "Kick73"  "Felt" 1
pads {
pad kickR {
usemic "Kick-In"
pitch 1.16878
fade 1
decay 0.5
fadetime 0.26
}
}
}
}
mixer {
Kick-In {
pan 0.5
volume 1.33352
phasereverse 1
effect 0 {
sidechain ""
effect 10
active 1
0 0.5
}
nobleed 0
leakvol 0.5
solo 1
mute 1
route buss 0
send 20 {
active 1
pan 0.5
volume 0.5
post fader
}
}
buss 10 {
pan 0
volume 0.5
phasereverse 0
solo 0
mute 0
route output 0
}
}
}
SongTrack 0 {
FileName "C:\\leak\\secret.mid"
}
"""
    clean = normalize_sd3p_to_neutral(dirty)
    assert 'drum -  "Drumsticks" 1' in clean
    assert "pitch " not in clean
    assert "fadetime " not in clean
    assert "effect 0" not in clean
    assert "send 20" not in clean
    assert "volume 1.33352" not in clean
    assert "C:\\leak\\secret.mid" not in clean
    assert 'BouncePrefix ""' in clean
    assert "route output 0" in clean


def test_run_init_config_first_e2e(tmp_path: Path, mock_library_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SD3_FORGE_HOME", str(tmp_path / "forge_home"))
    res = run_init(sd3_path=mock_library_dir, from_vst3=False, generate_midi_files=True)
    assert res["ok"] is True
    assert res["base_template_source"] == "config"

    inv_path = Path(res["inventory_path"])
    tpl_path = Path(res["base_template_path"])
    cfg_path = Path(res["config_path"])
    assert inv_path.exists()
    assert tpl_path.exists()
    assert cfg_path.exists()
    assert Path(res["midi_path"]).exists()
    assert Path(res["manifest_path"]).exists()

    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    assert "source_path" not in inv
    raw_tpl = tpl_path.read_bytes()
    assert raw_tpl.endswith(b"\x00")
    assert not raw_tpl.endswith(b"\x00\x00")
    txt_tpl = raw_tpl[:-1].decode("utf-8")
    assert 'drum -  "Drumsticks" 1' in txt_tpl
    assert "effect " not in txt_tpl


def test_new_preset_works_outside_repo_root(
    tmp_path: Path, mock_inventory_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sd3_forge.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["new-preset", "rock", "pkg-smoke"]) == 0

    spec_p = tmp_path / "presets" / "rock" / "pkg-smoke" / "02-spec-targets.yaml"
    bp_p = tmp_path / "presets" / "rock" / "pkg-smoke" / "03-sd3-blueprint.yaml"
    assert spec_p.exists()
    assert bp_p.exists()
    assert 'schema_version: "2.0"' in spec_p.read_text(encoding="utf-8")
    assert 'schema_version: "2.0"' in bp_p.read_text(encoding="utf-8")
    assert main(["validate", str(spec_p.parent), "--inventory", str(mock_inventory_path)]) == 0
