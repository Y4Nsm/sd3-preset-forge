"""Tests for the clean-room static 35-FX registry and `.sd3p` effect codec."""

from __future__ import annotations

import math
import re

import pytest

from sd3_forge.fx_catalog import (
    FX_BY_ID,
    FX_BY_NAME,
    encode_fx_params,
    list_native_fx_names,
    resolve_fx,
    validate_fx_params,
)
from sd3_forge.sd3p_codec import (
    NATIVE_FX_IDS,
    encode_effect_block,
    pan_str_to_stereo_pair,
)


def _parse_effect_block(block: str) -> tuple[int, dict[int, float], list[str]]:
    fx_id = int(re.search(r"(?m)^effect\s+(\d+)$", block).group(1))
    params = {int(k): float(v) for k, v in re.findall(r"(?m)^(\d+)\s+([-0-9.eE]+)$", block)}
    flags = [ln.strip() for ln in block.splitlines() if ln.strip() == "linked"]
    return fx_id, params, flags


def test_registry_covers_exact_35_fx_ids_10_to_44() -> None:
    assert set(FX_BY_ID.keys()) == set(range(10, 45))
    assert len(FX_BY_ID) == 35
    assert len(list_native_fx_names()) == 35
    for eid, spec in FX_BY_ID.items():
        assert spec.effect_id == eid
        assert spec.param_count >= 2
        assert spec.name in FX_BY_NAME
        assert spec.name in NATIVE_FX_IDS
        for p in spec.params:
            assert 0 <= p.index < spec.param_count


def test_every_one_of_35_fx_encodes_with_valid_indices_and_normalized_values() -> None:
    for eid, spec in FX_BY_ID.items():
        fx_id, values, _ = encode_fx_params(spec.name, {})
        assert fx_id == eid
        for idx, val in values.items():
            assert 0 <= idx < spec.param_count, f"{spec.name} emitted out-of-range key {idx}"
            assert 0.0 <= val <= 1.0, f"{spec.name} param {idx}={val} out of [0, 1]"

        block = encode_effect_block(0, spec.name, {}, active=True, sidechain="")
        parsed_id, parsed_vals, _ = _parse_effect_block(block)
        assert parsed_id == eid
        assert parsed_vals


def test_single_validation_compilation_contract_rejects_unknown_params() -> None:
    errs = validate_fx_params("Fat Muff", {"NonExistentKnob": 0.5})
    assert errs, "validate_fx_params must reject unknown parameter keys"
    with pytest.raises(ValueError, match="NonExistentKnob"):
        encode_fx_params("Fat Muff", {"NonExistentKnob": 0.5})

    # strict_v2 rejects GR inside params (must live in calibration_targets)
    v2_errs = validate_fx_params("Comp 76", {"Ratio": "4:1", "GR": "3-5 dB"}, strict_v2=True)
    assert any("calibration_targets" in e for e in v2_errs)


def test_fixed_indices_for_classic_comp_plate_hall_gate_and_10band_eq() -> None:
    # Classic Compressor (id=11): 0=Threshold, 1=Ratio, 2=Attack, 3=Release, 4=Makeup, 5=Mix, 6=Out Level, 7=SC HPF
    fx_id, vals, _ = encode_fx_params(
        "Classic Compressor",
        {"Threshold": "-18 dB", "Ratio": "4:1", "Attack": "10 ms", "Release": "100 ms", "Mix": "80%"},
    )
    assert fx_id == 11
    assert math.isclose(vals[0], (-18.0 + 60.0) / 60.0, abs_tol=1e-4)
    assert math.isclose(vals[1], (4.0 - 1.0) / 19.0, abs_tol=1e-4)
    assert math.isclose(vals[2], 0.1, abs_tol=1e-4)
    assert math.isclose(vals[3], 0.1, abs_tol=1e-4)
    assert math.isclose(vals[5], 0.8, abs_tol=1e-4)
    assert set(vals.keys()).issubset(set(range(8)))

    # Plate Reverb (id=20): Pre-Delay at index 7, Wet at 5, Size at 1 (<10)
    fx_id, vals, _ = encode_fx_params("Plate Reverb", {"Size": "60%", "PreDelay": "50 ms", "DryWet": "75%"})
    assert fx_id == 20
    assert math.isclose(vals[1], 0.6, abs_tol=1e-4)
    assert math.isclose(vals[5], 0.75, abs_tol=1e-4)
    assert math.isclose(vals[7], 0.1, abs_tol=1e-4)
    assert max(vals.keys()) < 10

    # Hall Reverb (id=22): Pre-Delay at 7, Wet at 5 (<10)
    fx_id, vals, _ = encode_fx_params("Hall Reverb", {"Size": "70%", "PreDelay": "25 ms", "DryWet": "90%"})
    assert fx_id == 22
    assert math.isclose(vals[1], 0.7, abs_tol=1e-4)
    assert math.isclose(vals[5], 0.9, abs_tol=1e-4)
    assert math.isclose(vals[7], 0.05, abs_tol=1e-4)
    assert max(vals.keys()) < 10

    # Frequency Gate (id=28): 0=Threshold, 1=Attack, 2=Hold, 3=Release, 4=ExpThresh, 6=LowCut, 7=HiCut
    fx_id, vals, _ = encode_fx_params(
        "Frequency Gate",
        {"Threshold": "-24 dB", "Attack": "5 ms", "Hold": "45 ms", "Release": "110 ms", "LowCut": "60 Hz", "SideChain_HPF": "450 Hz"},
    )
    assert fx_id == 28
    assert vals[0] != 0.5
    assert vals[1] < 0.86
    assert math.isclose(vals[2], 45.0 / 500.0, abs_tol=1e-4)
    assert math.isclose(vals[3], 0.234303, abs_tol=1e-4)
    assert vals[6] > 0.0
    assert math.isclose(vals[7], 0.283878, abs_tol=1e-4)

    # EQ (id=10) supports up to 10 bands + OutputLevel
    fx_id, vals, _ = encode_fx_params(
        "EQ",
        {
            "HPF": "30 Hz",
            "Cut_1": "200 Hz, -2 dB, Q 2",
            "Cut_2": "350 Hz, -3 dB, Q 3",
            "Cut_3": "500 Hz, -2 dB, Q 2",
            "Boost_1": "2.5 kHz, +3 dB, Q 1.5",
            "Boost_2": "5 kHz, +2 dB, Q 1.2",
            "HighShelf": "10 kHz, +2 dB",
            "OutputLevel": "+2 dB",
        },
    )
    assert fx_id == 10
    assert vals[6 * 13 + 0] == 1.0  # Band 7 (index 6) is HighShelf
    assert vals[7 * 13 + 12] == 0.75  # Band 8 unused
    assert vals[130] > 0.5


def test_newly_cataloged_fx_and_aliases() -> None:
    assert resolve_fx("Classic Echo").effect_id == 31
    assert resolve_fx("Compressor/Limiter").effect_id == 44

    # Dimension T buttons
    fx_id, vals, _ = encode_fx_params("Dimension T", {"Dimension1": "On", "Dimension3": True, "Dimension2": "Off"})
    assert fx_id == 38
    assert vals[0] == 1.0
    assert vals[1] == 0.0
    assert vals[2] == 1.0

    # Fat Muff
    fx_id, vals, _ = encode_fx_params("Fat Muff", {"Drive": "60%", "Tone": "40%", "Level": "75%"})
    assert fx_id == 43
    assert math.isclose(vals[0], 0.6)
    assert math.isclose(vals[1], 0.4)
    assert math.isclose(vals[2], 0.75)


def test_pan_str_to_stereo_pair_variants() -> None:
    assert pan_str_to_stereo_pair("L100/R100") == (0.0, 1.0)
    assert pan_str_to_stereo_pair("C") == (0.5, 0.5)
    l60, r60 = pan_str_to_stereo_pair("L60/R60")
    assert math.isclose(l60, 0.2, abs_tol=1e-4)
    assert math.isclose(r60, 0.8, abs_tol=1e-4)
    l80, r40 = pan_str_to_stereo_pair("L80/R40")
    assert math.isclose(l80, 0.1, abs_tol=1e-4)
    assert math.isclose(r40, 0.7, abs_tol=1e-4)
