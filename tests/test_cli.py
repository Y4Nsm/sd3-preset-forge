"""CLI tests including `--json` output and clean error handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sd3_forge.cli import main


def test_cli_validate_and_json_output(mock_inventory_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "validate",
            "presets/nu-metal/deftones-around-the-fur",
            "--inventory",
            str(mock_inventory_path),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == []


def test_cli_init_and_compile_e2e(
    tmp_path: Path,
    mock_library_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SD3_FORGE_HOME", str(tmp_path / "home"))
    rc_init = main(["init", "--sd3-path", str(mock_library_dir), "--no-midi", "--json"])
    assert rc_init == 0
    init_res = json.loads(capsys.readouterr().out)
    assert init_res["ok"] is True

    out_sd3p = tmp_path / "compiled.sd3p"
    rc_cmp = main(
        [
            "compile-sd3p",
            "presets/nu-metal/deftones-around-the-fur",
            "--out",
            str(out_sd3p),
        ]
    )
    assert rc_cmp == 0
    assert out_sd3p.exists()
    assert out_sd3p.read_bytes().endswith(b"\x00")


def test_cli_handles_missing_files_without_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["compile-sd3p", str(tmp_path / "does-not-exist"), "--template", str(tmp_path / "missing.sd3p")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
