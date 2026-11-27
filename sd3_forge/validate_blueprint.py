"""Blueprint and spec-targets validator (Typed IR v2, topology & 35-FX contract gate)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import ValidationError

from sd3_forge.fx_catalog import validate_fx_params
from sd3_forge.models import BlueprintV2, load_blueprint_ir
from sd3_forge.paths import default_inventory_path, load_package_json
from sd3_forge.sd3p_codec import BUS_NAME_RE, normalize_name, pan_str_to_norm, pan_str_to_stereo_pair

_CANONICAL_BLEED_GROUPS = {"All", "Kick", "Snare", "Hats", "Hi-Hat", "Toms", "Cymbals"}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_spec_targets(spec_path: Path) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not spec_path.exists():
        return ValidationResult(ok=False, errors=[f"Spec file not found: {spec_path}"])

    try:
        data = _load_yaml(spec_path)
    except Exception as exc:
        return ValidationResult(ok=False, errors=[f"YAML parse error in {spec_path}: {exc}"])

    schema = load_package_json("schemas/spec-targets.schema.json")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"Spec schema error at {list(exc.path)}: {exc.message}")
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    for group_name in ("safety", "kick", "snare_center", "snare_rimshot", "toms", "cymbals", "groove"):
        group = data.get(group_name, {})
        for metric_name, bound in group.items():
            mn = bound.get("min")
            mx = bound.get("max")
            ideal = bound.get("ideal")
            if isinstance(mn, (int, float)) and isinstance(mx, (int, float)) and not isinstance(mn, bool) and not isinstance(mx, bool):
                if mn > mx:
                    errors.append(f"{group_name}.{metric_name}: min ({mn}) > max ({mx})")
            if isinstance(ideal, (int, float)) and not isinstance(ideal, bool):
                if isinstance(mn, (int, float)) and not isinstance(mn, bool) and ideal < mn:
                    errors.append(f"{group_name}.{metric_name}: ideal ({ideal}) < min ({mn})")
                if isinstance(mx, (int, float)) and not isinstance(mx, bool) and ideal > mx:
                    errors.append(f"{group_name}.{metric_name}: ideal ({ideal}) > max ({mx})")

    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)


def _detect_bus_cycles(buses: list[Any], errors: list[str]) -> None:
    adj: dict[str, list[str]] = {}
    bus_names = {b.name for b in buses}
    for b in buses:
        targets: list[str] = []
        if b.route_to in bus_names:
            targets.append(b.route_to)
        for s in b.sends:
            if s.bus in bus_names:
                targets.append(s.bus)
        adj[b.name] = targets

    state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done

    def dfs(node: str, path: list[str]) -> bool:
        state[node] = 1
        for nxt in adj.get(node, []):
            if state.get(nxt, 0) == 1:
                cycle = " -> ".join([*path[path.index(nxt) :], nxt])
                errors.append(f"Routing cycle detected in buses: {cycle}")
                return True
            if state.get(nxt, 0) == 0:
                if dfs(nxt, [*path, nxt]):
                    return True
        state[node] = 2
        return False

    for b in buses:
        if state.get(b.name, 0) == 0:
            if dfs(b.name, [b.name]):
                break


def validate_blueprint_ir(
    ir: BlueprintV2,
    inv: dict[str, Any],
    *,
    strict_v2: bool,
) -> ValidationResult:
    """Validate a typed `BlueprintV2` IR against local Ground Truth inventory."""
    errors: list[str] = []
    warnings: list[str] = []

    positions = inv["positions"]
    drumsets = inv["drumsets"]
    available_channels = set(inv["microphones"]["available_channels"])
    forbidden_channels = set(inv["microphones"]["forbidden_channels"])
    available_bleed = set(inv["microphones"]["available_bleed_channels"])
    stereo_mixnames = {m["mixname"] for m in inv["microphones"].get("all_parsed", []) if m.get("stereo")}
    stack_pack = inv.get("stack_pack", {})
    stack_by_cat: dict[str, set[str]] = {
        cat: {normalize_name(it["name"]) for it in items} for cat, items in stack_pack.items()
    }

    base_kit = ir.kit.base_kit
    used_slots = {piece.slot for piece in ir.kit.pieces}
    unloaded_slots = set(ir.kit.unload_slots)

    if base_kit not in drumsets:
        errors.append(
            f"kit.base_kit '{base_kit}' is not in installed SD3 drumsets: {sorted(inv['base_kits'])}"
        )
    else:
        base_slots = set(drumsets[base_kit]["pieces"].keys())
        orphan_slots = sorted(base_slots - used_slots - unloaded_slots)
        if orphan_slots:
            errors.append(
                f"Orphan base_kit slots from '{base_kit}' not listed in kit.pieces or kit.unload_slots: {orphan_slots}"
            )
        overlap = sorted(used_slots & unloaded_slots)
        if overlap:
            errors.append(f"Slots listed in BOTH kit.pieces and kit.unload_slots: {overlap}")

    for piece in ir.kit.pieces:
        slot = piece.slot
        pname = normalize_name(piece.name)
        if slot not in positions:
            errors.append(f"kit.pieces slot '{slot}' does not exist in SD3 positions {list(positions.keys())}")
            continue
        valid_names = {normalize_name(p["name"]) for p in positions[slot]["pieces"]}
        if pname not in valid_names:
            errors.append(f"kit.pieces[{slot}] '{pname}' not found in SD3 slot '{slot}'.")
        if piece.envelope and slot in {"KickR", "Snare"} and piece.envelope.attack_ms > 0:
            warnings.append(
                f"Drums tab AHDSR attack_ms={piece.envelope.attack_ms} on '{slot}' softens transients; "
                "use Mixer 'Transient' insert to add attack."
            )
        for st in piece.stacks:
            cat = st.category
            sname = normalize_name(st.name)
            if cat not in stack_by_cat:
                errors.append(f"Stack category '{cat}' not found in StackPack ({sorted(stack_by_cat.keys())}).")
            elif sname not in stack_by_cat[cat]:
                errors.append(f"Stack '{sname}' not found in StackPack category '{cat}'.")

    defined_buses = {b.name for b in ir.buses}
    valid_routes = defined_buses | {"Output 1/2"}

    mix_mode = ir.mix_mode
    for mic in ir.mics:
        ch = mic.channel
        if ch in forbidden_channels:
            errors.append(f"FORBIDDEN Part 2-5 channel used in mics: '{ch}' (not installed in Part 1).")
        elif ch not in available_channels:
            errors.append(f"Unknown mic channel '{ch}'. Allowed channels: {sorted(available_channels)}")

        try:
            if ch in stereo_mixnames:
                pan_str_to_stereo_pair(mic.pan)
            else:
                pan_str_to_norm(mic.pan)
        except ValueError as exc:
            errors.append(f"Mic '{ch}' pan error: {exc}")

        if mic.route_to not in valid_routes:
            errors.append(f"Mic '{ch}' routes to undefined bus '{mic.route_to}'.")
        for s in mic.sends:
            if s.bus not in defined_buses:
                errors.append(f"Mic '{ch}' sends to undefined bus '{s.bus}'.")
            if s.pan is not None:
                try:
                    pan_str_to_stereo_pair(s.pan)
                except ValueError as exc:
                    errors.append(f"Mic '{ch}' send pan error: {exc}")

        if mix_mode == "internal_sd3":
            for ins in mic.inserts:
                cal = ins.calibration_targets.model_dump() if ins.calibration_targets else None
                errors.extend(
                    validate_fx_params(
                        ins.fx,
                        ins.params,
                        calibration_targets=cal,
                        strict_v2=strict_v2,
                        context_label=f"mic '{ch}'",
                    )
                )

    valid_bleed_sources = _CANONICAL_BLEED_GROUPS | set(positions.keys())
    for b_entry in ir.bleed.channels:
        bch = b_entry.channel
        if b_entry.enabled and bch not in available_bleed:
            errors.append(
                f"Bleed enabled on '{bch}', which has NO bleed in Part 1. Allowed bleed channels: {sorted(available_bleed)}"
            )
        for src in b_entry.sources:
            if src not in valid_bleed_sources:
                errors.append(
                    f"Bleed source '{src}' on '{bch}' is invalid; expected one of {sorted(valid_bleed_sources)}."
                )
        for src_k in b_entry.source_levels_db:
            if src_k not in valid_bleed_sources:
                errors.append(
                    f"Bleed source_levels_db key '{src_k}' on '{bch}' is invalid; expected one of {sorted(valid_bleed_sources)}."
                )

    seen_bus_indices: dict[int, str] = {}
    for bus in ir.buses:
        bm = BUS_NAME_RE.match(bus.name.strip())
        if bm:
            bnum = int(bm.group(1))
            if bnum < 1 or bnum > 32:
                errors.append(f"Bus '{bus.name}' index {bnum} out of valid range (Bus 1..Bus 32).")
            elif bnum in seen_bus_indices:
                errors.append(
                    f"Duplicate bus number Bus {bnum} shared by '{seen_bus_indices[bnum]}' and '{bus.name}'."
                )
            else:
                seen_bus_indices[bnum] = bus.name
        elif strict_v2 and mix_mode == "internal_sd3":
            errors.append(f"Bus '{bus.name}' must follow 'Bus N (Label)' naming (N in 1..32) for internal_sd3.")

        if bus.pan is not None:
            try:
                pan_str_to_stereo_pair(bus.pan)
            except ValueError as exc:
                errors.append(f"Bus '{bus.name}' pan error: {exc}")

        if bus.route_to not in valid_routes:
            errors.append(f"Bus '{bus.name}' routes to undefined bus '{bus.route_to}'.")
        for s in bus.sends:
            if s.bus not in defined_buses:
                errors.append(f"Bus '{bus.name}' sends to undefined bus '{s.bus}'.")
        if mix_mode == "internal_sd3":
            for ins in bus.inserts:
                cal = ins.calibration_targets.model_dump() if ins.calibration_targets else None
                errors.extend(
                    validate_fx_params(
                        ins.fx,
                        ins.params,
                        calibration_targets=cal,
                        strict_v2=strict_v2,
                        context_label=f"bus '{bus.name}'",
                    )
                )

    _detect_bus_cycles(ir.buses, errors)

    if ir.master_bus.channel != "Output 1/2":
        warnings.append(f"Master bus channel is '{ir.master_bus.channel}' (expected 'Output 1/2' for stereo bounce).")
    if mix_mode == "internal_sd3":
        for ins in ir.master_bus.inserts:
            cal = ins.calibration_targets.model_dump() if ins.calibration_targets else None
            errors.extend(
                validate_fx_params(
                    ins.fx,
                    ins.params,
                    calibration_targets=cal,
                    strict_v2=strict_v2,
                    context_label="master_bus",
                )
            )

    if ir.preflight_audit is None:
        warnings.append("Missing 'preflight_audit' block.")
    else:
        audit_dict = ir.preflight_audit.model_dump()
        unchecked = [k for k, v in audit_dict.items() if not v]
        if unchecked:
            warnings.append(f"Preflight audit has unchecked items: {unchecked}")

    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)


def validate_blueprint(
    blueprint_path: Path,
    inventory_path: Path | None = None,
) -> ValidationResult:
    resolved_inv = inventory_path or default_inventory_path()
    if not blueprint_path.exists():
        return ValidationResult(ok=False, errors=[f"Blueprint file not found: {blueprint_path}"])
    if not resolved_inv.exists():
        return ValidationResult(
            ok=False,
            errors=[f"Inventory file not found: {resolved_inv}. Run `sd3-forge init` first."],
        )

    try:
        bp = _load_yaml(blueprint_path)
    except Exception as exc:
        return ValidationResult(ok=False, errors=[f"YAML parse error in {blueprint_path}: {exc}"])

    try:
        ir, _, is_v2 = load_blueprint_ir(bp)
    except ValidationError as exc:
        errs = [
            f"Blueprint schema error at {list(err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return ValidationResult(ok=False, errors=errs)
    except ValueError as exc:
        return ValidationResult(ok=False, errors=[f"Blueprint schema error: {exc}"])

    inv = _load_json(resolved_inv)
    return validate_blueprint_ir(ir, inv, strict_v2=is_v2)


def validate_preset_dir(
    preset_dir: Path,
    inventory_path: Path | None = None,
) -> ValidationResult:
    spec_res = validate_spec_targets(preset_dir / "02-spec-targets.yaml")
    bp_res = validate_blueprint(preset_dir / "03-sd3-blueprint.yaml", inventory_path=inventory_path)
    errors = spec_res.errors + bp_res.errors
    warnings = spec_res.warnings + bp_res.warnings
    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)
