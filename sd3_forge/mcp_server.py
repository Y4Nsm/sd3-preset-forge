"""Thin 6-tool MCP (Model Context Protocol) wrapper over SD3 Preset Forge Layer 2/3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sd3_forge.analyze_bounce import run_analysis
from sd3_forge.calibrate import run_calibration
from sd3_forge.compile_sd3p import compile_blueprint_to_sd3p
from sd3_forge.daemon import daemon_status, start_daemon_background, stop_daemon
from sd3_forge.inventory_cli import (
    load_inventory,
    query_fx,
    query_keymap,
    query_kits,
    query_mics,
    query_pieces,
    query_stacks,
    query_summary,
)
from sd3_forge.profile_ref import profile_reference_wav
from sd3_forge.validate_blueprint import validate_preset_dir

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sd3-forge-mcp"
SERVER_VERSION = "1.0.0"

MCP_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "sd3_query_inventory",
        "description": "Query installed SD3 kits, pieces, mics, native FX, stacks, or MIDI keymaps compactly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": ["summary", "kits", "pieces", "mics", "fx", "stacks", "keymap"],
                    "default": "summary",
                },
                "kit": {"type": "string"},
                "slot": {"type": "string"},
                "search": {"type": "string"},
                "category": {"type": "string"},
                "name": {"type": "string"},
                "group": {"type": "string"},
                "bleed_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 50},
                "inventory_path": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "sd3_validate_preset",
        "description": "Validate 02-spec-targets.yaml and 03-sd3-blueprint.yaml against Ground Truth & 35-FX contract.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset_dir": {"type": "string"},
                "inventory_path": {"type": "string"},
            },
            "required": ["preset_dir"],
        },
    },
    {
        "name": "sd3_compile_preset",
        "description": "Compile a validated blueprint directory into a native `.sd3p` preset file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset_dir": {"type": "string"},
                "out_path": {"type": "string"},
                "template_path": {"type": "string"},
                "inventory_path": {"type": "string"},
                "install_to_sd3": {"type": "boolean", "default": False},
                "install_name": {"type": "string"},
            },
            "required": ["preset_dir"],
        },
    },
    {
        "name": "sd3_daemon_control",
        "description": "Start, inspect status, or stop the persistent headless Superior Drummer 3 VST3 worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start", "status", "stop"], "default": "status"},
                "vst3_path": {"type": "string"},
                "idle_timeout_s": {"type": "number", "default": 900.0},
                "state_path": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "sd3_calibrate_preset",
        "description": "Run bounded 2-stage analytical calibration with `.forge-history/best.yaml` auto-rollback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset_dir": {"type": "string"},
                "max_pitch_iters": {"type": "integer", "default": 3},
                "max_mix_iters": {"type": "integer", "default": 4},
                "inventory_path": {"type": "string"},
                "template_path": {"type": "string"},
                "vst3_path": {"type": "string"},
                "use_daemon": {"type": "boolean", "default": True},
                "run_canary": {"type": "boolean", "default": True},
            },
            "required": ["preset_dir"],
        },
    },
    {
        "name": "sd3_analyze_or_profile",
        "description": "Audit a rendered WAV bounce (`analyze`) or extract advisory macro priors (`profile_ref`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["analyze", "profile_ref"], "default": "analyze"},
                "wav_path": {"type": "string"},
                "preset_dir": {"type": "string"},
                "manifest_path": {"type": "string"},
                "align": {"type": "boolean", "default": True},
            },
            "required": ["mode", "wav_path"],
        },
    },
]


def _opt_path(val: Any) -> Path | None:
    return Path(val) if val else None


def tool_query_inventory(
    *,
    query: str = "summary",
    kit: str | None = None,
    slot: str | None = None,
    search: str | None = None,
    category: str | None = None,
    name: str | None = None,
    group: str | None = None,
    bleed_only: bool = False,
    limit: int = 50,
    inventory_path: str | None = None,
) -> dict[str, Any]:
    inv, resolved = load_inventory(_opt_path(inventory_path))
    if query == "summary":
        out = query_summary(inv)
        out["inventory_path"] = str(resolved)
        return out
    if query == "kits":
        return query_kits(inv, kit_name=kit)
    if query == "pieces":
        return query_pieces(inv, slot=slot, search=search, limit=int(limit))
    if query == "mics":
        return query_mics(inv, bleed_only=bool(bleed_only))
    if query == "fx":
        return query_fx(inv, category=category, search=search, name=name)
    if query == "stacks":
        return query_stacks(inv, category=category, search=search, limit=int(limit))
    if query == "keymap":
        return query_keymap(inv, group=group, search=search)
    raise ValueError(f"Unsupported inventory query {query!r}")


def tool_validate_preset(*, preset_dir: str, inventory_path: str | None = None) -> dict[str, Any]:
    return validate_preset_dir(Path(preset_dir), inventory_path=_opt_path(inventory_path)).to_dict()


def tool_compile_preset(
    *,
    preset_dir: str,
    out_path: str | None = None,
    template_path: str | None = None,
    inventory_path: str | None = None,
    install_to_sd3: bool = False,
    install_name: str | None = None,
) -> dict[str, Any]:
    compiled = compile_blueprint_to_sd3p(
        Path(preset_dir),
        out_path=_opt_path(out_path),
        template_path=_opt_path(template_path),
        inventory_path=_opt_path(inventory_path),
        install_to_sd3=bool(install_to_sd3),
        install_name=install_name,
    )
    return {"ok": True, "out_path": str(compiled), "size_bytes": compiled.stat().st_size}


def tool_daemon_control(
    *,
    action: str = "status",
    vst3_path: str | None = None,
    idle_timeout_s: float = 900.0,
    state_path: str | None = None,
) -> dict[str, Any]:
    resolved_state = _opt_path(state_path)
    if action == "status":
        return daemon_status(state_path=resolved_state)
    if action == "start":
        return start_daemon_background(
            vst3_path=_opt_path(vst3_path),
            idle_timeout_s=float(idle_timeout_s),
            state_path=resolved_state,
        )
    if action == "stop":
        return stop_daemon(state_path=resolved_state)
    raise ValueError(f"Unsupported daemon action {action!r}; expected 'start', 'status', or 'stop'")


def tool_calibrate_preset(
    *,
    preset_dir: str,
    max_pitch_iters: int = 3,
    max_mix_iters: int = 4,
    inventory_path: str | None = None,
    template_path: str | None = None,
    vst3_path: str | None = None,
    use_daemon: bool = True,
    run_canary: bool = True,
) -> dict[str, Any]:
    return run_calibration(
        Path(preset_dir),
        max_pitch_iters=int(max_pitch_iters),
        max_mix_iters=int(max_mix_iters),
        inventory_path=_opt_path(inventory_path),
        template_path=_opt_path(template_path),
        vst3_path=_opt_path(vst3_path),
        use_daemon=bool(use_daemon),
        run_canary=bool(run_canary),
    )


def tool_analyze_or_profile(
    *,
    mode: str = "analyze",
    wav_path: str,
    preset_dir: str | None = None,
    manifest_path: str | None = None,
    align: bool = True,
) -> dict[str, Any]:
    if mode == "profile_ref":
        return profile_reference_wav(Path(wav_path))
    if mode == "analyze":
        if not preset_dir:
            raise ValueError("`preset_dir` is required when mode='analyze'")
        return run_analysis(
            Path(preset_dir),
            Path(wav_path),
            manifest_path=_opt_path(manifest_path),
            align=bool(align),
        )
    raise ValueError(f"Unsupported mode {mode!r}; expected 'analyze' or 'profile_ref'")


_TOOL_DISPATCH: dict[str, Any] = {
    "sd3_query_inventory": tool_query_inventory,
    "sd3_validate_preset": tool_validate_preset,
    "sd3_compile_preset": tool_compile_preset,
    "sd3_daemon_control": tool_daemon_control,
    "sd3_calibrate_preset": tool_calibrate_preset,
    "sd3_analyze_or_profile": tool_analyze_or_profile,
}


def dispatch_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch one of the 6 registered MCP tools directly to Layer 2/3."""
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        raise ValueError(f"Unknown MCP tool {name!r}; available: {list(_TOOL_DISPATCH.keys())}")
    return fn(**(arguments or {}))


def handle_jsonrpc_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC 2.0 MCP message; returns `None` for notifications."""
    msg_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    if msg_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": MCP_TOOL_SPECS}}
    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        tool_args = params.get("arguments") or {}
        try:
            payload = dispatch_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": str(exc)}, ensure_ascii=False)}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_stdio_server(stdin: Any = None, stdout: Any = None) -> int:
    """Run newline-delimited JSON-RPC 2.0 MCP stdio loop."""
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout
    for raw_line in in_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict):
                raise ValueError("JSON-RPC payload must be a JSON object")
            resp = handle_jsonrpc_message(msg)
        except Exception as exc:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
        if resp is not None:
            out_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out_stream.flush()
    return 0


def build_fastmcp_server() -> Any:
    """Optional `FastMCP` server adapter when `sd3-preset-forge[mcp]` extra is installed."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "FastMCP mode requires the optional 'mcp' dependency. "
            "Install with: pip install 'sd3-preset-forge[mcp]' (or run default stdio mode without --fastmcp)."
        ) from exc

    server = FastMCP(SERVER_NAME)
    for fn in _TOOL_DISPATCH.values():
        server.tool()(fn)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sd3-forge-mcp", description="SD3 Preset Forge MCP Server")
    parser.add_argument("--list-tools", action="store_true", help="Print the 6 MCP tool schemas as JSON and exit")
    parser.add_argument("--fastmcp", action="store_true", help="Run via optional FastMCP SDK instead of stdlib stdio")
    args = parser.parse_args(argv)

    if args.list_tools:
        print(json.dumps(MCP_TOOL_SPECS, indent=2, ensure_ascii=False))
        return 0
    if args.fastmcp:
        build_fastmcp_server().run()
        return 0
    return run_stdio_server()


if __name__ == "__main__":
    raise SystemExit(main())
