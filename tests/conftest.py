from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "md-img-local.py"


@pytest.fixture(scope="session")
def script() -> ModuleType:
    """Загружает md-img-local.py как модуль (в имени файла дефисы)."""
    spec = importlib.util.spec_from_file_location("md_img_local", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["md_img_local"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_main(script: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Запускает main() с заданными аргументами командной строки."""

    def run(*argv: str) -> None:
        monkeypatch.setattr(sys, "argv", ["md-img-local.py", *map(str, argv)])
        script.main()

    return run
