"""Mocked tests for headless VST3 rendering (`sd3_forge.render_sd3`)."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from sd3_forge.generate_test_midi import generate_midi_and_manifest
from sd3_forge.render_sd3 import render_sd3p_to_wav
from sd3_forge.sd3p_codec import juce_b64_encode, unwrap_vc2_state


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


class _FakeVST3Plugin:
    def __init__(self, responses: list[np.ndarray]) -> None:
        self.raw_state = _make_template_raw_state()
        self._responses = responses
        self.calls: list[dict] = []

    def __call__(self, messages, duration: float, sample_rate: int, buffer_size: int, reset: bool = True) -> np.ndarray:
        self.calls.append(
            {"n_msgs": len(messages), "duration": duration, "sr": sample_rate, "reset": reset}
        )
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


def test_render_with_mock_plugin_normal_and_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sd3_forge.render_sd3.time.sleep", lambda _s: None)
    midi_p, _ = generate_midi_and_manifest(tmp_path)
    sd3p_p = tmp_path / "preset.sd3p"
    sd3p_p.write_bytes(b"PlugVersion 3.4.4\nSAMPLER {\n}\n\x00")

    sr = 44100
    silent = np.zeros((2, sr), dtype=np.float32)
    valid = np.full((2, sr), 0.25, dtype=np.float32)

    # First silent -> retry succeeds
    plug = _FakeVST3Plugin([silent, valid])
    out_wav = tmp_path / "out.wav"
    info = render_sd3p_to_wav(sd3p_p, out_wav, midi_path=midi_p, plugin=plug, sample_rate=sr)

    assert len(plug.calls) == 2
    assert plug.calls[0]["reset"] is True
    assert out_wav.exists()
    assert abs(info["peak_linear"] - 0.25) < 1e-4

    # Verify VC2! payload reached plug.raw_state cleanly
    _, blob = unwrap_vc2_state(plug.raw_state)
    assert b"SAMPLER {" in blob


def test_render_persistent_silence_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sd3_forge.render_sd3.time.sleep", lambda _s: None)
    midi_p, _ = generate_midi_and_manifest(tmp_path)
    sd3p_p = tmp_path / "preset.sd3p"
    sd3p_p.write_bytes(b"PlugVersion 3.4.4\n\x00")

    silent = np.zeros((2, 4410), dtype=np.float32)
    plug = _FakeVST3Plugin([silent, silent])
    with pytest.raises(RuntimeError, match="rendered silence"):
        render_sd3p_to_wav(sd3p_p, tmp_path / "fail.wav", midi_path=midi_p, plugin=plug)
