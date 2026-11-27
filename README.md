# SD3 Preset Forge

**English** | [Português (Brasil)](README.pt-BR.md)

Deterministic, TDD-driven preset engineering forge for **Toontrack Superior Drummer 3**, built for autonomous AI coding agents (**Claude Code, Cursor, Codex, Antigravity**) and human mix engineers.

- **Compact Ground Truth Querying (`sd3-forge inventory`):** Extracts and filters local kit pieces, installed mics, stacks, keymaps, and all 35 native FX (`effect 10..44`) without bloating agent context.
- **Typed IR v2 & Lossless `.sd3p` Compiler:** Validates Pydantic v2 blueprints (`schema_version: "2.0"`) and compiles losslessly into `.sd3p` presets.
- **Persistent VST3 Worker & Analytical Calibrator:** Keeps `Superior Drummer 3.vst3` resident via `sd3-forge daemon`, verifies loaded slots with a pre-flight canary, and calibrates pitch + spectral/balance trims with `.forge-history/` auto-rollback (`sd3-forge calibrate`).
- **Anti-Goodhart DSP Engine v2:** Scores bounces across ISO 3382 Schroeder decay, fundamental pitch, snare ring peaks, per-cymbal harshness, tom pitch/pan ordering, and ITU-R BS.1770-4 loudness (`test-report.json`, `test-report.md`, `diagnostic-plots.png`).
- See [AGENTS.md](AGENTS.md) for the agent workflow and [docs/ROADMAP.md](docs/ROADMAP.md) for the full architecture.

---

## Installation

```bash
# Quick isolated install directly from GitHub (CLI + 6-tool MCP server)
pipx install "git+https://github.com/Y4Nsm/sd3-preset-forge.git"
# or with uv:
uv tool install "git+https://github.com/Y4Nsm/sd3-preset-forge.git"

# Or install directly via pip:
pip install "sd3-preset-forge @ git+https://github.com/Y4Nsm/sd3-preset-forge.git@v1.0.0"

# From source (development + optional local VST3 render + FastMCP extras):
git clone https://github.com/Y4Nsm/sd3-preset-forge.git
cd sd3-preset-forge
pip install -e ".[dev,render,mcp]"
```

---

## Quickstart

```bash
# 1. Initialize local Ground Truth inventory.json, neutral base template, and MIDI v2 suite
sd3-forge init

# 2. Query installed kit pieces, mics, and FX compactly
sd3-forge inventory summary --json
sd3-forge inventory pieces --slot Snare --json

# 3. Validate a preset blueprint against your local Ground Truth
sd3-forge validate presets/nu-metal/deftones-around-the-fur --json

# 4. Start persistent VST3 daemon and run bounded 2-stage calibration
sd3-forge daemon start --json
sd3-forge calibrate presets/nu-metal/deftones-around-the-fur --json
sd3-forge daemon stop --json

# 5. Compile blueprint to .sd3p (and optionally copy to SD3 User Presets with --install)
sd3-forge compile-sd3p presets/nu-metal/deftones-around-the-fur --install
```

### Other CLI Commands

```bash
sd3-forge auto-test presets/<genre>/<slug> --version v-auto   # Validate -> compile -> render -> analyze
sd3-forge profile-ref <reference.wav> --json                    # Advisory priors from a drum stem (numpy/scipy)
sd3-forge migrate <preset_dir> --in-place                       # Upgrade v1 blueprint YAML to schema_version 2.0
sd3-forge new-preset grunge alice-in-chains-facelift            # Scaffold a new preset directory
sd3-forge generate-midi [--scope kick|snare|toms|cymbals|full]  # Generate test MIDI v2 suite or short probe
sd3-forge render preset.sd3p out.wav                            # Render any .sd3p offline via daemon or VST3
sd3-forge analyze <preset_dir> <bounce.wav>                     # Run DSP v2 audit on any WAV bounce
```

Environment overrides (optional, auto-detected on Windows & macOS by default):
- `SD3_LIBRARY_PATH` — path to your `SL-SuperiorDrummer3` directory
- `SD3_VST3_PATH` — path to `Superior Drummer 3.vst3`
- `SD3_PRESETS_DIR` — path to your user `.sd3p` presets folder
- `SD3_FORGE_HOME` — override config/data directory

---

## MCP Server (`sd3-forge-mcp`) & Claude Code Skill

`sd3-preset-forge` ships both a Claude Code Skill ([.claude/skills/sd3-forge/SKILL.md](.claude/skills/sd3-forge/SKILL.md)) and an optional zero-overhead 6-tool stdio MCP server (`sd3-forge-mcp`):

```json
{
  "mcpServers": {
    "sd3-forge": {
      "command": "sd3-forge-mcp"
    }
  }
}
```

Exposed MCP tools: `sd3_query_inventory`, `sd3_validate_preset`, `sd3_compile_preset`, `sd3_daemon_control`, `sd3_calibrate_preset`, `sd3_analyze_or_profile`. Inspect schemas anytime with `sd3-forge-mcp --list-tools`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for TDD standards and CI instructions.

---

## Legal, Trademark & Interoperability Notice

- **Independent Project:** `sd3-preset-forge` is an independent open-source interoperability tool and is **not affiliated with, endorsed by, or sponsored by Toontrack Music AB** or any drum/cymbal manufacturer or recording artist referenced in preset documentation.
- **No Proprietary Assets Distributed:** This repository ships **zero** Toontrack sample libraries (`.obw`), factory `.sd3p` saves, proprietary audio bounces (`.wav`), or binary assets. All preset compilation and rendering operate strictly on the user's own legitimately licensed local installation of Superior Drummer 3.
- **Trademarks:** Superior Drummer 3 and Toontrack are registered trademarks of Toontrack Music AB. All brand/artist names are used solely for descriptive acoustic reference.
