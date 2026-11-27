"""Clean-room static registry and encoder for all 35 native SD3 mixer effects (effect 10..44)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def canonical_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def parse_hz(val: Any) -> float:
    s = str(val).strip().lower()
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(khz|hz)?", s)
    if not m:
        raise ValueError(f"Cannot parse Hz from {val!r}")
    num = float(m.group(1))
    if m.group(2) == "khz":
        num *= 1000.0
    return num


def parse_first_float(val: Any) -> float:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(val))
    if not m:
        raise ValueError(f"Cannot parse number from {val!r}")
    return float(m.group(0))


def parse_ms(val: Any) -> float:
    s = str(val).strip().lower()
    num = parse_first_float(s)
    if re.search(r"\b\d+(?:\.\d+)?\s*s\b", s) and "ms" not in s:
        return num * 1000.0
    return num


def parse_sec(val: Any) -> float:
    s = str(val).strip().lower()
    num = parse_first_float(s)
    if "ms" in s:
        return num / 1000.0
    return num


def parse_pct(val: Any) -> float:
    num = parse_first_float(val)
    if "%" in str(val) or num > 1.0:
        return clamp01(num / 100.0)
    return clamp01(num)


def parse_band_spec(val: Any) -> tuple[float, float, float]:
    """Parse '350 Hz, -5.5 dB, Q 3.5' (Q optional -> 1.0) into `(hz, db, q)`."""
    s = str(val)
    parts = [p.strip() for p in s.split(",")]
    hz = parse_hz(parts[0])
    db = parse_first_float(parts[1]) if len(parts) > 1 else 0.0
    q = 1.0
    for p in parts[2:]:
        qm = re.search(r"q\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)", p, re.I)
        if qm:
            q = float(qm.group(1))
        else:
            q = parse_first_float(p)
    return hz, db, q


def interp_table(x: float, pts: list[tuple[float, float]]) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return pts[-1][1]


def parse_bool_norm(val: Any, *, invert: bool = False) -> float:
    if isinstance(val, bool):
        on = val
    elif isinstance(val, (int, float)):
        on = float(val) >= 0.5
    else:
        s = str(val).strip().lower()
        if s in {"on", "true", "yes", "1", "enabled", "bypassed"}:
            on = True
        elif s in {"off", "false", "no", "0", "disabled", "in"}:
            on = False
        else:
            on = parse_first_float(s) >= 0.5
    if invert:
        return 0.0 if on else 1.0
    return 1.0 if on else 0.0


@dataclass(frozen=True)
class FxParamSpec:
    """Static definition of a single `.sd3p` parameter slot inside an effect block."""

    index: int
    name: str
    unit: str = "%"
    min_val: float = 0.0
    max_val: float = 100.0
    default_norm: float = 0.0
    curve: str = "linear"  # linear | log | bool | inverted_bool | choice | db_signed | ratio_num
    aliases: tuple[str, ...] = ()
    choices: tuple[tuple[str, float], ...] = ()
    allowed_values: tuple[str, ...] = ()
    forbidden_units: tuple[str, ...] = ()
    enforce_unit: bool = False


@dataclass(frozen=True)
class FxSpec:
    """Static metadata + parameter table for one native SD3 mixer FX."""

    effect_id: int
    name: str
    category: str
    model_inspiration: str
    param_count: int
    params: tuple[FxParamSpec, ...]
    aliases: tuple[str, ...] = ()
    forbidden_keys: tuple[str, ...] = ()
    extra_param_keys: tuple[str, ...] = ()
    default_flags: tuple[str, ...] = ()
    controls_summary: tuple[str, ...] = ()


def _p(
    idx: int,
    name: str,
    unit: str = "%",
    min_v: float = 0.0,
    max_v: float = 100.0,
    default: float = 0.5,
    *,
    curve: str = "linear",
    aliases: tuple[str, ...] = (),
    choices: tuple[tuple[str, float], ...] = (),
    allowed_values: tuple[str, ...] = (),
    forbidden_units: tuple[str, ...] = (),
    enforce_unit: bool = False,
) -> FxParamSpec:
    return FxParamSpec(
        index=idx,
        name=name,
        unit=unit,
        min_val=min_v,
        max_val=max_v,
        default_norm=default,
        curve=curve,
        aliases=aliases,
        choices=choices,
        allowed_values=allowed_values,
        forbidden_units=forbidden_units,
        enforce_unit=enforce_unit,
    )


def _build_eq_params() -> tuple[FxParamSpec, ...]:
    items: list[FxParamSpec] = []
    for b in range(10):
        base = b * 13
        n = b + 1
        items.extend(
            [
                _p(base + 0, f"Band {n} Mode", "choice", 0.0, 1.0, 0.75),
                _p(base + 1, f"Band {n} Gain", "dB", -18.0, 18.0, 0.5),
                _p(base + 2, f"Band {n} Frequency", "Hz", 20.0, 20000.0, 0.5, curve="log"),
                _p(base + 3, f"Band {n} Q", "Q", 0.1, 10.0, 0.5, curve="log"),
                _p(base + 4, f"Band {n} Slope", "ratio", 0.0, 1.0, 0.0),
                _p(base + 5, f"Band {n} Side Mode", "choice", 0.0, 1.0, 0.0),
                _p(base + 6, f"Band {n} Side Gain", "dB", -18.0, 18.0, 0.5),
                _p(base + 7, f"Band {n} Side Frequency", "Hz", 20.0, 20000.0, 0.5, curve="log"),
                _p(base + 8, f"Band {n} Side Q", "Q", 0.1, 10.0, 0.5, curve="log"),
                _p(base + 9, f"Band {n} Side Slope", "ratio", 0.0, 1.0, 0.0),
                _p(base + 10, f"Band {n} Mid/Side", "choice", 0.0, 1.0, 0.0),
                _p(base + 11, f"Band {n} Solo", "bool", 0.0, 1.0, 0.0, curve="bool"),
                _p(base + 12, f"Band {n} Toggle On/Off", "bool", 0.0, 1.0, 0.75),
            ]
        )
    items.append(_p(130, "Output Level", "dB", -18.0, 18.0, 0.5, aliases=("OutputLevel", "OutLevel", "Level")))
    return tuple(items)


def _build_mbc_params() -> tuple[FxParamSpec, ...]:
    items: list[FxParamSpec] = [
        _p(0, "Bands 1-2 Freq", "Hz", 20.0, 20000.0, 0.25, curve="log", aliases=("Crossover1", "XOver1")),
        _p(1, "Bands 2-3 Freq", "Hz", 20.0, 20000.0, 0.5, curve="log", aliases=("Crossover2", "XOver2")),
        _p(2, "Bands 3-4 Freq", "Hz", 20.0, 20000.0, 0.78, curve="log", aliases=("Crossover3", "XOver3")),
        _p(3, "Master Gain", "%", 0.0, 100.0, 0.5, aliases=("Gain",)),
        _p(4, "Master Level", "%", 0.0, 100.0, 0.5, aliases=("Level",)),
    ]
    idx = 5
    for b in range(1, 5):
        items.extend(
            [
                _p(idx + 0, f"Band {b} Drive", "%", 0.0, 100.0, 0.5, aliases=(f"B{b}Drive", f"Band{b}_Drive")),
                _p(idx + 1, f"Band {b} Attack", "ms", 0.1, 100.0, 0.3, aliases=(f"B{b}Attack", f"Band{b}_Attack")),
                _p(idx + 2, f"Band {b} Release", "ms", 10.0, 1000.0, 0.4, aliases=(f"B{b}Release", f"Band{b}_Release")),
                _p(idx + 3, f"Band {b} Ratio", "ratio", 1.0, 20.0, 0.2, curve="ratio_num", aliases=(f"B{b}Ratio", f"Band{b}_Ratio")),
                _p(idx + 4, f"Band {b} Level", "%", 0.0, 100.0, 0.5, aliases=(f"B{b}Level", f"Band{b}_Level")),
            ]
        )
        idx += 5
    for b in range(1, 5):
        items.append(_p(24 + b, f"Band {b} Solo", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=(f"B{b}Solo",)))
    items.append(_p(29, "Mix", "%", 0.0, 100.0, 1.0))
    items.append(_p(30, "Side Chain HPF", "Hz", 20.0, 20000.0, 0.0, curve="log", aliases=("SideChain_HPF",)))
    return tuple(items)


_DELAY_REVERB_ALIASES_TIME = ("Time", "Reverb Time", "ReverbTime")


FX_SPECS: tuple[FxSpec, ...] = (
    FxSpec(
        effect_id=10,
        name="EQ",
        category="EQ_and_Filters",
        model_inspiration="Parametric equalizer",
        param_count=131,
        params=_build_eq_params(),
        extra_param_keys=("HPF", "LPF", "LowShelf", "Low_Shelf", "HighShelf", "High_Shelf", "bands", "OutputLevel", "Output Level", "OutLevel", "Level"),
        controls_summary=("Bands (Freq, Gain, Q, Type, Slope)",),
    ),
    FxSpec(
        effect_id=11,
        name="Classic Compressor",
        category="Dynamics",
        model_inspiration="Transparent studio VCA/RMS compressor",
        param_count=8,
        params=(
            _p(0, "Threshold", "dB", -60.0, 0.0, 0.7),
            _p(1, "Ratio", "ratio", 1.0, 20.0, 0.157895, curve="ratio_num"),
            _p(2, "Attack", "ms", 0.0, 100.0, 0.1),
            _p(3, "Release", "ms", 0.0, 1000.0, 0.1),
            _p(4, "Makeup", "dB", -12.0, 12.0, 0.5, aliases=("Gain", "Gain / Output", "GainOutput")),
            _p(5, "Mix", "%", 0.0, 100.0, 1.0, aliases=("DryWet",)),
            _p(6, "Out Level", "%", 0.0, 100.0, 0.5, aliases=("OutLevel", "Output", "Level")),
            _p(7, "Side Chain HPF", "Hz", 20.0, 20000.0, 0.0, curve="log", aliases=("SideChain_HPF", "SideChainHPF")),
        ),
        controls_summary=("Threshold", "Ratio", "Attack", "Release", "Gain / Output", "Mix"),
    ),
    FxSpec(
        effect_id=12,
        name="Multiband Compressor",
        category="Dynamics",
        model_inspiration="Split-frequency multiband dynamics",
        param_count=31,
        params=_build_mbc_params(),
        controls_summary=("Crossover Frequencies", "Threshold", "Ratio", "Attack/Release", "Gain", "Mix"),
    ),
    FxSpec(
        effect_id=13,
        name="Creative Filter",
        category="EQ_and_Filters",
        model_inspiration="Resonant multimode filter",
        param_count=16,
        params=(
            _p(0, "Cutoff Frequency", "Hz", 20.0, 20000.0, 0.5, curve="log", aliases=("Cutoff", "Freq")),
            _p(1, "Resonance", "%", 0.0, 100.0, 0.2),
            _p(2, "Poles", "%", 0.0, 100.0, 0.333333),
            _p(3, "Mode", "%", 0.0, 100.0, 0.0, aliases=("FilterMode",), choices=(("lowpass", 0.0), ("lp", 0.0), ("bandpass", 0.5), ("bp", 0.5), ("highpass", 1.0), ("hp", 1.0))),
            _p(4, "Analogue", "%", 0.0, 100.0, 0.0, aliases=("Analog",)),
            _p(5, "Mod. Source", "%", 0.0, 100.0, 0.0, aliases=("ModSource",)),
            _p(6, "Mod. Amount", "%", 0.0, 100.0, 0.0, aliases=("ModAmount",)),
            _p(7, "Polarity", "%", 0.0, 100.0, 0.0),
            _p(8, "Out Level", "%", 0.0, 100.0, 0.5, aliases=("OutLevel", "Level")),
            _p(9, "LFO Speed", "%", 0.0, 100.0, 0.25, aliases=("LFOSpeed",)),
            _p(10, "LFO Waveform", "%", 0.0, 100.0, 0.0, aliases=("LFOWaveform",)),
            _p(11, "LFO Synced Speed", "%", 0.0, 100.0, 0.5, aliases=("LFOSyncedSpeed",)),
            _p(12, "Envelope Release", "ms", 1.0, 1000.0, 0.25, aliases=("EnvelopeRelease", "Release")),
            _p(13, "Sequence", "%", 0.0, 100.0, 0.0),
            _p(14, "Sequence Speed", "%", 0.0, 100.0, 0.25, aliases=("SequenceSpeed",)),
            _p(15, "Sequence Synced Speed", "%", 0.0, 100.0, 0.5, aliases=("SequenceSyncedSpeed",)),
        ),
        controls_summary=("Cutoff", "Resonance", "Filter Mode"),
    ),
    FxSpec(
        effect_id=14,
        name="1981 Classic Reverb",
        category="Reverb",
        model_inspiration="Early 80s digital rack reverb",
        param_count=6,
        params=(
            _p(0, "Dry", "%", 0.0, 100.0, 0.0),
            _p(1, "Wet", "%", 0.0, 100.0, 0.7, aliases=("DryWet",)),
            _p(2, "Decay", "s", 0.1, 10.0, 0.4),
            _p(3, "Pre-Delay", "ms", 0.0, 500.0, 0.04, aliases=("PreDelay",)),
            _p(4, "High", "%", 0.0, 100.0, 0.7),
            _p(5, "Level", "%", 0.0, 100.0, 0.5),
        ),
        controls_summary=("Dry", "Wet", "Decay", "Pre-Delay"),
    ),
    FxSpec(
        effect_id=15,
        name="Transient",
        category="Dynamics",
        model_inspiration="Envelope transient shaper",
        param_count=2,
        params=(
            _p(0, "Attack", "dB", -15.0, 15.0, 0.5, curve="db_signed", forbidden_units=("%",), enforce_unit=True),
            _p(1, "Sustain", "dB", -24.0, 24.0, 0.5, curve="db_signed", forbidden_units=("%",), enforce_unit=True),
        ),
        controls_summary=("Attack", "Sustain"),
    ),
    FxSpec(
        effect_id=16,
        name="Punch Exciter 180",
        category="Dynamics",
        model_inspiration="Classic dynamic/harmonic aural exciter",
        param_count=3,
        params=(
            _p(0, "Processed", "%", 0.0, 100.0, 0.3, aliases=("Drive", "Harmonics", "Mix")),
            _p(1, "Compression", "%", 0.0, 100.0, 0.5),
            _p(2, "Level", "%", 0.0, 100.0, 0.5),
        ),
        controls_summary=("Drive / Harmonics", "Mix"),
    ),
    FxSpec(
        effect_id=17,
        name="Tape Simulator",
        category="Distortion",
        model_inspiration="Analog reel-to-reel tape machine",
        param_count=6,
        params=(
            _p(0, "Drive", "%", 0.0, 100.0, 0.23),
            _p(1, "Bias", "%", 0.0, 100.0, 0.5, choices=(("normal", 0.5), ("norm", 0.5))),
            _p(2, "Speed", "%", 0.0, 100.0, 0.666667, choices=(("7.5ips", 0.333333), ("15ips", 0.666667), ("30ips", 1.0))),
            _p(3, "Noise", "%", 0.0, 100.0, 0.0),
            _p(4, "Wow/Flutter", "%", 0.0, 100.0, 0.0, aliases=("WowFlutter",)),
            _p(5, "Level", "%", 0.0, 100.0, 0.333333),
        ),
        controls_summary=("Drive", "Bias", "Noise", "Wow / Flutter", "Level"),
    ),
    FxSpec(
        effect_id=18,
        name="Bitcrusher",
        category="Distortion",
        model_inspiration="Digital resolution/sample-rate reducer",
        param_count=4,
        params=(
            _p(0, "Bits", "ratio", 1.0, 24.0, 0.5),
            _p(1, "Downsample", "ratio", 1.0, 64.0, 0.25, aliases=("Down Sample", "DownSample")),
            _p(2, "Anti-Alias", "bool", 0.0, 1.0, 1.0, curve="bool", aliases=("AntiAlias",)),
            _p(3, "Drive", "%", 0.0, 100.0, 0.25),
        ),
        controls_summary=("Bits", "Down Sample", "Drive", "Anti-Alias"),
    ),
    FxSpec(
        effect_id=19,
        name="Valve Distortion Box",
        category="Distortion",
        model_inspiration="Modern tube saturation unit",
        param_count=6,
        params=(
            _p(0, "Drive", "%", 0.0, 100.0, 0.11),
            _p(1, "Overdrive", "%", 0.0, 100.0, 1.0),
            _p(2, "Dist. Type", "%", 0.0, 100.0, 0.0, aliases=("DistType", "DistortionType")),
            _p(3, "Bias", "%", 0.0, 100.0, 0.2),
            _p(4, "Low-Pass Filter", "choice", 0.0, 1.0, 0.0, aliases=("LowPassFilter", "LPF"), choices=(("off", 0.0), ("7 khz", 0.25), ("7khz", 0.25), ("4 khz", 0.75), ("4khz", 0.75)), allowed_values=("Off", "4 kHz", "7 kHz")),
            _p(5, "Out Level", "%", 0.0, 100.0, 0.833333, aliases=("OutLevel", "DryWet", "Level")),
        ),
        controls_summary=("Overdrive", "Drive", "Low Pass Filter (Off / 4 kHz / 7 kHz)", "Distortion Type", "Out Level"),
    ),
    FxSpec(
        effect_id=20,
        name="Plate Reverb",
        category="Reverb",
        model_inspiration="Steel plate reverb",
        param_count=10,
        params=(
            _p(0, "Reverb Time", "s", 0.1, 10.0, 0.25, aliases=("ReverbTime", "Time")),
            _p(1, "Size", "%", 0.0, 100.0, 0.6),
            _p(2, "Diffusion", "%", 0.0, 100.0, 0.8),
            _p(3, "Shape", "%", 0.0, 100.0, 0.5),
            _p(4, "Color", "%", 0.0, 100.0, 0.25),
            _p(5, "Wet", "%", 0.0, 100.0, 1.0, aliases=("DryWet",)),
            _p(6, "Level", "%", 0.0, 100.0, 1.0),
            _p(7, "Pre-Delay", "ms", 0.0, 500.0, 0.04, aliases=("PreDelay",)),
            _p(8, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(9, "Pre-Delay BPM", "%", 0.0, 100.0, 0.0, aliases=("PreDelayBPM",)),
        ),
        controls_summary=("Reverb Time", "Pre-Delay", "Size", "Shape", "Diffusion", "Color", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=21,
        name="Room Reverb",
        category="Reverb",
        model_inspiration="Acoustic studio room simulator",
        param_count=14,
        params=(
            _p(0, "Reverb Time", "s", 0.1, 10.0, 0.424522, aliases=("ReverbTime", "Time")),
            _p(1, "Diffusion", "%", 0.0, 100.0, 0.5),
            _p(2, "Decay", "s", 0.0, 2.0, 0.75),
            _p(3, "Wet", "%", 0.0, 100.0, 1.0, aliases=("DryWet",)),
            _p(4, "Damping", "%", 0.0, 100.0, 0.4),
            _p(5, "Level", "%", 0.0, 100.0, 1.0),
            _p(6, "Pre-Delay", "ms", 0.0, 500.0, 0.036, aliases=("PreDelay",)),
            _p(7, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(8, "Pre-Delay BPM", "%", 0.0, 100.0, 0.0, aliases=("PreDelayBPM",)),
            _p(9, "Size", "%", 0.0, 100.0, 0.65),
            _p(10, "High", "%", 0.0, 100.0, 0.74807),
            _p(11, "Low", "%", 0.0, 100.0, 0.37884),
            _p(12, "Motion", "%", 0.0, 100.0, 0.2),
            _p(13, "Depth", "%", 0.0, 100.0, 0.2),
        ),
        controls_summary=("Reverb Time", "Decay", "Pre-Delay", "Size", "Diffusion", "Damping", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=22,
        name="Hall Reverb",
        category="Reverb",
        model_inspiration="Large hall reverb",
        param_count=10,
        params=(
            _p(0, "Reverb Time", "s", 0.1, 10.0, 0.35, aliases=("ReverbTime", "Time")),
            _p(1, "Size", "%", 0.0, 100.0, 0.7),
            _p(2, "Diffusion", "%", 0.0, 100.0, 0.7),
            _p(3, "Shape", "%", 0.0, 100.0, 0.65),
            _p(4, "High", "%", 0.0, 100.0, 0.5, aliases=("Damping",)),
            _p(5, "Wet", "%", 0.0, 100.0, 1.0, aliases=("DryWet",)),
            _p(6, "Level", "%", 0.0, 100.0, 1.0),
            _p(7, "Pre-Delay", "ms", 0.0, 500.0, 0.05, aliases=("PreDelay",)),
            _p(8, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(9, "Pre-Delay BPM", "%", 0.0, 100.0, 0.0, aliases=("PreDelayBPM",)),
        ),
        controls_summary=("Reverb Time", "Pre-Delay", "Size", "Diffusion", "Damping", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=23,
        name="Inverse Reverb",
        category="Reverb",
        model_inspiration="Reverse/gated envelope reverb",
        param_count=11,
        params=(
            _p(0, "Reverb Time", "s", 0.1, 5.0, 0.25, aliases=("ReverbTime", "Time")),
            _p(1, "Diffusion", "%", 0.0, 100.0, 0.8),
            _p(2, "High", "%", 0.0, 100.0, 0.75),
            _p(3, "Wet", "%", 0.0, 100.0, 1.0, aliases=("DryWet",)),
            _p(4, "Pre-Delay", "ms", 0.0, 500.0, 0.0, aliases=("PreDelay",)),
            _p(5, "Low", "%", 0.0, 100.0, 0.4),
            _p(6, "Level", "%", 0.0, 100.0, 1.0),
            _p(7, "Pre-Delay Sync", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("PreDelaySync",)),
            _p(8, "Pre-Delay BPM", "%", 0.0, 100.0, 0.0, aliases=("PreDelayBPM",)),
            _p(9, "Time Sync", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("TimeSync",)),
            _p(10, "Synced Time", "%", 0.0, 100.0, 0.5, aliases=("SyncedTime",)),
        ),
        controls_summary=("Time", "Pre-Delay", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=24,
        name="Spring Reverb",
        category="Reverb",
        model_inspiration="Spring reverb tank",
        param_count=6,
        params=(
            _p(0, "Time", "s", 0.1, 5.0, 0.35),
            _p(1, "Bright", "%", 0.0, 100.0, 0.4, aliases=("Tone",)),
            _p(2, "Wet", "%", 0.0, 100.0, 1.0, aliases=("DryWet",)),
            _p(3, "Tension", "%", 0.0, 100.0, 0.6),
            _p(4, "Level", "%", 0.0, 100.0, 0.5),
            _p(5, "Pre-Delay", "ms", 0.0, 500.0, 0.0, aliases=("PreDelay",)),
        ),
        controls_summary=("Time", "Tone", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=25,
        name="Distortion",
        category="Distortion",
        model_inspiration="Classic overdrive pedal",
        param_count=3,
        params=(
            _p(0, "Drive", "%", 0.0, 100.0, 0.38),
            _p(1, "Tone", "%", 0.0, 100.0, 0.65),
            _p(2, "Level", "%", 0.0, 100.0, 0.35),
        ),
        controls_summary=("Drive", "Tone"),
    ),
    FxSpec(
        effect_id=26,
        name="Filter Delay",
        category="Delay",
        model_inspiration="Filtered feedback delay",
        param_count=11,
        params=(
            _p(0, "Time", "ms", 1.0, 2000.0, 0.3),
            _p(1, "Repeat", "%", 0.0, 100.0, 0.25, aliases=("Feedback",)),
            _p(2, "Speed", "%", 0.0, 100.0, 0.15),
            _p(3, "Center", "Hz", 20.0, 20000.0, 0.6, curve="log", aliases=("FilterCutoff", "Cutoff")),
            _p(4, "Depth", "%", 0.0, 100.0, 0.5),
            _p(5, "Level", "%", 0.0, 100.0, 0.75),
            _p(6, "Synced Speed", "%", 0.0, 100.0, 0.3, aliases=("SyncedSpeed",)),
            _p(7, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(8, "Stereo Reverse", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("StereoReverse",)),
            _p(9, "Reverse", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(10, "Mix", "%", 0.0, 100.0, 0.5, aliases=("DryWet",)),
        ),
        controls_summary=("Time", "Feedback", "Filter Cutoff", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=27,
        name="Phaser",
        category="Modulation",
        model_inspiration="Multi-stage phaser",
        param_count=5,
        params=(
            _p(0, "Speed", "%", 0.0, 100.0, 0.5, aliases=("Rate",)),
            _p(1, "Resonance", "%", 0.0, 100.0, 0.6, aliases=("Feedback", "Depth")),
            _p(2, "Level", "%", 0.0, 100.0, 0.75, aliases=("Mix",)),
            _p(3, "Sync Speed", "%", 0.0, 100.0, 0.3, aliases=("SyncSpeed",)),
            _p(4, "Sync On", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("SyncOn", "Sync")),
        ),
        controls_summary=("Rate", "Depth", "Feedback", "Mix"),
    ),
    FxSpec(
        effect_id=28,
        name="Frequency Gate",
        category="Dynamics",
        model_inspiration="Sidechain-filtered noise gate / expander",
        param_count=8,
        params=(
            _p(0, "Threshold", "dB", -60.0, 0.0, 0.5),
            _p(1, "Attack", "ms", 0.0, 100.0, 0.869176),
            _p(2, "Hold", "ms", 0.0, 500.0, 0.04),
            _p(3, "Release", "ms", 10.0, 1500.0, 0.415),
            _p(4, "Exp Thresh", "dB", -60.0, 0.0, 0.0, aliases=("ExpanderThreshold", "ExpThresh")),
            _p(5, "Ratio", "ratio", 1.0, 20.0, 1.0, curve="ratio_num"),
            _p(6, "Low Cut", "Hz", 20.0, 20000.0, 0.0, curve="log", aliases=("LowCut",)),
            _p(7, "Hi Cut", "Hz", 20.0, 20000.0, 1.0, curve="log", aliases=("HiCut", "SideChain_HPF", "SideChainHPF")),
        ),
        controls_summary=("Threshold", "Attack", "Hold", "Release", "Expander Threshold", "Low Cut", "Hi Cut"),
    ),
    FxSpec(
        effect_id=29,
        name="Punch Exciter 361",
        category="Dynamics",
        model_inspiration="Modified harmonic exciter (Vocal Mod)",
        param_count=5,
        params=(
            _p(0, "Dry", "%", 0.0, 100.0, 0.78),
            _p(1, "Vocal Mod", "bool", 0.0, 1.0, 0.0, curve="inverted_bool", aliases=("VocalMod",)),
            _p(2, "Compression", "%", 0.0, 100.0, 0.25),
            _p(3, "Wet", "%", 0.0, 100.0, 0.22, aliases=("Mix",)),
            _p(4, "Out Level", "%", 0.0, 100.0, 0.5, aliases=("OutLevel", "Level")),
        ),
        controls_summary=("Compression", "Vocal Mod (HPF)", "Mix"),
    ),
    FxSpec(
        effect_id=30,
        name="Tremolo",
        category="Modulation",
        model_inspiration="Amplitude modulation",
        param_count=6,
        params=(
            _p(0, "Waveform", "%", 0.0, 100.0, 0.0),
            _p(1, "Speed", "%", 0.0, 100.0, 0.3, aliases=("Rate",)),
            _p(2, "Intensity", "%", 0.0, 100.0, 0.35, aliases=("Depth",)),
            _p(3, "Synced Speed", "%", 0.0, 100.0, 0.5, aliases=("SyncedSpeed",)),
            _p(4, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(5, "Panning", "bool", 0.0, 1.0, 0.0, curve="bool"),
        ),
        controls_summary=("Rate", "Depth"),
    ),
    FxSpec(
        effect_id=31,
        name="1981 Classic Echo",
        aliases=("Classic Echo",),
        category="Delay",
        model_inspiration="Clean studio delay",
        param_count=14,
        params=(
            _p(0, "Dry", "%", 0.0, 100.0, 0.0),
            _p(1, "Wet", "%", 0.0, 100.0, 1.0, aliases=("DryWet", "Mix")),
            _p(2, "Delay Left", "ms", 0.0, 2000.0, 0.5, aliases=("DelayLeft", "Time")),
            _p(3, "Repeat Left", "%", 0.0, 100.0, 0.5, aliases=("RepeatLeft", "Feedback")),
            _p(4, "Delay Right", "ms", 0.0, 2000.0, 0.5, aliases=("DelayRight",)),
            _p(5, "Repeat Right", "%", 0.0, 100.0, 0.5, aliases=("RepeatRight",)),
            _p(6, "Bass", "%", 0.0, 100.0, 0.5),
            _p(7, "Treble", "%", 0.0, 100.0, 0.5, aliases=("Filter",)),
            _p(8, "Reverse", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(9, "Left Sync", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("LeftSync", "Sync")),
            _p(10, "Synced Delay Left", "%", 0.0, 100.0, 0.5, aliases=("SyncedDelayLeft",)),
            _p(11, "Right Sync", "bool", 0.0, 100.0, 0.0, curve="bool", aliases=("RightSync",)),
            _p(12, "Synced Delay Right", "%", 0.0, 100.0, 0.5, aliases=("SyncedDelayRight",)),
            _p(13, "Output Level", "%", 0.0, 100.0, 0.5, aliases=("OutputLevel", "Level")),
        ),
        controls_summary=("Time / Sync", "Feedback", "Filter", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=32,
        name="Auto-Wah",
        category="Modulation",
        model_inspiration="Envelope follower filter",
        param_count=10,
        params=(
            _p(0, "Filter", "%", 0.0, 100.0, 0.1, aliases=("Q",)),
            _p(1, "Speed", "%", 0.0, 100.0, 0.5),
            _p(2, "Depth", "%", 0.0, 100.0, 0.8, aliases=("Range",)),
            _p(3, "Sensitivity", "%", 0.0, 100.0, 0.4),
            _p(4, "Release", "ms", 1.0, 1000.0, 0.5),
            _p(5, "Mode", "%", 0.0, 100.0, 0.5),
            _p(6, "Polarity", "%", 0.0, 100.0, 0.0),
            _p(7, "Level", "%", 0.0, 100.0, 0.75),
            _p(8, "Synced Speed", "%", 0.0, 100.0, 0.5, aliases=("SyncedSpeed",)),
            _p(9, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
        ),
        controls_summary=("Sensitivity", "Range", "Q"),
    ),
    FxSpec(
        effect_id=33,
        name="String Machine Chorus",
        category="Modulation",
        model_inspiration="BBD ensemble chorus",
        param_count=3,
        params=(
            _p(0, "Depth", "%", 0.0, 100.0, 0.3, aliases=("Rate",)),
            _p(1, "Mix", "%", 0.0, 100.0, 0.3),
            _p(2, "Out Level", "%", 0.0, 100.0, 0.5, aliases=("OutLevel", "Level")),
        ),
        controls_summary=("Depth", "Mix", "Out Level"),
    ),
    FxSpec(
        effect_id=34,
        name="Limiter Pedal",
        category="Dynamics",
        model_inspiration="Stompbox bass/guitar limiter",
        param_count=5,
        params=(
            _p(0, "Sensitivity", "%", 0.0, 100.0, 0.3),
            _p(1, "Attack Time", "ms", 0.1, 100.0, 0.5, aliases=("Attack", "AttackTime")),
            _p(2, "Release Time", "ms", 10.0, 1000.0, 0.7, aliases=("Release", "ReleaseTime")),
            _p(3, "Level", "%", 0.0, 100.0, 0.75),
            _p(4, "Stereo", "bool", 0.0, 1.0, 1.0, curve="bool"),
        ),
        controls_summary=("Sensitivity", "Attack", "Release"),
    ),
    FxSpec(
        effect_id=35,
        name="Chorus",
        category="Modulation",
        model_inspiration="Stereo chorus",
        param_count=6,
        params=(
            _p(0, "LFO Speed", "%", 0.0, 100.0, 0.15, aliases=("LFOSpeed", "Rate")),
            _p(1, "Depth", "%", 0.0, 100.0, 0.5),
            _p(2, "Amount", "%", 0.0, 100.0, 0.7, aliases=("Mix",)),
            _p(3, "Stereo", "bool", 0.0, 1.0, 1.0, curve="bool"),
            _p(4, "Synced Speed", "%", 0.0, 100.0, 0.0, aliases=("SyncedSpeed",)),
            _p(5, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
        ),
        controls_summary=("Rate", "Depth", "Mix"),
    ),
    FxSpec(
        effect_id=36,
        name="Vibrato",
        category="Modulation",
        model_inspiration="Pitch modulation",
        param_count=5,
        params=(
            _p(0, "LFO Speed", "%", 0.0, 100.0, 0.2, aliases=("LFOSpeed", "Rate")),
            _p(1, "Depth", "%", 0.0, 100.0, 0.5),
            _p(2, "Level", "%", 0.0, 100.0, 0.75),
            _p(3, "Synced Speed", "%", 0.0, 100.0, 0.0, aliases=("SyncedSpeed",)),
            _p(4, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
        ),
        controls_summary=("Rate", "Depth"),
    ),
    FxSpec(
        effect_id=37,
        name="Flanger",
        category="Modulation",
        model_inspiration="Tape/analog flanger",
        param_count=7,
        params=(
            _p(0, "LFO Rate", "%", 0.0, 100.0, 0.4, aliases=("LFORate", "Rate")),
            _p(1, "Range", "%", 0.0, 100.0, 0.7, aliases=("Depth",)),
            _p(2, "Color", "%", 0.0, 100.0, 0.5, aliases=("Feedback",)),
            _p(3, "Intensity", "%", 0.0, 100.0, 0.6, aliases=("Mix",)),
            _p(4, "Synced Speed", "%", 0.0, 100.0, 0.4, aliases=("SyncedSpeed",)),
            _p(5, "Sync", "bool", 0.0, 1.0, 0.0, curve="bool"),
            _p(6, "Level", "%", 0.0, 100.0, 0.75),
        ),
        controls_summary=("Rate", "Depth", "Feedback", "Mix"),
    ),
    FxSpec(
        effect_id=38,
        name="Dimension T",
        category="Modulation",
        model_inspiration="Spatial stereo chorus",
        param_count=4,
        params=(
            _p(0, "Dimension 1", "bool", 0.0, 1.0, 1.0, curve="bool", aliases=("Dimension1", "Mode1", "Dim1")),
            _p(1, "Dimension 2", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("Dimension2", "Mode2", "Dim2")),
            _p(2, "Dimension 3", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("Dimension3", "Mode3", "Dim3")),
            _p(3, "Dimension 4", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("Dimension4", "Mode4", "Dim4")),
        ),
        controls_summary=("Mode Buttons (Dimension 1..4)",),
    ),
    FxSpec(
        effect_id=39,
        name="Tape Delay",
        category="Delay",
        model_inspiration="Vintage tape echo",
        param_count=13,
        params=(
            _p(0, "Time", "ms", 1.0, 2000.0, 0.4),
            _p(1, "Repeat", "%", 0.0, 100.0, 0.25, aliases=("Feedback",)),
            _p(2, "Spread", "%", 0.0, 100.0, 0.25),
            _p(3, "Wow/Flutter", "%", 0.0, 100.0, 0.1, aliases=("WowFlutter", "Tone / Flutter")),
            _p(4, "Dist", "%", 0.0, 100.0, 0.25, aliases=("Drive",)),
            _p(5, "Mix", "%", 0.0, 100.0, 0.3, aliases=("DryWet",)),
            _p(6, "Level", "%", 0.0, 100.0, 0.75),
            _p(7, "Stereo Reverse", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("StereoReverse",)),
            _p(8, "Reverse Mode", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("ReverseMode",)),
            _p(9, "Synced Time", "%", 0.0, 100.0, 0.5, aliases=("SyncedTime",)),
            _p(10, "Time Sync", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("TimeSync", "Sync")),
            _p(11, "Synced Spread", "%", 0.0, 100.0, 0.5, aliases=("SyncedSpread",)),
            _p(12, "Spread Sync", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("SpreadSync",)),
        ),
        controls_summary=("Time / Sync", "Feedback", "Tone / Flutter", "Dry / Wet"),
    ),
    FxSpec(
        effect_id=40,
        name="Comp 76",
        category="Dynamics",
        model_inspiration="UREI 1176 FET compressor",
        param_count=6,
        params=(
            _p(0, "Input", "%", 0.0, 100.0, 0.583333, aliases=("InputGain",)),
            _p(1, "Output", "%", 0.0, 100.0, 0.75, aliases=("OutputLevel", "OutLevel")),
            _p(2, "Attack", "scale", 1.0, 7.0, 0.5, aliases=("AttackTime",)),
            _p(3, "Release", "scale", 1.0, 7.0, 0.5, aliases=("ReleaseTime",)),
            _p(4, "Ratio", "choice", 0.0, 1.0, 0.0, allowed_values=("4:1", "8:1", "12:1", "20:1", "All"), choices=(("4:1", 0.0), ("8:1", 0.25), ("12:1", 0.5), ("20:1", 0.75), ("all", 1.0))),
            _p(5, "Mix", "%", 0.0, 100.0, 1.0),
        ),
        extra_param_keys=("GR",),
        controls_summary=("Input", "Output", "Attack (1=fastest..7=slowest)", "Release (1=fastest..7=slowest)", "Ratio (4:1, 8:1, 12:1, 20:1, All)", "Mix"),
    ),
    FxSpec(
        effect_id=41,
        name="Comp 670",
        category="Dynamics",
        model_inspiration="Fairchild 670 variable-mu tube compressor",
        param_count=11,
        params=(
            _p(0, "Left/Mid Gain", "%", 0.0, 100.0, 0.3, aliases=("InputGain", "LeftGain")),
            _p(1, "Left/Mid Threshold", "scale", -24.0, 10.0, 0.125, aliases=("Threshold", "LeftThreshold")),
            _p(2, "Left/Mid DC Threshold", "%", 0.0, 100.0, 0.5, aliases=("DCThreshold",)),
            _p(3, "Left/Mid Time Constant", "scale", 1.0, 6.0, 0.295, aliases=("TimeConstant",)),
            _p(4, "Right/Side Gain", "%", 0.0, 100.0, 0.3, aliases=("RightGain",)),
            _p(5, "Right/Side Threshold", "scale", -24.0, 10.0, 0.125, aliases=("RightThreshold",)),
            _p(6, "Right/Side DC Threshold", "%", 0.0, 100.0, 0.5, aliases=("RightDCThreshold",)),
            _p(7, "Right/Side Time Constant", "scale", 1.0, 6.0, 0.295, aliases=("RightTimeConstant",)),
            _p(8, "Mix", "%", 0.0, 100.0, 1.0),
            _p(9, "Level", "%", 0.0, 100.0, 0.5, aliases=("Output",)),
            _p(10, "Stereo - Mid/Side", "%", 0.0, 100.0, 0.0, aliases=("Mode", "MSMatrix")),
        ),
        extra_param_keys=("GR", "linked"),
        default_flags=("linked",),
        controls_summary=("Input Gain", "Threshold", "Time Constant", "M/S Matrix (Mid/Side)", "Output"),
    ),
    FxSpec(
        effect_id=42,
        name="EQ84",
        category="EQ_and_Filters",
        model_inspiration="British 1084-style console EQ",
        param_count=15,
        params=(
            _p(0, "Level", "%", 0.0, 100.0, 0.5, aliases=("OutLevel",)),
            _p(1, "High Freq", "Hz", 10000.0, 16000.0, 0.0),
            _p(2, "High Gain", "dB", -15.0, 15.0, 0.5),
            _p(3, "High Mute", "bool", 0.0, 1.0, 1.0, aliases=("HighMute",)),
            _p(4, "Mid Freq", "Hz", 350.0, 10000.0, 0.5),
            _p(5, "Mid Gain", "dB", -15.0, 15.0, 0.5),
            _p(6, "Mid Q", "bool", 0.0, 1.0, 0.0, aliases=("HiQ",)),
            _p(7, "Mid Mute", "bool", 0.0, 1.0, 1.0, aliases=("MidMute",)),
            _p(8, "Low Freq", "Hz", 35.0, 220.0, 0.667),
            _p(9, "Low Gain", "dB", -15.0, 15.0, 0.5),
            _p(10, "Low Mute", "bool", 0.0, 1.0, 1.0, aliases=("LowMute",)),
            _p(11, "Low Cut Freq", "Hz", 45.0, 360.0, 0.0, aliases=("HPF",)),
            _p(12, "Low Cut Bypass", "bool", 0.0, 1.0, 1.0),
            _p(13, "High Cut Freq", "Hz", 6000.0, 18000.0, 0.0, aliases=("LPF",)),
            _p(14, "High Cut Bypass", "bool", 0.0, 1.0, 1.0),
        ),
        forbidden_keys=("LowMid", "HighMid"),
        extra_param_keys=("Low", "Mid", "High", "HPF", "LPF", "HiQ", "InOut"),
        controls_summary=("HPF", "LPF", "Low (Freq, Gain)", "Mid (Freq, Gain, Hi-Q)", "High (Freq, Gain)", "In/Out"),
    ),
    FxSpec(
        effect_id=43,
        name="Fat Muff",
        category="Distortion",
        model_inspiration="Classic fuzz pedal",
        param_count=3,
        params=(
            _p(0, "Drive", "%", 0.0, 100.0, 0.45),
            _p(1, "Tone", "%", 0.0, 100.0, 0.6),
            _p(2, "Level", "%", 0.0, 100.0, 0.45),
        ),
        controls_summary=("Drive", "Tone"),
    ),
    FxSpec(
        effect_id=44,
        name="Compressor / Limiter",
        aliases=("Compressor/Limiter",),
        category="Dynamics",
        model_inspiration="Modern clean compressor/peak limiter",
        param_count=6,
        params=(
            _p(0, "Threshold", "dB", -48.0, 0.0, 0.25),
            _p(1, "Ratio", "ratio", 1.5, 20.0, 0.35),
            _p(2, "Attack", "ms", 0.05, 50.0, 0.370512),
            _p(3, "Release", "ms", 50.0, 1000.0, 0.0),
            _p(4, "Makeup", "%", 0.0, 100.0, 0.0),
            _p(5, "Auto-Makeup", "bool", 0.0, 1.0, 0.0, curve="bool", aliases=("AutoMakeup",)),
        ),
        controls_summary=("Threshold", "Ratio (1.5:1-13:1+)", "Attack", "Release", "Auto-Makeup", "Makeup"),
    ),
)

FX_BY_ID: dict[int, FxSpec] = {spec.effect_id: spec for spec in FX_SPECS}
FX_BY_NAME: dict[str, FxSpec] = {}
FX_BY_CANONICAL: dict[str, FxSpec] = {}
for _spec in FX_SPECS:
    FX_BY_NAME[_spec.name] = _spec
    FX_BY_CANONICAL[canonical_key(_spec.name)] = _spec
    for _alias in _spec.aliases:
        FX_BY_NAME[_alias] = _spec
        FX_BY_CANONICAL[canonical_key(_alias)] = _spec

NATIVE_FX_IDS: dict[str, int] = {name: spec.effect_id for name, spec in FX_BY_NAME.items()}


def resolve_fx(name_or_id: str | int) -> FxSpec:
    """Resolve an FX name, alias, or numeric effect ID to its `FxSpec`."""
    if isinstance(name_or_id, int):
        if name_or_id not in FX_BY_ID:
            raise ValueError(f"Unsupported SD3 FX ID: {name_or_id}")
        return FX_BY_ID[name_or_id]
    s = str(name_or_id).strip()
    if s in FX_BY_NAME:
        return FX_BY_NAME[s]
    ck = canonical_key(s)
    if ck in FX_BY_CANONICAL:
        return FX_BY_CANONICAL[ck]
    raise ValueError(f"Non-native or unknown SD3 FX: {name_or_id!r}")


def list_native_fx_grouped() -> dict[str, list[dict[str, Any]]]:
    """Return all 35 FX grouped by category for `inventory.json`."""
    grouped: dict[str, list[dict[str, Any]]] = {
        "Dynamics": [],
        "Distortion": [],
        "EQ_and_Filters": [],
        "Delay": [],
        "Reverb": [],
        "Modulation": [],
    }
    for spec in FX_SPECS:
        grouped.setdefault(spec.category, []).append(
            {
                "effect_id": spec.effect_id,
                "name": spec.name,
                "aliases": list(spec.aliases),
                "model_inspiration": spec.model_inspiration,
                "controls": list(spec.controls_summary) or [p.name for p in spec.params],
            }
        )
    return grouped


def list_native_fx_names() -> list[str]:
    """Return the canonical 35 FX display names in category order."""
    grouped = list_native_fx_grouped()
    return [item["name"] for items in grouped.values() for item in items]


def _param_lookup_for_spec(spec: FxSpec) -> dict[str, FxParamSpec]:
    table: dict[str, FxParamSpec] = {}
    for p in spec.params:
        table[canonical_key(p.name)] = p
        for al in p.aliases:
            table[canonical_key(al)] = p
    return table


def _is_eq_band_key(key: str) -> bool:
    kl = key.lower()
    return (
        kl in {"hpf", "lpf", "lowshelf", "low_shelf", "highshelf", "high_shelf", "bands"}
        or kl.startswith(("cut", "boost", "bell"))
    )


def _encode_generic_param(spec: FxParamSpec, raw_val: Any) -> float:
    s = str(raw_val).strip()
    sl = s.lower()

    if spec.choices:
        for ch_key, ch_norm in spec.choices:
            if ch_key == sl or (ch_key != "all" and ch_key in sl):
                return clamp01(ch_norm)
            if ch_key == "all" and "all" in sl:
                return clamp01(ch_norm)

    if spec.curve == "bool":
        return parse_bool_norm(raw_val, invert=False)
    if spec.curve == "inverted_bool":
        return parse_bool_norm(raw_val, invert=True)
    if spec.curve == "db_signed":
        num = max(spec.min_val, min(spec.max_val, parse_first_float(raw_val)))
        return clamp01((num - spec.min_val) / (spec.max_val - spec.min_val))
    if spec.curve == "ratio_num":
        num = parse_first_float(raw_val)
        return clamp01((num - spec.min_val) / (spec.max_val - spec.min_val))
    if spec.curve == "log":
        hz = parse_hz(raw_val)
        hz = max(spec.min_val, min(spec.max_val, hz))
        return clamp01(math.log10(hz / spec.min_val) / math.log10(spec.max_val / spec.min_val))

    # Linear unit conversions
    if spec.unit == "%":
        return parse_pct(raw_val)
    if spec.unit == "ms":
        ms = parse_ms(raw_val)
        return clamp01((ms - spec.min_val) / (spec.max_val - spec.min_val))
    if spec.unit == "s":
        sec = parse_sec(raw_val)
        return clamp01((sec - spec.min_val) / (spec.max_val - spec.min_val))
    if spec.unit == "dB":
        db = parse_first_float(raw_val)
        return clamp01((db - spec.min_val) / (spec.max_val - spec.min_val))
    if spec.unit == "scale":
        v = parse_first_float(raw_val)
        if 0.0 <= v <= 1.0 and spec.min_val == 0.0 and spec.max_val > 1.0 and "." in s:
            return clamp01(v)
        return clamp01((v - spec.min_val) / (spec.max_val - spec.min_val))
    if spec.unit == "Hz":
        hz = parse_hz(raw_val)
        return clamp01((hz - spec.min_val) / (spec.max_val - spec.min_val))
    num = parse_first_float(raw_val)
    return clamp01((num - spec.min_val) / max(1e-9, (spec.max_val - spec.min_val)))


def validate_fx_params(
    fx_name: str,
    params: dict[str, Any] | None,
    *,
    calibration_targets: dict[str, Any] | None = None,
    strict_v2: bool = False,
    context_label: str = "insert",
) -> list[str]:
    """Validate an FX name and its parameter dict against the static 35-FX contract."""
    errors: list[str] = []
    try:
        spec = resolve_fx(fx_name)
    except ValueError:
        return [f"Non-native FX '{fx_name}' on {context_label} (must be one of 35 SD3 native FX)."]

    p = params or {}
    if not isinstance(p, dict):
        return [f"{spec.name} params error on {context_label}: expected dict."]

    forbidden_norm = {canonical_key(k) for k in spec.forbidden_keys}
    param_table = _param_lookup_for_spec(spec)
    extra_norm = {canonical_key(k) for k in spec.extra_param_keys}

    for key, val in p.items():
        if key == "raw_params":
            if not isinstance(val, dict):
                errors.append(f"{spec.name} raw_params error on {context_label}: must be a dict of index -> float.")
            else:
                for rk in val:
                    try:
                        idx = int(rk)
                    except (TypeError, ValueError):
                        errors.append(f"{spec.name} raw_params error on {context_label}: non-integer key {rk!r}.")
                        continue
                    if idx < 0 or idx >= spec.param_count:
                        errors.append(
                            f"{spec.name} raw_params error on {context_label}: index {idx} out of range 0..{spec.param_count - 1}."
                        )
            continue

        ck = canonical_key(key)
        if ck in forbidden_norm:
            errors.append(
                f"{spec.name} topology error on {context_label}: parameter '{key}' does not exist in SD3 UI "
                f"(forbidden keys: {list(spec.forbidden_keys)})."
            )
            continue

        if strict_v2 and ck == "gr":
            errors.append(
                f"{spec.name} v2 schema error on {context_label}: 'GR' belongs in calibration_targets.target_gr_db, not params."
            )
            continue

        if spec.effect_id == 10 and _is_eq_band_key(key):
            if key.lower() != "bands":
                try:
                    if key.lower() in {"hpf", "lpf"}:
                        parse_hz(val)
                    else:
                        parse_band_spec(val)
                except ValueError as exc:
                    errors.append(f"EQ band error on {context_label} ({key}): {exc}")
            continue

        if ck not in param_table and ck not in extra_norm:
            errors.append(f"{spec.name} parameter error on {context_label}: unknown parameter '{key}'.")
            continue

        pspec = param_table.get(ck)
        if not pspec:
            continue

        raw_str = str(val).strip()
        for bad_unit in pspec.forbidden_units:
            if bad_unit in raw_str:
                errors.append(
                    f"{spec.name} UI unit error on {context_label}: {key}='{raw_str}' uses forbidden unit "
                    f"'{bad_unit}' (expected '{pspec.unit}')."
                )

        if pspec.enforce_unit and pspec.unit != "scale":
            if not re.search(rf"(?<![A-Za-z]){re.escape(pspec.unit)}\b", raw_str, flags=re.I):
                errors.append(
                    f"{spec.name} UI unit error on {context_label}: {key}='{raw_str}' missing unit '{pspec.unit}'."
                )

        if pspec.allowed_values:
            if raw_str not in pspec.allowed_values and raw_str.lower() not in {a.lower() for a in pspec.allowed_values}:
                errors.append(
                    f"{spec.name} value error on {context_label}: {key}='{raw_str}' not in allowed {list(pspec.allowed_values)}."
                )

        if pspec.unit in {"dB", "scale"} and pspec.min_val < pspec.max_val:
            m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)", raw_str)
            if m:
                num_val = float(m.group(1))
                if num_val < pspec.min_val:
                    errors.append(
                        f"{spec.name} range error on {context_label}: {key}={num_val} < min {pspec.min_val} {pspec.unit}."
                    )
                if num_val > pspec.max_val:
                    errors.append(
                        f"{spec.name} range error on {context_label}: {key}={num_val} > max {pspec.max_val} {pspec.unit}."
                    )

    if calibration_targets is not None and "target_gr_db" in calibration_targets and calibration_targets["target_gr_db"] is not None:
        tg = calibration_targets["target_gr_db"]
        if isinstance(tg, (list, tuple)):
            if len(tg) != 2:
                errors.append(f"{spec.name} calibration_targets error on {context_label}: target_gr_db list must have 2 elements.")
        elif not isinstance(tg, (int, float)):
            errors.append(f"{spec.name} calibration_targets error on {context_label}: target_gr_db must be numeric or [min, max].")

    return errors


# ---------------------------------------------------------------------------
# Specialized calibrated encoders (preserving exact Deftones calibrations)
# ---------------------------------------------------------------------------

_EQ_TYPE_MAP = {
    "HPF": 0.0,
    "LPF": 0.111111,
    "BELL": 0.444444,
    "LOWSHELF": 0.888889,
    "HIGHSHELF": 1.0,
}


def _encode_eq(params: dict[str, Any], *, steep_hpf: bool = False) -> tuple[dict[int, float], list[str]]:
    bands: list[tuple[str, float, float, float, float]] = []

    def add_band(btype: str, hz: float, db: float = 0.0, q: float = 1.0, slope: float = 0.0) -> None:
        if len(bands) < 10:
            bands.append((btype, hz, db, q, slope))

    out_level = 0.5
    for key, val in params.items():
        if key == "raw_params":
            continue
        kl = key.lower()
        ck = canonical_key(key)
        if kl == "hpf":
            if steep_hpf:
                add_band("HPF", parse_hz(val), 0.0, 0.8574, 0.2)
            else:
                add_band("HPF", parse_hz(val), 0.0, 1.0, 0.0)
        elif kl == "lpf":
            add_band("LPF", parse_hz(val), 0.0, 0.7111, 0.0)
        elif kl.startswith(("cut", "boost", "bell")):
            hz, db, q = parse_band_spec(val)
            add_band("BELL", hz, db, q, 0.0)
        elif kl in {"lowshelf", "low_shelf"}:
            hz, db, q = parse_band_spec(val)
            add_band("LOWSHELF", hz, db, q, 0.0)
        elif kl in {"highshelf", "high_shelf"}:
            hz, db, q = parse_band_spec(val)
            add_band("HIGHSHELF", hz, db, q, 0.0)
        elif kl == "bands" and isinstance(val, list):
            for entry in val:
                if isinstance(entry, dict):
                    bt = str(entry.get("type", "BELL")).upper()
                    add_band(
                        bt,
                        parse_hz(entry.get("freq", entry.get("hz", "1000 Hz"))),
                        float(entry.get("gain_db", entry.get("db", 0.0))),
                        float(entry.get("q", 1.0)),
                        float(entry.get("slope", 0.0)),
                    )
        elif ck in {"outputlevel", "outlevel", "level"}:
            db = max(-18.0, min(18.0, parse_first_float(val)))
            out_level = clamp01((db + 18.0) / 36.0)
        else:
            raise ValueError(f"Unknown EQ parameter: {key!r}")

    out: dict[int, float] = {}
    for b in range(10):
        base = 13 * b
        if b < len(bands):
            btype, hz, db, q, slope = bands[b]
            hz_clamped = max(20.0, min(20000.0, hz))
            q_clamped = max(0.1, min(10.0, q))
            db_clamped = max(-18.0, min(18.0, db))
            out[base + 0] = _EQ_TYPE_MAP.get(btype, 0.444444)
            out[base + 1] = clamp01((db_clamped + 18.0) / 36.0)
            out[base + 2] = clamp01(math.log10(hz_clamped / 20.0) / 3.0)
            out[base + 3] = clamp01(0.5 + 0.5 * math.log10(q_clamped))
            out[base + 4] = slope
            out[base + 10] = 0.0
            out[base + 11] = 0.0
            out[base + 12] = 0.0
        else:
            out[base + 12] = 0.75
    out[130] = out_level
    return out, []


def _gr_mid_from_inputs(params: dict[str, Any], calibration_targets: dict[str, Any] | None) -> float | None:
    if calibration_targets and calibration_targets.get("target_gr_db") is not None:
        tg = calibration_targets["target_gr_db"]
        if isinstance(tg, (list, tuple)):
            return sum(float(x) for x in tg) / len(tg)
        return float(tg)
    if "GR" in params:
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(params["GR"]))]
        return sum(nums) / len(nums) if nums else 4.0
    return None


def _encode_comp76(params: dict[str, Any], calibration_targets: dict[str, Any] | None = None) -> tuple[dict[int, float], list[str]]:
    ratio_str = str(params.get("Ratio", "4:1")).strip().lower()
    ratio_map = {"4:1": 0.0, "8:1": 0.25, "12:1": 0.5, "20:1": 0.75, "all": 1.0}
    ratio_val = ratio_map.get(ratio_str, 0.0)
    if ratio_str not in ratio_map and "all" in ratio_str:
        ratio_val = 1.0

    atk = parse_first_float(params.get("Attack", params.get("AttackTime", 4.0)))
    rel = parse_first_float(params.get("Release", params.get("ReleaseTime", 4.0)))

    gr_mid = _gr_mid_from_inputs(params, calibration_targets)
    if "Input" in params:
        inp = clamp01(parse_pct(params["Input"]) if "%" in str(params["Input"]) else parse_first_float(params["Input"]))
    elif gr_mid is not None:
        if ratio_val >= 0.99:
            inp = 0.71
        elif gr_mid >= 9.0:
            inp = 0.84
        elif gr_mid >= 5.0:
            inp = 0.74
        elif gr_mid >= 3.5:
            inp = 0.90
        else:
            inp = 0.65
    else:
        inp = 0.583333

    out_lvl = clamp01(parse_first_float(params["Output"])) if "Output" in params else 0.75
    mix = parse_pct(params["Mix"]) if "Mix" in params else 1.0

    return {
        0: inp,
        1: out_lvl,
        2: clamp01((max(1.0, min(7.0, atk)) - 1.0) / 6.0),
        3: clamp01((max(1.0, min(7.0, rel)) - 1.0) / 6.0),
        4: ratio_val,
        5: mix,
    }, []


def _encode_eq84(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    h_hz, h_db = (10000.0, 0.0)
    m_hz, m_db, m_hiq = (3200.0, 0.0, 0.0)
    l_hz, l_db = (110.0, 0.0)
    level = 0.5
    h_mute = 1.0
    m_mute = 1.0
    l_mute = 1.0

    if "High" in params:
        h_hz, h_db, _ = parse_band_spec(params["High"])
    if "Mid" in params:
        ms = str(params["Mid"])
        m_hz, m_db, _ = parse_band_spec(ms)
        m_hiq = 1.0 if ("hi-q on" in ms.lower() or "high" in ms.lower()) else 0.0
    if "HiQ" in params:
        m_hiq = parse_bool_norm(params["HiQ"])
    if "Low" in params:
        l_hz, l_db, _ = parse_band_spec(params["Low"])
    if "Level" in params:
        level = parse_pct(params["Level"])
    if "HighMute" in params:
        h_mute = parse_bool_norm(params["HighMute"], invert=True)
    if "MidMute" in params:
        m_mute = parse_bool_norm(params["MidMute"], invert=True)
    if "LowMute" in params:
        l_mute = parse_bool_norm(params["LowMute"], invert=True)

    hpf_active = "HPF" in params
    lpf_active = "LPF" in params
    hpf_hz = parse_hz(params["HPF"]) if hpf_active else 90.0
    lpf_hz = parse_hz(params["LPF"]) if lpf_active else 6000.0

    high_pos = interp_table(h_hz, [(10000.0, 0.0), (12000.0, 0.5), (16000.0, 1.0)])
    mid_pos = interp_table(
        m_hz,
        [
            (350.0, 0.0),
            (700.0, 0.16667),
            (1600.0, 0.33334),
            (3200.0, 0.5),
            (4800.0, 0.66667),
            (7260.0, 0.83333),
            (10000.0, 1.0),
        ],
    )
    low_pos = interp_table(l_hz, [(35.0, 0.0), (60.0, 0.333), (110.0, 0.667), (220.0, 1.0)])
    hpf_pos = interp_table(hpf_hz, [(45.0, 0.0), (70.0, 0.333), (90.0, 0.5), (160.0, 0.667), (360.0, 1.0)])
    lpf_pos = interp_table(lpf_hz, [(6000.0, 0.0), (8000.0, 0.25), (10000.0, 0.5), (14000.0, 0.75), (18000.0, 1.0)])

    return {
        0: level,
        1: high_pos,
        2: clamp01((max(-15.0, min(15.0, h_db)) + 15.0) / 30.0),
        3: h_mute,
        4: mid_pos,
        5: clamp01((max(-15.0, min(15.0, m_db)) + 15.0) / 30.0),
        6: m_hiq,
        7: m_mute,
        8: low_pos,
        9: clamp01((max(-15.0, min(15.0, l_db)) + 15.0) / 30.0),
        10: l_mute,
        11: hpf_pos if hpf_active else 0.0,
        12: 0.0 if hpf_active else 1.0,
        13: lpf_pos if lpf_active else 0.0,
        14: 0.0 if lpf_active else 1.0,
    }, []


def _encode_comp670(params: dict[str, Any], calibration_targets: dict[str, Any] | None = None) -> tuple[dict[int, float], list[str]]:
    gr_mid = _gr_mid_from_inputs(params, calibration_targets)
    if "Threshold" in params and not re.search(r"suave|gr", str(params["Threshold"]), re.I):
        v = parse_first_float(params["Threshold"])
        thresh = clamp01(abs(v) / 10.0 if v < 0 else (v if v <= 1.0 else v / 10.0))
    else:
        if gr_mid is None:
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(params.get("Threshold", "1.5")))]
            gr_mid = sum(nums) / len(nums) if nums else 1.5
        thresh = 0.18 if gr_mid >= 1.8 else 0.125

    tc_s = str(params.get("TimeConstant", "")).lower()
    tc = 0.295 if ("auto" in tc_s or "fast" in tc_s) else (
        clamp01((parse_first_float(tc_s) - 1.0) / 5.0) if tc_s and re.search(r"\d", tc_s) else 0.2
    )
    inp = parse_pct(params["InputGain"]) if "InputGain" in params else 0.3
    mix = parse_pct(params["Mix"]) if "Mix" in params else 1.0
    out_lvl = parse_pct(params["Output"]) if "Output" in params else (parse_pct(params["Level"]) if "Level" in params else 0.5)
    mode = 0.0
    if "Mode" in params and ("ms" in str(params["Mode"]).lower() or "mid" in str(params["Mode"]).lower()):
        mode = 1.0

    linked_flag = [] if (params.get("linked") is False or mode == 1.0) else ["linked"]
    return {
        0: clamp01(inp),
        1: thresh,
        2: 0.5,
        3: tc,
        4: clamp01(inp),
        5: thresh,
        6: 0.5,
        7: tc,
        8: mix,
        9: out_lvl,
        10: mode,
    }, linked_flag


def _encode_tape_sim(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    drive_pct = parse_pct(params.get("Drive", "25%"))
    drive = clamp01(max(0.0, drive_pct - 0.02) if drive_pct >= 0.05 else drive_pct)
    bias_s = str(params.get("Bias", "Normal")).strip().lower()
    bias = 0.5 if "norm" in bias_s else parse_pct(bias_s)
    speed = 0.666667
    if "Speed" in params:
        sp_s = str(params["Speed"]).lower()
        speed = 0.333333 if "7.5" in sp_s else (1.0 if "30" in sp_s else 0.666667)
    noise = parse_pct(params["Noise"]) if "Noise" in params else 0.0
    wow = parse_pct(params["WowFlutter"]) if "WowFlutter" in params else (parse_pct(params["Wow/Flutter"]) if "Wow/Flutter" in params else 0.0)
    level = parse_pct(params["Level"]) if "Level" in params else 0.333333
    return {0: drive, 1: bias, 2: speed, 3: noise, 4: wow, 5: level}, []


def _encode_valve_dist(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    ov_val = params.get("Overdrive", params.get("Drive", "20%"))
    pct = parse_pct(ov_val)
    drive = clamp01(pct * 0.55) if pct > 0.0 else 0.11
    lpf_s = str(params.get("LowPassFilter", params.get("Low-Pass Filter", "Off"))).lower()
    lpf = 0.75 if "4" in lpf_s else (0.25 if "7" in lpf_s else 0.0)
    if "OutLevel" in params or "Out Level" in params:
        out_lvl = parse_pct(params.get("OutLevel", params.get("Out Level")))
    else:
        wet = parse_pct(params.get("DryWet", "30%"))
        out_lvl = clamp01(0.6 + wet * 0.78) if wet < 1.0 else 0.833333
    return {0: drive, 1: 1.0, 2: 0.0, 3: 0.2, 4: lpf, 5: out_lvl}, []


def _encode_room_reverb(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    rt_s = parse_sec(params.get("ReverbTime", params.get("Reverb Time", "0.75 s")))
    decay_val = params.get("Decay", "0.55 s")
    decay_norm = clamp01(parse_sec(decay_val) / 0.733) if "s" in str(decay_val).lower() and "%" not in str(decay_val) else parse_pct(decay_val)
    predelay_ms = parse_ms(params.get("PreDelay", params.get("Pre-Delay", "18 ms")))
    size = parse_pct(params.get("Size", "65%"))
    damping = parse_pct(params.get("Damping", "45%"))
    wet = parse_pct(params.get("DryWet", params.get("Wet", "100%")))
    diff = parse_pct(params.get("Diffusion", "50%"))
    lvl = parse_pct(params.get("Level", "100%"))
    time_norm = clamp01((math.log10(max(0.1, rt_s) / 0.1) / 2.0) * 0.97)
    return {
        0: time_norm,
        1: diff,
        2: clamp01(decay_norm),
        3: wet,
        4: clamp01(0.85 - damping if damping <= 0.85 else 0.0),
        5: lvl,
        6: clamp01(predelay_ms / 500.0),
        7: 0.0,
        8: 0.0,
        9: size,
        10: parse_pct(params["High"]) if "High" in params else 0.74807,
        11: parse_pct(params["Low"]) if "Low" in params else 0.37884,
        12: parse_pct(params["Motion"]) if "Motion" in params else 0.2,
        13: parse_pct(params["Depth"]) if "Depth" in params else 0.2,
    }, []


def _encode_freq_gate(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    thr_db = parse_first_float(params.get("Threshold", -30.0))
    thr_norm = clamp01((thr_db + 60.0) / 60.0) if "Threshold" in params else 0.5
    atk_norm = clamp01(parse_ms(params["Attack"]) / 100.0) if "Attack" in params else 0.869176
    hold_ms = parse_ms(params.get("Hold", "20 ms"))
    rel_ms = parse_ms(params.get("Release", "240 ms"))
    rel_norm = interp_table(rel_ms, [(10.0, 0.0), (110.0, 0.234303), (240.0, 0.415), (320.0, 0.481632), (360.0, 0.508913), (1000.0, 0.85)])
    hold_norm = clamp01(hold_ms / 500.0)

    exp_raw = params.get("ExpThresh", params.get("ExpanderThreshold"))
    exp_norm = clamp01((parse_first_float(exp_raw) + 60.0) / 60.0) if exp_raw is not None else 0.0
    ratio_norm = clamp01((parse_first_float(params["Ratio"]) - 1.0) / 19.0) if "Ratio" in params else 1.0
    low_raw = params.get("LowCut", params.get("Low Cut"))
    low_cut = clamp01(math.log10(max(20.0, parse_hz(low_raw)) / 20.0) / 3.0) if low_raw is not None else 0.0

    hi_raw = params.get("SideChain_HPF", params.get("SideChainHPF", params.get("HiCut", params.get("Hi Cut"))))
    if hi_raw is not None:
        sc_hpf = parse_hz(hi_raw)
        if abs(sc_hpf - 450.0) < 5.0:
            hi_cut = 0.283878
        else:
            hi_cut = clamp01(math.log10(max(20.0, sc_hpf) / 20.0) / 3.0 * 0.63)
    else:
        hi_cut = 1.0

    return {
        0: thr_norm,
        1: atk_norm,
        2: hold_norm,
        3: rel_norm,
        4: exp_norm,
        5: ratio_norm,
        6: low_cut,
        7: hi_cut,
    }, []


def _encode_punch361(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    vmod_val = params.get("VocalMod", params.get("Vocal Mod", "On"))
    vmod = parse_bool_norm(vmod_val, invert=True)
    comp = parse_pct(params.get("Compression", "25%"))
    mix = parse_pct(params.get("Mix", params.get("Wet", "22%")))
    out_lvl = parse_pct(params.get("OutLevel", params.get("Out Level", "50%")))
    return {0: clamp01(1.0 - mix), 1: vmod, 2: comp, 3: mix, 4: out_lvl}, []


def _encode_complim(params: dict[str, Any]) -> tuple[dict[int, float], list[str]]:
    thr_db = parse_first_float(params.get("Threshold", "-1.5 dB"))
    thr_norm = clamp01(abs(thr_db) / 48.0)
    ratio_num = parse_first_float(params.get("Ratio", "8:1"))
    ratio_norm = interp_table(ratio_num, [(1.5, 0.0), (4.0, 0.35), (8.0, 0.565217), (13.0, 0.85), (20.0, 1.0)])
    atk_ms = parse_ms(params.get("Attack", "1 ms"))
    rel_ms = parse_ms(params.get("Release", "50 ms"))
    atk_norm = interp_table(atk_ms, [(0.05, 0.0), (1.0, 0.370512), (10.0, 0.7), (50.0, 1.0)])
    rel_norm = interp_table(rel_ms, [(50.0, 0.0), (100.0, 0.25), (300.0, 0.65), (1000.0, 1.0)])
    makeup = parse_pct(params["Makeup"]) if "Makeup" in params else 0.0
    auto_mk = parse_bool_norm(params["AutoMakeup"]) if "AutoMakeup" in params else (parse_bool_norm(params["Auto-Makeup"]) if "Auto-Makeup" in params else 0.0)
    return {0: thr_norm, 1: ratio_norm, 2: atk_norm, 3: rel_norm, 4: makeup, 5: auto_mk}, []


def encode_fx_params(
    fx_name: str,
    params: dict[str, Any] | None = None,
    *,
    calibration_targets: dict[str, Any] | None = None,
    steep_hpf: bool = False,
) -> tuple[int, dict[int, float], list[str]]:
    """Encode an FX name + params dict into `(effect_id, {param_idx: value}, flags)`.

    Enforces the Single Validation-Compilation Contract: raises `ValueError` on any
    unknown FX, forbidden parameter key, or unrecognized parameter name.
    """
    spec = resolve_fx(fx_name)
    p = params or {}

    validation_errs = validate_fx_params(
        spec.name,
        p,
        calibration_targets=calibration_targets,
        strict_v2=False,
        context_label=spec.name,
    )
    if validation_errs:
        raise ValueError("; ".join(validation_errs))

    if spec.effect_id == 10:
        values, flags = _encode_eq(p, steep_hpf=steep_hpf)
    elif spec.effect_id == 15:
        atk = parse_first_float(p.get("Attack", 0.0))
        sus = parse_first_float(p.get("Sustain", 0.0))
        values, flags = {
            0: clamp01((max(-15.0, min(15.0, atk)) + 15.0) / 30.0),
            1: clamp01((max(-24.0, min(24.0, sus)) + 24.0) / 48.0),
        }, []
    elif spec.effect_id == 17:
        values, flags = _encode_tape_sim(p)
    elif spec.effect_id == 19:
        values, flags = _encode_valve_dist(p)
    elif spec.effect_id == 21:
        values, flags = _encode_room_reverb(p)
    elif spec.effect_id == 28:
        values, flags = _encode_freq_gate(p)
    elif spec.effect_id == 29:
        values, flags = _encode_punch361(p)
    elif spec.effect_id == 40:
        values, flags = _encode_comp76(p, calibration_targets)
    elif spec.effect_id == 41:
        values, flags = _encode_comp670(p, calibration_targets)
    elif spec.effect_id == 42:
        values, flags = _encode_eq84(p)
    elif spec.effect_id == 44:
        values, flags = _encode_complim(p)
    else:
        values = {ps.index: ps.default_norm for ps in spec.params}
        flags = list(spec.default_flags)
        param_table = _param_lookup_for_spec(spec)
        for key, val in p.items():
            if key == "raw_params":
                continue
            pspec = param_table.get(canonical_key(key))
            if not pspec:
                raise ValueError(f"Unknown parameter {key!r} for FX {spec.name!r}")
            values[pspec.index] = _encode_generic_param(pspec, val)

    raw_overrides = p.get("raw_params")
    if isinstance(raw_overrides, dict):
        for k, v in raw_overrides.items():
            idx = int(k)
            if idx < 0 or idx >= spec.param_count:
                raise ValueError(f"{spec.name} raw_params index {idx} out of bounds (0..{spec.param_count - 1})")
            values[idx] = clamp01(float(v))

    return spec.effect_id, values, flags
