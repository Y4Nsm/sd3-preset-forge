# Metodologia de Métricas Acústicas — `analyze_bounce.py`

Este documento explica exatamente o que o motor DSP da Forja mede em um bounce estéreo exportado do SD3 usando `test-suite/standard-test-groove.mid`.

---

## 1. Alinhamento Automático & Segurança (`safety`)

- **Auto-alinhamento (`alignment_offset_ms`):** Detecta o primeiro transiente acima de `max(0.03, 0.12 * pico_3s)` nos primeiros 3 segundos e alinha o tempo `0.0s` do MIDI a esse ponto (`-2 ms` de margem). Isso torna a análise imune a silêncios iniciais no bounce.
- **`true_peak_dbfs`:** Oversampling polifásico 4x. Deve ficar `<= -0.5 dBFS` (ideal `-1.5 dBFS`) para evitar clipping inter-sample.
- **`clipping_samples`:** Amostras com `|x| >= 0.999`. Meta rígida: `0`.
- **`lr_balance_db`:** Diferença RMS entre canal esquerdo e direito (`<= ±1.5 dB`).
- **`*_stereo_correlation`:** Correlação de Pearson `[-1, +1]`.
  - Kick e Snare próximos de `+0.85 a +1.0` (foco central sólido).
  - Groove geral entre `+0.25 e +0.85` (largura estéreo saudável sem cancelamento de fase em mono).

---

## 2. Métricas por Instrumento

### Kick (`kick`)
- **`fundamental_hz`:** Pico espectral (FFT com janela Hann + interpolação parabólica) entre `35–100 Hz` nos primeiros `150 ms`.
  - *Nu Metal:* tipicamente `50–66 Hz` (Korn mais sub ~50–55 Hz; Deftones/Slipknot ~55–62 Hz).
  - *Grunge:* tipicamente `55–72 Hz` (mais orgânico e encorpado).
- **Razões espectrais (dB relativos ao RMS da janela do golpe):**
  - `sub_30_70_db` (peso físico), `punch_70_130_db` (soco no peito), `boxiness_250_550_db` (som de papelão — manter controlado!), `click_3000_6000_db` (ataque de batedor).
- **`crest_factor_db`:** Relação Pico/RMS (`9–20 dB`). Se cair abaixo de `8 dB`, houve excesso de compressão/clipping.
- **`decay_t20_ms`:** Tempo de queda de `20 dB` após o pico (`120–380 ms`).

### Snare Center & Rimshot (`snare_center`, `snare_rimshot`)
- **`fundamental_hz`:** Pico em `120–320 Hz` na janela `5–120 ms`. O relatório calcula automaticamente o **delta em semitons** (`12 * log2(ideal / medido)`) para você girar o knob **Pitch** do SD3 sem chute.
  - *Caixa aguda/estalo (Deftones, 311, Incubus):* `210–245 Hz`.
  - *Caixa média/pesada (Korn, Grunge, Soundgarden):* `165–205 Hz`.
- **`ring_prominence_db`:** Pico menos mediana na banda `300–750 Hz` na cauda (`25–250 ms`). Mede o "ring" metálico/madeira. Se passar de `15–18 dB`, exige corte estreito no `EQ` ou controle de `Sustain`.
- **`crack_2000_5000_db`:** Presença/estalo nos primeiros `80 ms`.
- **`wire_sizzle_7000_14000_db`:** Brilho e resposta da esteira (`Snare Bottom`).
- **`decay_t30_ms`:** Tempo de queda de `30 dB` (captura também o efeito do `Room Reverb` / `Amb Ribbon`).

### Toms (`toms`)
- **`racktom1_hz > racktom2_hz > floortom1_hz > floortom2_hz`:** Garante progressão monotônica limpa (`pitch_order_valid: true`).

### Pratos (`cymbals`) & Groove (`groove`)
- **`harshness_ratio_db`:** Energia `3–6 kHz` menos `8–16 kHz`. Valores positivos muito altos (`> +2 dB`) indicam pratos estridentes/ardidos.
- **`cymbals_stereo_width`:** `1 - correlation` (valores entre `0.35 e 1.15` indicam abertura estéreo natural de `OH Dyn` + `Amb Ribbon`).
- **Groove (6 bandas + `kick_to_snare_peak_diff_db`):** Garante equilíbrio entre bumbo e caixa sem afogar os médios-graves (`150–500 Hz`).
