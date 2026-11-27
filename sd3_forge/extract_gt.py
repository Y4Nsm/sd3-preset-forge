"""Deterministic Ground Truth Extractor for Toontrack Superior Drummer 3.

Reads a user's local SD3/SDX library files (`Aversion`, `uberconf`, `micconf`,
`padconf`, `InstallerConfig`, `instrumentgroups`, `StackPack`, `soundDB`,
`Sounds/*.obw`) and produces a portable, privacy-clean `inventory.json`
(no local filesystem paths embedded).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from sd3_forge.config_parser import ConfigNode, parse_config_ast
from sd3_forge.fx_catalog import list_native_fx_grouped, list_native_fx_names
from sd3_forge.paths import default_inventory_path, detect_sd3_library_path, load_package_text
from sd3_forge.sd3p_codec import normalize_name

PART1_AVAILABLE_CHANNELS = [
    "Kick In",
    "Kick Out",
    "Kick Sub",
    "Snare Top",
    "Snare Bottom",
    "Hi-Hat",
    "Racktom 1",
    "Racktom 2",
    "Racktom 3",
    "Floortom 1",
    "Floortom 2",
    "OH Dyn",
    "Amb Ribbon",
]

PART1_BLEED_CHANNELS = [
    "Snare Bottom",
    "OH Dyn",
    "Amb Ribbon",
]

FORBIDDEN_CHANNELS = [
    "OH Cond",
    "Amb Near",
    "Amb Mid",
    "Front L/R",
    "Center",
    "Surround L/R",
    "Front Height",
    "Rear Height",
    "Rear Ht Wide",
]

_STEREO_ROOM_CHANNELS = ["OH Cond", "Amb Near", "Amb Mid"]
_SURROUND_CHANNELS = ["Front L/R", "Center", "Surround L/R"]
_HEIGHT_CHANNELS = ["Front Height", "Rear Height", "Rear Ht Wide"]

# Official 35 native insert effects in Superior Drummer 3 Mixer (sourced from static registry)
NATIVE_FX: dict[str, list[dict[str, Any]]] = list_native_fx_grouped()

MIDI_KEYMAP: list[dict[str, Any]] = [
    {"note": 36, "instrument": "Kick", "articulation": "Open", "group": "Kick"},
    {"note": 35, "instrument": "Kick", "articulation": "Hit", "group": "Kick"},
    {"note": 38, "instrument": "Snare", "articulation": "Center", "group": "Snare"},
    {"note": 40, "instrument": "Snare", "articulation": "Rimshot", "group": "Snare"},
    {"note": 37, "instrument": "Snare", "articulation": "Sidestick", "group": "Snare"},
    {"note": 33, "instrument": "Snare", "articulation": "Edge", "group": "Snare"},
    {"note": 125, "instrument": "Snare", "articulation": "Off Center", "group": "Snare"},
    {"note": 39, "instrument": "Snare", "articulation": "Closed Roll", "group": "Snare"},
    {"note": 68, "instrument": "Snare", "articulation": "Muted Hit", "group": "Snare"},
    {"note": 69, "instrument": "Snare", "articulation": "Flam", "group": "Snare"},
    {"note": 70, "instrument": "Snare", "articulation": "Muted Accent", "group": "Snare"},
    {"note": 71, "instrument": "Snare", "articulation": "Rim Only", "group": "Snare"},
    {"note": 48, "instrument": "Racktom 1", "articulation": "Center", "group": "Toms"},
    {"note": 82, "instrument": "Racktom 1", "articulation": "Rimshot", "group": "Toms"},
    {"note": 81, "instrument": "Racktom 1", "articulation": "Rim Only", "group": "Toms"},
    {"note": 47, "instrument": "Racktom 2", "articulation": "Center", "group": "Toms"},
    {"note": 80, "instrument": "Racktom 2", "articulation": "Rimshot", "group": "Toms"},
    {"note": 79, "instrument": "Racktom 2", "articulation": "Rim Only", "group": "Toms"},
    {"note": 45, "instrument": "Racktom 3", "articulation": "Center", "group": "Toms"},
    {"note": 78, "instrument": "Racktom 3", "articulation": "Rimshot", "group": "Toms"},
    {"note": 77, "instrument": "Racktom 3", "articulation": "Rim Only", "group": "Toms"},
    {"note": 43, "instrument": "Floortom 1", "articulation": "Center", "group": "Toms"},
    {"note": 75, "instrument": "Floortom 1", "articulation": "Rimshot", "group": "Toms"},
    {"note": 74, "instrument": "Floortom 1", "articulation": "Rim Only", "group": "Toms"},
    {"note": 41, "instrument": "Floortom 2", "articulation": "Center", "group": "Toms"},
    {"note": 73, "instrument": "Floortom 2", "articulation": "Rimshot", "group": "Toms"},
    {"note": 72, "instrument": "Floortom 2", "articulation": "Rim Only", "group": "Toms"},
    {"note": 42, "instrument": "Hi-Hat", "articulation": "GM Closed", "group": "Hi-Hat"},
    {"note": 46, "instrument": "Hi-Hat", "articulation": "GM Open", "group": "Hi-Hat"},
    {"note": 44, "instrument": "Hi-Hat", "articulation": "GM Pedal", "group": "Hi-Hat"},
    {"note": 21, "instrument": "Hi-Hat", "articulation": "Closed Pedal", "group": "Hi-Hat"},
    {"note": 22, "instrument": "Hi-Hat", "articulation": "Closed Edge", "group": "Hi-Hat"},
    {"note": 23, "instrument": "Hi-Hat", "articulation": "Open Pedal", "group": "Hi-Hat"},
    {"note": 24, "instrument": "Hi-Hat", "articulation": "Open 1", "group": "Hi-Hat"},
    {"note": 25, "instrument": "Hi-Hat", "articulation": "Open 2", "group": "Hi-Hat"},
    {"note": 26, "instrument": "Hi-Hat", "articulation": "Open 3", "group": "Hi-Hat"},
    {"note": 60, "instrument": "Hi-Hat", "articulation": "Open Edge 4", "group": "Hi-Hat"},
    {"note": 61, "instrument": "Hi-Hat", "articulation": "Closed Tip", "group": "Hi-Hat"},
    {"note": 62, "instrument": "Hi-Hat", "articulation": "Tight Edge", "group": "Hi-Hat"},
    {"note": 63, "instrument": "Hi-Hat", "articulation": "Tight Tip", "group": "Hi-Hat"},
    {"note": 64, "instrument": "Hi-Hat", "articulation": "Open Edge 0", "group": "Hi-Hat"},
    {"note": 65, "instrument": "Hi-Hat", "articulation": "Seq Hits", "group": "Hi-Hat"},
    {"note": 86, "instrument": "Cymbal 1", "articulation": "Crashed", "group": "Crash"},
    {"note": 85, "instrument": "Cymbal 1", "articulation": "Bell Shank", "group": "Crash"},
    {"note": 84, "instrument": "Cymbal 1", "articulation": "Bow Tip", "group": "Crash"},
    {"note": 83, "instrument": "Cymbal 1", "articulation": "Muted", "group": "Crash"},
    {"note": 49, "instrument": "Cymbal 2", "articulation": "Crashed", "group": "Crash"},
    {"note": 50, "instrument": "Cymbal 2", "articulation": "Muted", "group": "Crash"},
    {"note": 55, "instrument": "Cymbal 3", "articulation": "Crashed", "group": "Crash"},
    {"note": 56, "instrument": "Cymbal 3", "articulation": "Muted", "group": "Crash"},
    {"note": 57, "instrument": "Cymbal 4", "articulation": "Crashed", "group": "Crash"},
    {"note": 58, "instrument": "Cymbal 4", "articulation": "Muted", "group": "Crash"},
    {"note": 52, "instrument": "Cymbal 5", "articulation": "Crashed", "group": "Crash"},
    {"note": 54, "instrument": "Cymbal 5", "articulation": "Muted", "group": "Crash"},
    {"note": 51, "instrument": "Ride", "articulation": "Bow Tip", "group": "Ride"},
    {"note": 53, "instrument": "Ride", "articulation": "Bell Shank", "group": "Ride"},
    {"note": 59, "instrument": "Ride", "articulation": "Crashed", "group": "Ride"},
    {"note": 29, "instrument": "Ride", "articulation": "Bow Shank", "group": "Ride"},
    {"note": 30, "instrument": "Ride", "articulation": "Bell Tip", "group": "Ride"},
    {"note": 118, "instrument": "Ride", "articulation": "Muted", "group": "Ride"},
]


def _iter_descendants(node: ConfigNode) -> list[ConfigNode]:
    out: list[ConfigNode] = []
    if not node.children:
        return out
    for child in node.children:
        out.append(child)
        if child.children:
            out.extend(_iter_descendants(child))
    return out


def parse_uberconf(text: str) -> dict[str, Any]:
    """Parse SD3/SDX `uberconf` via brace+macro AST."""
    ast = parse_config_ast(text, expand_macros=True)
    pos_nodes = [n for n in ast if n.is_block and n.head == "positions"]
    ds_nodes = [n for n in ast if n.is_block and n.head == "drumsets"]
    if not pos_nodes or not ds_nodes:
        raise ValueError("Could not locate positions/drumsets blocks in uberconf")

    positions: dict[str, dict[str, Any]] = {}
    for slot_node in pos_nodes[0].children or []:
        if not slot_node.is_block or len(slot_node.tokens) < 2:
            continue
        slot_id = slot_node.tokens[0]
        try:
            slot_num = int(slot_node.tokens[1])
        except ValueError:
            continue

        desc = slot_id
        close_mics: list[str] = []
        split_mics: list[str] = []
        pads: list[dict[str, str]] = []
        pieces: list[dict[str, str]] = []

        for child in slot_node.children or []:
            if child.is_block:
                if child.head == "pads":
                    for pchild in child.children or []:
                        if not pchild.is_block and len(pchild.tokens) >= 3:
                            pads.append(
                                {
                                    "id": pchild.tokens[0],
                                    "code": pchild.tokens[1],
                                    "label": normalize_name(pchild.tokens[2]),
                                }
                            )
                continue

            toks = child.tokens
            if not toks:
                continue
            head = toks[0]
            if head == "description" and len(toks) >= 2:
                desc = toks[1]
            elif head == "close" and len(toks) >= 2:
                close_mics.append(toks[1])
            elif head == "split" and len(toks) >= 2:
                split_mics.append(toks[1])
            elif head in {"description", "close", "split", "pads"}:
                continue
            elif len(toks) >= 3:
                pieces.append({"id": toks[0], "code": toks[1], "name": normalize_name(toks[2])})

        positions[slot_id] = {
            "slot_id": slot_id,
            "slot_index": slot_num,
            "description": desc,
            "close_mics": close_mics,
            "split_mics": split_mics,
            "pads": pads,
            "pieces": pieces,
        }

    drumsets: dict[str, dict[str, Any]] = {}
    for ds_node in ds_nodes[0].children or []:
        if not ds_node.is_block or not ds_node.tokens:
            continue
        ds_name = ds_node.tokens[0].strip()
        if ds_name == "Empty Kit":
            continue
        sticks = "Drumsticks"
        kit_map: dict[str, str] = {}
        for child in ds_node.children or []:
            if child.is_block or not child.tokens:
                continue
            if child.tokens[0] == "sticks" and len(child.tokens) >= 2:
                sticks = child.tokens[1]
            elif child.tokens[0] in {"sticks", "crmat"}:
                continue
            elif len(child.tokens) == 2:
                kit_map[child.tokens[0]] = child.tokens[1]
        drumsets[ds_name] = {
            "name": ds_name,
            "sticks": sticks,
            "slot_pieces": kit_map,
        }

    return {"positions": positions, "drumsets": drumsets}


def parse_micconf(text: str) -> list[dict[str, Any]]:
    """Parse SD3/SDX `micconf` via brace AST and pair stereo L/R channels."""
    ast = parse_config_ast(text, expand_macros=True)
    mics: list[dict[str, Any]] = []

    for node in ast:
        if not node.is_block or node.head != "mic":
            continue
        stmts = [c.tokens for c in (node.children or []) if not c.is_block and c.tokens]
        flags = {t[0] for t in stmts}
        if "dummy" in flags:
            continue

        by_key = {t[0]: t[1:] for t in stmts}
        internal_name = by_key["name"][0] if by_key.get("name") else None
        mixname = by_key["mixname"][0] if by_key.get("mixname") else None
        bouncename = by_key["bouncename"][0] if by_key.get("bouncename") else mixname
        is_stereo = "stereo" in flags
        has_bleed = "bleedcontrol" in flags
        is_ambient = "ambientoffset" in flags or "roomtime" in flags
        is_always = "always" in flags
        pan_val = float(by_key["pan"][0]) if by_key.get("pan") else 0.5
        vol_val = float(by_key["volume"][0]) if by_key.get("volume") else 1.0

        # Stereo right-hand channel entries omit `mixname` right after the left stereo entry
        if not mixname:
            if (
                mics
                and is_stereo
                and internal_name
                and mics[-1]["stereo"]
                and mics[-1]["right_internal_name"] is None
            ):
                mics[-1]["right_internal_name"] = internal_name
            continue

        mics.append(
            {
                "internal_name": internal_name or mixname,
                "right_internal_name": None,
                "mixname": mixname,
                "bouncename": bouncename or mixname,
                "stereo": is_stereo,
                "bleedcontrol": has_bleed,
                "ambient": is_ambient,
                "always": is_always,
                "default_pan": pan_val,
                "default_volume": vol_val,
                "installed_part1": mixname in PART1_AVAILABLE_CHANNELS,
                "bleed_available_part1": mixname in PART1_BLEED_CHANNELS,
            }
        )

    # Synthetic fixtures may declare stereo=True without explicit right-channel block
    for mic in mics:
        if mic["stereo"] and mic["right_internal_name"] is None:
            mic["right_internal_name"] = f"{mic['internal_name']}R"

    return mics


def parse_padconf(text: str) -> dict[str, Any]:
    """Parse SD3/SDX `padconf` with template expansion."""
    ast = parse_config_ast(text, expand_macros=True)
    defaultpad: dict[str, Any] = {"usemic": []}
    pads: dict[str, dict[str, Any]] = {}

    for node in ast:
        if not node.is_block:
            continue
        if node.head == "defaultpad":
            for child in node.children or []:
                if not child.is_block and child.tokens:
                    if child.tokens[0] == "usemic":
                        defaultpad["usemic"].extend(child.tokens[1:])
                    elif child.tokens[0] == "cycle" and len(child.tokens) >= 2:
                        defaultpad["cycle"] = child.tokens[1]
                    elif child.tokens[0] == "maxpoly" and len(child.tokens) >= 2:
                        defaultpad["maxpoly"] = int(child.tokens[1])
        elif node.head == "pad" and len(node.tokens) >= 2:
            pad_id = node.tokens[1]
            usemic: list[str] = []
            for child in node.children or []:
                if not child.is_block and child.tokens and child.tokens[0] == "usemic":
                    usemic.extend(child.tokens[1:])
            pads[pad_id] = {"usemic": usemic}

    return {"defaultpad": defaultpad, "pads": pads}


def parse_installer_config(text: str) -> list[dict[str, Any]]:
    """Parse SD3/SDX `InstallerConfig` options and OBW pack mappings."""
    ast = parse_config_ast(text, expand_macros=True)
    options: list[dict[str, Any]] = []

    def _visit(nodes: list[ConfigNode]) -> None:
        for node in nodes:
            if not node.is_block:
                continue
            if node.head == "Option":
                name: str | None = None
                default_opt = False
                obw_nums: set[int] = set()
                for child in _iter_descendants(node):
                    if child.is_block or not child.tokens:
                        continue
                    head = child.tokens[0]
                    if head == "Name" and len(child.tokens) >= 2:
                        name = child.tokens[1]
                    elif head == "DefaultOption":
                        default_opt = True
                    elif head == "FileName" and len(child.tokens) >= 2:
                        m = re.search(r"soundb(\d+)\.obw", child.tokens[1], re.I)
                        if m:
                            obw_nums.add(int(m.group(1)))
                if name:
                    options.append(
                        {
                            "name": name,
                            "default_option": default_opt,
                            "obw_numbers": sorted(obw_nums),
                        }
                    )
            else:
                _visit(node.children or [])

    _visit(ast)
    return options


def parse_instrumentgroups(text: str) -> dict[str, list[int]]:
    """Parse SD3/SDX `instrumentgroups` into `{group_name: [midi_notes...]}`."""
    ast = parse_config_ast(text, expand_macros=False)
    groups: dict[str, list[int]] = {}
    for node in ast:
        if not node.is_block or node.head != "name" or len(node.tokens) < 2:
            continue
        grp_name = node.tokens[1]
        notes: set[int] = set()
        for child in node.children or []:
            if not child.is_block and len(child.tokens) >= 2 and child.tokens[0] == "note":
                try:
                    notes.add(int(child.tokens[1]))
                except ValueError:
                    continue
        if notes:
            groups[grp_name] = sorted(notes)
    return groups


def parse_stackpack(stackpack_path: Path) -> dict[str, list[dict[str, str]]]:
    """Parse SD3 `StackPack` trailing text index via brace AST."""
    if not stackpack_path.exists():
        return {}
    data = stackpack_path.read_bytes()
    tail = data[-300000:] if len(data) > 300000 else data
    text = tail.decode("latin-1", errors="ignore")
    m = re.search(r"positions\s*\{", text)
    if not m:
        return {}

    # Find matching closing brace for the trailing `positions { ... }` block
    sub = text[m.start() :]
    open_idx = sub.find("{")
    depth = 0
    end_idx = len(sub)
    in_quotes = False
    for idx in range(open_idx, len(sub)):
        ch = sub[idx]
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = idx + 1
                    break

    ast = parse_config_ast(sub[:end_idx], expand_macros=False)
    pos_nodes = [n for n in ast if n.is_block and n.head == "positions"]
    if not pos_nodes:
        return {}

    categories: dict[str, list[dict[str, str]]] = {}
    for cat_node in pos_nodes[0].children or []:
        if not cat_node.is_block or not cat_node.tokens:
            continue
        cat_name = cat_node.tokens[0]
        items: list[dict[str, str]] = []
        for child in cat_node.children or []:
            if child.is_block or not child.tokens:
                continue
            toks = child.tokens
            if toks[0] == "description" and len(toks) >= 2:
                cat_name = toks[1]
            elif toks[0] in {"description", "close", "pads"}:
                continue
            elif len(toks) >= 3:
                items.append({"id": toks[0], "code": toks[1], "name": normalize_name(toks[2])})
        if items:
            categories[cat_name] = items
    return categories


def inspect_installed_obws(
    sd3_path: Path,
    installer_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sounds_dir = sd3_path / "Sounds"
    obw_files = sorted(sounds_dir.glob("soundb*.obw"), key=lambda p: p.name) if sounds_dir.exists() else []
    obw_nums = sorted(
        int(m.group(1))
        for p in obw_files
        if (m := re.search(r"soundb(\d+)\.obw", p.name))
    )
    obw_set = set(obw_nums)

    has_full = any(24 <= n <= 150 for n in obw_nums)
    installed_packs: list[str] = []
    missing_packs: list[str] = []

    if installer_options and any(opt["obw_numbers"] for opt in installer_options):
        for opt in installer_options:
            req = set(opt["obw_numbers"])
            if not req:
                continue
            if req.issubset(obw_set):
                installed_packs.append(opt["name"])
            else:
                missing_packs.append(opt["name"])
    else:
        installed_packs = (
            ["Basic Setup", "Stereo Room Setup", "Surround Setup"]
            if has_full
            else ["Basic Setup - Sticks Only", "Basic Setup - All Tools"]
        )
        missing_packs = (
            []
            if has_full
            else ["Stereo Room Setup (Part 2/3)", "Surround Setup 5.0", "Height Surround Setup 11.0", "Additional Bleed"]
        )

    return {
        "pack_name": "Full Core Library (Parts 1-5)" if has_full else "Part 1 - Basic Setup (All Tools)",
        "obw_count": len(obw_files),
        "obw_numbers": obw_nums,
        "installed_packs": installed_packs,
        "missing_packs": missing_packs,
    }


def query_sounddb(sounddb_path: Path, *, fallback_lib_id: str | None = None, fallback_name: str | None = None) -> dict[str, Any]:
    if not sounddb_path.exists():
        lib_id = fallback_lib_id or "SL-SUPERIOR_DRUMMER_3"
        formatted = fallback_name or (
            "Superior Drummer 3 - Core Library" if lib_id == "SL-SUPERIOR_DRUMMER_3" else lib_id
        )
        return {
            "lib_id": lib_id,
            "formatted_name": formatted,
            "version": "1.3.0",
            "entity_count": 0,
            "manufacturers": [],
        }
    conn = sqlite3.connect(str(sounddb_path))
    try:
        lib_row = conn.execute("SELECT LibID, FormattedName, Version FROM LIBRARY LIMIT 1").fetchone()
        manufacturers = [r[0] for r in conn.execute("SELECT Name FROM MANUFACTURER ORDER BY Name").fetchall()]
        entity_count = conn.execute("SELECT COUNT(*) FROM SOUNDENTITY").fetchone()[0]
    finally:
        conn.close()
    return {
        "lib_id": lib_row[0] if lib_row else (fallback_lib_id or "SL-SUPERIOR_DRUMMER_3"),
        "formatted_name": lib_row[1] if lib_row else (fallback_name or "Superior Drummer 3 - Core Library"),
        "version": lib_row[2] if lib_row else "1.3.0",
        "entity_count": entity_count,
        "manufacturers": manufacturers,
    }


def _resolve_channel_capabilities(
    lib_id: str,
    mics: list[dict[str, Any]],
    obw_nums: list[int],
) -> tuple[list[str], list[str], list[str]]:
    parsed_mixnames = [m["mixname"] for m in mics]
    if lib_id != "SL-SUPERIOR_DRUMMER_3":
        avail = parsed_mixnames
        bleed = [m["mixname"] for m in mics if m.get("bleedcontrol")]
        if not bleed:
            bleed = list(parsed_mixnames)
        return avail, bleed, []

    # Core SD3: unlock additional mic packs when their OBW ranges exist on disk
    obw_set = set(obw_nums)
    avail = list(PART1_AVAILABLE_CHANNELS)
    if any(24 <= n <= 52 for n in obw_set):
        avail.extend(_STEREO_ROOM_CHANNELS)
    if any(53 <= n <= 78 for n in obw_set):
        avail.extend(_SURROUND_CHANNELS)
    if any(79 <= n <= 113 for n in obw_set):
        avail.extend(_HEIGHT_CHANNELS)

    avail_set = set(avail)
    all_core = set(parsed_mixnames) | set(PART1_AVAILABLE_CHANNELS) | set(FORBIDDEN_CHANNELS)
    forbidden = [ch for ch in PART1_AVAILABLE_CHANNELS + FORBIDDEN_CHANNELS if ch in all_core and ch not in avail_set]
    # Add any unknown parsed core mics not in PART1/FORBIDDEN
    for ch in parsed_mixnames:
        if ch not in avail_set and ch not in forbidden:
            forbidden.append(ch)

    if any(114 <= n <= 150 for n in obw_set):
        bleed = [m["mixname"] for m in mics if m["mixname"] in avail_set and m.get("bleedcontrol")] or list(avail)
    else:
        bleed = [ch for ch in PART1_BLEED_CHANNELS if ch in avail_set]
        if any(24 <= n <= 52 for n in obw_set):
            for ch in _STEREO_ROOM_CHANNELS:
                if ch in avail_set and ch not in bleed:
                    bleed.append(ch)
    return avail, bleed, forbidden


def _extract_library_identity(ic_text: str | None, ig_text: str | None) -> tuple[str | None, str | None]:
    lib_id: str | None = None
    product: str | None = None
    if ic_text:
        m_id = re.search(r"(?m)^\s*Name\s+(\S+)\s*$", ic_text)
        m_desc = re.search(r'(?m)^\s*Description\s+"([^"]+)"', ic_text)
        if m_id:
            lib_id = m_id.group(1)
        if m_desc:
            product = m_desc.group(1)
    if ig_text:
        m_id = re.search(r"(?m)^\s*Id\s+(\S+)\s*$", ig_text)
        m_prod = re.search(r'(?m)^\s*Product\s+"([^"]+)"', ig_text)
        if m_id and not lib_id:
            lib_id = m_id.group(1)
        if m_prod and not product:
            product = m_prod.group(1)
    return lib_id, product


def build_inventory(sd3_path: Path | None = None) -> dict[str, Any]:
    resolved = sd3_path or detect_sd3_library_path()
    if resolved is None or not resolved.exists():
        raise FileNotFoundError(
            f"SD3 library directory not found: {resolved}. "
            "Pass `--sd3-path <dir>` or set SD3_LIBRARY_PATH."
        )
    uber_path = resolved / "uberconf"
    if not uber_path.exists():
        raise FileNotFoundError(f"Missing 'uberconf' in SD3 library directory: {resolved}")

    aversion_path = resolved / "Aversion"
    aversion_lines = aversion_path.read_text(encoding="utf-8", errors="ignore").splitlines() if aversion_path.exists() else []
    uber = parse_uberconf(uber_path.read_text(encoding="utf-8", errors="ignore"))

    micconf_path = resolved / "micconf"
    mics = parse_micconf(micconf_path.read_text(encoding="utf-8", errors="ignore")) if micconf_path.exists() else []

    padconf_path = resolved / "padconf"
    padconf = parse_padconf(padconf_path.read_text(encoding="utf-8", errors="ignore")) if padconf_path.exists() else {"defaultpad": {"usemic": []}, "pads": {}}

    ic_path = resolved / "InstallerConfig"
    ic_text = ic_path.read_text(encoding="utf-8", errors="ignore") if ic_path.exists() else None
    installer_options = parse_installer_config(ic_text) if ic_text else []

    ig_path = resolved / "instrumentgroups"
    ig_text = ig_path.read_text(encoding="utf-8", errors="ignore") if ig_path.exists() else None
    instrument_groups = parse_instrumentgroups(ig_text) if ig_text else {}

    stack_pack = parse_stackpack(resolved / "StackPack")
    obw_info = inspect_installed_obws(resolved, installer_options=installer_options or None)

    fb_lib_id, fb_name = _extract_library_identity(ic_text, ig_text)
    sdb_info = query_sounddb(resolved / "soundDB", fallback_lib_id=fb_lib_id, fallback_name=fb_name)
    if sdb_info["lib_id"] != "SL-SUPERIOR_DRUMMER_3" and installer_options:
        obw_info["pack_name"] = sdb_info["formatted_name"]

    avail_ch, bleed_ch, forb_ch = _resolve_channel_capabilities(
        sdb_info["lib_id"],
        mics,
        obw_info["obw_numbers"],
    )
    channel_map: dict[str, list[str]] = {}
    for mic in mics:
        ch_pair = [mic["internal_name"]]
        if mic.get("right_internal_name"):
            ch_pair.append(mic["right_internal_name"])
        channel_map[mic["mixname"]] = ch_pair

    piece_lookup: dict[str, dict[str, str]] = {}
    for slot_id, pos in uber["positions"].items():
        for p in pos["pieces"]:
            piece_lookup[p["id"]] = {"slot_id": slot_id, "name": p["name"], "code": p["code"]}

    resolved_drumsets: dict[str, Any] = {}
    for ds_name, ds in uber["drumsets"].items():
        resolved_slots = {}
        for slot, pid in ds["slot_pieces"].items():
            resolved_slots[slot] = piece_lookup.get(pid, {"id": pid, "name": pid})["name"]
        resolved_drumsets[ds_name] = {
            "name": ds_name,
            "sticks": ds["sticks"],
            "pieces": resolved_slots,
        }

    base_kits = [k for k in resolved_drumsets if "brushes" not in k.lower() and "rods" not in k.lower() and "mallet" not in k.lower()]
    if not base_kits:
        base_kits = list(resolved_drumsets.keys())

    all_fx_flat = list_native_fx_names()
    fx_cal = yaml.safe_load(load_package_text("data/fx-ui-calibration.yaml")) or {}

    return {
        "schema_version": "2.0.0",
        "library": sdb_info,
        "aversion": aversion_lines,
        "installation": obw_info,
        "base_kits": base_kits,
        "drumsets": resolved_drumsets,
        "positions": uber["positions"],
        "microphones": {
            "all_parsed": mics,
            "channel_map": channel_map,
            "available_channels": avail_ch,
            "available_bleed_channels": bleed_ch,
            "forbidden_channels": forb_ch,
        },
        "padconf": padconf,
        "instrument_groups": instrument_groups,
        "stack_pack": stack_pack,
        "native_fx": NATIVE_FX,
        "native_fx_names": all_fx_flat,
        "fx_ui_calibration": fx_cal,
        "drums_tab_envelope": {
            "type": "AHDSR",
            "allowed_fields": ["attack_ms", "hold_ms", "decay_ms", "sustain_db", "release_ms"],
            "note": "Positive attack_ms softens transient; use Mixer 'Transient' insert to boost attack.",
        },
        "fx_param_rules": {
            "EQ84": {
                "max_bands": 3,
                "allowed_band_keys": ["HPF", "LPF", "Low", "Mid", "High", "HiQ", "InOut"],
                "forbidden_keys": ["LowMid", "HighMid"],
            },
            "Comp 76": {
                "attack_scale": "1 (fastest) to 7 (slowest)",
                "release_scale": "1 (fastest) to 7 (slowest)",
            },
        },
        "midi_keymap": MIDI_KEYMAP,
    }


def extract_inventory_to_file(sd3_path: Path | None = None, out_path: Path | None = None) -> Path:
    inv = build_inventory(sd3_path)
    target = out_path or default_inventory_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(inv, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
