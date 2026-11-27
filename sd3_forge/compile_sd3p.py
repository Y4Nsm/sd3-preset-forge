"""Lossless compiler from validated Blueprint IR (`v1` or `v2`) into native SD3 `.sd3p` files."""

from __future__ import annotations

import json
import re
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from sd3_forge.models import (
    BleedChannel,
    BlueprintV2,
    DrumEnvelope,
    InsertFx,
    SendConfig,
    StackLayer,
    load_blueprint_ir,
)
from sd3_forge.paths import default_base_template_path, default_inventory_path, detect_user_presets_dir
from sd3_forge.sd3p_codec import (
    UI_MIC_TO_SD3,
    bus_name_to_sd3_pair,
    db_to_linear,
    encode_effect_block,
    fmt_num,
    normalize_name,
    pan_str_to_norm,
    pan_str_to_stereo_pair,
    route_to_sd3,
    semitones_to_pitch,
)
from sd3_forge.validate_blueprint import validate_blueprint_ir, validate_spec_targets

_CLOSE_MIC_EQ_CHANNELS = {
    "Kick-In",
    "Kick-Out",
    "Kick-Sub",
    "SnareTop",
    "SnareBottom",
    "Hats",
    "Tom1",
    "Tom2",
    "Tom3",
    "Tom4",
    "Tom5",
}


def _find_matching_brace(text: str, open_idx: int) -> int:
    """Return index of matching `}` for `{` at `open_idx`, respecting quotes."""
    depth = 0
    in_quotes = False
    i = open_idx
    n = len(text)
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
    raise ValueError(f"Unclosed brace starting at offset {open_idx}")


def _find_named_block(text: str, header_regex: str, start: int = 0, end: int | None = None) -> tuple[int, int, int] | None:
    """Find `(block_start, open_brace_idx, close_brace_idx)` for top/nested block."""
    search_slice = text[start:end] if end is not None else text[start:]
    m = re.search(header_regex, search_slice, re.M)
    if not m:
        return None
    block_start = start + m.start()
    open_idx = text.find("{", block_start)
    if open_idx == -1 or (end is not None and open_idx >= end):
        return None
    close_idx = _find_matching_brace(text, open_idx)
    return block_start, open_idx, close_idx


def _build_piece_lookup(inventory: dict[str, Any]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for slot, slot_data in inventory.get("positions", {}).items():
        for p in slot_data.get("pieces", []):
            lookup[(slot, normalize_name(p["name"]).lower())] = p["id"]
    return lookup


def _build_stack_lookup(inventory: dict[str, Any]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for cat, items in inventory.get("stack_pack", {}).items():
        for item in items:
            lookup[(cat, normalize_name(item["name"]).lower())] = item["id"]
    return lookup


def _slot_matches_bleed_source(slot: str, source_token: str) -> bool:
    if source_token == "All":
        return True
    if source_token == "Kick":
        return slot in {"Kick", "KickR", "KickL"}
    if source_token == "Snare":
        return slot in {"Snare", "SnareR", "SnareL"}
    if source_token in {"Hats", "Hi-Hat"}:
        return slot == "Hats"
    if source_token == "Toms":
        return slot.startswith("Tom")
    if source_token == "Cymbals":
        return slot.startswith(("Cymbal", "Ride"))
    return slot.lower() == source_token.lower()


def _resolve_channel_map(inventory: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    ch_map: dict[str, tuple[str, str | None]] = dict(UI_MIC_TO_SD3)
    inv_map = inventory.get("microphones", {}).get("channel_map", {})
    for mixname, pair in inv_map.items():
        if isinstance(pair, list) and len(pair) >= 2:
            ch_map[mixname] = (str(pair[0]), str(pair[1]))
        elif isinstance(pair, list) and len(pair) == 1:
            ch_map[mixname] = (str(pair[0]), None)
    return ch_map


def _apply_pad_bleed(
    lines: list[str],
    *,
    slot: str,
    close_mics: set[str],
    bleed_channels: list[BleedChannel],
    channel_map: dict[str, tuple[str, str | None]],
) -> list[str]:
    if not bleed_channels:
        return lines

    # Extract existing `usemic` tokens and `leakvolume` pairs
    usemic_tokens: list[str] = []
    has_usemic = False
    leak_pairs: dict[str, str] = {}
    other_lines: list[str] = []

    for ln in lines:
        s = ln.strip()
        if s.startswith("usemic "):
            has_usemic = True
            toks = re.findall(r'"([^"]+)"|(\S+)', s[len("usemic ") :])
            for q, u in toks:
                tok = q or u
                if tok and tok not in usemic_tokens:
                    usemic_tokens.append(tok)
        elif s.startswith("leakvolume "):
            for ch_name, val_s in re.findall(r'"([^"]+)"\s+([-0-9.eE]+)', s):
                leak_pairs[ch_name] = val_s
        else:
            other_lines.append(ln)

    for b_cfg in bleed_channels:
        pair = channel_map.get(b_cfg.channel)
        if not pair:
            continue
        internals = [c for c in pair if c]
        allowed = b_cfg.enabled and any(_slot_matches_bleed_source(slot, src) for src in b_cfg.sources)

        for ch_int in internals:
            is_close = ch_int in close_mics
            if allowed:
                if has_usemic or bleed_channels:
                    if ch_int not in usemic_tokens:
                        usemic_tokens.append(ch_int)
            elif not is_close and ch_int in usemic_tokens:
                usemic_tokens.remove(ch_int)

        # Apply source_levels_db on the primary internal channel
        matched_db: float | None = None
        if b_cfg.source_levels_db:
            if slot in b_cfg.source_levels_db:
                matched_db = float(b_cfg.source_levels_db[slot])
            else:
                for src_k, lvl_db in b_cfg.source_levels_db.items():
                    if _slot_matches_bleed_source(slot, src_k):
                        matched_db = float(lvl_db)
                        break
        if allowed and matched_db is not None:
            leak_pairs[internals[0]] = fmt_num(db_to_linear(matched_db))

    rebuilt: list[str] = []
    if usemic_tokens:
        rebuilt.append("usemic " + " ".join(f'"{t}"' for t in usemic_tokens))
    rebuilt.extend(other_lines)
    if leak_pairs:
        rebuilt.append("leakvolume " + " ".join(f'"{k}" {v}' for k, v in leak_pairs.items()))
    return rebuilt


def _update_pad_block(
    pad_body: str,
    *,
    slot: str,
    pitch_st: float,
    level_db: float,
    envelope: DrumEnvelope | None,
    is_cymbal: bool,
    close_mics: set[str],
    bleed_channels: list[BleedChannel],
    channel_map: dict[str, tuple[str, str | None]],
) -> str:
    """Update pitch, pvolume, AHDSR envelope, and per-source bleed inside one `pad ... { ... }` body."""
    lines = [ln for ln in pad_body.splitlines() if ln.strip() != ""]
    lines = [ln for ln in lines if not ln.startswith("pitch ")]

    if abs(level_db) > 1e-6:
        lines = [ln for ln in lines if not ln.startswith("pvolume ")]
        lines.append(f"pvolume {fmt_num(db_to_linear(level_db))}")

    lines = _apply_pad_bleed(
        lines,
        slot=slot,
        close_mics=close_mics,
        bleed_channels=bleed_channels,
        channel_map=channel_map,
    )

    if envelope is not None and not is_cymbal:
        has_any_env = (
            envelope.attack_ms > 0.0
            or envelope.hold_ms is not None
            or envelope.decay_ms is not None
            or envelope.sustain_db is not None
            or envelope.release_ms is not None
        )
        if has_any_env:
            lines = [
                ln
                for ln in lines
                if not ln.startswith(("fade ", "fadeonset ", "attack ", "hold ", "decay ", "sustain ", "fadetime "))
            ]
            lines.append("fade 1")
            if envelope.attack_ms > 0.0:
                lines.append(f"attack {fmt_num(envelope.attack_ms / 1000.0)}")
            if envelope.hold_ms is not None:
                lines.append(f"fadeonset {fmt_num(envelope.hold_ms / 1000.0)}")
            if envelope.decay_ms is not None:
                lines.append(f"decay {fmt_num(envelope.decay_ms / 1000.0)}")
            if envelope.sustain_db is not None:
                lines.append(f"sustain {fmt_num(db_to_linear(envelope.sustain_db))}")
            if envelope.release_ms is not None:
                lines.append(f"fadetime {fmt_num(envelope.release_ms / 1000.0)}")

    if abs(pitch_st) > 1e-6:
        lines.append(f"pitch {fmt_num(semitones_to_pitch(pitch_st))}")

    return "\n".join(lines)


def _extract_mastermics_block(instbox_text: str) -> str:
    span = _find_named_block(instbox_text, r"^mastermics\s*\{")
    if span:
        s, _, e = span
        return instbox_text[s : e + 1]
    return "mastermics {\nnrmaster 0\nclose  0 0 0\n}"


def _strip_extra_xpads(instbox_text: str) -> str:
    """Remove existing `xpad <k> ... { ... }` blocks for k >= 1 while preserving `xpad 0`."""
    while True:
        span = _find_named_block(instbox_text, r"^xpad\s+[1-9]\d*\s+")
        if not span:
            break
        s, _, e = span
        after = e + 1
        if after < len(instbox_text) and instbox_text[after] == "\n":
            after += 1
        instbox_text = instbox_text[:s] + instbox_text[after:]
    return instbox_text


def _build_stack_xpads(
    stacks: list[StackLayer],
    *,
    stack_lookup: dict[tuple[str, str], str],
    mastermics_block: str,
) -> list[str]:
    blocks: list[str] = []
    for idx, layer in enumerate(stacks, start=1):
        stack_id = stack_lookup.get((layer.category, normalize_name(layer.name).lower()))
        if not stack_id:
            raise ValueError(f"Could not resolve StackPack ID for ({layer.category!r}, {layer.name!r})")
        pad_name = layer.pad_name or normalize_name(layer.category).replace(" ", "") or f"Stack{idx}"
        pad_lines = [
            "velocityknee L 5",
            "cycle S ",
            "velvol",
        ]
        if abs(layer.level_db) > 1e-6:
            pad_lines.append(f"pvolume {fmt_num(db_to_linear(layer.level_db))}")
        if abs(layer.pitch_semitones) > 1e-6:
            pad_lines.append(f"pitch {fmt_num(semitones_to_pitch(layer.pitch_semitones))}")
        blocks.append(
            "\n".join(
                [
                    f"xpad {idx} {layer.library_id} {{",
                    f'pos "{layer.category}"',
                    mastermics_block,
                    "laylims {",
                    "}",
                    f'drum "{stack_id}"  "Drumsticks" -1',
                    "pads {",
                    f"pad {pad_name} {{",
                    *pad_lines,
                    "}",
                    "}",
                    "}",
                ]
            )
        )
    return blocks


def _update_instbox(
    instbox_text: str,
    target_drum_id: str | None,
    slot: str,
    pitch_st: float,
    level_db: float,
    envelope: DrumEnvelope | None,
    stacks: list[StackLayer],
    stack_lookup: dict[tuple[str, str], str],
    close_mics: set[str],
    bleed_channels: list[BleedChannel],
    channel_map: dict[str, tuple[str, str | None]],
) -> str:
    """Update `drum` assignment, pad pitches/envelopes/bleed, and `xpad 1..K` stacks inside `instbox`."""
    instbox_text = _strip_extra_xpads(instbox_text)

    dm = re.search(r'(?m)^drum\s+([^\s]+)\s+"([^"]+)"\s+(\d+)\s*$', instbox_text)
    if dm:
        old_raw = dm.group(1)
        old_id = None if old_raw == "-" else old_raw.strip('"')
        old_tool = dm.group(2)
        old_flag = dm.group(3)
        if target_drum_id is None:
            new_drum_line = 'drum -  "Drumsticks" 1'
        else:
            if old_id == target_drum_id:
                tool, flag = old_tool, old_flag
            elif slot.startswith("Kick"):
                tool, flag = "Felt", "1"
            else:
                tool, flag = "Drumsticks", "1"
            new_drum_line = f'drum "{target_drum_id}"  "{tool}" {flag}'
        instbox_text = instbox_text[: dm.start()] + new_drum_line + instbox_text[dm.end() :]

    pads_span = _find_named_block(instbox_text, r"^pads\s*\{")
    if pads_span:
        _, pads_open, pads_close = pads_span
        pads_inner = instbox_text[pads_open + 1 : pads_close]
        is_cymbal = slot == "Hats" or slot.startswith(("Cymbal", "Ride"))

        out_parts: list[str] = []
        cursor = 0
        for pm in re.finditer(r"(?m)^pad\s+[A-Za-z0-9_]+\s*\{", pads_inner):
            if pm.start() < cursor:
                continue
            out_parts.append(pads_inner[cursor : pm.start()])
            pad_open = pads_inner.find("{", pm.start())
            pad_close = _find_matching_brace(pads_inner, pad_open)
            header = pads_inner[pm.start() : pad_open + 1]
            body = pads_inner[pad_open + 1 : pad_close]
            new_body = _update_pad_block(
                body,
                slot=slot,
                pitch_st=pitch_st,
                level_db=level_db,
                envelope=envelope,
                is_cymbal=is_cymbal,
                close_mics=close_mics,
                bleed_channels=bleed_channels,
                channel_map=channel_map,
            )
            out_parts.append(f"{header}\n{new_body}\n}}")
            cursor = pad_close + 1
        out_parts.append(pads_inner[cursor:])
        new_pads_inner = "".join(out_parts)
        instbox_text = instbox_text[: pads_open + 1] + new_pads_inner + instbox_text[pads_close:]

    if stacks and target_drum_id is not None:
        mastermics = _extract_mastermics_block(instbox_text)
        xpad_blocks = _build_stack_xpads(stacks, stack_lookup=stack_lookup, mastermics_block=mastermics)
        it_m = re.search(r"(?m)^InstrumentType\b", instbox_text)
        insert_pos = it_m.start() if it_m else instbox_text.rfind("}")
        instbox_text = (
            instbox_text[:insert_pos].rstrip()
            + "\n"
            + "\n".join(xpad_blocks)
            + "\n"
            + instbox_text[insert_pos:]
        )

    return instbox_text


def _encode_inserts(inserts: list[InsertFx], *, steep_hpf: bool) -> list[str]:
    blocks: list[str] = []
    for idx, ins in enumerate(inserts):
        cal = ins.calibration_targets.model_dump() if ins.calibration_targets else None
        blocks.append(
            encode_effect_block(
                idx,
                ins.fx,
                ins.params,
                calibration_targets=cal,
                steep_hpf=steep_hpf if ins.fx == "EQ" else False,
                active=ins.active,
                sidechain=ins.sidechain,
            )
        )
    return blocks


def _rewrite_channel_body(
    orig_body: str,
    *,
    pan: float,
    volume_linear: float,
    phasereverse: int,
    effects: list[str],
    route: str | None,
    sends: list[tuple[int, float, float, bool]],
    bleed_enabled: bool | None = None,
    bleed_linear: float | None = None,
    hidden: bool | None = None,
    clear_route: bool = False,
) -> str:
    """Rebuild one SD3 mixer channel body cleanly, preserving bleed defaults when unchanged."""
    nobleed_val = "0"
    xtrafade_val = "0"
    leakvol_val: str | None = None

    m_nb = re.search(r"(?m)^nobleed\s+(\d+)", orig_body)
    if m_nb:
        nobleed_val = m_nb.group(1)
    m_xf = re.search(r"(?m)^xtrafade\s+([-0-9.eE]+)", orig_body)
    if m_xf:
        xtrafade_val = m_xf.group(1)
    m_lv = re.search(r"(?m)^leakvol\s+([-0-9.eE]+)", orig_body)
    if m_lv:
        leakvol_val = m_lv.group(1)

    has_bleed_fields = any(x is not None for x in (m_nb, m_xf, m_lv))
    if bleed_enabled is not None:
        nobleed_val = "0" if bleed_enabled else "1"
        has_bleed_fields = True
    if bleed_linear is not None:
        leakvol_val = fmt_num(bleed_linear)
        has_bleed_fields = True

    lines: list[str] = [
        f"pan {fmt_num(pan)}",
        f"volume {fmt_num(volume_linear)}",
        f"phasereverse {phasereverse}",
    ]
    lines.extend(effects)
    if has_bleed_fields:
        lines.append(f"nobleed {nobleed_val}")
        lines.append(f"xtrafade {xtrafade_val}")
        if leakvol_val is not None:
            lines.append(f"leakvol {leakvol_val}")
    lines.append("solo 0")
    lines.append("mute 0")
    if hidden:
        lines.append("hidden")
    if route is not None and not clear_route:
        lines.append(f"route {route}")
    elif not clear_route:
        m_rt = re.search(r"(?m)^route\s+(.+)$", orig_body)
        if m_rt:
            lines.append(f"route {m_rt.group(1).strip()}")
    for send_bus_idx, send_pan, send_vol_lin, is_pre in sends:
        lines.extend(
            [
                f"send {send_bus_idx} {{",
                "active 1",
                f"pan {fmt_num(send_pan)}",
                f"volume {fmt_num(send_vol_lin)}",
                "pre" if is_pre else "post fader",
                "}",
            ]
        )
    return "\n" + "\n".join(lines) + "\n"


def _build_send_lists(
    sends: list[SendConfig],
    *,
    is_stereo: bool,
) -> tuple[list[tuple[int, float, float, bool]], list[tuple[int, float, float, bool]]]:
    sends_l: list[tuple[int, float, float, bool]] = []
    sends_r: list[tuple[int, float, float, bool]] = []
    for s in sends:
        _, _, dst_idx = bus_name_to_sd3_pair(s.bus)
        s_lin = db_to_linear(s.level_db)
        if s.pan is not None:
            p_l, p_r = pan_str_to_stereo_pair(s.pan)
        else:
            p_l = 0.0 if is_stereo else 0.5
            p_r = 1.0
        sends_l.append((dst_idx, p_l, s_lin, s.pre_fader))
        sends_r.append((dst_idx, p_r, s_lin, s.pre_fader))
    return sends_l, sends_r


def compile_blueprint_to_sd3p(
    preset_dir: Path,
    out_path: Path | None = None,
    template_path: Path | None = None,
    inventory_path: Path | None = None,
    install_to_sd3: bool = False,
    install_name: str | None = None,
) -> Path:
    """Compile `<preset_dir>/03-sd3-blueprint.yaml` into a ready-to-load `.sd3p` file."""
    resolved_inv = inventory_path or default_inventory_path()
    resolved_tpl = template_path or default_base_template_path()

    if not resolved_inv.exists():
        raise FileNotFoundError(f"Inventory file not found: {resolved_inv}. Run `sd3-forge init` first.")
    if not resolved_tpl.exists():
        raise FileNotFoundError(
            f"Base neutral template not found: {resolved_tpl}. "
            "Run `sd3-forge init` or pass `--template <path>`."
        )

    spec_res = validate_spec_targets(preset_dir / "02-spec-targets.yaml")
    if not spec_res.ok:
        raise ValueError(f"Spec targets validation failed for {preset_dir}:\n" + "\n".join(spec_res.errors))

    bp_path = preset_dir / "03-sd3-blueprint.yaml"
    if not bp_path.exists():
        raise FileNotFoundError(f"Blueprint file not found: {bp_path}")

    raw_bp = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    ir, _, is_v2 = load_blueprint_ir(raw_bp)
    inventory = json.loads(resolved_inv.read_text(encoding="utf-8"))

    bp_res = validate_blueprint_ir(ir, inventory, strict_v2=is_v2)
    if not bp_res.ok:
        raise ValueError(f"Blueprint validation failed for {preset_dir}:\n" + "\n".join(bp_res.errors))

    if ir.mix_mode != "internal_sd3":
        raise ValueError(f"Cannot compile non-internal mix_mode: {ir.mix_mode!r}")

    return compile_ir_to_sd3p(
        ir,
        inventory=inventory,
        template_path=resolved_tpl,
        out_path=out_path or (preset_dir / f"{ir.metadata.preset_id}.sd3p"),
        install_to_sd3=install_to_sd3,
        install_name=install_name,
    )


def compile_ir_to_sd3p(
    ir: BlueprintV2,
    *,
    inventory: dict[str, Any],
    template_path: Path,
    out_path: Path,
    install_to_sd3: bool = False,
    install_name: str | None = None,
) -> Path:
    """Compile an already-validated `BlueprintV2` IR object into `.sd3p` bytes."""
    piece_lookup = _build_piece_lookup(inventory)
    stack_lookup = _build_stack_lookup(inventory)
    channel_map = _resolve_channel_map(inventory)

    raw_tmpl = template_path.read_bytes()
    text = raw_tmpl.rstrip(b"\x00").decode("utf-8", errors="replace")

    piece_by_slot = {p.slot: p for p in ir.kit.pieces}
    unload_slots = set(ir.kit.unload_slots)
    bleed_channels = ir.bleed.channels

    for idx in range(32):
        span = _find_named_block(text, rf"^instbox {idx}\s*\{{")
        if not span:
            if idx >= 14:
                break
            continue
        b_start, _b_open, b_close = span
        ib_text = text[b_start : b_close + 1]
        pm = re.search(r'pos\s+"([^"]+)"', ib_text)
        if not pm:
            continue
        slot = pm.group(1)
        slot_close = set(inventory.get("positions", {}).get(slot, {}).get("close_mics", []))

        if slot in unload_slots:
            new_ib = _update_instbox(
                ib_text,
                target_drum_id=None,
                slot=slot,
                pitch_st=0.0,
                level_db=0.0,
                envelope=None,
                stacks=[],
                stack_lookup=stack_lookup,
                close_mics=slot_close,
                bleed_channels=[],
                channel_map=channel_map,
            )
        elif slot in piece_by_slot:
            p_cfg = piece_by_slot[slot]
            norm_name = normalize_name(p_cfg.name).lower()
            drum_id = piece_lookup.get((slot, norm_name))
            if not drum_id:
                raise ValueError(f"Could not resolve drum ID for {slot} -> {p_cfg.name!r}")
            new_ib = _update_instbox(
                ib_text,
                target_drum_id=drum_id,
                slot=slot,
                pitch_st=float(p_cfg.pitch_semitones),
                level_db=float(p_cfg.level_db),
                envelope=p_cfg.envelope,
                stacks=p_cfg.stacks,
                stack_lookup=stack_lookup,
                close_mics=slot_close,
                bleed_channels=bleed_channels,
                channel_map=channel_map,
            )
        else:
            continue

        text = text[:b_start] + new_ib + text[b_close + 1 :]

    mix_span = _find_named_block(text, r"^mixer\s*\{")
    if not mix_span:
        raise ValueError("Template missing top-level `mixer { ... }` block")
    _, mix_open, mix_close = mix_span
    mix_text = text[mix_open + 1 : mix_close]

    def replace_mixer_channel(ch_name: str, builder_fn: Any) -> None:
        nonlocal mix_text
        ch_span = _find_named_block(mix_text, rf"^{re.escape(ch_name)}\s*\{{")
        if not ch_span:
            return
        _c_start, c_open, c_close = ch_span
        new_body = builder_fn(mix_text[c_open + 1 : c_close])
        mix_text = mix_text[: c_open + 1] + new_body + mix_text[c_close:]

    bleed_cfg: dict[str, tuple[bool, float]] = {}
    for b_entry in ir.bleed.channels:
        pair = channel_map.get(b_entry.channel)
        if not pair:
            continue
        lvl_lin = db_to_linear(b_entry.level_db)
        bleed_cfg[pair[0]] = (b_entry.enabled, lvl_lin)
        if pair[1]:
            bleed_cfg[pair[1]] = (b_entry.enabled, lvl_lin)

    configured_sd3_channels: set[str] = set()
    for mic in ir.mics:
        if mic.channel not in channel_map:
            raise ValueError(f"Unmapped SD3 mic channel: {mic.channel!r}")
        l_ch, r_ch = channel_map[mic.channel]
        configured_sd3_channels.add(l_ch)
        if r_ch:
            configured_sd3_channels.add(r_ch)

        vol_lin = db_to_linear(mic.fader_db)
        ph = 1 if mic.phase_invert else 0
        route = route_to_sd3(mic.route_to)
        if r_ch:
            pan_l, pan_r = pan_str_to_stereo_pair(mic.pan)
        else:
            pan_l, pan_r = pan_str_to_norm(mic.pan), 1.0

        sends_l, sends_r = _build_send_lists(mic.sends, is_stereo=bool(r_ch))
        fx_blocks = _encode_inserts(mic.inserts, steep_hpf=l_ch in _CLOSE_MIC_EQ_CHANNELS)

        l_bleed = bleed_cfg.get(l_ch)
        replace_mixer_channel(
            l_ch,
            partial(
                _rewrite_channel_body,
                pan=pan_l,
                volume_linear=vol_lin,
                phasereverse=ph,
                effects=fx_blocks,
                route=route,
                sends=sends_l,
                bleed_enabled=l_bleed[0] if l_bleed else None,
                bleed_linear=l_bleed[1] if l_bleed else None,
            ),
        )
        if r_ch:
            r_bleed = bleed_cfg.get(r_ch)
            replace_mixer_channel(
                r_ch,
                partial(
                    _rewrite_channel_body,
                    pan=pan_r,
                    volume_linear=vol_lin,
                    phasereverse=ph,
                    effects=[],
                    route=route,
                    sends=sends_r,
                    bleed_enabled=r_bleed[0] if r_bleed else None,
                    bleed_linear=r_bleed[1] if r_bleed else None,
                ),
            )

    # Zero any template mic channel omitted from `ir.mics` so no stale audio/FX leak through
    all_known_sd3_pairs = list(channel_map.values())
    for l_ch, r_ch in all_known_sd3_pairs:
        if l_ch not in configured_sd3_channels:
            l_bleed = bleed_cfg.get(l_ch)
            replace_mixer_channel(
                l_ch,
                partial(
                    _rewrite_channel_body,
                    pan=0.0 if r_ch else 0.5,
                    volume_linear=0.0,
                    phasereverse=0,
                    effects=[],
                    route="output 0",
                    sends=[],
                    bleed_enabled=l_bleed[0] if l_bleed else False,
                    bleed_linear=l_bleed[1] if l_bleed else None,
                ),
            )
        if r_ch and r_ch not in configured_sd3_channels:
            r_bleed = bleed_cfg.get(r_ch)
            replace_mixer_channel(
                r_ch,
                partial(
                    _rewrite_channel_body,
                    pan=1.0,
                    volume_linear=0.0,
                    phasereverse=0,
                    effects=[],
                    route="output 0",
                    sends=[],
                    bleed_enabled=r_bleed[0] if r_bleed else False,
                    bleed_linear=r_bleed[1] if r_bleed else None,
                ),
            )

    configured_bus_indices: set[int] = set()
    for bus in ir.buses:
        l_bus, r_bus, b_idx = bus_name_to_sd3_pair(bus.name)
        configured_bus_indices.add(b_idx)
        vol_lin = db_to_linear(bus.fader_db)
        route = route_to_sd3(bus.route_to)
        pan_l, pan_r = pan_str_to_stereo_pair(bus.pan) if bus.pan is not None else (0.0, 1.0)
        b_sends_l, b_sends_r = _build_send_lists(bus.sends, is_stereo=True)
        b_fx = _encode_inserts(bus.inserts, steep_hpf=False)

        replace_mixer_channel(
            l_bus,
            partial(
                _rewrite_channel_body,
                pan=pan_l,
                volume_linear=vol_lin,
                phasereverse=0,
                effects=b_fx,
                route=route,
                sends=b_sends_l,
                hidden=False,
            ),
        )
        replace_mixer_channel(
            r_bus,
            partial(
                _rewrite_channel_body,
                pan=pan_r,
                volume_linear=vol_lin,
                phasereverse=0,
                effects=[],
                route=route,
                sends=b_sends_r,
                hidden=False,
            ),
        )

    for b_idx in range(32):
        if b_idx not in configured_bus_indices:
            replace_mixer_channel(
                f"buss {2 * b_idx}",
                partial(
                    _rewrite_channel_body,
                    pan=0.0,
                    volume_linear=1.0,
                    phasereverse=0,
                    effects=[],
                    route="output -1",
                    sends=[],
                    hidden=True,
                ),
            )
            replace_mixer_channel(
                f"buss {2 * b_idx + 1}",
                partial(
                    _rewrite_channel_body,
                    pan=1.0,
                    volume_linear=1.0,
                    phasereverse=0,
                    effects=[],
                    route="output -1",
                    sends=[],
                    hidden=False,
                ),
            )

    m_vol_lin = db_to_linear(ir.master_bus.fader_db)
    m_fx = _encode_inserts(ir.master_bus.inserts, steep_hpf=False)
    replace_mixer_channel(
        "output 0",
        partial(
            _rewrite_channel_body,
            pan=0.0,
            volume_linear=m_vol_lin,
            phasereverse=0,
            effects=m_fx,
            route=None,
            sends=[],
            clear_route=True,
        ),
    )
    replace_mixer_channel(
        "output 1",
        partial(
            _rewrite_channel_body,
            pan=1.0,
            volume_linear=m_vol_lin,
            phasereverse=0,
            effects=[],
            route=None,
            sends=[],
            clear_route=True,
        ),
    )

    text = text[: mix_open + 1] + mix_text + text[mix_close:]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8") + b"\x00"
    out_path.write_bytes(payload)

    if install_to_sd3:
        presets_dir = detect_user_presets_dir()
        presets_dir.mkdir(parents=True, exist_ok=True)
        fname = install_name or f"Forge - {ir.metadata.preset_id}.sd3p"
        if not fname.lower().endswith(".sd3p"):
            fname += ".sd3p"
        (presets_dir / fname).write_bytes(payload)

    return out_path
