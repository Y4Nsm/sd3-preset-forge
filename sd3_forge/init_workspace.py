"""Config-first, zero-proprietary workspace initialization (`sd3-forge init`)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sd3_forge.extract_gt import extract_inventory_to_file
from sd3_forge.generate_test_midi import generate_midi_and_manifest
from sd3_forge.paths import (
    default_base_template_path,
    default_inventory_path,
    detect_sd3_library_path,
    detect_sd3_vst3_path,
    detect_user_presets_dir,
    forge_data_dir,
    save_config,
)
from sd3_forge.sd3p_codec import unwrap_vc2_state


def _find_matching_brace(text: str, open_idx: int) -> int:
    depth = 0
    in_quotes = False
    n = len(text)
    i = open_idx
    while i < n:
        ch = text[i]
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    raise ValueError(f"Unclosed brace at offset {open_idx}")


def normalize_sd3p_to_neutral(raw_sd3p_text: str) -> str:
    """Strip FX, sends, custom pitches/envelopes, SongTrack paths, and dirty mixer state."""
    text = raw_sd3p_text.rstrip("\x00").replace("\r\n", "\n")

    # 1. Strip SongTrack / Drumtracker embedded data & local FileName leaks
    text = re.sub(r'(?m)^BouncePrefix\s+"[^"]*"', 'BouncePrefix ""', text)
    text = re.sub(r'(?m)^ChosenKitPresetName\s+"[^"]*"', 'ChosenKitPresetName ""', text)
    st_m = re.search(r"(?m)^SongTrack\s+\d+\s*\{", text)
    if st_m:
        o = text.find("{", st_m.start())
        c = _find_matching_brace(text, o)
        text = text[: st_m.start()] + "SongTrack 0 {\n}" + text[c + 1 :]

    # 2. Unload all instbox slots and clean pad pitch/envelope overrides
    out_parts: list[str] = []
    pos = 0
    for im in re.finditer(r"(?m)^instbox\s+(\d+)(?:\s+\"[^\"]*\")?\s*\{", text):
        if im.start() < pos:
            continue
        out_parts.append(text[pos : im.start()])
        o = text.find("{", im.start())
        c = _find_matching_brace(text, o)
        ib_idx = im.group(1)
        ib_body = text[o + 1 : c]
        ib_body = re.sub(r'(?m)^drum\s+.*$', 'drum -  "Drumsticks" 1', ib_body)
        # Clean pitch / AHDSR overrides inside pad blocks while keeping default mic maps
        ib_body = re.sub(r"(?m)^(?:pitch|fade|fadetime|fadeonset|decay|attack|hold|sustain)\s+.*\n?", "", ib_body)
        out_parts.append(f"instbox {ib_idx} {{{ib_body}}}")
        pos = c + 1
    out_parts.append(text[pos:])
    text = "".join(out_parts)

    # 3. Clean mixer { ... }: remove all effect/send blocks and reset levels/routing
    mix_m = re.search(r"(?m)^mixer\s*\{", text)
    if mix_m:
        mo = text.find("{", mix_m.start())
        mc = _find_matching_brace(text, mo)
        mix_body = text[mo + 1 : mc]

        cleaned_channels: list[str] = []
        mpos = 0
        for cm in re.finditer(r"(?m)^([A-Za-z0-9_-]+(?:\s+\d+)?)\s*\{", mix_body):
            if cm.start() < mpos:
                continue
            cleaned_channels.append(mix_body[mpos : cm.start()])
            ch_name = cm.group(1).strip()
            co = mix_body.find("{", cm.start())
            cc = _find_matching_brace(mix_body, co)
            ch_body = mix_body[co + 1 : cc]

            # Remove nested effect { ... } and send { ... } blocks
            stripped_sub: list[str] = []
            spos = 0
            for sm in re.finditer(r"(?m)^(?:effect|send)\s+\d+\s*\{", ch_body):
                if sm.start() < spos:
                    continue
                stripped_sub.append(ch_body[spos : sm.start()])
                so = ch_body.find("{", sm.start())
                sc = _find_matching_brace(ch_body, so)
                spos = sc + 1
            stripped_sub.append(ch_body[spos:])
            inner = "".join(stripped_sub)

            is_channel_pair_end = ch_name.endswith("R") or (
                (ch_name.startswith("buss ") or ch_name.startswith("output "))
                and int(ch_name.split()[1]) % 2 == 1
            )
            inner = re.sub(r"(?m)^volume\s+.*$", "volume 1", inner)
            inner = re.sub(r"(?m)^phasereverse\s+.*$", "phasereverse 0", inner)
            inner = re.sub(r"(?m)^solo\s+.*$", "solo 0", inner)
            inner = re.sub(r"(?m)^mute\s+.*$", "mute 0", inner)
            if ch_name.startswith("buss "):
                b_num = int(ch_name.split()[1])
                inner = re.sub(r"(?m)^hidden\s*\n?", "", inner)
                if b_num >= 10 and b_num % 2 == 0:
                    inner = inner.rstrip() + "\nhidden\n"
                inner = re.sub(r"(?m)^route\s+.*$", "route output 0" if b_num < 10 else "route output -1", inner)
            elif not ch_name.startswith("output "):
                inner = re.sub(r"(?m)^route\s+.*$", "route output 0", inner)
                if "leakvol " in inner:
                    inner = re.sub(r"(?m)^leakvol\s+.*$", "leakvol 1", inner)
                if "nobleed " in inner:
                    inner = re.sub(r"(?m)^nobleed\s+.*$", "nobleed 0", inner)
            elif is_channel_pair_end:
                inner = re.sub(r"(?m)^pan\s+.*$", "pan 1", inner)

            # Clean extra blank lines
            inner_lines = [ln for ln in inner.splitlines() if ln.strip() != ""]
            cleaned_channels.append(f"{ch_name} {{\n" + "\n".join(inner_lines) + "\n}")
            mpos = cc + 1
        cleaned_channels.append(mix_body[mpos:])
        text = text[: mo + 1] + "".join(cleaned_channels) + text[mc:]

    # 4. Ensure non-empty clean tail lines
    return text.strip() + "\n"


def _synthesize_minimal_sd3p(uberconf_text: str, micconf_text: str) -> str:
    """Synthesize a clean minimal `.sd3p` skeleton from `uberconf` and `micconf` when `s3presetconf` is absent."""
    from sd3_forge.extract_gt import parse_micconf, parse_uberconf

    uber = parse_uberconf(uberconf_text)
    mics = parse_micconf(micconf_text) if micconf_text.strip() else []
    ordered_slots = sorted(uber["positions"].values(), key=lambda p: p["slot_index"])

    lines: list[str] = [
        "PlugVersion 3.4.4",
        "SAMPLER {",
        "HQ {",
        'soundlib "SL-SUPERIOR_DRUMMER_3"',
        "mastervol 1",
        "mastervol2 1",
        "}",
        "xmics {",
        "}",
    ]
    mic_names = [m["internal_name"] for m in mics] or ["Kick-In", "SnareTop", "Oh-Beyer", "Ambience-R88"]
    for idx, slot in enumerate(ordered_slots):
        lines.extend(
            [
                f"instbox {idx} {{",
                "xpad 0 SL-SUPERIOR_DRUMMER_3 {",
                f'pos "{slot["slot_id"]}"',
                "mastermics {",
                "nrmaster 0",
                "close 0 0 0",
                "}",
                'drum -  "Drumsticks" 1',
                "pads {",
                "pad default {",
                "}",
                "}",
                "}",
                "InstrumentType Undefined",
                "}",
            ]
        )

    lines.append("mixer {")
    for m in mics:
        lines.extend(
            [
                f"{m['internal_name']} {{",
                f"pan {m['default_pan'] if not m['stereo'] else 0}",
                "volume 1",
                "phasereverse 0",
                "nobleed 0",
                "xtrafade 0",
                "leakvol 1",
                "solo 0",
                "mute 0",
                "route output 0",
                "}",
            ]
        )
        if m["stereo"]:
            lines.extend(
                [
                    f"{m['internal_name']}R {{",
                    "pan 1",
                    "volume 1",
                    "phasereverse 0",
                    "nobleed 0",
                    "xtrafade 0",
                    "leakvol 1",
                    "solo 0",
                    "mute 0",
                    "route output 0",
                    "}",
                ]
            )
    if not mics:
        for ch in mic_names:
            lines.extend([f"{ch} {{", "pan 0.5", "volume 1", "phasereverse 0", "solo 0", "mute 0", "route output 0", "}"])
    for b in range(64):
        hidden = "\nhidden" if (b >= 10 and b % 2 == 0) else ""
        rt = "output 0" if b < 10 else "output -1"
        lines.extend([f"buss {b} {{", f"pan {b % 2}", "volume 1", "phasereverse 0", f"solo 0\nmute 0{hidden}", f"route {rt}", "}"])
    for o in range(32):
        lines.extend([f"output {o} {{", f"pan {o % 2}", "volume 1", "phasereverse 0", "solo 0", "mute 0", "}"])
    lines.extend(["}", "macros {", "}", "}", "SongTrack 0 {", "}", ""])
    return "\n".join(lines)


def _extract_first_s3presetconf_block(s3presetconf_text: str) -> str | None:
    """Convert first preset entry in `s3presetconf` into a clean standalone `.sd3p` text."""
    # Find first quoted preset block with `instbox 0` and `mixer {`
    m = re.search(r'(?m)^"[^"]+"\s*\{', s3presetconf_text)
    if not m:
        return None
    o = s3presetconf_text.find("{", m.start())
    c = _find_matching_brace(s3presetconf_text, o)
    body = s3presetconf_text[o + 1 : c]
    ib_start = body.find("instbox 0")
    if ib_start == -1 or "mixer {" not in body:
        return None
    ezx_m = re.search(r'(?m)^EZX\s+"([^"]+)"', body)
    lib_id = ezx_m.group(1) if ezx_m else "SL-SUPERIOR_DRUMMER_3"
    core_body = body[ib_start:]
    return (
        f'PlugVersion 3.4.4\nSAMPLER {{\nHQ {{\nsoundlib "{lib_id}"\nmastervol 1\nmastervol2 1\n}}\n'
        f"xmics {{\n}}\n{core_body}\n}}\nSongTrack 0 {{\n}}\n"
    )


def build_neutral_base_sd3p(
    sd3_library_path: Path | None,
    vst3_path: Path | None = None,
    from_vst3: bool = False,
) -> bytes:
    """Build a normalized neutral `.sd3p` baseline from local config files (or VST3)."""
    raw_text: str | None = None

    if from_vst3:
        resolved_vst3 = vst3_path or detect_sd3_vst3_path()
        if resolved_vst3 is None or not resolved_vst3.exists():
            raise FileNotFoundError(f"SD3 VST3 plugin not found: {resolved_vst3}")
        try:
            from pedalboard import load_plugin
        except ImportError as exc:
            raise RuntimeError(
                "Capturing base template from VST3 requires `pip install 'sd3-preset-forge[render]'`."
            ) from exc
        plug = load_plugin(str(resolved_vst3))
        _, blob = unwrap_vc2_state(plug.raw_state)
        j_idx = blob.find(b"\x00\x00\x00\x00\x00\x00\x00\x00JUCEPrivateData")
        end_idx = j_idx if j_idx != -1 else len(blob)
        raw_text = blob[176:end_idx].rstrip(b"\x00").decode("utf-8", errors="replace")
    else:
        if sd3_library_path and (sd3_library_path / "s3presetconf").exists():
            s3pc_text = (sd3_library_path / "s3presetconf").read_bytes().decode("utf-8", errors="replace")
            raw_text = _extract_first_s3presetconf_block(s3pc_text)
        if raw_text is None:
            if sd3_library_path and (sd3_library_path / "uberconf").exists():
                uber_txt = (sd3_library_path / "uberconf").read_text(encoding="utf-8", errors="replace")
                mic_txt = (
                    (sd3_library_path / "micconf").read_text(encoding="utf-8", errors="replace")
                    if (sd3_library_path / "micconf").exists()
                    else ""
                )
                raw_text = _synthesize_minimal_sd3p(uber_txt, mic_txt)
            else:
                raise FileNotFoundError(
                    "Cannot synthesize base .sd3p without SD3 library `s3presetconf` or `uberconf`."
                )

    neutral = normalize_sd3p_to_neutral(raw_text)
    return neutral.encode("utf-8") + b"\x00"


def run_init(
    sd3_path: Path | None = None,
    vst3_path: Path | None = None,
    presets_dir: Path | None = None,
    from_vst3: bool = False,
    generate_midi_files: bool = True,
) -> dict[str, Any]:
    """Initialize local user configuration, Ground Truth inventory, clean `.sd3p` template, and test MIDI."""
    resolved_lib = sd3_path or detect_sd3_library_path()
    if resolved_lib is None or not resolved_lib.exists():
        raise FileNotFoundError(
            f"SD3 library path not found: {resolved_lib}. "
            "Pass `--sd3-path <dir>` or set SD3_LIBRARY_PATH."
        )

    resolved_vst3 = vst3_path or detect_sd3_vst3_path()
    resolved_presets = presets_dir or detect_user_presets_dir()

    cfg: dict[str, Any] = {
        "sd3_library_path": str(resolved_lib),
        "sd3_presets_dir": str(resolved_presets),
    }
    if resolved_vst3 is not None:
        cfg["sd3_vst3_path"] = str(resolved_vst3)
    cfg_path = save_config(cfg)

    inv_path = extract_inventory_to_file(sd3_path=resolved_lib, out_path=default_inventory_path())

    tpl_bytes = build_neutral_base_sd3p(resolved_lib, vst3_path=resolved_vst3, from_vst3=from_vst3)
    tpl_path = default_base_template_path()
    tpl_path.parent.mkdir(parents=True, exist_ok=True)
    tpl_path.write_bytes(tpl_bytes)

    midi_path_str: str | None = None
    manifest_path_str: str | None = None
    if generate_midi_files:
        midi_p, man_p = generate_midi_and_manifest(forge_data_dir() / "test-suite")
        midi_path_str = str(midi_p)
        manifest_path_str = str(man_p)

    return {
        "ok": True,
        "config_path": str(cfg_path),
        "inventory_path": str(inv_path),
        "base_template_path": str(tpl_path),
        "base_template_source": "vst3" if from_vst3 else "config",
        "midi_path": midi_path_str,
        "manifest_path": manifest_path_str,
    }
