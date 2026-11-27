"""Typed Pydantic v2 Intermediate Representation (IR) for SD3 Preset Forge blueprints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PresetMetadata(_StrictModel):
    preset_id: str
    genre: str
    reference: str


class PreflightAudit(_StrictModel):
    envelope_ahdsr_checked: bool
    fx_bands_checked: bool
    unused_slots_resolved: bool
    part1_mics_only: bool
    raw_baseline_planned: bool


class DrumEnvelope(_StrictModel):
    attack_ms: float = Field(default=0.0, ge=0.0)
    hold_ms: float | None = Field(default=None, ge=0.0)
    decay_ms: float | None = Field(default=None, ge=0.0)
    sustain_db: float | None = Field(default=None, le=0.0)
    release_ms: float | None = Field(default=None, ge=0.0)


class StackLayer(_StrictModel):
    category: str
    name: str
    library_id: str = "SP-SUPERIOR_DRUMMER_3"
    pad_name: str | None = None
    level_db: float = 0.0
    pitch_semitones: float = Field(default=0.0, ge=-12.0, le=12.0)


class KitPiece(_StrictModel):
    slot: str
    name: str
    pitch_semitones: float = Field(default=0.0, ge=-12.0, le=12.0)
    level_db: float = 0.0
    envelope: DrumEnvelope | None = None
    stacks: list[StackLayer] = Field(default_factory=list)


class KitConfig(_StrictModel):
    base_kit: str
    unload_slots: list[str] = Field(default_factory=list)
    pieces: list[KitPiece] = Field(min_length=4)


class CalibrationTargets(_StrictModel):
    target_gr_db: float | tuple[float, float] | None = None
    notes: str | None = None

    @field_validator("target_gr_db", mode="before")
    @classmethod
    def _coerce_gr_target(cls, v: Any) -> float | tuple[float, float] | None:
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            if len(v) != 2:
                raise ValueError("target_gr_db list must contain exactly 2 numbers [min, max]")
            lo, hi = float(v[0]), float(v[1])
            return (lo, hi)
        return float(v)


class InsertFx(_StrictModel):
    fx: str
    purpose: str | None = None
    active: bool = True
    sidechain: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    calibration_targets: CalibrationTargets | None = None


class SendConfig(_StrictModel):
    bus: str
    level_db: float = 0.0
    pre_fader: bool = False
    pan: str | float | None = None


class MicChannel(_StrictModel):
    channel: str
    fader_db: float
    pan: str | float = "C"
    phase_invert: bool = False
    route_to: str = "Output 1/2"
    sends: list[SendConfig] = Field(default_factory=list)
    inserts: list[InsertFx] = Field(default_factory=list)


class BleedChannel(_StrictModel):
    channel: str
    enabled: bool
    level_db: float = 0.0
    sources: list[str]
    source_levels_db: dict[str, float] = Field(default_factory=dict)


class BleedConfig(_StrictModel):
    channels: list[BleedChannel]


class BusChannel(_StrictModel):
    name: str
    fader_db: float
    pan: str | float | None = None
    route_to: str = "Output 1/2"
    sends: list[SendConfig] = Field(default_factory=list)
    inserts: list[InsertFx] = Field(default_factory=list)


class MasterBus(_StrictModel):
    channel: str
    fader_db: float
    inserts: list[InsertFx] = Field(default_factory=list)


class BlueprintV2(_StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    metadata: PresetMetadata
    mix_mode: Literal["internal_sd3", "multi_out"]
    preflight_audit: PreflightAudit | None = None
    kit: KitConfig
    mics: list[MicChannel] = Field(min_length=4)
    bleed: BleedConfig
    buses: list[BusChannel] = Field(default_factory=list)
    master_bus: MasterBus


def load_blueprint_ir(raw: dict[str, Any]) -> tuple[BlueprintV2, list[str], bool]:
    """Validate/coerce a blueprint dict into `BlueprintV2`.

    Returns `(ir, deprecation_warnings, is_v2)`.
    """
    if not isinstance(raw, dict):
        raise ValueError("Blueprint YAML root must be a mapping.")

    if str(raw.get("schema_version", "")) == "2.0":
        ir = BlueprintV2.model_validate(raw)
        return ir, [], True

    from sd3_forge.migrate import migrate_v1_dict_to_v2

    migrated = migrate_v1_dict_to_v2(raw)
    ir = BlueprintV2.model_validate(migrated)
    warnings = [
        "Deprecated blueprint schema v1 (missing schema_version: '2.0'); "
        "run `sd3-forge migrate <preset_dir> --in-place` to upgrade."
    ]
    return ir, warnings, False
