---
name: sd3-forge
description: Engineer, validate, compile, and calibrate Toontrack Superior Drummer 3 presets (`schema_version: "2.0"`) cleanly using local Ground Truth and anti-Goodhart DSP audits.
---

# SD3 Preset Forge Skill

Use this workflow whenever creating, editing, validating, or calibrating a Toontrack Superior Drummer 3 preset (`presets/<genre>/<slug>/`).

## Interfaces
You can use either:
- **CLI (`sd3-forge <cmd> --json`)** in bash/terminal
- **MCP Server (`sd3-forge-mcp`)** exposing the 6 tools:
  - `sd3_query_inventory`
  - `sd3_validate_preset`
  - `sd3_compile_preset`
  - `sd3_daemon_control`
  - `sd3_calibrate_preset`
  - `sd3_analyze_or_profile`

## 3-Turn Preset Workflow
1. **Turn 1 — Discover Ground Truth & Author:**
   - Query `sd3-forge inventory summary --json`, `kits`, `pieces --slot <Slot>`, `mics --bleed-only`, and `fx`. Never dump raw `inventory.json`.
   - Optionally extract advisory macro priors with `sd3-forge profile-ref <stem.wav> --json`.
   - Scaffold with `sd3-forge new-preset <genre> <slug>`, then write `01-research.md`, `02-spec-targets.yaml` (`schema_version: "2.0"`, `max_warnings: 1`), and `03-sd3-blueprint.yaml` (`schema_version: "2.0"`, explicit `unload_slots` for unused tom/cymbal slots).
2. **Turn 2 — Validate, Start Worker & Calibrate:**
   - Gate schema + Ground Truth + 35-FX contract via `sd3-forge validate <dir> --json`.
   - Keep `Superior Drummer 3.vst3` warm via `sd3-forge daemon start --json`, then run `sd3-forge calibrate <dir> --json` (canaries, Stage 1 Secant pitch, Stage 2 causal trims, `.forge-history/best.yaml` rollback).
3. **Turn 3 — Finalize, Install & Stop Worker:**
   - Inspect `test-report.json` (`hard_failures == 0`, `warnings <= max_warnings`). Apply surgical mix tweaks + `sd3-forge auto-test <dir> --version v-final` if needed.
   - Install `.sd3p` via `sd3-forge compile-sd3p <dir> --install`, stop the daemon (`sd3-forge daemon stop --json`), and update `04-calibration-log.md`.

## Non-Negotiable Rules
- Use only exact kit pieces, mics, stacks, and native FX names returned by `sd3-forge inventory`.
- Never put compressor `GR` in `params`; use `calibration_targets.target_gr_db`.
- Never weaken `02-spec-targets.yaml` bounds or relax test assertions to make a failing check pass.
- Never commit `.sd3p`, `.wav`, `inventory.json`, `.forge-history/`, `test-report.*`, `diagnostic-plots.png`, or local machine paths.
