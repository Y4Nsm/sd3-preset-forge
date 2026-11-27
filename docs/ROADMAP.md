# SD3 Preset Forge — Master Roadmap (TDD & Interoperability Architecture)

> Audited architecture plan combining **Clean-Room Interoperability**, **Strict Red → Green → Refactor TDD**, and **Agent-First Hybrid Orchestration** for Claude Code, Cursor, Codex, Antigravity, and CLI/CI workflows.

---

## Architecture Overview (4-Layer Hybrid)

1. **Layer 1 — Local Ground Truth & DSP Verifier**: `sd3-forge init` (config-first, zero proprietary git assets) + multi-pack extractor + anti-Goodhart DSP engine.
2. **Layer 2 — Core Engine & Calibrator (`sd3_forge/`)**: Pydantic v2 Typed IR, clean-room static 35-FX catalog, lossless `.sd3p` compiler, persistent VST3 worker, analytical 2-stage calibrator + `.forge-history/` rollback.
3. **Layer 3 — Agent-First JSON CLI (`sd3-forge <cmd> --json`)**: Universal interface for any AI coding agent or CI runner.
4. **Layer 4 — AI Interfaces (`AGENTS.md`, `CLAUDE.md`, Optional Skill & Thin MCP Server)**: Token-efficient instructions + optional `sd3-forge-mcp` wrapper over Layer 2/3.

---

## Core TDD & Execution Principles

- **Red → Green → Refactor**: Every bug fix or DSP formula starts with a failing test against structural ASTs or exact synthetic mathematical ground truth (`<= ±0.2 dB`, `<= ±0.5 Hz`, `<= ±5 ms`).
- **CI Test Isolation**: `@pytest.mark.vst3` gates live VST3 tests; `pytest -m "not vst3"` runs cleanly on Ubuntu/macOS/Windows CI using synthetic fixtures with zero proprietary assets.
- **Single Validation-Compilation Contract**: Anything accepted by `sd3-forge validate` compiles without silent drops; unimplemented or unknown keys fail explicitly.
- **Automatic Checkpoint Rollback**: `.forge-history/best.yaml` rejects any candidate that increases `hard_failures` or worsens scalar loss.

---

## Milestones

### Milestone 0 — Open-Source Foundation, Legal/IP Hygiene, Packaging & `sd3-forge init` *(Done)*
- Purge local paths and user/factory `.sd3p`/`inventory.json` dumps from git; add MIT `LICENSE`, hardened `.gitignore`, and non-affiliation / EULA notices.
- Consolidate package into `sd3_forge/`, expose `sd3-forge` CLI entrypoint, drop unused `librosa`, make `pedalboard` an optional `[render]` extra with lazy imports, load package resources via `importlib.resources`.
- Implement cross-platform path detection (`paths.py`) and config-first `sd3-forge init` generating local `inventory.json` + clean neutral `.sd3p` template in `platformdirs` user data dir.
- Add synthetic fixtures (`tests/fixtures/`) and cross-platform GitHub Actions CI (`ubuntu`, `macos`, `windows`).

### Milestone 1 — Multi-Library Ground Truth, Clean-Room 35-FX Registry, Typed IR v2 & Lossless Compiler *(Done)*
- Replace regex slicing with brace-aware + macro-expanding (`TEMPLATE`/`USE`) config parser (`uberconf`, `micconf`, `padconf`, `InstallerConfig`, `instrumentgroups`, `soundDB`) supporting Core Part 1, Full Parts 1–5, and SDXs/EZXs.
- Clean-room static 35-FX catalog (`sd3_forge/fx_catalog.py`) covering `effect 10..44` verified offline against `s3presetconf` + controlled probes (no fragile runtime binary scraping).
- Pydantic v2 Typed IR (`schema_version: "2.0"`) separating `calibration_targets` (e.g. `target_gr_db`) from explicit knobs, plus `sd3-forge migrate` v1→v2.
- Lossless compiler fixing `envelope` (`fadeonset`/`decay`/`sustain`/`fadetime`), `bleed.sources` (`usemic`/`leakvolume`), `stacks` (`xpad`), stereo pan, pre/post sends, full reset of omitted channels/buses `0..63`, and all 35 FX.

### Milestone 2 — Anti-Goodhart DSP Engine v2, Multi-Velocity MIDI & Lightweight Reference Priors *(Done)*
- Asymmetric Tukey window (fixes `-13.4 dB` Hann transient attenuation), Parseval 2x fix, Attack/Body/Tail separation.
- ISO 3382 Schroeder EDC ($T_{20}/T_{30}$ with $R^2$ + drop guard) and Direct-to-Reverberant Ratio (DRR).
- Log-magnitude parabolic pitch + prominence/sub-100 Hz centroid guard; `280–1600 Hz` sliding-median ring detector returning exact `ring_peaks_hz`; per-cymbal evaluation; dynamic unloaded-tom handling + pan azimuth check; active crest ($T_{95}$); ITU-R BS.1770-4 LUFS/LRA; cross-correlation onset alignment; strict warn budget + causal JSON patches.
- Multi-velocity MIDI v2 (`35..125` ladders, ghost-to-backbeat check, all loaded cymbals, double-kick, flams, chokes, bleed stress, `>= 4s` post-cymbal spacing) + short `--scope` probes.
- Lightweight `numpy`/`scipy` `sd3-forge profile-ref <stem.wav>` advisory macro-priors (no PyTorch/Demucs bloat) + formal `deftones-around-the-fur` v2 recalibration (`0 FAIL`, `<= 1 WARN`).

### Milestone 3 — Persistent VST3 Worker, Analytical 2-Stage Calibrator & Lean Agent Harness *(Done)*
- Persistent VST3 worker (`sd3-forge daemon`) holding `Superior Drummer 3.vst3` in memory + pre-flight multi-slot canary + burst-averaged probes + final `cycle S` validation gate.
- 2-stage bounded analytical calibrator (`sd3-forge calibrate`: Secant pitch → causal FFT notch/band/fader trim) + `.forge-history/best.yaml` auto-rollback.
- Compact `sd3-forge inventory` query CLI (`--json`) + lean English `<120`-line `AGENTS.md` / `CLAUDE.md` + `CONTRIBUTING.md`, verified by end-to-end creation of a brand-new 3-tom Grunge preset (`alice-in-chains-facelift`) in `<= 3` agent turns.

### Milestone 4 — Optional MCP Server (`sd3-forge-mcp`) & Claude Code Skill (Post-Core) *(Done)*
- Thin 6-tool MCP wrapper (`sd3_forge/mcp_server.py`) over the stabilized Core + Worker + `.claude/skills/sd3-forge/SKILL.md`.
- Complete `pipx`/`uv tool` isolated clean-install verification for v1.0 release.

---

## Key Architectural Trade-offs

| Decision | Rejected Alternative | Rationale |
| :--- | :--- | :--- |
| Clean-room static 35-FX registry | Runtime binary/XML scraping in `init` | Embedded `<catalog>` XML `engine_index` differs from `.sd3p` params; static specs survive SD3 updates across Windows & macOS. |
| Persistent VST3 daemon (`raw_state` reuse) | `macros {}` binding | `macros` only saves ~1.1s while introducing pack-dependent `ix1` offsets and 100-param quantization limits. |
| 4–6 hit burst averaging + final `cycle S` pass | Disabling `cycle S` during calibration | Prevents overfitting narrow EQ notches to a single round-robin sample. |
| Lightweight `numpy`/`scipy` `profile-ref` | Demucs / PyTorch (~3.5 GB) + MR-STFT | Eliminates 3 GB dependency failures and avoids fitting Demucs cymbal separation artifacts. |
| Analytical bounded 2-stage calibrator | Black-box CMA-ES | Converges in < 2 minutes, remains auditable, and avoids exploiting metric loopholes. |
