from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from helpers import URL, FakeResponse, FakeSession

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


@pytest.fixture(autouse=True)
def default_language(script: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Фиксирует английский язык, чтобы тесты не зависели от локали машины."""
    monkeypatch.setenv("MD_IMG_LOCAL_LANG", "en")
    script.set_language("en")
    yield
    script.set_language("en")


@pytest.fixture
def fake_session(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Подменяет сессию; запоминает, какой прокси передан в build_session()."""
    fake = FakeSession({URL: FakeResponse()})

    def build_session(proxy: str | None) -> FakeSession:
        fake.proxies.append(proxy)
        return fake

    monkeypatch.setattr(script, "build_session", build_session)
    return fake


@pytest.fixture
def run_main(script: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Запускает main() с заданными аргументами командной строки."""

    def run(*argv: str) -> None:
        monkeypatch.setattr(sys, "argv", ["md-img-local.py", *map(str, argv)])
        script.main()

    return run
