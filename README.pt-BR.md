# SD3 Preset Forge

[English](README.md) | **Português (Brasil)**

Ferramenta CLI open-source, calibrador DSP e servidor MCP para o **Toontrack Superior Drummer 3**. Crie presets `.sd3p` a partir de YAML **manualmente ou de forma automática** com agentes de código (**Claude Code, Cursor, Codex, Antigravity**), usando a IA estritamente como ferramenta determinística de engenharia sobre a sua própria biblioteca do SD3, sem geração de áudio por IA.

- **Fluxo Manual ou Automatizado por Agente:** Edite os blueprints na mão como arquivos de texto comuns, ou conecte um agente via CLI/MCP para consultar suas peças instaladas, compilar `.sd3p`, renderizar no seu `Superior Drummer 3.vst3` real e iterar automaticamente contra metas de DSP.
- **Inventário da Biblioteca Local (`sd3-forge inventory`):** Escaneia e filtra peças de bateria, microfones instalados, stacks, keymaps e todos os 35 efeitos nativos do SD3 (`effect 10..44`) diretamente da sua instalação local.
- **Typed IR v2 e Compilador `.sd3p` Sem Perdas:** Valida blueprints Pydantic v2 (`schema_version: "2.0"`) e compila diretamente em presets nativos `.sd3p`.
- **Worker VST3 Persistente e Calibrador Analítico:** Mantém `Superior Drummer 3.vst3` residente via `sd3-forge daemon`, verifica os slots carregados com canário pré-voo e calibra afinação + cortes/balanço espectral com rollback automático via `.forge-history/` (`sd3-forge calibrate`).
- **Motor de Auditoria DSP Offline (`dsp_metrics.py`):** Audita bounces com decaimento Schroeder EDC (com corte de piso de ruído estilo Lundeby), frequência fundamental, picos de ring de caixa/tons, harshness por prato, ordem de pitch/pan dos tons e loudness ITU-R BS.1770-4 (`test-report.json`, `test-report.md`, `diagnostic-plots.png`).
- **Exemplos da Core Library Incluídos:** Kits prontos usando apenas o mixer interno do SD3 em `presets/` (Deftones *Around the Fur* e Alice In Chains *Facelift*). Sem geração de áudio por IA e sem nenhum sample da Toontrack.
- Consulte [AGENTS.md](AGENTS.md) para o fluxo com agentes e [docs/ROADMAP.md](docs/ROADMAP.md) para a arquitetura completa.

---

## Instalação

```bash
# Instalação rápida e isolada direto do GitHub (CLI + servidor MCP de 6 ferramentas)
pipx install "git+https://github.com/Y4Nsm/sd3-preset-forge.git"
# ou usando uv:
uv tool install "git+https://github.com/Y4Nsm/sd3-preset-forge.git"

# Ou instalar diretamente via pip:
pip install "sd3-preset-forge @ git+https://github.com/Y4Nsm/sd3-preset-forge.git@v1.0.0"

# A partir do código-fonte (desenvolvimento + renderização VST3 local + extras FastMCP):
git clone https://github.com/Y4Nsm/sd3-preset-forge.git
cd sd3-preset-forge
pip install -e ".[dev,render,mcp]"
```

---

## Início Rápido

```bash
# 1. Inicializar Ground Truth local (inventory.json), template neutro e suíte MIDI v2
sd3-forge init

# 2. Consultar peças, microfones e efeitos disponíveis de forma compacta
sd3-forge inventory summary --json
sd3-forge inventory pieces --slot Snare --json

# 3. Validar o blueprint do preset contra o Ground Truth local
sd3-forge validate presets/nu-metal/deftones-around-the-fur --json

# 4. Iniciar daemon VST3 persistente e executar calibração limitada em 2 estágios
sd3-forge daemon start --json
sd3-forge calibrate presets/nu-metal/deftones-around-the-fur --json
sd3-forge daemon stop --json

# 5. Compilar blueprint em .sd3p (e copiar opcionalmente para os User Presets do SD3 com --install)
sd3-forge compile-sd3p presets/nu-metal/deftones-around-the-fur --install
```

### Outros Comandos do CLI

```bash
sd3-forge auto-test presets/<genero>/<slug> --version v-auto    # Validate -> compile -> render -> analyze
sd3-forge profile-ref <referencia.wav> --json                    # Priors acústicos auxiliares a partir de um stem (numpy/scipy)
sd3-forge migrate <pasta_preset> --in-place                      # Atualizar blueprint v1 para schema_version 2.0
sd3-forge new-preset grunge alice-in-chains-facelift             # Criar estrutura de um novo preset
sd3-forge generate-midi [--scope kick|snare|toms|cymbals|full]   # Gerar suíte MIDI v2 completa ou probe curto
sd3-forge render preset.sd3p out.wav                             # Renderizar qualquer .sd3p offline via daemon ou VST3
sd3-forge analyze <pasta_preset> <bounce.wav>                    # Executar auditoria DSP v2 em qualquer bounce WAV
```

Variáveis de ambiente opcionais (detectadas automaticamente por padrão no Windows e macOS):
- `SD3_LIBRARY_PATH` — caminho para a pasta `SL-SuperiorDrummer3`
- `SD3_VST3_PATH` — caminho para o plugin `Superior Drummer 3.vst3`
- `SD3_PRESETS_DIR` — caminho para sua pasta de presets `.sd3p` de usuário
- `SD3_FORGE_HOME` — sobrescrever diretório local de configuração/dados

---

## Automação Opcional: Servidor MCP (`sd3-forge-mcp`) e Skill para Agentes

O `sd3-preset-forge` inclui uma Skill para Claude Code ([.claude/skills/sd3-forge/SKILL.md](.claude/skills/sd3-forge/SKILL.md)) e um servidor MCP opcional de 6 ferramentas via stdio (`sd3-forge-mcp`):

```json
{
  "mcpServers": {
    "sd3-forge": {
      "command": "sd3-forge-mcp"
    }
  }
}
```

Ferramentas MCP expostas: `sd3_query_inventory`, `sd3_validate_preset`, `sd3_compile_preset`, `sd3_daemon_control`, `sd3_calibrate_preset`, `sd3_analyze_or_profile`. Inspecione os schemas a qualquer momento com `sd3-forge-mcp --list-tools`.

Veja [CONTRIBUTING.md](CONTRIBUTING.md) para padrões de TDD e instruções de CI.

---

## Aviso Legal, Marcas Registradas e Interoperabilidade

- **Projeto Independente:** O `sd3-preset-forge` é uma ferramenta open-source independente de interoperabilidade e **não é afiliado, endossado ou patrocinado pela Toontrack Music AB**, nem por qualquer fabricante de baterias/pratos ou artista citado na documentação dos presets.
- **Nenhum Ativo Proprietário Distribuído:** Este repositório distribui **zero** bibliotecas de áudio da Toontrack (`.obw`), presets `.sd3p` de fábrica, bounces `.wav` proprietários ou binários comerciais. Toda compilação e renderização operam estritamente sobre a instalação local devidamente licenciada do Superior Drummer 3 do próprio usuário.
- **Marcas Registradas:** Superior Drummer 3 e Toontrack são marcas registradas da Toontrack Music AB. Todos os nomes de marcas e artistas são usados exclusivamente como referência acústica descritiva.
