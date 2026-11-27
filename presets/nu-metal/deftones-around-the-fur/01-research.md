# Pesquisa de Referência — Deftones (*Around the Fur* / *White Pony*)

- **Preset ID:** `deftones-around-the-fur`
- **Banda / Álbuns:** Deftones — *Around the Fur* (1997) e *White Pony* (2000)
- **Baterista:** Abe Cunningham
- **Produtor / Engenheiro:** Terry Date
- **Estúdio principal:** Studio Litho, Seattle (WA) (*Around the Fur* / *White Pony*)

---

## 1. Kit Real & Afinação

### Bumbo (Kick)
- `[Verified Source]` *(MusicRadar / Equipboard / Tama Artist)*: Abe Cunningham utiliza kits **Tama Starclassic** (Maple/Bubinga), com bumbo principal **22"x18"** (ou 22"x20" em eras seguintes), batida pesada e definição firme para atravessar guitarras afinadas baixo (7 cordas / Drop C#).
- `[Acoustic Inference]`: Bumbo com fundamental firme entre **52–64 Hz**, corte moderado nos médios-graves de "caixa de papelão" (300–450 Hz) e ataque de batedor nítido em **3.5–5.0 kHz**, mantendo corpo natural de estúdio sem soar artificialmente clicado como metalcore moderno.

### Caixa (Snare — Assinatura do Som)
- `[Verified Source]` *(Ultimate-Guitar / MusicRadar / entrevistas Abe Cunningham & Terry Date)*: O timbre clássico de caixa do *Around the Fur* e *White Pony* destaca-se pela **afinação bem alta / tensionada na pele batedeira** (incentivada por Stephen Carpenter e lapidada por Terry Date) com **estalo cortante ("crack")** e peso encorpado de casco metálico pesado — historicamente associada a cascos fundidos como a **6.5"x14" Tama Bell Brass** e caixas de aço/latão profundas.
- `[Acoustic Inference]`: Fundamental da caixa centrada entre **210–245 Hz** (afinação média-alta a alta para uma 6.5x14"), com *ring* metálico musical e controlado entre **400–600 Hz** (nunca morto/choked, nem descontrolado) e forte energia de *crack* em **2.5–4.5 kHz**.

### Tons & Pratos
- `[Verified Source]` *(Equipboard / MetalForge / Reddit Zildjian rig)*: Configuração típica de Abe Cunningham com **Rack Toms 10" e 12"** e **Floor Toms 16" e 18"** (ou 14"/16"), além de pratos grandes e brilhantes (**Hi-Hat 15"**, **Crashes 18"–20"**, **Ride 22"** usado também como crash/wash, **China 18"–20"** e splash).

---

## 2. Captação, Sala & Mixagem (Estilo Terry Date)

- `[Verified Source]` *(Reverb / LouderSound / entrevistas Terry Date)*:
  - **Close mics clássicos:** Shure SM57 / Beyerdynamic M201 em Top/Bottom da caixa com alinhamento cuidadoso de fase.
  - **Overheads & Sala:** Condensadores/dinâmicos capturando abertura orgânica do kit + microfones de sala fortemente comprimidos no estilo **1176 / Distressor** e consoles **SSL**.
  - **Estética de mixagem:** Compressão paralela agressiva ("Slam Bus") + saturação analógica/fita para colar o kit e dar respiração explosiva ao backbeat da caixa, com reverb/sala controlada que cresce nos hits de caixa/tons sem embolar os pratos.
- `[Acoustic Inference]` *(Adaptação determinística para SD3 Core Library Part 1)*:
  - Como a Part 1 não possui `Amb Near/Mid` nem `OH Cond`, o blueprint compensa exatamente essa arquitetura usando:
    1. `Amb Ribbon` fortemente comprimido com `Comp 76` + `Tape Simulator`.
    2. Bus dedicado **`Studio Litho Room Bus`** com `Room Reverb` (filtrado em 115 Hz – 7.5 kHz) + `Comp 76`, alimentado por Sends de `Snare Top`, `Snare Bottom`, `Floortom 1/2` e leve toque de `Kick Out` (sem pratos/hi-hat).
    3. **`Parallel Slam Bus`** com `Comp 76` (All-Buttons / 20:1) somado por baixo de Kick + Snare + Toms.
