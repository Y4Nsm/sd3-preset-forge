"""Shared pytest fixtures ensuring CI tests run with zero proprietary local assets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sd3_forge.extract_gt import build_inventory
from sd3_forge.init_workspace import build_neutral_base_sd3p

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MOCK_LIB_DIR = FIXTURES_DIR / "mock_sd3_library"


@pytest.fixture(scope="session")
def mock_library_dir() -> Path:
    return MOCK_LIB_DIR


@pytest.fixture(scope="session")
def mock_inventory_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("gt")
    inv = build_inventory(MOCK_LIB_DIR)
    p = tmp / "inventory.json"
    p.write_text(json.dumps(inv, indent=2), encoding="utf-8")
    return p


@pytest.fixture(scope="session")
def synthetic_base_sd3p_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("tpl")
    p = tmp / "synthetic-neutral.sd3p"
    p.write_bytes(build_neutral_base_sd3p(MOCK_LIB_DIR, from_vst3=False))
    return p
