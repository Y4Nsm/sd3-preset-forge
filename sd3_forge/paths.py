"""Cross-platform path resolution, user config persistence, and package resource loaders."""

from __future__ import annotations

import json
import os
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "sd3-preset-forge"


def forge_config_dir() -> Path:
    """Return user config directory (respecting optional SD3_FORGE_HOME override)."""
    env_home = os.environ.get("SD3_FORGE_HOME")
    if env_home:
        return Path(env_home) / "config"
    return Path(user_config_dir(APP_NAME, appauthor=False))


def forge_data_dir() -> Path:
    """Return user data directory (respecting optional SD3_FORGE_HOME override)."""
    env_home = os.environ.get("SD3_FORGE_HOME")
    if env_home:
        return Path(env_home) / "data"
    return Path(user_data_dir(APP_NAME, appauthor=False))


def config_file_path() -> Path:
    return forge_config_dir() / "config.json"


def load_config() -> dict[str, Any]:
    cfg_path = config_file_path()
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


def save_config(cfg: dict[str, Any]) -> Path:
    cfg_path = config_file_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg_path


def _win32_documents_dir() -> Path:
    """Resolve Windows Documents folder via KnownFolder API (handles OneDrive redirection)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            # FOLDERID_Documents: {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            docs_guid = _GUID(
                0xFDD39AD0,
                0x238F,
                0x46AF,
                (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
            )
            p_path = ctypes.c_wchar_p()
            hr = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(docs_guid), 0, None, ctypes.byref(p_path)
            )
            if hr == 0 and p_path.value:
                res = Path(p_path.value)
                ctypes.windll.ole32.CoTaskMemFree(p_path)
                return res
        except Exception:
            pass
    return Path.home() / "Documents"


def detect_sd3_vst3_path(platform: str | None = None) -> Path | None:
    """Auto-detect Superior Drummer 3.vst3 across Windows and macOS."""
    env_val = os.environ.get("SD3_VST3_PATH")
    if env_val:
        return Path(env_val)
    cfg_val = load_config().get("sd3_vst3_path")
    if cfg_val:
        return Path(cfg_val)

    plat = platform or sys.platform
    candidates: list[Path] = []
    if plat == "win32":
        prog = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        prog_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        candidates.extend(
            [
                prog / "Common Files" / "VST3" / "Toontrack" / "Superior Drummer 3.vst3",
                prog / "Common Files" / "VST3" / "Superior Drummer 3.vst3",
                prog_x86 / "Common Files" / "VST3" / "Toontrack" / "Superior Drummer 3.vst3",
            ]
        )
    elif plat == "darwin":
        candidates.extend(
            [
                Path("/Library/Audio/Plug-Ins/VST3/Superior Drummer 3.vst3"),
                Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3" / "Superior Drummer 3.vst3",
            ]
        )
    else:
        candidates.extend(
            [
                Path.home() / ".vst3" / "Superior Drummer 3.vst3",
                Path("/usr/local/lib/vst3/Superior Drummer 3.vst3"),
            ]
        )

    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0] if candidates else None


def detect_sd3_library_path(platform: str | None = None) -> Path | None:
    """Auto-detect local SD3 Core Library (`SL-SuperiorDrummer3`) installation."""
    env_val = os.environ.get("SD3_LIBRARY_PATH")
    if env_val:
        return Path(env_val)
    cfg_val = load_config().get("sd3_library_path")
    if cfg_val:
        return Path(cfg_val)

    plat = platform or sys.platform
    candidates: list[Path] = []
    if plat == "win32":
        prog_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        public_docs = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Documents"
        candidates.extend(
            [
                prog_data / "Toontrack" / "Superior Drummer 3" / "SL-SuperiorDrummer3",
                public_docs / "Toontrack" / "Superior Drummer 3" / "SL-SuperiorDrummer3",
                Path(r"C:\Toontrack\SL-SuperiorDrummer3"),
            ]
        )
    elif plat == "darwin":
        candidates.extend(
            [
                Path("/Library/Application Support/Toontrack/SL-SuperiorDrummer3"),
                Path("/Library/Application Support/Toontrack/Superior Drummer 3/SL-SuperiorDrummer3"),
                Path.home() / "Library" / "Application Support" / "Toontrack" / "SL-SuperiorDrummer3",
            ]
        )

    for cand in candidates:
        if cand.exists():
            return cand
    return None


def detect_user_presets_dir(platform: str | None = None) -> Path:
    """Resolve user Superior Drummer 3 `.sd3p` presets folder across Windows/macOS."""
    env_val = os.environ.get("SD3_PRESETS_DIR")
    if env_val:
        return Path(env_val)
    cfg_val = load_config().get("sd3_presets_dir")
    if cfg_val:
        return Path(cfg_val)

    plat = platform or sys.platform
    if plat == "win32":
        docs = _win32_documents_dir()
    else:
        docs = Path.home() / "Documents"
    return docs / "Toontrack" / "Superior Drummer 3"


def default_inventory_path() -> Path:
    """Return path to local `inventory.json` (data dir first, then repo fallback)."""
    data_inv = forge_data_dir() / "inventory.json"
    if data_inv.exists():
        return data_inv
    repo_inv = Path("docs/sd3-ground-truth/inventory.json")
    if repo_inv.exists():
        return repo_inv
    return data_inv


def default_base_template_path() -> Path:
    """Return path to clean local `base-neutral.sd3p` in user data dir."""
    return forge_data_dir() / "base-neutral.sd3p"


def daemon_state_path() -> Path:
    """Return path to runtime JSON state file for the persistent VST3 daemon."""
    return forge_data_dir() / "daemon.json"


def default_test_suite_dir() -> Path:
    """Return directory containing `standard-test-groove.mid` and `midi-manifest.json`."""
    data_suite = forge_data_dir() / "test-suite"
    if (data_suite / "midi-manifest.json").exists():
        return data_suite
    repo_suite = Path("test-suite")
    if (repo_suite / "midi-manifest.json").exists():
        return repo_suite
    return data_suite


def default_midi_path() -> Path:
    return default_test_suite_dir() / "standard-test-groove.mid"


def default_manifest_path() -> Path:
    return default_test_suite_dir() / "midi-manifest.json"


def load_package_json(rel_path: str) -> Any:
    """Load a bundled JSON asset (`schemas/blueprint.schema.json`, etc.) via importlib.resources."""
    res = resources.files("sd3_forge").joinpath(rel_path)
    return json.loads(res.read_text(encoding="utf-8"))


def load_package_text(rel_path: str) -> str:
    """Load a bundled text/YAML asset (`data/fx-ui-calibration.yaml`) via importlib.resources."""
    res = resources.files("sd3_forge").joinpath(rel_path)
    return res.read_text(encoding="utf-8")
