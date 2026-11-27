# Guia Passo a Passo no SD3 — Deftones (*Around the Fur* / *White Pony*)

> **Versão Final Calibrada (`v5` — `PASS` 28/32, 0 FAIL)** | **Mixagem 100% dentro do Superior Drummer 3** (ao final você salva um único arquivo `.sd3p`).

---

## Mini-Glossário Rápido (O Que Significam os Botões em Inglês do SD3)

| Termo no SD3 | O que é na prática | Onde fica |
| :--- | :--- | :--- |
| **Remove Instrument** | Tira uma peça do kit (libera RAM/CPU e remove o canal sobrando do Mixer). | Aba *Drums* → botão direito na peça → *More...* → *Remove Instrument* |
| **Tuning (`0:00.0`)** | Afinação no formato **`oitava:semitons.décimos`** (ex.: `0:02.7` = +2.7 semitons). | Aba *Drums* → painel direito → caixa **Tuning** |
| **Envelope and Offset** | Controla **quanto tempo dura o som** (AHDSR). Deixe `Attack` sempre em `0 ms` para não perder impacto! | Aba *Drums* → painel direito → caixa **Envelope and Offset** (botão *On/Off*) |
| **Bus 1..32** | Canais de grupo pré-disponíveis no Mixer do SD3. Quando você escolhe `Bus 1` na saída de um microfone, o `Bus 1` aparece automaticamente na direita do Mixer. | Aba *Mixer* → campo **Output** na base do canal |
| **Send** | Envia uma "cópia" do som de um canal para um Bus paralelo (Reverb ou Compressão Paralela). | Aba *Mixer* → seção **Sends** do canal |
| **Insert** | Efeito colocado na cadeia daquele canal (EQ, Compressor, Saturação, Gate, Transient). | Aba *Mixer* → seção **Inserts** do canal |
| **Phase (`Ø`)** | Inverte a polaridade do microfone (evita que `Snare Top` e `Snare Bottom` se cancelem e deixem a caixa magra). | Aba *Mixer* → ícone `Ø` no canal |
| **Bleed** | Vazamento natural de outras peças dentro de um microfone (ex.: bumbo vazando na esteira). | Aba *Mixer* → painel **Bleed** (ou propriedades do canal) |
| **Bounce** | Exportar/renderizar o MIDI do *Song Track* direto para um arquivo `.wav` (o SD3 acrescenta `_Out_1+2` no nome). | Aba inferior *Song Track* → menu **Track → Bounce...** |
| **GR (Gain Reduction)** | Medidor de quanto o compressor está comprimindo o som (ex.: `3–5 dB` no medidor). | Dentro da janela do compressor (`Comp 76` / `Comp 670`) |
| **HPF / LPF** | **HPF** corta graves sobrando abaixo daquela frequência; **LPF** corta agudos acima dela (`1 k = 1000 Hz`). | Dentro do plugin **EQ** ou **EQ84** |

---

## Fase 1 — Montar as Peças na Aba `Drums`

1. Carregue o kit base **`Pearl Masterworks`** (*Core Library*).
2. **O que JÁ vem certo no `Pearl Masterworks`:** Snare `6.5x14" Tama Bell Brass`, Chimbal `15" Paiste 2002 Extra Heavy`, Toms `8x10"`, `9x12"`, `15x16"`, `16x18"`, Crashes/Splash/China (`17"`, `20"`, `10"`, `18"`, `18" China`).
3. **Apenas as 3 alterações de peça:**
   1. Clique com o botão direito no **`Racktom 3` (`10x13"`)** → **More... → Remove Instrument**.
   2. Troque o Bumbo (`Kick`) de `16x24"` para **`18x22" Pearl Masterworks`**.
   3. Troque o Ride (`Cymbal 4`) de `24" Paiste 2002 Ride` para **`22" Zildjian K Constantinople Medium Thin Low Ride`**.

---

## Fase 2 — Afinação (`Tuning 0:00.0`) e Cauda (`Envelope and Offset`)

Na aba **Drums**, clique em cada peça e digite/ajuste no painel direito (**formato `oitava:semitons.décimos`**):

| Peça (clique nela) | **Tuning** (digite no SD3) | **Envelope and Offset** (`Attack` sempre `0 ms`) |
| :--- | :---: | :--- |
| **Kick (`18x22" Pearl Masterworks`)** | **`0:02.7`** | **Desligado (`Off`)** *(preserva sustain natural > 80 ms)* |
| **Snare (`6.5x14" Tama Bell Brass`)** | **`0:02.7`** *(222.8 Hz medidos)* | **On:** `Attack: 0 ms` \| `Decay: 480 ms` \| `Release: 260 ms` |
| **Hi-Hat (`15" Paiste 2002`)** | **`0:00.0`** | Desligado *(padrão)* |
| **Racktom 1 (`8x10"`)** | **`0:00.0`** | **On:** `Attack: 0 ms` \| `Decay: 450 ms` \| `Release: 220 ms` |
| **Racktom 2 (`9x12"`)** | **`-0:00.5`** | **On:** `Attack: 0 ms` \| `Decay: 480 ms` \| `Release: 240 ms` |
| **Floortom 1 (`15x16"`)** | **`-0:01.0`** | **On:** `Attack: 0 ms` \| `Decay: 560 ms` \| `Release: 280 ms` |
| **Floortom 2 (`16x18"`)** | **`-0:01.5`** | **On:** `Attack: 0 ms` \| `Decay: 620 ms` \| `Release: 320 ms` |
| **Todos os Pratos** | **`0:00.0`** | Desligado *(padrão)* |

---

## Fase 3 — Configurar os Microfones da Esquerda no `Mixer`

> **`Bus 1`** = Kick Bus | **`Bus 2`** = Snare Bus | **`Bus 3`** = Toms Bus | **`Bus 4`** = Parallel Slam | **`Bus 5`** = Room Bus.

### 3.1 Bloco do Bumbo (`Output: Bus 1`)

#### **`Kick In`**
* **Fader:** `+2.5 dB` | **Pan:** `C`
* **Output:** **`Bus 1`** | **Sends:** nenhum
* **Insert 1 → `EQ` (5 bandas):**
  * **HPF:** `48 Hz`
  * **Corte (papelão):** `360 Hz` (`0.36 k`) | `-5.5 dB` | `Q 1.6`
  * **Boost (click):** `4.2 kHz` | `+9.0 dB` | `Q 1.3`
* **Insert 2 → `Transient`** *(escala em dB: Attack `-15..+15 dB`, Sustain `-24..+24 dB`)*:
  * **Attack:** **`+6.0 dB`**
  * **Sustain:** **`+2.5 dB`**

#### **`Kick Out`**
* **Fader:** `-2.0 dB` | **Pan:** `C`
* **Output:** **`Bus 1`** | **Send → `Bus 5`:** **`-13.0 dB`**
* **Insert 1 → `EQ` (5 bandas):**
  * **HPF:** `52 Hz`
  * **Boost (corpo):** `58 Hz` | `+4.0 dB` | `Q 1.4`
  * **Corte (lama):** `310 Hz` (`0.31 k`) | `-4.5 dB` | `Q 1.5`
  * **LPF:** `7.0 kHz`

#### **`Kick Sub`**
* **Fader:** `-14.0 dB` | **Pan:** `C`
* **Output:** **`Bus 1`** | **Sends:** nenhum
* **Insert 1 → `EQ` (5 bandas):**
  * **HPF:** `45 Hz`
  * **LPF:** `105 Hz`

---

### 3.2 Bloco da Caixa (`Output: Bus 2`)

#### **`Snare Top`**
* **Fader:** `0.0 dB` | **Pan:** `C`
* **Output:** **`Bus 2`** | **Send → `Bus 5`:** **`-8.0 dB`**
* **Insert 1 → `EQ84`** *(3 bandas contínuas; `1 k = 1000 Hz`)*:
  * **HPF (Low Cut):** `90 Hz`
  * **Low:** `225 Hz` *(~`0.22 k`)* | `+2.0 dB`
  * **Mid:** `3.2 kHz` | `+3.0 dB` *(Hi-Q desligado)*
  * **High:** `10 kHz` | `+1.5 dB`
* **Insert 2 → `EQ` (5 bandas):**
  * **Corte 1 (ring):** `350 Hz` *(`0.35 k`)* | `-5.5 dB` | `Q 3.5`
  * **Corte 2 (ring):** `555 Hz` *(`0.55 k`)* | `-3.5 dB` | `Q 4.0`
* **Insert 3 → `Comp 76`:**
  * **Ratio:** `4:1` | **Attack:** `5` | **Release:** `2` | **GR:** **`3–5 dB`**

#### **`Snare Bottom`**
* **Fader:** `-5.5 dB` | **Pan:** `C` | **Phase (`Ø`):** **LIGADO (Invert)**
* **Output:** **`Bus 2`** | **Send → `Bus 5`:** **`-12.0 dB`**
* **Insert 1 → `Frequency Gate`:** Side Chain HPF `450 Hz` | Hold `45 ms` | Release `110 ms`
* **Insert 2 → `EQ` (5 bandas):** HPF `180 Hz` | High Shelf `8.5 kHz` (`+2.5 dB`)

---

### 3.3 Bloco dos Toms (`Output: Bus 3`)

#### **`Racktom 1`**
* **Fader:** `-1.5 dB` | **Pan:** `L45` | **Output:** **`Bus 3`** | **Send → `Bus 5`:** **`-11.0 dB`**
* **Insert 1 → `Frequency Gate`:** `Release: 240 ms`
* **Insert 2 → `EQ` (5 bandas):** HPF `80 Hz` | Corte `420 Hz` (`-3.5 dB`, `Q 1.5`) | Boost `4.0 kHz` (`+2.5 dB`, `Q 1.6`)

#### **`Racktom 2`**
* **Fader:** `-1.5 dB` | **Pan:** `L15` | **Output:** **`Bus 3`** | **Send → `Bus 5`:** **`-11.0 dB`**
* **Insert 1 → `Frequency Gate`:** `Release: 260 ms`
* **Insert 2 → `EQ` (5 bandas):** HPF `70 Hz` | Corte `380 Hz` (`-3.5 dB`, `Q 1.5`) | Boost `3.8 kHz` (`+2.5 dB`, `Q 1.6`)

#### **`Floortom 1`**
* **Fader:** `-1.0 dB` | **Pan:** `R28` | **Output:** **`Bus 3`** | **Send → `Bus 5`:** **`-10.0 dB`**
* **Insert 1 → `Frequency Gate`:** `Release: 320 ms`
* **Insert 2 → `EQ` (5 bandas):** HPF `55 Hz` | Corte `320 Hz` (`-4.0 dB`, `Q 1.4`) | Boost `3.5 kHz` (`+2.5 dB`, `Q 1.6`)

#### **`Floortom 2`**
* **Fader:** `-1.0 dB` | **Pan:** `R58` | **Output:** **`Bus 3`** | **Send → `Bus 5`:** **`-10.0 dB`**
* **Insert 1 → `Frequency Gate`:** `Release: 360 ms`
* **Insert 2 → `EQ` (5 bandas):** HPF `45 Hz` | Corte `290 Hz` (`-4.0 dB`, `Q 1.4`) | Boost `3.2 kHz` (`+2.5 dB`, `Q 1.6`)

---

### 3.4 Bloco de Chimbal e Overheads (`Output: Out 1/2`)

#### **`Hi-Hat`**
* **Fader:** `-5.0 dB` | **Pan:** `L35` | **Output:** **`Out 1/2`**
* **Insert 1 → `EQ` (5 bandas):** HPF `380 Hz` | Corte `4.2 kHz` (`-4.0 dB`, `Q 1.8`) | High Shelf `8.5 kHz` (`+5.5 dB`)

#### **`OH Dyn`**
* **Fader:** `-3.5 dB` | **Pan:** `L100 / R100` | **Output:** **`Out 1/2`**
* **Insert 1 → `EQ` (5 bandas):**
  * **HPF:** `240 Hz`
  * **Corte 1:** `360 Hz` (`-2.5 dB`, `Q 1.3`)
  * **Corte 2:** `4.2 kHz` (`-7.0 dB`, `Q 1.2`)
  * **High Shelf:** `7.5 kHz` (`+12.0 dB`)
* **Insert 2 → `Comp 670`:** Threshold para **`1.5–2.5 dB` de GR**

---

### 3.5 Sala Física (`Amb Ribbon`) & Controle de Vazamento (`Bleed`)

#### **`Amb Ribbon`**
* **Fader:** `-4.5 dB` | **Pan:** `L100 / R100` | **Output:** **`Out 1/2`**
* **Insert 1 → `EQ` (5 bandas):** HPF `110 Hz` | Corte `350 Hz` (`-3.0 dB`, `Q 1.2`) | LPF `14.0 kHz`
* **Insert 2 → `Comp 76`:** Ratio `12:1` | Attack `3` | Release `1` | **GR `8–12 dB`**
* **Insert 3 → `Tape Simulator`:** Drive **~35% do curso** | Bias `Normal`

#### **Controle de `Bleed` (somente Part 1):**
* **`Snare Bottom`** → painel **Bleed** → ative bleed de `Kick` e `Toms` em **`-10.0 dB`**.
* **`OH Dyn`** e **`Amb Ribbon`** → mantenha bleed ativo em **`0.0 dB`**.

---

## Fase 4 — Configurar os 5 Buses na Direita do `Mixer`

#### **`Bus 1` (Kick Bus)**
* **Fader:** `-1.0 dB` | **Output:** `Out 1/2` | **Send → `Bus 4`:** `-6.0 dB`
* **Insert 1 → `Comp 76`:** Ratio `4:1` | Attack `6` | Release `2` | **GR `3–4 dB`**
* **Insert 2 → `Tape Simulator`:** Drive **~25% do curso**
* **Insert 3 → `EQ` (5 bandas):** HPF `60 Hz` | Boost 1: `62 Hz` (`+2.0 dB`, `Q 1.4`) | Boost 2: `4.5 kHz` (`+5.5 dB`, `Q 1.2`)

#### **`Bus 2` (Snare Bus)**
* **Fader:** `0.0 dB` | **Output:** `Out 1/2` | **Send → `Bus 4`:** `-3.0 dB`
* **Insert 1 → `Transient`:** Attack `+2.5 dB` | Sustain `0.0 dB`
* **Insert 2 → `Punch Exciter 361`:** Vocal Mod `On` | Compression ~25% do curso | Mix ~22%
* **Insert 3 → `EQ` (5 bandas):** Corte 1: `350 Hz` (`-8.0 dB`, `Q 4.5`) | Corte 2: `555 Hz` (`-4.0 dB`, `Q 4.5`)

#### **`Bus 3` (Toms Bus)**
* **Fader:** `-1.5 dB` | **Output:** `Out 1/2` | **Send → `Bus 4`:** `-7.0 dB`
* **Insert 1 → `Comp 76`:** Ratio `4:1` | Attack `5` | Release `3`

#### **`Bus 4` (Parallel Slam Bus)**
* **Fader:** `-9.5 dB` | **Output:** `Out 1/2`
* **Insert 1 → `EQ`:** HPF `65 Hz` | Corte `320 Hz` (`-4.0 dB`, `Q 1.2`)
* **Insert 2 → `Comp 76`:** Ratio **`All`** | Attack `2` | Release `1` | **GR `12–18 dB`**
* **Insert 3 → `Valve Distortion Box`:** Overdrive **~20% do curso** | LPF `7 kHz` | Dry/Wet `30%`

#### **`Bus 5` (Studio Litho Room Bus)**
* **Fader:** `-7.5 dB` | **Output:** `Out 1/2`
* **Insert 1 → `Room Reverb`:** Reverb Time `0.75 s` | Decay `0.55 s` | Pre-Delay `18 ms` | Size `65%` | Damping `45%` | Dry/Wet `100%`
* **Insert 2 → `EQ`:** HPF `115 Hz` | LPF `7.2 kHz`
* **Insert 3 → `Comp 76`:** Ratio `8:1` | Attack `3` | Release `2` | **GR `5–7 dB`**

---

## Fase 5 — Canal Geral de Saída (`Out 1/2`)

* **Fader:** **`+2.5 dB`**
* **Insert 1 → `EQ` (5 bandas):** HPF `28 Hz` | Corte 1: `350 Hz` (`-3.5 dB`, `Q 2.0`) | Corte 2: `240 Hz` (`-2.0 dB`, `Q 1.2`)
* **Insert 2 → `Comp 670`:** Threshold suave para **`1–2 dB` de GR**
* **Insert 3 → `Tape Simulator`:** Drive **~18% do curso**
* **Insert 4 → `Compressor / Limiter`:** Threshold `-1.5 dB` | Ratio `8:1` | Attack `1 ms` | Release `50 ms`
