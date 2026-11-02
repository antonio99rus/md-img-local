"""Единая точка импорта TOML-парсера для тестов.

В Python 3.11+ используется стандартный ``tomllib``; на Python 3.10 —
обратно совместимый ``tomli`` из dev-зависимостей.
"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - выполняется только на Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = ["tomllib"]
