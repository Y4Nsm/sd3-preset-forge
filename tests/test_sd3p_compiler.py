"""Unit and integration tests for SD3 `.sd3p` codec and blueprint compiler."""

from __future__ import annotations

import math
import re
import struct
from pathlib import Path

from sd3_forge.compile_sd3p import _find_named_block, compile_blueprint_to_sd3p
from sd3_forge.sd3p_codec import (
    db_to_linear,
    encode_effect_block,
    juce_b64_decode,
    juce_b64_encode,
    pan_str_to_norm,
    semitones_to_pitch,
    unwrap_vc2_state,
    wrap_vc2_state,
)


def _extract_block(txt: str, header_regex: str) -> str:
    span = _find_named_block(txt, header_regex)
    assert span is not None, f"Block not found for pattern: {header_regex}"
    s, _, e = span
    return txt[s : e + 1]


def _parse_effect_params(block: str) -> tuple[int, dict[int, float], list[str]]:
    fx_id = int(re.search(r"(?m)^effect\s+(\d+)$", block).group(1))
    params = {int(k): float(v) for k, v in re.findall(r"(?m)^(\d+)\s+([-0-9.eE]+)$", block)}
    flags = [ln.strip() for ln in block.splitlines() if ln.strip() == "linked"]
    return fx_id, params, flags


def test_juce_b64_roundtrip_all_mod_lengths() -> None:
    for size in (1, 2, 3, 17, 64, 1025):
        payload = bytes((i * 37 + 11) % 256 for i in range(size))
        enc = juce_b64_encode(payload)
        assert enc.startswith(f"{size}.")
        assert juce_b64_decode(enc) == payload


def test_vc2_wrap_unwrap_updates_sizes_and_preserves_trailer() -> None:
    prefix = bytearray(176)
    prefix[0:4] = b"VstW"
    prefix[16:20] = b"CcnK"
    prefix[24:28] = b"FBCh"
    trailer = b"\x00" * 8 + b"JUCEPrivateData\x00\x01"
    orig_inner = b"PlugVersion 3.4.4\n\x00" + trailer
    struct.pack_into(">I", prefix, 20, 152 + len(orig_inner))
    struct.pack_into(">I", prefix, 172, len(orig_inner))
    orig_blob = bytes(prefix) + orig_inner
    orig_xml = f'<?xml version="1.0"?><VST3PluginState><IComponent>{juce_b64_encode(orig_blob)}</IComponent></VST3PluginState>'
    raw_state = b"VC2!" + struct.pack("<I", len(orig_xml.encode())) + orig_xml.encode() + b"\x00"

    t_xml, t_blob = unwrap_vc2_state(raw_state)
    assert t_blob == orig_blob

    new_sd3p = b"PlugVersion 3.4.4\nSAMPLER {\n}\n"
    wrapped = wrap_vc2_state(t_xml, t_blob, new_sd3p)
    _, new_blob = unwrap_vc2_state(wrapped)

    ccnk_size = struct.unpack_from(">I", new_blob, 20)[0]
    chunk_size = struct.unpack_from(">I", new_blob, 172)[0]
    expected_inner = new_sd3p + b"\x00" + trailer
    assert chunk_size == len(expected_inner)
    assert ccnk_size == 152 + len(expected_inner)
    assert new_blob[176:] == expected_inner


def test_unit_conversions_match_sd3_values() -> None:
    assert math.isclose(db_to_linear(2.5), 1.33352, rel_tol=1e-4)
    assert math.isclose(db_to_linear(-8.0), 0.398107, rel_tol=1e-4)
    assert math.isclose(semitones_to_pitch(2.7), 1.16878, rel_tol=1e-4)
    assert math.isclose(semitones_to_pitch(-1.5), 0.917004, rel_tol=1e-4)
    assert math.isclose(pan_str_to_norm("C"), 0.5)
    assert math.isclose(pan_str_to_norm("L35"), 0.325)
    assert math.isclose(pan_str_to_norm("R58"), 0.79)


def test_fx_encoders_match_calibrated_deftones_settings() -> None:
    # Transient (id=15)
    fx_id, p, _ = _parse_effect_params(
        encode_effect_block(0, "Transient", {"Attack": "+6.0 dB", "Sustain": "+2.5 dB"})
    )
    assert fx_id == 15
    assert math.isclose(p[0], 0.7, abs_tol=1e-4)
    assert math.isclose(p[1], 0.552083, abs_tol=1e-4)

    # EQ84 (id=42) on Snare Top
    fx_id, p, _ = _parse_effect_params(
        encode_effect_block(
            0,
            "EQ84",
            {
                "HPF": "90 Hz",
                "Low": "225 Hz, +2.0 dB",
                "Mid": "3.2 kHz, +3.0 dB (Hi-Q Off)",
                "High": "10 kHz, +1.5 dB",
            },
        )
    )
    assert fx_id == 42
    assert math.isclose(p[2], 0.55, abs_tol=1e-4)
    assert math.isclose(p[4], 0.5, abs_tol=1e-4)
    assert math.isclose(p[5], 0.6, abs_tol=1e-4)
    assert p[6] == 0.0
    assert p[8] == 1.0
    assert math.isclose(p[9], 0.566667, abs_tol=1e-4)
    assert math.isclose(p[11], 0.5, abs_tol=1e-4)
    assert p[12] == 0.0
    assert p[14] == 1.0

    # Comp 76 (id=40)
    fx_id, p, _ = _parse_effect_params(
        encode_effect_block(1, "Comp 76", {"Ratio": "4:1", "Attack": "5", "Release": "2", "GR": "3-5 dB"})
    )
    assert fx_id == 40
    assert math.isclose(p[2], 0.666667, abs_tol=1e-4)
    assert math.isclose(p[3], 0.166667, abs_tol=1e-4)
    assert p[4] == 0.0

    # EQ (id=10)
    fx_id, p, _ = _parse_effect_params(
        encode_effect_block(
            0,
            "EQ",
            {"HPF": "28 Hz", "Cut_1": "350 Hz, -3.5 dB, Q 2.0", "HighShelf": "7.5 kHz, +12.0 dB"},
        )
    )
    assert fx_id == 10
    assert p[0] == 0.0  # HPF
    assert math.isclose(p[2], math.log10(28.0 / 20.0) / 3.0, abs_tol=1e-4)
    assert math.isclose(p[13], 0.444444, abs_tol=1e-4)  # Bell
    assert math.isclose(p[14], (-3.5 + 18.0) / 36.0, abs_tol=1e-4)
    assert math.isclose(p[16], 0.5 + 0.5 * math.log10(2.0), abs_tol=1e-4)
    assert p[26] == 1.0  # HighShelf
    assert math.isclose(p[27], (12.0 + 18.0) / 36.0, abs_tol=1e-4)
    assert p[130] == 0.5

    # Comp 670 (id=41) has linked flag
    fx_id, _, flags = _parse_effect_params(
        encode_effect_block(1, "Comp 670", {"Threshold": "Suave (1.5 dB GR)", "TimeConstant": "Fast/Auto"})
    )
    assert fx_id == 41
    assert "linked" in flags


def test_compile_deftones_blueprint_to_sd3p(
    tmp_path: Path,
    mock_inventory_path: Path,
    synthetic_base_sd3p_path: Path,
) -> None:
    out_sd3p = tmp_path / "deftones-test.sd3p"
    compile_blueprint_to_sd3p(
        Path("presets/nu-metal/deftones-around-the-fur"),
        out_path=out_sd3p,
        template_path=synthetic_base_sd3p_path,
        inventory_path=mock_inventory_path,
    )

    raw = out_sd3p.read_bytes()
    assert raw.endswith(b"\x00")
    assert not raw.endswith(b"\x00\x00")

    txt = raw[:-1].decode("utf-8")
    assert 'drum "Kick73"  "Felt" 1' in txt
    assert 'drum "Snare13"  "Drumsticks" 1' in txt
    assert 'drum -  "Drumsticks" 1' in txt  # Unloaded Tom3
    assert "pitch 1.16878" in txt
    assert "effect 42" in txt
    assert "effect 21" in txt
    assert "effect 29" in txt
    assert "linked" in txt


def test_compile_v2_lossless_features(
    tmp_path: Path,
    mock_inventory_path: Path,
    synthetic_base_sd3p_path: Path,
) -> None:
    import yaml

    preset_dir = tmp_path / "v2-preset"
    preset_dir.mkdir()
    (preset_dir / "02-spec-targets.yaml").write_text(
        Path("presets/nu-metal/deftones-around-the-fur/02-spec-targets.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    v2_bp = {
        "schema_version": "2.0",
        "metadata": {"preset_id": "v2-test", "genre": "grunge", "reference": "V2 Test"},
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
            "unload_slots": ["Tom2", "Tom3", "Tom4", "Tom5", "Cymbal2", "Cymbal3", "Cymbal4", "Cymbal5", "Cymbal6"],
            "pieces": [
                {
                    "slot": "KickR",
                    "name": '18x22" Pearl Masterworks',
                    "pitch_semitones": 0.0,
                    "level_db": 2.0,
                    "envelope": {"attack_ms": 0, "hold_ms": 15, "decay_ms": 480, "sustain_db": -6.0, "release_ms": 260},
                },
                {
                    "slot": "Snare",
                    "name": '6.5x14" Tama Bell Brass',
                    "pitch_semitones": 1.0,
                    "envelope": {"attack_ms": 0, "decay_ms": 400, "release_ms": 200},
                    "stacks": [
                        {
                            "category": "Snares",
                            "name": "Synthetic Clap Stack",
                            "library_id": "SP-SUPERIOR_DRUMMER_3",
                            "level_db": -6.0,
                            "pitch_semitones": 2.0,
                        }
                    ],
                },
                {"slot": "Hats", "name": '15" Paiste 2002 Extra Heavy', "pitch_semitones": 0.0},
                {"slot": "Tom1", "name": '8x10" Pearl Masterworks', "pitch_semitones": 0.0},
                {"slot": "Cymbal1", "name": '17" Paiste 2002 Medium Crash', "pitch_semitones": 0.0},
            ],
        },
        "mics": [
            {
                "channel": "Kick In",
                "fader_db": 0.0,
                "sends": [{"bus": "Bus 6 (Verb Bus)", "level_db": -6.0, "pre_fader": True}],
                "inserts": [{"fx": "Classic Compressor", "params": {"Threshold": "-18 dB", "Ratio": "4:1", "Mix": "80%"}}],
            },
            {
                "channel": "Snare Top",
                "fader_db": 0.0,
                "inserts": [{"fx": "Fat Muff", "params": {"Drive": "60%", "Tone": "40%", "Level": "75%"}}],
            },
            {"channel": "OH Dyn", "fader_db": -3.0, "pan": "L60/R60", "inserts": [{"fx": "Dimension T", "params": {"Dimension1": "On"}}]},
            {"channel": "Amb Ribbon", "fader_db": -5.0, "pan": "L80/R40", "inserts": [{"fx": "Chorus", "params": {"Rate": "20%", "Depth": "40%", "Mix": "50%"}}]},
        ],
        "bleed": {
            "channels": [
                {"channel": "Snare Bottom", "enabled": True, "level_db": -8.0, "sources": ["Kick", "Toms"], "source_levels_db": {"Kick": -6.0}},
                {"channel": "OH Dyn", "enabled": True, "level_db": 0.0, "sources": ["All"]},
            ]
        },
        "buses": [
            {
                "name": "Bus 6 (Verb Bus)",
                "fader_db": -4.0,
                "pan": "L70/R70",
                "route_to": "Output 1/2",
                "inserts": [{"fx": "Plate Reverb", "params": {"Size": "60%", "PreDelay": "20 ms", "DryWet": "100%"}}],
            }
        ],
        "master_bus": {
            "channel": "Output 1/2",
            "fader_db": 0.0,
            "inserts": [{"fx": "Compressor / Limiter", "params": {"Threshold": "-2 dB"}}],
        },
    }
    (preset_dir / "03-sd3-blueprint.yaml").write_text(yaml.safe_dump(v2_bp, sort_keys=False), encoding="utf-8")

    # Append sentinel untouched block to template to verify lossless preservation
    tpl_text = synthetic_base_sd3p_path.read_bytes()[:-1].decode("utf-8")
    tpl_with_sentinel = tpl_text + '\nSongTrack 0\nBoxStatePreset {\n  custom_marker "KEEP_ME"\n}\n'
    sentinel_tpl = tmp_path / "sentinel-base.sd3p"
    sentinel_tpl.write_bytes(tpl_with_sentinel.encode("utf-8") + b"\x00")

    out_sd3p = tmp_path / "v2-compiled.sd3p"
    compile_blueprint_to_sd3p(
        preset_dir,
        out_path=out_sd3p,
        template_path=sentinel_tpl,
        inventory_path=mock_inventory_path,
    )
    txt = out_sd3p.read_bytes()[:-1].decode("utf-8")

    # 1. Envelope even when attack_ms == 0
    assert "fadeonset 0.015" in txt
    assert "decay 0.48" in txt
    assert "sustain 0.501187" in txt
    assert "fadetime 0.26" in txt

    # 2. Per-source bleed: Kick has SnareBottom & leakvolume, Cymbal1 excludes SnareBottom
    kick_ib = re.search(r"instbox 0 \{.*?\nInstrumentType", txt, re.S).group(0)
    cym1_ib = re.search(r'pos "Cymbal1".*?\nInstrumentType', txt, re.S).group(0)
    assert "SnareBottom" in kick_ib
    assert 'leakvolume "SnareBottom" 0.501187' in kick_ib
    assert "SnareBottom" not in cym1_ib

    # 3. Stacks compiled into xpad 1 while preserving xpad 0
    snare_ib = re.search(r'instbox 1 \{.*?\nInstrumentType', txt, re.S).group(0)
    assert "xpad 0 SL-SUPERIOR_DRUMMER_3" in snare_ib
    assert "xpad 1 SP-SUPERIOR_DRUMMER_3" in snare_ib
    assert 'drum "st_s1"' in snare_ib

    # 4. Stereo pan & pre-fader send & Bus 6 + reset of omitted mics and unused buses (0..63)
    oh_l = _extract_block(txt, r"^Oh-Beyer\s*\{")
    oh_r = _extract_block(txt, r"^Oh-BeyerR\s*\{")
    assert "pan 0.2" in oh_l
    assert "pan 0.8" in oh_r

    kick_in = _extract_block(txt, r"^Kick-In\s*\{")
    assert "send 5 {\nactive 1\n" in kick_in
    assert "\npre\n" in kick_in

    # Omitted mic Kick-Out zeroed cleanly
    kick_out = _extract_block(txt, r"^Kick-Out\s*\{")
    assert "volume 0\n" in kick_out

    # Unused Bus 12 (buss 22) reset cleanly
    buss_22 = _extract_block(txt, r"^buss 22\s*\{")
    assert "route output -1" in buss_22
    assert "hidden" in buss_22

    # Newly added FX IDs present
    assert "effect 11" in txt  # Classic Compressor
    assert "effect 43" in txt  # Fat Muff
    assert "effect 38" in txt  # Dimension T
    assert "effect 35" in txt  # Chorus
    assert "effect 20" in txt  # Plate Reverb

    # Lossless tail preserved
    assert 'custom_marker "KEEP_ME"' in txt
