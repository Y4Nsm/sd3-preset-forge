"""TDD tests for the persistent VST3 worker (`sd3_forge.daemon`) and pre-flight canary."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest

from sd3_forge.generate_test_midi import generate_midi_and_manifest
from sd3_forge.sd3p_codec import juce_b64_encode


def _make_template_raw_state() -> bytes:
    prefix = bytearray(176)
    prefix[0:4] = b"VstW"
    prefix[16:20] = b"CcnK"
    prefix[24:28] = b"FBCh"
    trailer = b"\x00" * 8 + b"JUCEPrivateData\x00\x01"
    inner = b"PlugVersion 3.4.4\n\x00" + trailer
    struct.pack_into(">I", prefix, 20, 152 + len(inner))
    struct.pack_into(">I", prefix, 172, len(inner))
    blob = bytes(prefix) + inner
    xml = f'<?xml version="1.0"?><VST3PluginState><IComponent>{juce_b64_encode(blob)}</IComponent></VST3PluginState>'
    return b"VC2!" + struct.pack("<I", len(xml.encode())) + xml.encode() + b"\x00"


class _PulseFakeVST3Plugin:
    """Mock VST3 plugin emitting short pulses at every note_on timestamp (except `silent_notes`)."""

    def __init__(self, silent_notes: set[int] | None = None) -> None:
        self.raw_state = _make_template_raw_state()
        self.silent_notes = set(silent_notes or ())
        self.render_calls = 0

    def __call__(
        self, messages, duration: float, sample_rate: int, buffer_size: int, reset: bool = True
    ) -> np.ndarray:
        self.render_calls += 1
        n_samp = max(sample_rate, int(round(duration * sample_rate)))
        audio = np.zeros((2, n_samp), dtype=np.float32)
        pulse_n = int(0.08 * sample_rate)
        t_vec = np.arange(pulse_n, dtype=np.float32) / sample_rate
        burst = (0.3 * np.exp(-25.0 * t_vec) * np.sin(2.0 * np.pi * 180.0 * t_vec)).astype(np.float32)
        for raw_bytes, abs_t in messages:
            if not raw_bytes:
                continue
            status = raw_bytes[0] & 0xF0
            if status == 0x90 and len(raw_bytes) >= 3 and raw_bytes[2] > 0:
                note = raw_bytes[1]
                if note in self.silent_notes:
                    continue
                idx0 = int(round(abs_t * sample_rate))
                idx1 = min(n_samp, idx0 + pulse_n)
                if idx1 > idx0:
                    seg = burst[: idx1 - idx0]
                    audio[0, idx0:idx1] += seg
                    audio[1, idx0:idx1] += seg
        return audio


def test_daemon_reuses_single_plugin_instance_and_auth(
    tmp_path: Path, synthetic_base_sd3p_path: Path
) -> None:
    from sd3_forge.daemon import DaemonClient, ForgeDaemonServer, daemon_status

    load_count = 0
    plug = _PulseFakeVST3Plugin()

    def factory(_vst3_path: Path | None) -> _PulseFakeVST3Plugin:
        nonlocal load_count
        load_count += 1
        return plug

    state_path = tmp_path / "daemon.json"
    midi_p, _ = generate_midi_and_manifest(tmp_path / "midi", scope="kick")
    server = ForgeDaemonServer(
        vst3_path=tmp_path / "dummy.vst3",
        state_path=state_path,
        idle_timeout_s=60.0,
        plugin_factory=factory,
    )
    server.start_in_thread()
    try:
        assert state_path.exists()
        st = daemon_status(state_path=state_path)
        assert st["running"] is True
        assert st["renders"] == 0

        # Missing or wrong X-Forge-Token must return HTTP 403
        req = Request(
            f"http://127.0.0.1:{st['port']}/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-Forge-Token": "wrong"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5.0)
        assert exc_info.value.code == 403

        client = DaemonClient.from_state_file(state_path)
        for i in range(3):
            out_wav = tmp_path / f"r{i}.wav"
            res = client.render(synthetic_base_sd3p_path, out_wav, midi_path=midi_p)
            assert out_wav.exists()
            assert res["peak_dbfs"] > -30.0

        assert load_count == 1
        assert plug.render_calls == 3
        st2 = daemon_status(state_path=state_path)
        assert st2["renders"] == 3
    finally:
        server.stop()

    assert not state_path.exists()


def test_daemon_canary_detects_silent_slot_and_skips_unloaded(
    tmp_path: Path, synthetic_base_sd3p_path: Path
) -> None:
    from sd3_forge.daemon import DaemonClient, ForgeDaemonServer

    # Make note 43 (Tom4) silent
    plug = _PulseFakeVST3Plugin(silent_notes={43})
    state_path = tmp_path / "daemon.json"
    server = ForgeDaemonServer(
        vst3_path=tmp_path / "dummy.vst3",
        state_path=state_path,
        idle_timeout_s=60.0,
        plugin_factory=lambda _p: plug,
    )
    server.start_in_thread()
    try:
        client = DaemonClient.from_state_file(state_path)
        res_fail = client.canary(synthetic_base_sd3p_path, unload_slots=[])
        assert res_fail["ok"] is False
        assert "Tom4" in res_fail["silent_slots"]

        res_ok = client.canary(synthetic_base_sd3p_path, unload_slots=["Tom4"])
        assert res_ok["ok"] is True
        assert res_ok["silent_slots"] == []
    finally:
        server.stop()


def test_render_via_daemon_or_direct_fallback_and_stale_state(
    tmp_path: Path, synthetic_base_sd3p_path: Path
) -> None:
    from sd3_forge.daemon import daemon_status, render_via_daemon_or_direct

    state_path = tmp_path / "daemon.json"
    # Write stale daemon.json pointing to an unused port
    state_path.write_text(
        json.dumps({"pid": 999999, "host": "127.0.0.1", "port": 59999, "token": "abc"}),
        encoding="utf-8",
    )
    st = daemon_status(state_path=state_path)
    assert st["running"] is False

    # Direct fallback works seamlessly via injected plugin when no daemon is active
    midi_p, _ = generate_midi_and_manifest(tmp_path / "midi", scope="kick")
    plug = _PulseFakeVST3Plugin()
    out_wav = tmp_path / "direct.wav"
    res = render_via_daemon_or_direct(
        synthetic_base_sd3p_path,
        out_wav,
        midi_path=midi_p,
        use_daemon=True,
        state_path=state_path,
        plugin=plug,
    )
    assert out_wav.exists()
    assert res["via_daemon"] is False
    assert plug.render_calls == 1


def test_daemon_recycles_plugin_and_skips_identical_state(tmp_path: Path) -> None:
    from sd3_forge.daemon import DaemonClient, ForgeDaemonServer

    load_count = 0

    def factory(_vst3_path: Path | None) -> _PulseFakeVST3Plugin:
        nonlocal load_count
        load_count += 1
        return _PulseFakeVST3Plugin()

    state_path = tmp_path / "daemon.json"
    midi_p, _ = generate_midi_and_manifest(tmp_path / "midi", scope="kick")
    p1 = tmp_path / "p1.sd3p"
    p2 = tmp_path / "p2.sd3p"
    p3 = tmp_path / "p3.sd3p"
    p1.write_bytes(b"PlugVersion 3.4.4\n// A\n\x00")
    p2.write_bytes(b"PlugVersion 3.4.4\n// B\n\x00")
    p3.write_bytes(b"PlugVersion 3.4.4\n// C\n\x00")

    server = ForgeDaemonServer(
        vst3_path=tmp_path / "dummy.vst3",
        state_path=state_path,
        idle_timeout_s=60.0,
        max_state_reloads=2,
        plugin_factory=factory,
    )
    server.start_in_thread()
    try:
        client = DaemonClient.from_state_file(state_path)
        # Same payload twice -> only 1 raw_state reload, 1 plugin instance
        client.render(p1, tmp_path / "a1.wav", midi_path=midi_p)
        client.render(p1, tmp_path / "a2.wav", midi_path=midi_p)
        assert load_count == 1
        # Second distinct payload -> hits max_state_reloads=2 inside existing plugin
        client.render(p2, tmp_path / "b1.wav", midi_path=midi_p)
        assert load_count == 1
        # Third distinct payload -> triggers automatic plugin recycle before raw_state swap
        client.render(p3, tmp_path / "c1.wav", midi_path=midi_p)
        assert load_count == 2
    finally:
        server.stop()
