"""Headless offline VST3 renderer for SD3 Preset Forge via Pedalboard."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import mido
import numpy as np
import soundfile as sf

from sd3_forge.paths import default_midi_path, detect_sd3_vst3_path
from sd3_forge.sd3p_codec import unwrap_vc2_state, wrap_vc2_state


def load_midi_messages(midi_path: Path) -> tuple[list[tuple[bytes, float]], float]:
    """Load MIDI events as `(raw_bytes, abs_time_seconds)` tuples plus total duration."""
    if not midi_path.exists():
        raise FileNotFoundError(f"MIDI file not found: {midi_path}")
    mid = mido.MidiFile(str(midi_path))
    messages: list[tuple[bytes, float]] = []
    t = 0.0
    for msg in mid:
        t += msg.time
        if not msg.is_meta:
            messages.append((msg.bytes(), t))
    return messages, t


def render_sd3p_to_wav(
    sd3p_path: Path,
    out_wav: Path,
    midi_path: Path | None = None,
    vst3_path: Path | None = None,
    sample_rate: int = 44100,
    buffer_size: int = 512,
    tail_seconds: float = 4.0,
    plugin: Any | None = None,
) -> dict[str, Any]:
    """Render an `.sd3p` preset offline through SD3 VST3 and write a 24-bit WAV."""
    if not sd3p_path.exists():
        raise FileNotFoundError(f"Preset file not found: {sd3p_path}")

    resolved_midi = midi_path or default_midi_path()
    t_start = time.time()

    if plugin is None:
        try:
            from pedalboard import load_plugin
        except ImportError as exc:
            raise RuntimeError(
                "Headless VST3 rendering requires the optional 'render' dependency. "
                "Install with: pip install 'sd3-preset-forge[render]'"
            ) from exc

        resolved_vst3 = vst3_path or detect_sd3_vst3_path()
        if resolved_vst3 is None or not resolved_vst3.exists():
            raise FileNotFoundError(
                f"SD3 VST3 plugin not found: {resolved_vst3}. "
                "Set SD3_VST3_PATH or run `sd3-forge init --vst3-path <path>`."
            )
        plugin = load_plugin(str(resolved_vst3))

    template_xml, template_blob = unwrap_vc2_state(plugin.raw_state)
    sd3p_bytes = sd3p_path.read_bytes()
    plugin.raw_state = wrap_vc2_state(template_xml, template_blob, sd3p_bytes)

    messages, total_midi_s = load_midi_messages(resolved_midi)
    duration_s = total_midi_s + tail_seconds

    t_render0 = time.time()
    audio = plugin(
        messages,
        duration=duration_s,
        sample_rate=sample_rate,
        buffer_size=buffer_size,
        reset=True,
    )
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-4:
        # Fallback retry in case sample streaming needed brief time after state injection
        time.sleep(3.0)
        audio = plugin(
            messages,
            duration=duration_s,
            sample_rate=sample_rate,
            buffer_size=buffer_size,
            reset=True,
        )
        peak = float(np.max(np.abs(audio)))
        if peak < 1e-4:
            raise RuntimeError(
                f"SD3 VST3 rendered silence (peak={peak:.6g}) for {sd3p_path}. "
                "Verify SD3 Core Library paths and preset kit pieces."
            )

    render_time_s = time.time() - t_render0
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), audio.T, sample_rate, subtype="PCM_24")

    return {
        "out_wav": str(out_wav),
        "sample_rate": sample_rate,
        "duration_s": float(audio.shape[1] / sample_rate),
        "peak_linear": peak,
        "peak_dbfs": float(20.0 * np.log10(max(peak, 1e-12))),
        "render_time_s": float(render_time_s),
        "total_time_s": float(time.time() - t_start),
        "plugin": plugin,
    }
