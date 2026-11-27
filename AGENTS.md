# SD3 Preset Forge — Agent Guide

Deterministic, TDD-driven preset engineering forge for Toontrack Superior Drummer 3 (`schema_version: "2.0"`).

## Pipeline Architecture
1. **Local Ground Truth (`sd3-forge init` / `inventory`)**: Parses user's installed library into local `inventory.json` and builds clean `base-neutral.sd3p`.
2. **Typed IR & Validator (`sd3-forge validate`)**: Validates `02-spec-targets.yaml` + `03-sd3-blueprint.yaml` against Pydantic v2 IR, active kit pieces, Part 1/installed mics, bus routing, and the static 35-FX contract (`effect 10..44`).
3. **Lossless Compiler (`sd3-forge compile-sd3p`)**: Compiles blueprint directly into native `.sd3p` (resetting omitted channels/buses `0..63`, encoding AHDSR envelopes, bleed sources, stacks, sends, and FX).
4. **Persistent VST3 Worker (`sd3-forge daemon`)**: Keeps `Superior Drummer 3.vst3` resident on `127.0.0.1` across scoped probes and iterations, with a pre-flight multi-slot audio canary.
5. **Anti-Goodhart DSP Engine & Calibrator (`sd3-forge analyze` / `calibrate`)**: Evaluates bounces across ISO 3382 decay, pitch, `280-1600 Hz` ring peaks, per-cymbal harshness, unloaded toms/pan order, LUFS/LRA, and calibrates in 2 bounded stages with `.forge-history/best.yaml` auto-rollback.

## Standard 3-Turn Preset Workflow
### Turn 1 — Query Inventory & Author Initial Blueprint
1. Query installed kits, slots, mics, and FX (never dump raw `inventory.json`):
   ```bash
   sd3-forge inventory summary --json
   sd3-forge inventory kits --kit "Ludwig Classic 70s 3 Ply" --json
   sd3-forge inventory pieces --slot Snare --json
   sd3-forge inventory mics --bleed-only --json
   ```
2. Optional advisory priors from a reference drum stem (`numpy`/`scipy`, no PyTorch):
   ```bash
   sd3-forge profile-ref <stem.wav> --json
   ```
3. Scaffold `presets/<genre>/<slug>/` with `sd3-forge new-preset <genre> <slug>`, then author:
   - `01-research.md`: Tag facts `[Verified Source]` vs `[Acoustic Inference]`.
   - `02-spec-targets.yaml`: Set `schema_version: "2.0"` and `max_warnings: 1`.
   - `03-sd3-blueprint.yaml`: Set `schema_version: "2.0"`, exact piece/mic/FX names from `inventory`, explicit `unload_slots` for any unused tom/cymbal slots, `target_gr_db` inside `calibration_targets`, and clean gain staging.

### Turn 2 — Validate, Start Daemon & Calibrate
```bash
sd3-forge validate presets/<genre>/<slug> --json
sd3-forge daemon start --json
sd3-forge calibrate presets/<genre>/<slug> --json
```
- `calibrate` runs the pre-flight canary, full baseline, Stage 1 Secant pitch (`KickR`/`Snare`), Stage 2 causal notch/balance trims, auto-rollback on regression, and final full-length MIDI v2 gate.

### Turn 3 — Verify, Install & Clean Up
1. Inspect `presets/<genre>/<slug>/test-report.json` (`hard_failures == 0`, `warnings <= max_warnings`).
2. If minor mix tweaks are needed, edit `03-sd3-blueprint.yaml` and run:
   ```bash
   sd3-forge auto-test presets/<genre>/<slug> --version v-final
   ```
3. Install compiled `.sd3p` to user SD3 presets and stop the daemon:
   ```bash
   sd3-forge compile-sd3p presets/<genre>/<slug> --install
   sd3-forge daemon stop --json
   ```
4. Update `presets/<genre>/<slug>/04-calibration-log.md`.

## Strict Rules for Agents
- **Zero Hallucination**: Every kit piece, mic name, stack item, and native FX must come verbatim from `sd3-forge inventory`.
- **Single Validation-Compilation Contract**: Never emit unknown keys or unsupported FX params; `calibration_targets.target_gr_db` holds GR goals, not `params.GR`.
- **Anti-Goodhart Integrity**: Never weaken `02-spec-targets.yaml` bounds, delete failing checks, or relax test assertions to pass.
- **Clean-Room & IP Hygiene**: Never commit `.sd3p`, `.wav`, `inventory.json`, `test-report.*`, `diagnostic-plots.png`, `.forge-history/`, or local machine paths.

## CLI Reference
| Command | Purpose |
| :--- | :--- |
| `sd3-forge init [--from-vst3]` | Detect SD3 install, extract `inventory.json`, build `base-neutral.sd3p` & MIDI v2 |
| `sd3-forge inventory <subcmd> --json` | Query `summary`, `kits`, `pieces`, `mics`, `fx`, `stacks`, `keymap` |
| `sd3-forge profile-ref <wav> --json` | Extract lightweight advisory acoustic priors from a drum reference |
| `sd3-forge validate <dir> --json` | Schema + Ground Truth + 35-FX contract gate |
| `sd3-forge migrate <dir> --in-place` | Upgrade v1 blueprint YAML to `schema_version: "2.0"` |
| `sd3-forge daemon start\|status\|stop` | Manage persistent headless VST3 worker (`127.0.0.1`) |
| `sd3-forge calibrate <dir> --json` | Run 2-stage bounded analytical calibrator with `.forge-history/` rollback |
| `sd3-forge auto-test <dir>` | Validate -> compile -> render (daemon/direct) -> DSP audit |
| `sd3-forge compile-sd3p <dir> [--install]` | Compile `.sd3p` and optionally copy to user SD3 presets folder |
| `sd3-forge-mcp [--list-tools]` | Optional 6-tool MCP stdio server (see `.claude/skills/sd3-forge/SKILL.md`) |
