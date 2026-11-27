# Calibration Log — `alice-in-chains-facelift`

- **Preset ID:** `alice-in-chains-facelift` (`schema_version: "2.0"`)
- **Reference:** Alice In Chains — *Facelift* (1990) | Sean Kinney & Dave Jerden
- **Base Kit & Geometry:** `Ludwig Classic 70s 3 Ply` with 3 loaded toms (`Tom1`, `Tom4`, `Tom5`) and explicit `unload_slots: ["Tom2", "Tom3"]`.

## Calibration Pipeline Trace
1. **Validation Gate:** `sd3-forge validate presets/grunge/alice-in-chains-facelift --json` -> `PASS` (`0` errors, `0` warnings).
2. **Pre-Flight Multi-Slot Canary (`sd3-forge daemon`):** All 7 loaded kit slots passed audio verification (`KickR -7.55 dBFS`, `Snare -6.18 dBFS`, `Tom1 -14.48 dBFS`, `Tom4 -12.35 dBFS`, `Tom5 -10.42 dBFS`, `Hats -14.45 dBFS`, `Cymbal1 -16.44 dBFS`; unloaded `Tom2` and `Tom3` skipped cleanly).
3. **2-Stage Bounded Calibration (`sd3-forge calibrate`):**
   - **Baseline (`iter_000`):** `3` hard failures, `5` warnings, `scalar_loss = 360.6364`.
   - **Stage 1 (`iter_001` Secant Snare Pitch):** Tuned `8x14" Ludwig Coliseum` down to `-3.4 st` (`snare_center.fundamental_hz = 195.67 Hz`), reducing hard failures to `2` (`scalar_loss = 276.0463`).
   - **Stage 2 (`iter_002..iter_004` + `.forge-history/best.yaml` rollback):** Applied snare notches (`732 Hz`, `456 Hz`) and master `320 Hz` trim while automatically rejecting & rolling back candidates that increased warnings (`iter_002`, `iter_004`).
4. **Final Mix Polish & Verified MIDI v2 Bounce (`v-final.wav`, `112.0s`, rendered via persistent VST3 daemon in `19.8s`):**
   - Switched `KickR` to `'16x24" Pearl Masterworks'` (`+5.5 st`) for tighter sub decay and double-kick clarity, notched bleed-borne `301 / 742 / 902 Hz` snare rimshot overtones across `Snare Top`, `Bus 2`, `OH Dyn`, `Amb Ribbon`, and `Bus 4`, and tuned `Comp 670` threshold (`0.18`) + `Comp 76` attack (`4`).

## Final Verification Metrics (`v-final.wav`)
- **Result:** **`PASS`** — **43/44 PASS | 1 WARN | 0 FAIL** (`scalar_loss = 0.2471`, `warn_budget_exceeded = false`)
- **Safety:** True Peak `-6.38 dBFS`, `0` clipped samples, L/R Balance `-0.41 dB`, Groove Corr `0.846`, Kick Corr `0.957`, Snare Corr `0.679`
- **Kick:** `f0 = 49.93 Hz`, `sub_30_70 = -2.94 dB`, `punch_70_130 = -4.54 dB`, `T20 = 275.6 ms` (`R^2 = 0.978`), `DRR = +3.05 dB`, `Double-Kick Clarity = 6.07 dB`
- **Snare Center / Rimshot:** `f0 = 202.86 Hz / 202.30 Hz`, Center Ring `15.64 dB` (PASS), `T30 = 648.3 ms`, Ghost-to-Backbeat `8.17 dB`, Rimshot Ring `20.13 dB` (`1 WARN`)
- **3 Loaded Toms (`Tom1`, `Tom4`, `Tom5`):** `130.0 Hz -> 73.4 Hz -> 58.8 Hz`, Pan L/R `+3.16 -> -2.63 -> -8.50 dB` (`pitch_order_valid = True`, `pan_order_valid = True`)
- **Cymbals:** Harshness `-0.66 dB`, Width `0.981`, Choke Attenuation `12.13 dB`
- **Groove:** Integrated Loudness `-22.13 LUFS`, `LRA = 1.11 LU`, Kick-to-Snare Diff `-1.71 dB`
