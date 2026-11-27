"""Persistent localhost VST3 worker daemon and multi-slot pre-flight canary for SD3 Preset Forge."""

from __future__ import annotations

import argparse
import gc
import hashlib
import http.client
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import mido
import numpy as np
import soundfile as sf

from sd3_forge.paths import daemon_state_path, default_midi_path, detect_sd3_vst3_path
from sd3_forge.render_sd3 import load_midi_messages, render_sd3p_to_wav
from sd3_forge.sd3p_codec import unwrap_vc2_state, wrap_vc2_state

CANARY_SLOTS: tuple[tuple[str, int], ...] = (
    ("KickR", 36),
    ("Snare", 38),
    ("Tom1", 48),
    ("Tom2", 47),
    ("Tom3", 45),
    ("Tom4", 43),
    ("Tom5", 41),
    ("Hats", 42),
    ("Cymbal1", 49),
)


def _to_dbfs(val: float) -> float:
    return float(20.0 * np.log10(max(val, 1e-12)))


def build_canary_midi(
    unload_slots: set[str] | list[str] | None = None,
) -> tuple[list[tuple[bytes, float]], list[dict[str, Any]], float]:
    """Build a ~2.5s deterministic pre-flight canary sequence over loaded kit slots."""
    unloaded = set(unload_slots or ())
    messages: list[tuple[bytes, float]] = []
    schedule: list[dict[str, Any]] = []
    t = 0.05
    step = 0.24
    for slot, note in CANARY_SLOTS:
        if slot in unloaded:
            continue
        note_on = mido.Message("note_on", channel=9, note=note, velocity=120).bytes()
        note_off = mido.Message("note_off", channel=9, note=note, velocity=0).bytes()
        messages.append((note_on, t))
        messages.append((note_off, t + 0.12))
        schedule.append({"slot": slot, "note": note, "time_s": round(t, 4)})
        t += step
    total_duration = round(t + 0.35, 3)
    return messages, schedule, total_duration


def evaluate_canary_audio(
    audio: np.ndarray,
    sr: int,
    slots_schedule: list[dict[str, Any]],
    threshold_dbfs: float = -60.0,
) -> dict[str, Any]:
    """Check that every scheduled kit slot emits audible audio above `threshold_dbfs`."""
    arr = np.asarray(audio)
    if arr.ndim == 2 and arr.shape[0] in (1, 2) and arr.shape[1] > arr.shape[0]:
        # Pedalboard returns (channels, samples)
        arr = arr.T
    if arr.ndim == 1:
        mono = arr
    else:
        mono = np.mean(arr, axis=1)

    slot_results: list[dict[str, Any]] = []
    silent_slots: list[str] = []
    win_samp = int(0.22 * sr)
    for item in slots_schedule:
        idx0 = max(0, int(item["time_s"] * sr))
        idx1 = min(len(mono), idx0 + win_samp)
        seg = mono[idx0:idx1]
        peak_lin = float(np.max(np.abs(seg))) if len(seg) else 0.0
        peak_db = round(_to_dbfs(peak_lin), 2)
        audible = peak_db > threshold_dbfs
        if not audible:
            silent_slots.append(str(item["slot"]))
        slot_results.append(
            {
                "slot": item["slot"],
                "note": item["note"],
                "peak_dbfs": peak_db,
                "audible": audible,
            }
        )

    return {
        "ok": len(silent_slots) == 0,
        "threshold_dbfs": threshold_dbfs,
        "slots": slot_results,
        "silent_slots": silent_slots,
    }


def _default_plugin_factory(vst3_path: Path | None) -> Any:
    try:
        from pedalboard import load_plugin
    except ImportError as exc:
        raise RuntimeError(
            "Headless VST3 rendering requires the optional 'render' dependency. "
            "Install with: pip install 'sd3-preset-forge[render]'"
        ) from exc

    resolved = vst3_path or detect_sd3_vst3_path()
    if resolved is None or not resolved.exists():
        raise FileNotFoundError(
            f"SD3 VST3 plugin not found: {resolved}. Set SD3_VST3_PATH or pass `--vst3`."
        )
    return load_plugin(str(resolved))


class _WorkerJob:
    def __init__(self, op: str, payload: dict[str, Any]) -> None:
        self.op = op
        self.payload = payload
        self.done = threading.Event()
        self.result: dict[str, Any] | None = None
        self.error: BaseException | None = None


class ForgeDaemonServer:
    """Thread-safe localhost HTTP daemon keeping one SD3 VST3 instance pinned to a single worker thread."""

    def __init__(
        self,
        *,
        vst3_path: Path | None = None,
        state_path: Path | None = None,
        port: int = 0,
        idle_timeout_s: float = 900.0,
        max_state_reloads: int = 4,
        plugin_factory: Callable[[Path | None], Any] | None = None,
    ) -> None:
        self.vst3_path = vst3_path or detect_sd3_vst3_path()
        self.state_path = state_path or daemon_state_path()
        self.idle_timeout_s = float(idle_timeout_s)
        self.max_state_reloads = int(max_state_reloads)
        self.token = secrets.token_hex(16)
        self._plugin_factory = plugin_factory or _default_plugin_factory

        self._job_queue: queue.Queue[_WorkerJob | None] = queue.Queue()
        self._worker_ready = threading.Event()
        self._worker_init_error: BaseException | None = None
        self._stop_event = threading.Event()

        self._renders = 0
        self._started_at = time.time()
        self._last_activity = time.monotonic()
        self._stats_lock = threading.Lock()

        self._httpd: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self.port: int = port

    def _worker_loop(self) -> None:
        plugin: Any = None
        template_xml: str = ""
        template_blob: bytes = b""
        last_sd3p_hash: str | None = None
        state_reloads = 0

        def _recycle_plugin() -> None:
            nonlocal plugin, template_xml, template_blob, last_sd3p_hash, state_reloads
            plugin = None
            gc.collect()
            plugin = self._plugin_factory(self.vst3_path)
            template_xml, template_blob = unwrap_vc2_state(plugin.raw_state)
            last_sd3p_hash = None
            state_reloads = 0

        def _ensure_preset_loaded(sd3p_bytes: bytes, *, force_recycle: bool = False) -> None:
            nonlocal last_sd3p_hash, state_reloads
            digest = hashlib.sha256(sd3p_bytes).hexdigest()
            if not force_recycle and digest == last_sd3p_hash:
                return
            if force_recycle or (self.max_state_reloads > 0 and state_reloads >= self.max_state_reloads):
                _recycle_plugin()
            plugin.raw_state = wrap_vc2_state(template_xml, template_blob, sd3p_bytes)
            state_reloads += 1
            last_sd3p_hash = digest
            if self._plugin_factory is _default_plugin_factory:
                time.sleep(0.35)

        try:
            plugin = self._plugin_factory(self.vst3_path)
            template_xml, template_blob = unwrap_vc2_state(plugin.raw_state)
        except BaseException as exc:
            self._worker_init_error = exc
            self._worker_ready.set()
            return
        self._worker_ready.set()

        while True:
            job = self._job_queue.get()
            if job is None:
                break
            try:
                if job.op == "render":
                    p = job.payload
                    sd3p_path = Path(p["sd3p_path"])
                    out_wav = Path(p["out_wav"])
                    midi_path = Path(p["midi_path"]) if p.get("midi_path") else default_midi_path()
                    sample_rate = int(p.get("sample_rate", 44100))
                    buffer_size = int(p.get("buffer_size", 512))
                    tail_seconds = float(p.get("tail_seconds", 4.0))

                    sd3p_bytes = sd3p_path.read_bytes()
                    _ensure_preset_loaded(sd3p_bytes)
                    messages, total_midi_s = load_midi_messages(midi_path)
                    duration_s = total_midi_s + tail_seconds
                    t0 = time.time()

                    def _render_once(
                        msgs: list[tuple[bytes, float]] = messages,
                        dur: float = duration_s,
                        sr: int = sample_rate,
                        bsz: int = buffer_size,
                    ) -> tuple[np.ndarray, float, float]:
                        arr = plugin(
                            msgs,
                            duration=dur,
                            sample_rate=sr,
                            buffer_size=bsz,
                            reset=True,
                        )
                        pk = float(np.max(np.abs(arr)))
                        t_pk = (
                            float(np.max(np.abs(arr[:, int(arr.shape[1] * 0.65) :])))
                            if dur >= 60.0 and arr.shape[1] > 100
                            else pk
                        )
                        return arr, pk, t_pk

                    audio, peak, tail_peak = _render_once()
                    if peak < 1e-4 or tail_peak < 1e-4:
                        time.sleep(2.5 if self._plugin_factory is _default_plugin_factory else 0.01)
                        audio, peak, tail_peak = _render_once()
                    if peak < 1e-4 or tail_peak < 1e-4:
                        _ensure_preset_loaded(sd3p_bytes, force_recycle=True)
                        audio, peak, tail_peak = _render_once()
                    if peak < 1e-4 or tail_peak < 1e-4:
                        raise RuntimeError(
                            f"SD3 VST3 rendered silence/dropout (peak={peak:.6g}, tail_peak={tail_peak:.6g}) for {sd3p_path}"
                        )

                    render_time_s = time.time() - t0
                    out_wav.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(str(out_wav), audio.T, sample_rate, subtype="PCM_24")
                    with self._stats_lock:
                        self._renders += 1
                    job.result = {
                        "out_wav": str(out_wav),
                        "sample_rate": sample_rate,
                        "duration_s": float(audio.shape[1] / sample_rate),
                        "peak_linear": peak,
                        "peak_dbfs": round(_to_dbfs(peak), 3),
                        "render_time_s": round(float(render_time_s), 3),
                        "total_time_s": round(float(time.time() - t0), 3),
                        "via_daemon": True,
                    }
                elif job.op == "canary":
                    p = job.payload
                    sd3p_path = Path(p["sd3p_path"])
                    unload_slots = p.get("unload_slots") or []
                    sample_rate = int(p.get("sample_rate", 44100))
                    _ensure_preset_loaded(sd3p_path.read_bytes())
                    messages, schedule, dur = build_canary_midi(unload_slots)
                    audio = plugin(
                        messages,
                        duration=dur,
                        sample_rate=sample_rate,
                        buffer_size=512,
                        reset=True,
                    )
                    res = evaluate_canary_audio(audio, sample_rate, schedule)
                    res["via_daemon"] = True
                    job.result = res
                else:
                    raise ValueError(f"Unknown worker operation: {job.op}")
            except BaseException as exc:
                job.error = exc
            finally:
                with self._stats_lock:
                    self._last_activity = time.monotonic()
                job.done.set()

    def _submit(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._stats_lock:
            self._last_activity = time.monotonic()
        job = _WorkerJob(op, payload)
        self._job_queue.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error
        assert job.result is not None
        return job.result

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        daemon = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: Any) -> None:
                return

            def _send_json(self, code: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8") or "{}")
                return data if isinstance(data, dict) else {}

            def _authorized(self) -> bool:
                return secrets.compare_digest(self.headers.get("X-Forge-Token", ""), daemon.token)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    with daemon._stats_lock:
                        renders = daemon._renders
                        idle_s = max(0.0, time.monotonic() - daemon._last_activity)
                    self._send_json(
                        200,
                        {
                            "status": "ok",
                            "running": True,
                            "pid": os.getpid(),
                            "host": "127.0.0.1",
                            "port": daemon.port,
                            "renders": renders,
                            "idle_s": round(idle_s, 1),
                            "idle_timeout_s": daemon.idle_timeout_s,
                            "vst3_path": str(daemon.vst3_path) if daemon.vst3_path else None,
                        },
                    )
                else:
                    self._send_json(404, {"error": f"Unknown endpoint {self.path}"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    try:
                        length = min(int(self.headers.get("Content-Length", "0")), 1_048_576)
                        if length > 0:
                            self.rfile.read(length)
                    except Exception:
                        pass
                    self._send_json(403, {"error": "Forbidden: missing or invalid X-Forge-Token"})
                    return
                try:
                    payload = self._read_json()
                    if self.path == "/render":
                        self._send_json(200, daemon._submit("render", payload))
                    elif self.path == "/canary":
                        self._send_json(200, daemon._submit("canary", payload))
                    elif self.path == "/shutdown":
                        self._send_json(200, {"status": "stopping"})
                        threading.Thread(target=daemon.stop, daemon=True).start()
                    else:
                        self._send_json(404, {"error": f"Unknown endpoint {self.path}"})
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})

        return _Handler

    def _write_state_file(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": "127.0.0.1",
                    "port": self.port,
                    "token": self.token,
                    "idle_timeout_s": self.idle_timeout_s,
                    "started_at": self._started_at,
                    "vst3_path": str(self.vst3_path) if self.vst3_path else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _remove_state_file(self) -> None:
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if data.get("token") == self.token:
                    self.state_path.unlink(missing_ok=True)
        except Exception:
            self.state_path.unlink(missing_ok=True)

    def _watchdog_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            if self.idle_timeout_s <= 0:
                continue
            with self._stats_lock:
                idle_s = time.monotonic() - self._last_activity
            if idle_s >= self.idle_timeout_s:
                self.stop()
                return

    def start(self) -> None:
        """Start worker thread + HTTP server (must be called before serving)."""
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="sd3-vst3-worker")
        self._worker_thread.start()
        self._worker_ready.wait()
        if self._worker_init_error is not None:
            raise self._worker_init_error

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), self._make_handler())
        self.port = int(self._httpd.server_address[1])
        self._write_state_file()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="sd3-watchdog")
        self._watchdog_thread.start()

    def serve_forever(self) -> None:
        """Start and block serving requests until `stop()` is called."""
        self.start()
        assert self._httpd is not None
        try:
            self._httpd.serve_forever(poll_interval=0.25)
        finally:
            self._cleanup()

    def start_in_thread(self) -> None:
        """Start server in a background thread (useful for tests)."""
        self.start()
        assert self._httpd is not None
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.1},
            daemon=True,
            name="sd3-daemon-http",
        )
        self._http_thread.start()

    def _cleanup(self) -> None:
        self._stop_event.set()
        self._job_queue.put(None)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)
        self._remove_state_file()

    def stop(self) -> None:
        if self._stop_event.is_set() and self._httpd is None:
            return
        self._stop_event.set()
        httpd = self._httpd
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
            self._httpd = None
        if self._http_thread and self._http_thread.is_alive():
            self._http_thread.join(timeout=3.0)
        self._cleanup()


class DaemonClient:
    """Lightweight HTTP JSON client for talking to an active `ForgeDaemonServer`."""

    def __init__(self, host: str, port: int, token: str) -> None:
        self.base_url = f"http://{host}:{port}"
        self.token = token

    @classmethod
    def from_state_file(cls, state_path: Path | None = None) -> DaemonClient:
        resolved = state_path or daemon_state_path()
        if not resolved.exists():
            raise FileNotFoundError(f"Daemon state file not found: {resolved}")
        data = json.loads(resolved.read_text(encoding="utf-8"))
        return cls(str(data.get("host", "127.0.0.1")), int(data["port"]), str(data["token"]))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 300.0) -> dict[str, Any]:
        headers = {"X-Forge-Token": self.token}
        raw_data = None
        if payload is not None:
            raw_data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(f"{self.base_url}{path}", data=raw_data, headers=headers, method=method)
        with urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        if isinstance(out, dict) and "error" in out:
            raise RuntimeError(out["error"])
        return out

    def health(self, timeout: float = 3.0) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=timeout)

    def render(
        self,
        sd3p_path: Path,
        out_wav: Path,
        *,
        midi_path: Path | None = None,
        sample_rate: int = 44100,
        buffer_size: int = 512,
        tail_seconds: float = 4.0,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/render",
            {
                "sd3p_path": str(Path(sd3p_path).resolve()),
                "out_wav": str(Path(out_wav).resolve()),
                "midi_path": str(Path(midi_path).resolve()) if midi_path else None,
                "sample_rate": sample_rate,
                "buffer_size": buffer_size,
                "tail_seconds": tail_seconds,
            },
            timeout=600.0,
        )

    def canary(
        self,
        sd3p_path: Path,
        *,
        unload_slots: set[str] | list[str] | None = None,
        sample_rate: int = 44100,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/canary",
            {
                "sd3p_path": str(Path(sd3p_path).resolve()),
                "unload_slots": sorted(set(unload_slots or ())),
                "sample_rate": sample_rate,
            },
            timeout=60.0,
        )

    def shutdown(self) -> dict[str, Any]:
        return self._request("POST", "/shutdown", {}, timeout=10.0)


def daemon_status(state_path: Path | None = None) -> dict[str, Any]:
    """Check whether a local VST3 daemon is running and clean up stale state if dead."""
    resolved = state_path or daemon_state_path()
    if not resolved.exists():
        return {"running": False, "state_path": str(resolved)}
    try:
        client = DaemonClient.from_state_file(resolved)
        info = client.health(timeout=2.0)
        info["state_path"] = str(resolved)
        return info
    except (OSError, URLError, ValueError, KeyError, RuntimeError):
        return {"running": False, "stale_state": True, "state_path": str(resolved)}


def start_daemon_background(
    *,
    vst3_path: Path | None = None,
    idle_timeout_s: float = 900.0,
    startup_timeout_s: float = 45.0,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Spawn detached `sd3-forge.daemon serve` subprocess and wait until `/health` responds."""
    resolved_state = state_path or daemon_state_path()
    existing = daemon_status(resolved_state)
    if existing.get("running"):
        return existing

    resolved_state.unlink(missing_ok=True)
    log_path = resolved_state.parent / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "sd3_forge.daemon",
        "serve",
        "--state-path",
        str(resolved_state),
        "--idle-timeout",
        str(idle_timeout_s),
    ]
    if vst3_path is not None:
        cmd.extend(["--vst3", str(vst3_path)])

    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True

    with open(log_path, "w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **popen_kwargs,
        )

    deadline = time.monotonic() + startup_timeout_s
    while time.monotonic() < deadline:
        st = daemon_status(resolved_state)
        if st.get("running"):
            return st
        rc = proc.poll()
        if rc is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-1200:] if log_path.exists() else ""
            raise RuntimeError(f"SD3 daemon exited during startup (rc={rc}): {tail.strip()}")
        time.sleep(0.25)

    raise RuntimeError(f"Timed out after {startup_timeout_s}s waiting for SD3 daemon to initialize.")


def stop_daemon(state_path: Path | None = None) -> dict[str, Any]:
    """Stop any running VST3 daemon cleanly and remove its state file."""
    resolved = state_path or daemon_state_path()
    st = daemon_status(resolved)
    if not st.get("running"):
        resolved.unlink(missing_ok=True)
        return {"stopped": False, "was_running": False, "state_path": str(resolved)}

    client = DaemonClient.from_state_file(resolved)
    try:
        client.shutdown()
    except (OSError, URLError):
        pass

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not resolved.exists():
            break
        time.sleep(0.1)
    resolved.unlink(missing_ok=True)
    return {"stopped": True, "was_running": True, "state_path": str(resolved)}


def render_via_daemon_or_direct(
    sd3p_path: Path,
    out_wav: Path,
    *,
    midi_path: Path | None = None,
    vst3_path: Path | None = None,
    sample_rate: int = 44100,
    tail_seconds: float = 4.0,
    use_daemon: bool = True,
    state_path: Path | None = None,
    plugin: Any | None = None,
) -> dict[str, Any]:
    """Render `.sd3p` via active daemon if running (`use_daemon=True`), else load VST3 directly."""
    resolved_state = state_path or daemon_state_path()
    if use_daemon and plugin is None:
        st = daemon_status(resolved_state)
        if st.get("running"):
            try:
                client = DaemonClient.from_state_file(resolved_state)
                return client.render(
                    sd3p_path,
                    out_wav,
                    midi_path=midi_path,
                    sample_rate=sample_rate,
                    tail_seconds=tail_seconds,
                )
            except (OSError, URLError, http.client.HTTPException):
                resolved_state.unlink(missing_ok=True)

    info = render_sd3p_to_wav(
        sd3p_path,
        out_wav,
        midi_path=midi_path,
        vst3_path=vst3_path,
        sample_rate=sample_rate,
        tail_seconds=tail_seconds,
        plugin=plugin,
    )
    info["via_daemon"] = False
    return info


def run_canary_via_daemon_or_direct(
    sd3p_path: Path,
    *,
    unload_slots: set[str] | list[str] | None = None,
    vst3_path: Path | None = None,
    sample_rate: int = 44100,
    use_daemon: bool = True,
    state_path: Path | None = None,
    plugin: Any | None = None,
) -> dict[str, Any]:
    """Run multi-slot pre-flight canary via daemon if active, or direct VST3 load."""
    resolved_state = state_path or daemon_state_path()
    if use_daemon and plugin is None:
        st = daemon_status(resolved_state)
        if st.get("running"):
            try:
                client = DaemonClient.from_state_file(resolved_state)
                return client.canary(sd3p_path, unload_slots=unload_slots, sample_rate=sample_rate)
            except (OSError, URLError, http.client.HTTPException):
                resolved_state.unlink(missing_ok=True)

    plug = plugin or _default_plugin_factory(vst3_path)
    template_xml, template_blob = unwrap_vc2_state(plug.raw_state)
    plug.raw_state = wrap_vc2_state(template_xml, template_blob, Path(sd3p_path).read_bytes())
    messages, schedule, dur = build_canary_midi(unload_slots)
    audio = plug(messages, duration=dur, sample_rate=sample_rate, buffer_size=512, reset=True)
    res = evaluate_canary_audio(audio, sample_rate, schedule)
    res["via_daemon"] = False
    return res


def _main_serve(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sd3_forge.daemon")
    sub = parser.add_subparsers(dest="action", required=True)
    p_srv = sub.add_parser("serve")
    p_srv.add_argument("--vst3", type=Path, default=None)
    p_srv.add_argument("--state-path", type=Path, default=None)
    p_srv.add_argument("--port", type=int, default=0)
    p_srv.add_argument("--idle-timeout", type=float, default=900.0)
    p_srv.add_argument("--max-state-reloads", type=int, default=4)
    args = parser.parse_args(argv)

    server = ForgeDaemonServer(
        vst3_path=args.vst3,
        state_path=args.state_path,
        port=args.port,
        idle_timeout_s=args.idle_timeout,
        max_state_reloads=args.max_state_reloads,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_serve())
