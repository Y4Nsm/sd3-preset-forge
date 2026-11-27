# Especificação do Formato `.sd3p` & Container VST3 (`VC2!`)

Documentação técnica de interoperabilidade sobre a estrutura textual `.sd3p`, o IR tipado v2 (`BlueprintV2`), todos os **35 efeitos nativos (`effect 10..44`)** e o framing JUCE `VC2!` usado ao hospedar o VST3.

## 1. Arquivo `.sd3p` (Plain-Text ASCII + `\x00`)
Todo preset `.sd3p` é um arquivo de texto estruturado em blocos `{ ... }` com exatamente **1 byte nulo (`0x00`) no final**.

Seções principais:
- `PlugVersion 3.4.4`
- `SAMPLER { HQ { soundlib "..." ... } xmics { } instbox 0..13 { ... } mixer { ... } }`
- Seções preservadas lossless pelo compilador: `SongTrack`, `editorVars`, `mixerState`, `sqlMidiProvider`, `sqlSoundProvider`, `BoxStatePreset`, `Drumtracker`, `SongCreator`, `EdrumPreset`

### 1.1 Slots de Kit (`instbox`), Envelopes AHDSR, Bleed por Fonte e Stacks (`xpad`)
Cada `instbox` corresponde a um slot `pos "<slot>"` (`KickR`, `Snare`, `Hats`, `Tom1..5`, `Cymbal1..6`):
- Peça carregada: `drum "<id>"  "<Tool>" 1` (ex.: `drum "Kick73"  "Felt" 1`, `drum "Snare13"  "Drumsticks" 1`)
- Slot descarregado (`unload_slots`): `drum -  "Drumsticks" 1`
- Afinação por pad (`pitch`): `2 ** (semitones / 12.0)` (ex.: `+2.7 st` → `1.16878`, `-1.5 st` → `0.917004`).
- Ganho do pad (`pvolume`): `10 ** (level_db / 20.0)`.
- **Envelope AHDSR por pad**: ativado com `fade 1` e campos em segundos/linear:
  - `attack <attack_ms / 1000>`
  - `fadeonset <hold_ms / 1000>`
  - `decay <decay_ms / 1000>`
  - `sustain <db_to_linear(sustain_db)>`
  - `fadetime <release_ms / 1000>`
- **Bleed seletivo por peça (`usemic` + `leakvolume`)**: cada `pad { ... }` controla quais microfones recebem vazamento via lista `usemic "MicA" "MicB" ...` e níveis relativos por canal via `leakvolume "Mic" <linear>`.
- **Stacking (`xpad 1..K`)**: camadas extras do `StackPack` são compiladas em blocos `xpad <k> <library_id> { pos "<category>" mastermics { ... } laylims { } drum "<stack_id>"  "Drumsticks" -1 pads { pad ... { ... pvolume ... pitch ... } } }`, preservando intacto o `xpad 0`.

### 1.2 Canais, Buses e Matemática Linear do Mixer
| Unidade UI | Fórmula `.sd3p` |
| :--- | :--- |
| Volume (`fader_db`, `send.level_db`, `bleed.level_db`) | `10 ** (db / 20.0)` |
| Pan mono (`C`, `Lxx`, `Rxx`) | `C = 0.5`, `Lxx = 0.5 - xx/200`, `Rxx = 0.5 + xx/200` |
| Canais estéreo (`L60/R60`, `L100/R100`, etc.) | FX apenas no canal `L` (`pan = left_0_1`); canal `R` (`pan = right_0_1`) espelha `volume`, `phasereverse`, `route`, `sends` e `leakvol` |
| Sends pré/pós-fader (`send k`) | Bloco `send k { active 1 pan <0..1> volume <lin> pre }` (`pre_fader: true`) ou `post fader` |
| Buses UI (`Bus 1..Bus 32`) | Pares `buss 2k` (`L`) / `buss 2k+1` (`R`) para `k in 0..31`; buses não usados são resetados com `route output -1` e `hidden` |
| Canais omitidos do blueprint | Resetados explicitamente (`volume 0`, sem inserts/sends) para evitar vazamento residual do template |
| Master (`Output 1/2`) | `output 0` (`L` + FX) / `output 1` (`R`) |

### 1.3 Catálogo Completo dos 35 Inserts Nativos (`effect 10..44`)
Definido de forma estática em [`sd3_forge/fx_catalog.py`](../../sd3_forge/fx_catalog.py):

| `effect` ID | Nome Canônico | Nº Params | Observações / Índices Chave |
| :---: | :--- | :---: | :--- |
| `10` | `EQ` | 131 | Até 10 bandas (`13 * b`): `+0` tipo, `+1` dB, `+2` Hz, `+3` Q, `+4` slope; `130` Output Level |
| `11` | `Classic Compressor` | 8 | `0` Threshold, `1` Ratio, `2` Attack, `3` Release, `4` Makeup, `5` Mix, `6` Out Level, `7` Side Chain HPF |
| `12` | `Multiband Compressor` | 31 | `0..2` Crossovers, `3` Master Gain, `4` Master Level, `5..24` 4 bandas ×5, `25..28` Solo, `29` Mix, `30` SC HPF |
| `13` | `Creative Filter` | 16 | `0` Cutoff, `1` Resonance, `2` Poles, `3` Mode, `4..15` Analog/Mod/Env/Seq |
| `14` | `1981 Classic Reverb` | 6 | `0` Dry, `1` Wet, `2` Decay, `3` Pre-Delay, `4` High, `5` Level |
| `15` | `Transient` | 2 | `0` Attack (`-15..+15 dB`), `1` Sustain (`-24..+24 dB`) |
| `16` | `Punch Exciter 180` | 3 | `0` Processed, `1` Compression, `2` Level |
| `17` | `Tape Simulator` | 6 | `0` Drive, `1` Bias, `2` Speed (`0.666667`=15 ips), `3` Noise, `4` Wow/Flutter, `5` Level |
| `18` | `Bitcrusher` | 4 | `0` Bits, `1` Downsample, `2` Anti-Alias, `3` Drive |
| `19` | `Valve Distortion Box` | 6 | `0` Drive, `1` Overdrive, `2` Dist. Type, `3` Bias, `4` LPF (`0`=Off, `0.25`=7 kHz, `0.75`=4 kHz), `5` Out Level |
| `20` | `Plate Reverb` | 10 | `0` Reverb Time, `1` Size, `2` Diffusion, `3` Shape, `4` Color, `5` Wet, `6` Level, `7` Pre-Delay (`ms/500`), `8..9` Sync/BPM |
| `21` | `Room Reverb` | 14 | `0` Time, `1` Diffusion, `2` Decay, `3` Wet, `4` Damping, `5` Level, `6` Pre-Delay, `9` Size, `10` High, `11` Low, `12..13` Motion/Depth |
| `22` | `Hall Reverb` | 10 | `0` Reverb Time, `1` Size, `2` Diffusion, `3` Shape, `4` High, `5` Wet, `6` Level, `7` Pre-Delay, `8..9` Sync/BPM |
| `23` | `Inverse Reverb` | 11 | `0` Reverb Time, `1` Diffusion, `2` High, `3` Wet, `4` Pre-Delay, `5` Low, `6` Level, `7..10` Syncs |
| `24` | `Spring Reverb` | 6 | `0` Time, `1` Bright, `2` Wet, `3` Tension, `4` Level, `5` Pre-Delay |
| `25` | `Distortion` | 3 | `0` Drive, `1` Tone, `2` Level |
| `26` | `Filter Delay` | 11 | `0` Time, `1` Repeat, `2` Speed, `3` Center, `4` Depth, `5` Level, `6..9` Sync/Reverse, `10` Mix |
| `27` | `Phaser` | 5 | `0` Speed, `1` Resonance, `2` Level, `3` Sync Speed, `4` Sync On |
| `28` | `Frequency Gate` | 8 | `0` Threshold, `1` Attack, `2` Hold, `3` Release, `4` Exp Thresh, `5` Ratio, `6` Low Cut, `7` Hi Cut (`450 Hz -> 0.283878`) |
| `29` | `Punch Exciter 361` | 5 | `0` Dry (`1-Mix`), `1` Vocal Mod (`0`=On, `1`=Off), `2` Compression, `3` Wet (`Mix`), `4` Out Level |
| `30` | `Tremolo` | 6 | `0` Waveform, `1` Speed, `2` Intensity, `3` Synced Speed, `4` Sync, `5` Panning |
| `31` | `1981 Classic Echo` | 14 | Alias `"Classic Echo"`; `0` Dry, `1` Wet, `2..5` L/R Delay & Repeat, `6..7` Bass/Treble, `8..13` Reverse/Sync/Output |
| `32` | `Auto-Wah` | 10 | `0` Filter, `1` Speed, `2` Depth, `3` Sensitivity, `4` Release, `5..9` Mode/Polarity/Level/Sync |
| `33` | `String Machine Chorus` | 3 | `0` Depth, `1` Mix, `2` Out Level |
| `34` | `Limiter Pedal` | 5 | `0` Sensitivity, `1` Attack Time, `2` Release Time, `3` Level, `4` Stereo |
| `35` | `Chorus` | 6 | `0` LFO Speed, `1` Depth, `2` Amount, `3` Stereo, `4..5` Sync |
| `36` | `Vibrato` | 5 | `0` LFO Speed, `1` Depth, `2` Level, `3..4` Sync |
| `37` | `Flanger` | 7 | `0` LFO Rate, `1` Range, `2` Color, `3` Intensity, `4..5` Sync, `6` Level |
| `38` | `Dimension T` | 4 | `0..3` Dimension 1..4 On/Off |
| `39` | `Tape Delay` | 13 | `0` Time, `1` Repeat, `2` Spread, `3` Wow/Flutter, `4` Dist, `5` Mix, `6` Level, `7..12` Reverse/Sync |
| `40` | `Comp 76` | 6 | `0` Input Gain, `1` Output Level, `2` Attack (`1..7 -> 0..1`), `3` Release (`1..7 -> 0..1`), `4` Ratio (`4:1`..`All`), `5` Mix |
| `41` | `Comp 670` | 11 | `0..3` Left/Mid, `4..7` Right/Side, `8` Mix, `9` Level, `10` Stereo/M-S (`linked` flag em estéreo) |
| `42` | `EQ84` | 15 | `0` Level, `1..3` High, `4..7` Mid (`6`=Hi-Q), `8..10` Low, `11..12` Low Cut, `13..14` High Cut |
| `43` | `Fat Muff` | 3 | `0` Drive, `1` Tone, `2` Level |
| `44` | `Compressor / Limiter` | 6 | Alias `"Compressor/Limiter"`; `0` Threshold, `1` Ratio, `2` Attack, `3` Release, `4` Makeup, `5` Auto-Makeup |

## 2. Container VST3 (`VC2!` / `IComponent`)
Ao hospedar `Superior Drummer 3.vst3` via `pedalboard`:
1. `plug.raw_state` usa o formato JUCE `VC2!`: `b"VC2!" + uint32_le(xml_len) + xml_bytes + b"\x00"`.
2. Dentro do XML, `<IComponent>` contém `<num_bytes>.<juce_base64>` usando o alfabeto `.A-Za-z0-9+` (empacotamento 6-bit LSB-first).
3. O blob decodificado contém header VST2/3 `VstW` (16 bytes) + `CcnK` (offset 16, tamanho big-endian no offset 20) + `FBCh` (148 bytes, tamanho big-endian do chunk no offset 172), seguido do conteúdo `.sd3p` terminado em `\x00` e do sufixo `\x00*8 + JUCEPrivateData...`.
4. Atualizar os dois tamanhos big-endian (`20` e `172`), reencodar em JUCE Base64 e chamar `plug(..., reset=True)` dispara carregamento síncrono dos samples e render offline determinístico.
