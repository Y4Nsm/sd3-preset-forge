# Princípios de Engenharia de Presets — SD3 Preset Forge

Estes princípios nasceram de erros reais auditados no desenvolvimento da Forja e servem como lei para qualquer gênero (Nu Metal, Grunge, Rock, Alt Metal).

---

## Os 8 Princípios Fundamentais

### 1. Ground Truth Local Antes de Qualquer Ideia
- Nenhuma peça, canal de microfone, bleed, som eletrônico (`StackPack`) ou efeito pode ser sugerido sem existir no `inventory.json` local extraído via `sd3-forge init` (ou `sd3-forge extract-gt`).
- Na **Part 1 (Basic Setup)** existem apenas 13 canais físicos (`OH Dyn` e `Amb Ribbon` como únicos ambiência/OH) e 3 canais com bleed (`Snare Bottom`, `OH Dyn`, `Amb Ribbon`). Nunca assumir `Amb Near`, `Amb Mid` ou `OH Cond`.

### 2. AHDSR da Aba *Drums* NÃO é Transient Shaper
- A caixa **Envelope and Offset** da aba *Drums* no SD3 usa **AHDSR** (`Attack`, `Hold`, `Decay`, `Sustain`, `Release`):
  - Aumentar `Attack` no AHDSR **suaviza/corta** o transiente inicial (efeito contrário ao que se quer em bumbo/caixa agressivos!).
  - Para **aumentar ataque/click**, use sempre o insert **`Transient`** no Mixer (`Attack` em **dB**, de `-15` a `+15 dB`).
  - Use `Decay` / `Release` no AHDSR da aba *Drums* apenas quando quiser **encurtar cauda/ring/bleed** de um casco.

### 3. Paridade de Topologia & Loop de Calibração da UI (`fx-ui-calibration.yaml`)
- Nunca inventar bandas, unidades (`%` vs `dB`) ou faixas de knobs que não foram confirmadas na interface real do SD3.
- O arquivo vivo [fx-ui-calibration.yaml](../../sd3_forge/data/fx-ui-calibration.yaml) classifica cada efeito:
  - **`verified_in_ui`:** unidade e faixa rígidas impostas pelo linter (ex.: `Transient` `Attack` em `[-15, +15] dB` e `Sustain` em `[-24, +24] dB`; `EQ84` com 3 bandas; `Comp 76` `1..7`).
  - **`manual_only`:** enquanto a leitura exata da UI não for confirmada (ex.: `Tape Simulator` Drive, `Valve Distortion Box` Overdrive), o blueprint deve indicar **posição relativa do knob + referência sonora/medidor** (ex.: *"~25% do curso / GR 3–4 dB"*), nunca unidades inventadas.
- Sempre que você abrir um insert no SD3 e confirmar uma faixa real diferente, atualizamos `fx-ui-calibration.yaml`, rodamos `forge extract-gt` e o linter trava aquilo para sempre.

### 4. Fluxo Esquerda → Direita no Mixer do SD3
- No SD3, `Bus 1..Bus 32` só aparecem na direita do Mixer depois que algum canal/send aponta para eles.
- Por isso, todo guia passo a passo deve instruir **Canais de Microfone (Esquerda) → Roteamento para `Bus 1..N` → Configuração dos Buses (Direita) → `Out 1/2`**.

### 5. Zero Slots Órfãos do Kit Base
- Ao carregar um `base_kit` (ex.: `Pearl Masterworks` vem com 5 toms), qualquer peça não utilizada **precisa** estar declarada em `kit.unload_slots` no YAML e instruída como **Remove Instrument** no guia `.md`.

### 6. Baseline Real (`v0-raw`) Antes de Fechar Afinação (RED Real)
- Amostras reais de estúdio têm afinações gravadas específicas. Um bounce rápido **cru** (`v0-raw_Out_1+2.wav`, sem inserts) permite que o `forge analyze` meça a fundamental real e calcule o **`pitch_delta_semitones` exato** no formato `0:00.0` do SD3.

### 7. Reuso por Template Base (`Forge-Part1-Template.sd3p`)
- Salve um User Preset com o roteamento limpo dos buses (`Bus 1..5`) em `Forge-Part1-Template.sd3p` para reutilizar em 3–4 minutos nos próximos presets.

### 8. Deltas Cirúrgicos e Prioridade Causal
- Quando `forge analyze` acusar `FAIL`/`WARN`, aja por prioridade: (1) Segurança/Fase → (2) Afinação (`Tuning 0:00.0`) → (3) Ressonâncias (`ring`/`boxiness`/`harshness`) → (4) Dinâmica/Sala.

---

## Registro Histórico de Erros Prevenidos (Anti-Regressão)

| Erro Descoberto | Causa Raiz | Trava Implementada |
| :--- | :--- | :--- |
| Parser puxou linhas de `pads` como Snares (36 vs 26) | `pads { ... }` dentro de `uberconf` | `extract_ground_truth.py` remove `pads { ... }` antes do parse + `test_core_kits_and_counts` |
| Uso de `Attack +12` no Envelope da aba *Drums* | Confusão entre AHDSR e Transient Shaper | `blueprint.schema.json` restringe `envelope` a AHDSR + warning em `attack_ms > 0` |
| Uso de 4 bandas (`LowMid` + `HighMid`) no `EQ84` | Atribuir 2 bandas médias ao Neve 1084 | `validate_blueprint.py` lê `fx-ui-calibration.yaml` e bloqueia `LowMid`/`HighMid` |
| Tom 3 do `Pearl Masterworks` sem destino no mixer | Omissão de `unload_slots` | `validate_blueprint.py` exige todo slot do `base_kit` em `pieces` ou `unload_slots` |
| Uso de `%` no `Transient` (`Attack +18%`) | Falta de verificação de unidade na UI real (`-15..+15 dB` / `-24..+24 dB`) | `fx-ui-calibration.yaml` + `validate_blueprint.py` bloqueiam `%` e checam `[-15..+15 dB]` e `[-24..+24 dB]` |
| Instruir Buses antes dos canais no Mixer | No SD3, `Bus 1..32` só aparecem após serem selecionados nos canais | Guias ordenados Esquerda → Direita (Microfones → Buses → Out 1/2) |
