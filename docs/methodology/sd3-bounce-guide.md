# Guia de Montagem, Template Base e Exportação de Áudio (`Bounce`) no SD3

Para que a validação TDD funcione sem interferência externa, o arquivo `.wav` de teste deve ser exportado **diretamente de dentro do Superior Drummer 3**, sem efeitos ou limiters na DAW.

---

## O Que Significam os Termos Principais no SD3
- **Remove Instrument:** remover uma peça sobrando do kit na aba *Drums* (botão direito na peça → *More...* → *Remove Instrument*).
- **Tuning / Envelope and Offset:** no painel direito da aba *Drums*, ajustam afinação em semitons (`Tuning`) e duração da cauda AHDSR (`Envelope and Offset`). **Nunca** suba o `Attack` do AHDSR para dar punch (isso amacia o golpe); use o insert `Transient` no *Mixer*.
- **Bus / Output / Send:** *Bus* é um canal de grupo; *Output* define a saída do canal; *Send* envia uma cópia do som para um Bus paralelo (Reverb ou Compressão Paralela).
- **Bounce:** termo do SD3 para **renderizar/exportar** o MIDI do *Song Track* em um arquivo de áudio `.wav`.

---

## Dica de Ouro: Salve o Template Base (`Forge-Part1-Template.sd3p`)
O SD3 não permite gerar arquivos `.sd3p` externamente. Na primeira vez em que você criar os **5 Buses internos** (`Kick Bus`, `Snare Bus`, `Toms Bus`, `Parallel Slam Bus`, `Room Bus`) e configurar os canais da Part 1, salve um User Preset limpo chamado **`Forge-Part1-Template.sd3p`** (*File → Save As...*).
Nos próximos presets (Korn, Slipknot, Grunge...), basta carregar esse template, trocar as peças e ajustar Tuning/EQ/Comp (~3–4 minutos).

---

## Passo Opcional Recomendado (30s) — Áudio Cru de Referência (`v0-raw.wav`)
Antes de montar o Mixer completo em um kit/caixa inédito:
1. Carregue o `base_kit`, faça as trocas/remoções de peças na aba *Drums*, deixe **Tuning em `0.0 st`** e **todos os inserts desligados**.
2. Arraste `test-suite/standard-test-groove.mid` para o **Song Track** (120 BPM) e exporte como `bounces/v0-raw.wav` usando os passos abaixo.
3. Rode `.\.venv\Scripts\python.exe -m forge.cli analyze presets/<genero>/<slug> presets/<genero>/<slug>/bounces/v0-raw.wav`.
4. O relatório informa o **`pitch_delta_semitones` exato** necessário para atingir a frequência alvo.

---

## Como Exportar o Áudio de Teste (`Track → Bounce...`)

1. Na parte inferior do SD3, abra a aba **Song Track** e confirme **120 BPM** e **4/4**.
2. Arraste o arquivo `test-suite/standard-test-groove.mid` para o compasso **`1.1.1`** (duração total: 33 compassos / 66 segundos).
3. Clique no menu **Track** (junto ao Song Track) → **Bounce...**.
4. Na aba **General**:
   - **Folder:** aponte para `presets/<genero>/<slug>/bounces/`.
   - **File Name:** `v1` (depois `v2`, `v3` nas rodadas de calibração).
   - **Sound Quality:** `24 bit` (`44.1 kHz`).
5. Na aba **Advanced**:
   - Selecione **Bounce Output Channels** *(isso gera um único arquivo `.wav` estéreo da mistura final do `Out 1/2`, em vez de separar um arquivo por microfone)*.
6. Clique em **Bounce** e aguarde a renderização offline.

---

## Rodar a Auditoria Automática (TDD)
```powershell
.\.venv\Scripts\python.exe -m forge.cli analyze presets/<genero>/<slug> presets/<genero>/<slug>/bounces/v1.wav
```
O script gera `test-report.json`, `test-report.md` e `diagnostic-plots.png` com os ajustes cirúrgicos exatos.
