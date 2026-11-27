"""Pure-Python codec for Toontrack Superior Drummer 3 (.sd3p) and VST3 VC2! state.

Handles:
- JUCE MemoryBlock::toBase64Encoding decode/encode (`.A-Za-z0-9+`, LSB-first 6-bit)
- VST3 `VC2!` / `VstW` / `CcnK` / `FBCh` container unwrap and wrap
- Unit conversions (`dB` -> linear, `semitones` -> pitch ratio, `pan` strings -> 0..1)
- Parameter-accurate serialization for all 35 SD3 native Mixer inserts via `fx_catalog`
"""

from __future__ import annotations

import re
import struct
from typing import Any

from sd3_forge.fx_catalog import (  # noqa: F401
    NATIVE_FX_IDS,
    encode_fx_params,
    parse_band_spec,
    parse_first_float,
    parse_hz,
    parse_ms,
    parse_pct,
    parse_sec,
)

# JUCE MemoryBlock::toBase64Encoding alphabet (index 0..63)
JUCE_B64_ALPHA = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"
_JUCE_B64_REV = {ch: idx for idx, ch in enumerate(JUCE_B64_ALPHA)}

# Part 1 fallback UI mic name -> (primary_sd3_channel, secondary_right_channel_or_None)
UI_MIC_TO_SD3: dict[str, tuple[str, str | None]] = {
    "Kick In": ("Kick-In", None),
    "Kick Out": ("Kick-Out", None),
    "Kick Sub": ("Kick-Sub", None),
    "Snare Top": ("SnareTop", None),
    "Snare Bottom": ("SnareBottom", "SnareBottomR"),
    "Hi-Hat": ("Hats", None),
    "Racktom 1": ("Tom1", None),
    "Racktom 2": ("Tom2", None),
    "Racktom 3": ("Tom3", None),
    "Floortom 1": ("Tom4", None),
    "Floortom 2": ("Tom5", None),
    "OH Dyn": ("Oh-Beyer", "Oh-BeyerR"),
    "Amb Ribbon": ("Ambience-R88", "Ambience-R88R"),
}

BUS_NAME_RE = re.compile(r"^Bus\s+(\d+)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# JUCE Base64 & VC2! VST3 container codec
# ---------------------------------------------------------------------------


def juce_b64_decode(encoded: str) -> bytes:
    """Decode JUCE MemoryBlock::toBase64Encoding string (`<byte_len>.<chars>`)."""
    if "." not in encoded:
        raise ValueError("Invalid JUCE base64 string: missing size '.' separator")
    size_str, data = encoded.split(".", 1)
    num_bytes = int(size_str)
    out = bytearray(num_bytes)
    pos = 0
    n = len(data)
    for i in range(0, n, 4):
        c0 = _JUCE_B64_REV[data[i]]
        c1 = _JUCE_B64_REV[data[i + 1]] if i + 1 < n else 0
        c2 = _JUCE_B64_REV[data[i + 2]] if i + 2 < n else 0
        c3 = _JUCE_B64_REV[data[i + 3]] if i + 3 < n else 0
        v = c0 | (c1 << 6) | (c2 << 12) | (c3 << 18)
        if pos < num_bytes:
            out[pos] = v & 0xFF
            pos += 1
        if pos < num_bytes:
            out[pos] = (v >> 8) & 0xFF
            pos += 1
        if pos < num_bytes:
            out[pos] = (v >> 16) & 0xFF
            pos += 1
    return bytes(out)


def juce_b64_encode(raw: bytes) -> str:
    """Encode raw bytes using JUCE MemoryBlock::toBase64Encoding (`<byte_len>.<chars>`)."""
    n = len(raw)
    out: list[str] = [f"{n}."]
    for i in range(0, n, 3):
        b0 = raw[i]
        b1 = raw[i + 1] if i + 1 < n else 0
        b2 = raw[i + 2] if i + 2 < n else 0
        v = b0 | (b1 << 8) | (b2 << 16)
        out.append(JUCE_B64_ALPHA[v & 0x3F])
        out.append(JUCE_B64_ALPHA[(v >> 6) & 0x3F])
        out.append(JUCE_B64_ALPHA[(v >> 12) & 0x3F])
        out.append(JUCE_B64_ALPHA[(v >> 18) & 0x3F])
    return "".join(out)


def unwrap_vc2_state(raw_state: bytes) -> tuple[str, bytes]:
    """Extract (xml_str, decoded_icomponent_blob) from VST3 VC2! raw_state."""
    if len(raw_state) < 8 or raw_state[:4] != b"VC2!":
        raise ValueError("raw_state does not start with 'VC2!' magic")
    xml_len = struct.unpack_from("<I", raw_state, 4)[0]
    xml_bytes = raw_state[8 : 8 + xml_len]
    xml_str = xml_bytes.decode("utf-8")
    m = re.search(r"<IComponent>(.*?)</IComponent>", xml_str, re.S)
    if not m:
        raise ValueError("Missing <IComponent> tag inside VC2! XML")
    blob = juce_b64_decode(m.group(1))
    return xml_str, blob


def wrap_vc2_state(template_xml: str, template_blob: bytes, sd3p_bytes: bytes) -> bytes:
    """Wrap `.sd3p` payload inside JUCE VC2! VST3 raw_state using a captured template header/trailer."""
    if len(template_blob) < 176 or template_blob[:4] != b"VstW" or template_blob[16:20] != b"CcnK":
        raise ValueError("Unexpected IComponent template_blob header")

    trailer_idx = template_blob.find(b"\x00\x00\x00\x00\x00\x00\x00\x00JUCEPrivateData")
    if trailer_idx == -1:
        trailer_idx = template_blob.find(b"JUCEPrivateData")
        if trailer_idx != -1:
            trailer_idx = max(176, trailer_idx - 8)
    trailer = template_blob[trailer_idx:] if trailer_idx != -1 else b""

    payload = sd3p_bytes if sd3p_bytes.endswith(b"\x00") else sd3p_bytes + b"\x00"
    inner = payload + trailer

    prefix = bytearray(template_blob[:176])
    struct.pack_into(">I", prefix, 20, 152 + len(inner))
    struct.pack_into(">I", prefix, 172, len(inner))

    new_blob = bytes(prefix) + inner
    b64 = juce_b64_encode(new_blob)
    new_xml = re.sub(
        r"<IComponent>.*?</IComponent>",
        lambda _: f"<IComponent>{b64}</IComponent>",
        template_xml,
        count=1,
        flags=re.S,
    )
    new_xml_bytes = new_xml.encode("utf-8")
    return b"VC2!" + struct.pack("<I", len(new_xml_bytes)) + new_xml_bytes + b"\x00"


# ---------------------------------------------------------------------------
# Unit conversions & string parsers
# ---------------------------------------------------------------------------


def db_to_linear(db: float) -> float:
    """Convert decibels to SD3 linear gain multiplier."""
    if db <= -120.0:
        return 0.0
    return 10.0 ** (db / 20.0)


def semitones_to_pitch(st: float) -> float:
    """Convert tuning in semitones to SD3 playback pitch ratio."""
    return 2.0 ** (st / 12.0)


def pan_str_to_norm(pan: Any) -> float:
    """Convert UI pan string ('C', 'L35', 'R28', 'L100', or numeric) to SD3 0..1 pan."""
    if isinstance(pan, (int, float)):
        return max(0.0, min(1.0, float(pan)))
    s = str(pan).strip().upper()
    if s in ("C", "CENTER", "0"):
        return 0.5
    if "/" in s:
        left, _ = pan_str_to_stereo_pair(s)
        return left
    m = re.match(r"^([LR])\s*(\d+(?:\.\d+)?)$", s)
    if m:
        side, amt = m.group(1), float(m.group(2))
        norm = 0.5 - (amt / 200.0) if side == "L" else 0.5 + (amt / 200.0)
        return max(0.0, min(1.0, norm))
    raise ValueError(f"Unrecognized pan format: {pan!r}")


def pan_str_to_stereo_pair(pan: Any) -> tuple[float, float]:
    """Convert stereo UI pan ('L100/R100', 'L60/R60', 'C', 'L35') into `(left_0_1, right_0_1)`."""
    if isinstance(pan, (int, float)):
        v = max(0.0, min(1.0, float(pan)))
        return v, v
    s = str(pan).strip().upper()
    if s in ("C", "CENTER", "0"):
        return 0.5, 0.5
    if "/" in s:
        left_part, right_part = (p.strip() for p in s.split("/", 1))
        return pan_str_to_norm(left_part), pan_str_to_norm(right_part)
    single = pan_str_to_norm(s)
    return single, single


def route_to_sd3(route_str: str) -> str:
    """Map UI route string ('Bus 1 (...)', 'Output 1/2') to SD3 route target."""
    s = route_str.strip()
    if s.lower().startswith("output"):
        return "output 0"
    m = BUS_NAME_RE.match(s)
    if m:
        bus_idx = int(m.group(1)) - 1
        if bus_idx < 0:
            raise ValueError(f"Invalid bus index in route: {route_str!r}")
        return f"buss {bus_idx}"
    raise ValueError(f"Unsupported route target: {route_str!r}")


def bus_name_to_sd3_pair(bus_name: str) -> tuple[str, str, int]:
    """Return ('buss 2k', 'buss 2k+1', bus_idx) for 'Bus N (...)'."""
    m = BUS_NAME_RE.match(bus_name.strip())
    if not m:
        raise ValueError(f"Invalid bus name: {bus_name!r}")
    bus_idx = int(m.group(1)) - 1
    if bus_idx < 0 or bus_idx > 31:
        raise ValueError(f"Bus index out of range (1..32): {bus_name!r}")
    return f"buss {2 * bus_idx}", f"buss {2 * bus_idx + 1}", bus_idx


def normalize_name(name: str) -> str:
    """Normalize SD3 piece/drum names (`^` caret quotes -> double quotes, collapse whitespace)."""
    return " ".join(str(name).replace("^", '"').strip().split())


def fmt_num(x: float) -> str:
    """Format float compactly like SD3 `.sd3p` serializer."""
    if abs(x) < 1e-9:
        return "0"
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.6g}"


def encode_effect_block(
    slot_idx: int,
    fx_name: str,
    params: dict[str, Any] | None = None,
    *,
    calibration_targets: dict[str, Any] | None = None,
    steep_hpf: bool = False,
    active: bool = True,
    sidechain: str = "",
) -> str:
    """Serialize one blueprint insert into an SD3 `.sd3p` `effect {slot_idx} { ... }` block."""
    fx_id, values, flags = encode_fx_params(
        fx_name,
        params,
        calibration_targets=calibration_targets,
        steep_hpf=steep_hpf,
    )
    sc_clean = str(sidechain).replace('"', "")
    lines = [
        f"effect {slot_idx} {{",
        f'sidechain "{sc_clean}"',
        f"effect {fx_id}",
        f"active {1 if active else 0}",
    ]
    for k in sorted(values):
        lines.append(f"{k} {fmt_num(values[k])}")
    for fl in flags:
        lines.append(fl)
    lines.append("}")
    return "\n".join(lines)
