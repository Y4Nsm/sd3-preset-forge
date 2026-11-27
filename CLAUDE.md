# Claude Code Instructions

Follow [AGENTS.md](AGENTS.md) and [.claude/skills/sd3-forge/SKILL.md](.claude/skills/sd3-forge/SKILL.md) for all preset engineering, validation, calibration, and clean-room rules.

## Key Commands
- Always prefer `--json` output on `sd3-forge` commands (`inventory`, `validate`, `daemon`, `calibrate`, `profile-ref`), or connect `sd3-forge-mcp`.
- Keep `sd3-forge daemon start` active while iterating on a preset, and run `sd3-forge daemon stop` before finishing.
- Never dump `inventory.json` directly into context; always filter via `sd3-forge inventory ... --json`.

## Development & Verification
```bash
ruff check sd3_forge tests
pytest -m "not vst3" -v
```
- Follow strict **Red -> Green -> Refactor TDD** on every code change.
- Never commit `.sd3p`, `.wav`, `inventory.json`, `.forge-history/`, `test-report.*`, or local paths.
