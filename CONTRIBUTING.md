# Contributing to SD3 Preset Forge

Thank you for contributing! Please follow these engineering and legal hygiene standards before opening a pull request.

## 1. Clean-Room Interoperability & IP Policy
- **Zero proprietary assets:** Never commit Toontrack sample archives (`.obw`), factory `.sd3p` saves, rendered proprietary `.wav` bounces, local `inventory.json` dumps, or user-specific filesystem paths.
- **No runtime binary scraping:** FX mappings live strictly in the static clean-room table in `sd3_forge/fx_catalog.py`.
- All non-VST3 tests must run cleanly using synthetic fixtures in `tests/fixtures/`.

## 2. Red -> Green -> Refactor TDD
1. Write a failing unit/integration test in `tests/` (`Red`) targeting synthetic mathematical ground truth or structural invariants.
2. Implement the minimal clean module change in `sd3_forge/` (`Green`).
3. Refactor cleanly while keeping functions small, typed, and `ruff`-clean (`Refactor`).
4. Never weaken assertions or skip tests without explicit markers (`@pytest.mark.vst3` is reserved strictly for optional tests requiring a real local `Superior Drummer 3.vst3`).

## 3. Local Verification Before PR
```bash
pip install -e ".[dev]"
ruff check sd3_forge tests
pytest -m "not vst3" -v
```
If modifying `AGENTS.md`, keep it concise and strictly under 120 lines.
