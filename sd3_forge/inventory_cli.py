"""Compact query utilities for local `inventory.json` (token-efficient CLI + JSON API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sd3_forge.fx_catalog import resolve_fx
from sd3_forge.paths import default_inventory_path


def load_inventory(inventory_path: Path | None = None) -> tuple[dict[str, Any], Path]:
    """Load local Ground Truth `inventory.json` and return `(data, resolved_path)`."""
    resolved = inventory_path or default_inventory_path()
    if not resolved.exists():
        raise FileNotFoundError(
            f"Inventory not found: {resolved}. Run `sd3-forge init` or pass `--inventory <path>`."
        )
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid inventory JSON root in {resolved}")
    return data, resolved


def _piece_entry(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "name": str(raw.get("name", "")),
            "sound": raw.get("sound"),
            "instrument": raw.get("instrument"),
            "articulation_count": len(raw.get("articulations", [])) if isinstance(raw.get("articulations"), list) else None,
        }
    return {"name": str(raw)}


def query_summary(inv: dict[str, Any]) -> dict[str, Any]:
    """Return high-level counts and library metadata from `inventory.json`."""
    mics_all = inv.get("microphones", {}).get("all_parsed", [])
    avail_mics = inv.get("microphones", {}).get("available_channels", [])
    native_fx = inv.get("native_fx", {})
    fx_count = sum(len(v) for v in native_fx.values() if isinstance(v, list))
    stack_pack = inv.get("stack_pack", {})
    stack_count = sum(len(v) for v in stack_pack.values() if isinstance(v, list))
    return {
        "schema_version": inv.get("schema_version"),
        "library": inv.get("library"),
        "installation": inv.get("installation"),
        "counts": {
            "base_kits": len(inv.get("base_kits", [])),
            "slots": len(inv.get("positions", {})),
            "total_mics": len(mics_all),
            "installed_mics": len(avail_mics),
            "native_fx": fx_count,
            "stack_categories": len(stack_pack),
            "stack_items": stack_count,
            "midi_notes": len(inv.get("midi_keymap", [])),
        },
        "slots": list(inv.get("positions", {}).keys()),
    }


def query_kits(inv: dict[str, Any], *, kit_name: str | None = None) -> dict[str, Any]:
    """List available `base_kits` or return the piece map for a specific `kit_name`."""
    base_kits = list(inv.get("base_kits", []))
    drumsets = inv.get("drumsets", {})
    if kit_name is None:
        return {"count": len(base_kits), "base_kits": base_kits}

    if kit_name not in drumsets:
        # Try case-insensitive exact match before failing
        match = next((k for k in drumsets if k.lower() == kit_name.lower()), None)
        if not match:
            raise ValueError(f"Unknown kit {kit_name!r}. Available kits: {base_kits}")
        kit_name = match
    return {"kit": drumsets[kit_name]}


def query_pieces(
    inv: dict[str, Any],
    *,
    slot: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Query verified kit pieces by slot and/or case-insensitive substring."""
    positions = inv.get("positions", {})
    if slot is not None:
        if slot not in positions:
            raise ValueError(f"Unknown slot {slot!r}. Valid slots: {list(positions.keys())}")
        target_slots = [slot]
    else:
        target_slots = list(positions.keys())

    needle = search.strip().lower() if search else None
    results: list[dict[str, Any]] = []
    for s in target_slots:
        for raw in positions.get(s, {}).get("pieces", []):
            item = _piece_entry(raw)
            if needle and needle not in item["name"].lower():
                continue
            item["slot"] = s
            results.append(item)

    truncated = len(results) > max(1, limit)
    capped = results[: max(1, limit)]
    return {
        "slot": slot,
        "search": search,
        "total_matches": len(results),
        "truncated": truncated,
        "pieces": capped,
    }


def query_mics(
    inv: dict[str, Any],
    *,
    bleed_only: bool = False,
    include_unavailable: bool = False,
) -> dict[str, Any]:
    """List mixer channels with stereo/bleed/ambient flags."""
    mics_info = inv.get("microphones", {})
    avail_set = set(mics_info.get("available_channels", []))
    bleed_avail_set = set(mics_info.get("available_bleed_channels", []))
    rows: list[dict[str, Any]] = []

    for m in mics_info.get("all_parsed", []):
        mixname = m.get("mixname")
        if not mixname:
            continue
        is_avail = bool(m.get("installed_part1", True)) or (mixname in avail_set)
        if not include_unavailable and avail_set and mixname not in avail_set:
            continue
        bleed_flag = bool(m.get("bleedcontrol"))
        bleed_installed = mixname in bleed_avail_set if bleed_avail_set else bool(m.get("bleed_available_part1"))
        if bleed_only and not (bleed_installed or (include_unavailable and bleed_flag)):
            continue
        rows.append(
            {
                "mixname": mixname,
                "stereo": bool(m.get("stereo")),
                "bleedcontrol": bleed_flag,
                "bleed_installed": bleed_installed,
                "ambient": bool(m.get("ambient")),
                "installed": is_avail,
            }
        )

    return {"count": len(rows), "mics": rows}


def query_fx(
    inv: dict[str, Any],
    *,
    category: str | None = None,
    search: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Query native SD3 effects catalog or inspect full parameter details for `--name`."""
    if name is not None:
        spec = resolve_fx(name)
        params = [
            {
                "index": p.index,
                "name": p.name,
                "unit": p.unit,
                "min_val": p.min_val,
                "max_val": p.max_val,
                "curve": p.curve,
                "aliases": list(p.aliases),
                "allowed_values": list(p.allowed_values) or [c[0] for c in p.choices],
            }
            for p in spec.params
        ]
        # Avoid dumping all 131 params for parametric EQ unless explicitly requested
        if spec.effect_id == 10 and len(params) > 20:
            params = params[:13] + [params[-1]]
        return {
            "effect": {
                "effect_id": spec.effect_id,
                "name": spec.name,
                "category": spec.category,
                "model_inspiration": spec.model_inspiration,
                "param_count": spec.param_count,
                "extra_param_keys": list(spec.extra_param_keys),
                "forbidden_keys": list(spec.forbidden_keys),
                "controls_summary": list(spec.controls_summary),
            },
            "params": params,
        }

    native_fx = inv.get("native_fx", {})
    cat_needle = category.strip().lower() if category else None
    text_needle = search.strip().lower() if search else None
    items: list[dict[str, Any]] = []
    for cat, fx_list in native_fx.items():
        if cat_needle and cat_needle not in cat.lower():
            continue
        if not isinstance(fx_list, list):
            continue
        for fx in fx_list:
            fx_name = str(fx.get("name", ""))
            insp = str(fx.get("model_inspiration", ""))
            if text_needle and text_needle not in fx_name.lower() and text_needle not in insp.lower():
                continue
            items.append(
                {
                    "effect_id": fx.get("effect_id"),
                    "name": fx_name,
                    "category": cat,
                    "model_inspiration": insp,
                    "controls": fx.get("controls", []),
                }
            )
    return {"count": len(items), "categories": list(native_fx.keys()), "fx": items}


def query_stacks(
    inv: dict[str, Any],
    *,
    category: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Query SD3 Stack Pack categories and sound items."""
    stack_pack = inv.get("stack_pack", {})
    cat_needle = category.strip().lower() if category else None
    text_needle = search.strip().lower() if search else None
    out: dict[str, list[dict[str, Any]]] = {}
    total = 0

    for cat, items in stack_pack.items():
        if cat_needle and cat_needle not in cat.lower():
            continue
        if not isinstance(items, list):
            continue
        matched: list[dict[str, Any]] = []
        for it in items:
            if isinstance(it, dict):
                label = str(it.get("name", ""))
                entry = {"id": it.get("id"), "code": it.get("code"), "name": label}
            else:
                label = str(it)
                entry = {"name": label}
            if text_needle and text_needle not in label.lower():
                continue
            matched.append(entry)
        if matched:
            out[cat] = matched[: max(1, limit)]
            total += len(matched)

    return {"categories": list(stack_pack.keys()), "total_items": total, "stacks": out}


def query_keymap(
    inv: dict[str, Any],
    *,
    group: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Query SD3 MIDI keymap notes by group or articulation substring."""
    keymap = inv.get("midi_keymap", [])
    grp_needle = group.strip().lower() if group else None
    text_needle = search.strip().lower() if search else None
    rows: list[dict[str, Any]] = []
    for entry in keymap:
        if not isinstance(entry, dict):
            continue
        g = str(entry.get("group", ""))
        inst = str(entry.get("instrument", ""))
        art = str(entry.get("articulation", ""))
        if grp_needle and grp_needle not in g.lower():
            continue
        if text_needle and text_needle not in f"{inst} {art} {g}".lower():
            continue
        rows.append(entry)
    return {"count": len(rows), "keymap": rows}
