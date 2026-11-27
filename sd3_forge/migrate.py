"""v1 -> v2 Blueprint migrator (Typed IR & explicit calibration_targets)."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml


def _parse_gr_value(gr_raw: Any) -> float | list[float]:
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(gr_raw))]
    if not nums:
        return 4.0
    if len(nums) >= 2:
        return [nums[0], nums[1]]
    return nums[0]


def _calibrated_comp76_input(ratio_str: str, gr_target: float | list[float]) -> str:
    gr_mid = sum(gr_target) / len(gr_target) if isinstance(gr_target, list) else float(gr_target)
    if "all" in ratio_str.lower():
        return "0.71"
    if gr_mid >= 9.0:
        return "0.84"
    if gr_mid >= 5.0:
        return "0.74"
    if gr_mid >= 3.5:
        return "0.90"
    return "0.65"


def _strip_parenthetical_scale(val: Any) -> Any:
    if not isinstance(val, str):
        return val
    # e.g. "5 (médio-lento; 1=rápido..7=lento)" -> "5"
    # e.g. "~35% do curso (saturação média-quente)" -> "35%"
    pct_m = re.search(r"~?\s*(\d+(?:\.\d+)?)\s*%", val)
    if pct_m:
        return f"{pct_m.group(1)}%"
    lead_m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*\(.*\)\s*$", val)
    if lead_m:
        return lead_m.group(1)
    return val


def _migrate_insert(ins: dict[str, Any]) -> dict[str, Any]:
    fx_name = str(ins.get("fx", ""))
    params = dict(ins.get("params", {}) or {})
    cal_targets = dict(ins.get("calibration_targets", {}) or {})

    if fx_name == "Comp 76":
        if "GR" in params:
            gr_target = _parse_gr_value(params.pop("GR"))
            cal_targets["target_gr_db"] = gr_target
            if "Input" not in params:
                params["Input"] = _calibrated_comp76_input(str(params.get("Ratio", "4:1")), gr_target)
        for k in ("Attack", "Release"):
            if k in params:
                params[k] = _strip_parenthetical_scale(params[k])
    elif fx_name == "Comp 670":
        if "GR" in params:
            gr_val = _parse_gr_value(params.pop("GR"))
            cal_targets["target_gr_db"] = gr_val
        if "Threshold" in params and re.search(r"suave|gr", str(params["Threshold"]), re.I):
            gr_val = _parse_gr_value(params["Threshold"])
            cal_targets["target_gr_db"] = gr_val
            gr_mid = sum(gr_val) / len(gr_val) if isinstance(gr_val, list) else float(gr_val)
            params["Threshold"] = 0.18 if gr_mid >= 1.8 else 0.125
        elif "Threshold" not in params and "target_gr_db" in cal_targets:
            tg = cal_targets["target_gr_db"]
            gr_mid = sum(tg) / len(tg) if isinstance(tg, list) else float(tg)
            params["Threshold"] = 0.18 if gr_mid >= 1.8 else 0.125
    elif fx_name in {"Tape Simulator", "Valve Distortion Box"}:
        for k in ("Drive", "Overdrive"):
            if k in params:
                params[k] = _strip_parenthetical_scale(params[k])

    out = dict(ins)
    out["params"] = params
    if cal_targets:
        out["calibration_targets"] = cal_targets
    return out


def migrate_v1_dict_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a v1 blueprint dict into canonical `schema_version: '2.0'` structure."""
    data = copy.deepcopy(raw)
    data["schema_version"] = "2.0"

    for piece in data.get("kit", {}).get("pieces", []):
        if "pitch_semitones" in piece and piece["pitch_semitones"] is None:
            piece["pitch_semitones"] = 0.0

    for mic in data.get("mics", []):
        if mic.get("pan") is None:
            mic["pan"] = "C"
        mic["inserts"] = [_migrate_insert(ins) for ins in mic.get("inserts", [])]

    for bus in data.get("buses", []):
        bus["inserts"] = [_migrate_insert(ins) for ins in bus.get("inserts", [])]

    master = data.get("master_bus")
    if isinstance(master, dict):
        master["inserts"] = [_migrate_insert(ins) for ins in master.get("inserts", [])]

    return data


def migrate_blueprint_file(
    target: Path,
    *,
    out_path: Path | None = None,
    in_place: bool = False,
) -> dict[str, Any]:
    """Load a blueprint (or preset dir), migrate to v2.0, validate via Pydantic IR, and write."""
    from sd3_forge.models import BlueprintV2

    src_path = target / "03-sd3-blueprint.yaml" if target.is_dir() else target
    if not src_path.exists():
        raise FileNotFoundError(f"Blueprint file not found: {src_path}")

    raw = yaml.safe_load(src_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid YAML object in {src_path}")

    migrated = migrate_v1_dict_to_v2(raw)
    BlueprintV2.model_validate(migrated)

    dest: Path | None = src_path if in_place else out_path
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    return {
        "ok": True,
        "source_path": str(src_path),
        "out_path": str(dest) if dest else None,
        "schema_version": "2.0",
    }
