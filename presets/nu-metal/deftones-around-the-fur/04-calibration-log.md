# Log de Calibração — `deftones-around-the-fur`

## Status Atual
- **Gate 0 (Ground Truth):** Concluído
- **Gate 1 (Spec Contract v2):** Concluído (`02-spec-targets.yaml` — `schema_version: "2.0"`, `max_warnings: 1`)
- **Gate 2 (Blueprint IR v2):** Validado contra Part 1 (`03-sd3-blueprint.yaml` — `schema_version: "2.0"`, `0` erros)
- **Gate 2.5 (Autocrítica Pré-Voo CRITIC):** Aprovado (`preflight_audit` completo, 0 erros)
- **Gate 3 (`v0-raw` → `v5`):** Histórico v1 concluído (`28/32 PASS | 4 WARN | 0 FAIL` na `v5`)
- **Gate 4 DSP v2 + MIDI v2 (`v10-m2.wav`):** **GREEN — `overall_status: PASS`** (**44/44 PASS | 0 WARN | 0 FAIL | `scalar_loss: 0.2883`**)
- **Próximo Passo Final:** Exportar/carregar o preset compilado em contexto musical (guitarra/baixo) e avançar para a Milestone 3 (worker VST3 persistente e calibrador analítico de 2 estágios).

---

## Histórico de Rodadas

| Versão | Arquivo | Status Geral | Métricas Principais Observadas | Diagnóstico / Notas |
| :--- | :--- | :---: | :--- | :--- |
| `v0-raw` | `bounces/v0-raw_Out_1+2.wav` | `FAIL` (21/32 PASS, 7 WARN, 4 FAIL) | `kick f0`: `38.61 Hz`; `snare f0`: `189.7 / 198.2 Hz`; `groove crest`: `21.40 dB` | Baseline cru sem Mixer (DSP v1) |
| `v5` | `bounces/v5_Out_1+2.wav` | `PASS` (28/32 PASS, 4 WARN, 0 FAIL) | `kick f0`: `50.74 Hz`; `snare`: `222.8 / 231.4 Hz`; 4 WARNs residuais | Aprovado no contrato DSP v1 |
| `v6-m2` | `bounces/v6-m2.wav` | `PASS` (26/32 PASS, 6 WARN, 0 FAIL) | `kick.decay_t20`: `630.9 ms`; `snare ring`: `19.66 / 20.14 dB` (`350/836/1227 Hz`); `cymbals harshness`: `+5.71 dB` | Baseline v1 reavaliado com DSP v2 (Tukey/Parseval/Schroeder) + MIDI v2 |
| `v7-m2` | `bounces/v7-m2.wav` | `FAIL` (41/44 PASS, 3 WARN, 0 FAIL) | `kick.decay_t20` PASS; `toms` `pan_order_valid=true`; `cymbals harshness`: `+5.90 dB`; `snare ring`: `18.48 / 18.55 dB` | Budget `max_warnings: 1` ativado; `OH Dyn` HighShelf em `8.5 kHz` reduziu denominador `8-16 kHz` |
| `v8-m2` | `bounces/v8-m2.wav` | `FAIL` (40/44 PASS, 2 WARN, 2 FAIL) | `cymbals.harshness` PASS; `snare crest`: `22.28 / 22.07 dB`; `snare_center.ring`: `18.10 dB` | Retorno do HighShelf para `7.0 kHz` + cortes no `Amb Ribbon`/`Hi-Hat` resolveram pratos; `555 Hz` reapareceu |
| `v9-m2` | `bounces/v9-m2.wav` | `FAIL` (42/44 PASS, 2 WARN, 0 FAIL) | `snare crest` PASS; `snare_center.ring`: `17.553 dB` (+0.05 dB); `groove.low`: `-2.974 dB` (+0.03 dB) | Todos os 44 hard checks PASS; restaram apenas `350 Hz` paralelo/sala e `+0.03 dB` em `60-150 Hz` |
| `v10-m2` | `bounces/v10-m2.wav` | **`PASS`** (**44/44 PASS, 0 WARN, 0 FAIL**) | `kick`: `60.08 Hz`, `decay_t20 358.3 ms (R²=0.935)`, `DRR 6.31 dB`, `double_kick 16.51 dB`; `snare`: `224.6 / 226.0 Hz`, `ring 17.06 / 16.79 dB`, `vel_dyn 8.89 dB`; `toms`: pitch + pan `true`; `cymbals`: harshness `+0.03 dB`, choke `13.78 dB`; `groove`: `-22.50 LUFS`, `LRA 2.03 LU` | **44/44 PASS, 0 WARN, 0 FAIL (`scalar_loss=0.2883`).** Notas de notch `350 Hz` em `Bus 4`/`Bus 5` e `-2.5 dB` no `Bus 1` zeraram avisos preservando o punch e caráter Terry Date. |
