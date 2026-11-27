"""TDD tests for the thin 6-tool `sd3-forge-mcp` wrapper over Layer 2/3 modules."""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


def _write_test_wav(path: Path) -> Path:
    sr = 44100
    dur = 3.0
    t = np.arange(int(sr * dur), dtype=np.float64) / sr
    sig = np.zeros_like(t)
    for hit_t, freq in [(0.1, 56.0), (0.6, 210.0), (1.1, 56.0), (1.6, 210.0), (2.1, 56.0), (2.5, 210.0)]:
        mask = t >= hit_t
        dt = t[mask] - hit_t
        sig[mask] += 0.4 * np.exp(-12.0 * dt) * np.sin(2.0 * np.pi * freq * dt)
    stereo = np.column_stack([sig, sig])
    sf.write(str(path), stereo, sr, subtype="PCM_24")
    return path


def test_mcp_tool_specs_contract() -> None:
    from sd3_forge.mcp_server import MCP_TOOL_SPECS

    names = [t["name"] for t in MCP_TOOL_SPECS]
    assert names == [
        "sd3_query_inventory",
        "sd3_validate_preset",
        "sd3_compile_preset",
        "sd3_daemon_control",
        "sd3_calibrate_preset",
        "sd3_analyze_or_profile",
    ]
    assert len(MCP_TOOL_SPECS) == 6
    for spec in MCP_TOOL_SPECS:
        assert spec["description"]
        schema = spec["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_mcp_stdio_protocol_and_all_tools(
    tmp_path: Path,
    mock_inventory_path: Path,
    synthetic_base_sd3p_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sd3_forge.mcp_server import handle_jsonrpc_message, main, run_stdio_server

    wav_path = _write_test_wav(tmp_path / "ref.wav")
    out_sd3p = tmp_path / "compiled.sd3p"
    daemon_state = tmp_path / "daemon.json"

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "sd3_query_inventory",
                "arguments": {"query": "summary", "inventory_path": str(mock_inventory_path)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "sd3_validate_preset",
                "arguments": {
                    "preset_dir": "presets/nu-metal/deftones-around-the-fur",
                    "inventory_path": str(mock_inventory_path),
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "sd3_compile_preset",
                "arguments": {
                    "preset_dir": "presets/nu-metal/deftones-around-the-fur",
                    "out_path": str(out_sd3p),
                    "template_path": str(synthetic_base_sd3p_path),
                    "inventory_path": str(mock_inventory_path),
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "sd3_daemon_control",
                "arguments": {"action": "status", "state_path": str(daemon_state)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "sd3_analyze_or_profile",
                "arguments": {"mode": "profile_ref", "wav_path": str(wav_path)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        },
    ]

    stdin_buf = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n{bad json\n")
    stdout_buf = io.StringIO()
    rc = run_stdio_server(stdin=stdin_buf, stdout=stdout_buf)
    assert rc == 0

    responses = [json.loads(line) for line in stdout_buf.getvalue().splitlines() if line.strip()]
    by_id = {resp.get("id"): resp for resp in responses}

    # Notification produces no response; 9 requests + 1 parse error -> 10 responses
    assert len(responses) == 10
    assert by_id[1]["result"]["protocolVersion"] == "2024-11-05"
    assert by_id[1]["result"]["serverInfo"]["name"] == "sd3-forge-mcp"
    assert "tools" in by_id[1]["result"]["capabilities"]
    assert by_id[2]["result"] == {}
    assert len(by_id[3]["result"]["tools"]) == 6

    inv_res = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert by_id[4]["result"]["isError"] is False
    assert inv_res["counts"]["native_fx"] == 35

    val_res = json.loads(by_id[5]["result"]["content"][0]["text"])
    assert val_res["ok"] is True

    cmp_res = json.loads(by_id[6]["result"]["content"][0]["text"])
    assert cmp_res["ok"] is True
    assert out_sd3p.exists()
    assert out_sd3p.read_bytes().endswith(b"\x00")

    dmn_res = json.loads(by_id[7]["result"]["content"][0]["text"])
    assert dmn_res["running"] is False

    prof_res = json.loads(by_id[8]["result"]["content"][0]["text"])
    assert prof_res["advisory_only"] is True

    assert by_id[9]["result"]["isError"] is True
    parse_err = next(r for r in responses if r.get("id") is None)
    assert parse_err["error"]["code"] == -32700

    unknown_meth = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 99, "method": "foo/bar", "params": {}})
    assert unknown_meth is not None and unknown_meth["error"]["code"] == -32601

    assert main(["--list-tools"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed) == 6
