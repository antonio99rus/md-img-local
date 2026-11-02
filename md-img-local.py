from __future__ import annotations

import argparse
import codecs
import hashlib
import ipaddress
import json
import locale
import os
import re
import shutil
import socket
import ssl
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit, unquote

import requests

import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INLINE_IMAGE_RE = re.compile(
    r'!\[([^\]]*)\]\(\s*(?:<([^>]+)>|(\S+?))'
    r'(?:\s+("(?:[^"\\]|\\.)*"|\'[^\']*\'))?\s*\)'
)
REF_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\[([^\]]*)\]')
HTML_IMG_RE = re.compile(
    r"(<img\b[^>]*?\bsrc\s*=\s*)"
    r"(?:([\"'])(.*?)\2|([^\s\"'>]+))"
    r"([^>]*>)",
    re.IGNORECASE | re.DOTALL,
)
HTML_SRCSET_RE = re.compile(
    r"(<(?:img|source)\b[^>]*?\bsrcset\s*=\s*)"
    r"(?:([\"'])(.*?)\2|([^\s\"'>]+))"
    r"([^>]*>)",
    re.IGNORECASE | re.DOTALL,
)
REF_DEF_RE = re.compile(
    r"^[ \t]*\[([^\]]+)\]:[ \t]*(?:<([^>]+)>|([^\s]+))"
    r"(?:[ \t]+(\"(?:[^\"\\]|\\.)*\"|'[^']*'|\([^)]*\)))?"
    r"[ \t]*\r?\n?",
    re.MULTILINE,
)

FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
ESCAPED_BANG_RE = re.compile(r"(?<!\\)(?:\\\\)*\\!")

BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

VERSION = "1.2.0"

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024
MAX_REDIRECTS = 5
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
REQUEST_TIMEOUT = (10, 30)
MAX_RETRIES = 2
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# SVG намеренно отсутствует: это активный контент, опасный при публикации media.
IMAGE_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/avif": ".avif",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

DEFAULT_PORTS = {"http": 80, "https": 443}
FILENAME_STEM_LIMIT = 80
URL_HASH_LENGTH = 16
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)

SENSITIVE_QUERY_MARKERS = (
    "token",
    "key",
    "secret",
    "signature",
    "sig",
    "password",
    "passwd",
    "auth",
    "expires",
    "session",
    "credential",
    "x-amz-",
)
LOG_URL_LIMIT = 200

# UA = "markdown-image-downloader/1.0"
USER_AGENT = f"md-img-local/{VERSION}"

PROXY_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")

DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "ru")

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "description": (
            "Download images referenced from a Markdown file into media/ "
            "and rewrite links to local paths"
        ),
        "help_markdown": "Source Markdown file",
        "help_media": (
            "Directory for images; defaults to media/ next to the Markdown file"
        ),
        "help_allow_private": (
            "Allow downloads from private, loopback and link-local addresses "
            "(disabled by default to prevent SSRF)"
        ),
        "help_no_backup": "Do not create a file.md.orig backup",
        "help_force": (
            "Overwrite an existing file.md.orig instead of rotating it"
        ),
        "help_write_mode": (
            "How to write the result: in-place keeps the file inode and "
            "hardlinks, atomic replaces the file via a temporary file "
            "(default: in-place)"
        ),
        "no_backup_requires_force": (
            "--no-backup with in-place writes requires --force: without a "
            "backup an interrupted write cannot be recovered"
        ),
        "help_proxy": (
            "Proxy to download through: http, https, socks4, socks4a, socks5, "
            "socks5h (port required), e.g. socks5://127.0.0.1:3066. "
            "When set, HTTP_PROXY, HTTPS_PROXY and NO_PROXY are ignored"
        ),
        "help_user_agent": (
            "User-Agent header for downloads "
            "(default: program name and version)"
        ),
        "help_lang": "Language of messages and help: en or ru (default: system locale)",
        "help_version": "show program's version number and exit",
        "help_flag": "show this help message and exit",
        "usage_prefix": "usage: ",
        "positional_title": "positional arguments",
        "options_title": "options",
        "error_prefix": "error",
        "arg_required": "the following arguments are required: {names}",
        "arg_unrecognized": "unrecognized arguments: {names}",
        "arg_invalid_choice": (
            "argument {argument}: invalid choice: {value} "
            "(choose from {choices})"
        ),
        "arg_expected_one": "argument {argument}: expected one argument",
        "file_not_found": "file not found: {path}",
        "read_error": "cannot read {path}: {error}",
        "media_not_directory": "media path is not a directory: {path}",
        "unexpected_error": "cannot complete: {error}",
        "encoding_error": (
            "cannot decode {path} as UTF-8/UTF-16/UTF-32: {error}"
        ),
        "proxy_spaces": "proxy URL must not contain spaces",
        "proxy_unsupported": (
            "unsupported proxy URL {value!r}: expected scheme {schemes}, "
            "e.g. socks5://127.0.0.1:3066"
        ),
        "proxy_invalid": "invalid proxy URL: {error}",
        "proxy_no_host": "proxy URL has no host",
        "proxy_no_port": "proxy URL has no port, e.g. socks5://127.0.0.1:3066",
        "proxy_only_scheme_host_port": (
            "proxy URL may only contain scheme, host and port"
        ),
        "socks_missing": (
            'SOCKS proxies require PySocks: install dependencies with "uv sync" '
            "or \"pip install 'requests[socks]'\""
        ),
        "proxy_banner": "[PROXY] {proxy}",
        "backup": "[BACKUP] {source} -> {backup}",
        "backup_rotated": "[BACKUP] rotated {backup} -> {path}",
        "no_backup_label": "no backup",
        "journal_found": (
            "interrupted write detected: {journal}; previous version: {backup}. "
            "Check the file or pass --force to discard the journal"
        ),
        "write_locked": (
            "cannot lock {path}: {error}. Is another copy of this program running?"
        ),
        "write_conflict": (
            "file changed while preparing the write: {path}; nothing was written"
        ),
        "write_verify_failed": (
            "verification failed for {path}; restored from {backup}"
        ),
        "write_no_recovery": (
            "write to {path} failed and no backup is available to restore it"
        ),
        "downloaded_file": "[OK] {url} -> {path}",
        "download_failed": "[ERROR] Failed to download {url}: {error}{hint}",
        "save_failed": "[ERROR] Failed to save {url}: {error}",
        "proxy_hint": " (proxy {proxy} unreachable?)",
        "download_too_large": "download too large (limit {limit} bytes)",
        "download_wrong_type": (
            "content type {content_type!r} is not an allowed image type"
        ),
        "content_type_missing": "missing or empty Content-Type",
        "url_scheme_blocked": (
            "unsupported URL scheme {scheme!r}: only http and https are allowed"
        ),
        "url_no_host": "URL has no host",
        "url_resolve_failed": "cannot resolve {host}: {error}",
        "url_private_blocked": (
            "refusing to download from {host} ({address}): private or "
            "non-public address; pass --allow-private to override"
        ),
        "redirect_no_location": "redirect response has no Location header",
        "redirect_too_many": "too many redirects (limit {limit})",
        "result": "\nResult: {path}",
        "found": "Unique images found: {count}",
        "downloaded": "Downloaded: {count}",
        "failed": "Errors: {count}",
    },
    "ru": {
        "description": (
            "Скачивает изображения из Markdown-файла в media/ "
            "и заменяет ссылки на локальные"
        ),
        "help_markdown": "Исходный Markdown-файл",
        "help_media": (
            "Каталог для изображений; по умолчанию media рядом с Markdown-файлом"
        ),
        "help_allow_private": (
            "Разрешить скачивание с приватных, loopback- и link-local адресов "
            "(по умолчанию запрещено для защиты от SSRF)"
        ),
        "help_no_backup": "Не создавать резервную копию файла.md.orig",
        "help_force": (
            "Перезаписывать существующий файл.md.orig вместо ротации"
        ),
        "help_write_mode": (
            "Способ записи результата: in-place сохраняет inode и hardlinks, "
            "atomic заменяет файл через временный "
            "(по умолчанию — in-place)"
        ),
        "no_backup_requires_force": (
            "--no-backup при записи in-place требует --force: без резервной "
            "копии прерванную запись не из чего восстановить"
        ),
        "help_proxy": (
            "Прокси для скачивания: http, https, socks4, socks4a, socks5, socks5h "
            "(порт обязателен), например socks5://127.0.0.1:3066. "
            "При указании прокси переменные HTTP_PROXY, HTTPS_PROXY и NO_PROXY игнорируются"
        ),
        "help_user_agent": (
            "Заголовок User-Agent для скачивания "
            "(по умолчанию — имя и версия программы)"
        ),
        "help_lang": (
            "Язык сообщений и справки: en или ru (по умолчанию — локаль системы)"
        ),
        "help_version": "показать версию программы и выйти",
        "help_flag": "показать эту справку и выйти",
        "usage_prefix": "использование: ",
        "positional_title": "позиционные аргументы",
        "options_title": "параметры",
        "error_prefix": "ошибка",
        "arg_required": "требуются следующие аргументы: {names}",
        "arg_unrecognized": "нераспознанные аргументы: {names}",
        "arg_invalid_choice": (
            "аргумент {argument}: недопустимое значение {value} "
            "(допустимо: {choices})"
        ),
        "arg_expected_one": "аргумент {argument}: требуется одно значение",
        "file_not_found": "файл не найден: {path}",
        "read_error": "не удалось прочитать {path}: {error}",
        "media_not_directory": "путь media не является каталогом: {path}",
        "unexpected_error": "не удалось выполнить: {error}",
        "encoding_error": (
            "не удалось декодировать {path} как UTF-8/UTF-16/UTF-32: {error}"
        ),
        "proxy_spaces": "адрес прокси не должен содержать пробелов",
        "proxy_unsupported": (
            "неподдерживаемый адрес прокси {value!r}: ожидается схема {schemes}, "
            "например socks5://127.0.0.1:3066"
        ),
        "proxy_invalid": "некорректный адрес прокси: {error}",
        "proxy_no_host": "в адресе прокси не указан хост",
        "proxy_no_port": (
            "в адресе прокси не указан порт, например socks5://127.0.0.1:3066"
        ),
        "proxy_only_scheme_host_port": (
            "в адресе прокси допустимы только схема, хост и порт"
        ),
        "socks_missing": (
            "для socks-прокси нужен PySocks: установите зависимости "
            "командой \"uv sync\" или \"pip install 'requests[socks]'\""
        ),
        "proxy_banner": "[PROXY] {proxy}",
        "backup": "[BACKUP] {source} -> {backup}",
        "backup_rotated": "[BACKUP] прежняя копия {backup} -> {path}",
        "no_backup_label": "бэкапа нет",
        "journal_found": (
            "обнаружена незавершённая запись: {journal}; прежняя версия: "
            "{backup}. Проверьте файл или укажите --force, чтобы отбросить журнал"
        ),
        "write_locked": (
            "не удалось заблокировать {path}: {error}. "
            "Возможно, уже запущена другая копия программы"
        ),
        "write_conflict": (
            "файл изменился во время подготовки записи: {path}; "
            "ничего не записано"
        ),
        "write_verify_failed": (
            "проверка записи не удалась для {path}; восстановлено из {backup}"
        ),
        "write_no_recovery": (
            "запись в {path} не удалась, а резервной копии для восстановления нет"
        ),
        "downloaded_file": "[OK] {url} -> {path}",
        "download_failed": "[ERROR] Не удалось скачать {url}: {error}{hint}",
        "save_failed": "[ERROR] Не удалось сохранить {url}: {error}",
        "proxy_hint": " (прокси {proxy} недоступен?)",
        "download_too_large": "файл слишком большой (лимит {limit} байт)",
        "download_wrong_type": (
            "тип содержимого {content_type!r} не входит в список "
            "разрешённых изображений"
        ),
        "content_type_missing": "отсутствует или пуст Content-Type",
        "url_scheme_blocked": (
            "неподдерживаемая схема URL {scheme!r}: разрешены только http и https"
        ),
        "url_no_host": "в URL не указан хост",
        "url_resolve_failed": "не удалось разрешить {host}: {error}",
        "url_private_blocked": (
            "скачивание с {host} ({address}) запрещено: приватный или "
            "непубличный адрес; используйте --allow-private, чтобы обойти запрет"
        ),
        "redirect_no_location": "в ответе-редиректе нет заголовка Location",
        "redirect_too_many": "слишком много редиректов (лимит {limit})",
        "result": "\nРезультат: {path}",
        "found": "Найдено уникальных изображений: {count}",
        "downloaded": "Скачано: {count}",
        "failed": "Ошибок: {count}",
    },
}

_language: ContextVar[str] = ContextVar(
    "md_img_local_language", default=DEFAULT_LANGUAGE
)


def normalize_language(value: str | None) -> str | None:
    """Приводит имя локали к коду поддерживаемого языка (en/ru)."""
    if not value:
        return None
    for part in value.lower().replace("-", "_").split(":"):
        primary = part.split(".")[0].split("@")[0].split("_")[0].strip()
        if primary in ("ru", "russian"):
            return "ru"
        if primary in ("en", "english"):
            return "en"
    return None


def _language_from_language_id(language_id: int) -> str | None:
    """Преобразует Windows LANGID в код поддерживаемого языка."""
    primary = language_id & 0x3FF
    if primary == 0x19:  # LANG_RUSSIAN
        return "ru"
    if primary == 0x09:  # LANG_ENGLISH
        return "en"
    return None


def _windows_ui_language() -> str | None:  # pragma: no cover - зависит от ОС
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return None
    return _language_from_language_id(language_id)


def detect_language(
    override: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Определяет язык вывода: --lang, переменные окружения, локаль ОС."""
    environ = os.environ if env is None else env
    if override:
        normalized = normalize_language(override)
        if normalized:
            return normalized

    custom = environ.get("MD_IMG_LOCAL_LANG")
    if custom:
        normalized = normalize_language(custom)
        if normalized:
            return normalized

    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = environ.get(name)
        if value:
            return normalize_language(value) or DEFAULT_LANGUAGE

    try:
        locale_name = locale.getlocale()[0]
    except (TypeError, ValueError):
        locale_name = None
    normalized = normalize_language(locale_name)
    if normalized:
        return normalized

    return _windows_ui_language() or DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language: {code}")
    _language.set(code)


def current_language() -> str:
    return _language.get()


def tr(key: str, **kwargs: object) -> str:
    """Возвращает сообщение на текущем языке с откатом на английский."""
    template = MESSAGES.get(current_language(), {}).get(key) or MESSAGES[
        DEFAULT_LANGUAGE
    ].get(key)
    if template is None:
        return key
    return template.format(**kwargs)


LONG_OPTIONS = (
    "--help",
    "--media",
    "--no-backup",
    "--force",
    "--write-mode",
    "--allow-private",
    "--proxy",
    "--lang",
    "--version",
    "--user-agent",
)


def _is_lang_option(argument: str) -> bool:
    """Проверяет --lang с учётом однозначных сокращений, как у argparse."""
    if not argument.startswith("--") or argument == "--":
        return False
    name = argument.split("=", 1)[0]
    matches = [option for option in LONG_OPTIONS if option.startswith(name)]
    return matches == ["--lang"]


def language_from_argv(argv: Sequence[str]) -> str | None:
    """Достаёт --lang до полного разбора, чтобы локализовать саму справку."""
    value: str | None = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            break
        if not _is_lang_option(argument):
            index += 1
            continue
        _, separator, inline = argument.partition("=")
        if separator:
            value = inline
            index += 1
            continue
        if index + 1 >= len(argv):
            break
        candidate = argv[index + 1]
        if candidate.startswith("-") and candidate != "-":
            # Значение съедено другим флагом: argparse сообщит об ошибке.
            index += 1
            continue
        value = candidate
        index += 2
    return value


def localize_argparse_message(message: str) -> str:
    """Переводит типовые ошибки argparse; остальное оставляет как есть."""
    match = re.fullmatch(r"the following arguments are required: (.+)", message)
    if match:
        return tr("arg_required", names=match.group(1))
    match = re.fullmatch(r"unrecognized arguments: (.+)", message)
    if match:
        return tr("arg_unrecognized", names=match.group(1))
    match = re.fullmatch(
        r"argument (.+?): invalid choice: (.+?) \(choose from (.+)\)", message
    )
    if match:
        return tr(
            "arg_invalid_choice",
            argument=match.group(1),
            value=match.group(2),
            choices=match.group(3),
        )
    match = re.fullmatch(r"argument (.+?): expected one argument", message)
    if match:
        return tr("arg_expected_one", argument=match.group(1))
    return message


class LocalizedHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = tr("usage_prefix")
        return super().add_usage(usage, actions, groups, prefix=prefix)

    def start_section(self, heading):
        titles = {
            "positional arguments": tr("positional_title"),
            "options": tr("options_title"),
        }
        return super().start_section(titles.get(heading, heading))


class LocalizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        translated = localize_argparse_message(message)
        self.exit(
            2, f"{self.prog}: {tr('error_prefix')}: {translated}\n"
        )


class ProxyConfigError(ValueError):
    """Некорректный или неподдерживаемый адрес прокси."""


def parse_proxy(raw: str | None) -> str | None:
    """Проверяет адрес прокси из командной строки и нормализует схему."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if any(char.isspace() for char in value):
        raise ProxyConfigError(tr("proxy_spaces"))

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in PROXY_SCHEMES:
        raise ProxyConfigError(
            tr(
                "proxy_unsupported",
                value=mask_url(value),
                schemes=", ".join(PROXY_SCHEMES),
            )
        )
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ProxyConfigError(tr("proxy_invalid", error=error)) from error
    if not host:
        raise ProxyConfigError(tr("proxy_no_host"))
    if port is None:
        raise ProxyConfigError(tr("proxy_no_port"))
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ProxyConfigError(tr("proxy_only_scheme_host_port"))

    return f"{scheme}://{parsed.netloc}"


def mask_proxy(proxy: str) -> str:
    """Скрывает пароль прокси, чтобы он не попадал в вывод."""
    parsed = urlsplit(proxy)
    if parsed.username is None and parsed.password is None:
        return proxy
    auth = parsed.username or ""
    if parsed.password is not None:
        auth = f"{auth}:***" if auth else ":***"
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{auth}@{host}"


def ensure_socks_support(proxy: str) -> None:
    """SOCKS-прокси в requests работает только с установленным PySocks."""
    if not urlsplit(proxy).scheme.startswith("socks"):
        return
    try:
        import socks  # noqa: F401
    except ImportError as error:
        raise ProxyConfigError(tr("socks_missing")) from error


def build_session(
    proxy: str | None, user_agent: str = USER_AGENT
) -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = sanitize_text(user_agent) or USER_AGENT
    session.verify = True
    session.max_redirects = MAX_REDIRECTS
    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        status=MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if proxy:
        # Явно указанный прокси должен главенствовать над HTTP_PROXY/HTTPS_PROXY/NO_PROXY.
        session.trust_env = False
        session.proxies.update({"http": proxy, "https": proxy})
    return session


class DownloadRejected(Exception):
    """Загрузка отклонена: размер, тип или отсутствие Content-Type."""


class UrlBlocked(DownloadRejected):
    """URL отклонён политикой безопасности (SSRF, схема, редиректы)."""


def content_type_of(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";")[0].strip().lower()


def read_limited(response: requests.Response, limit: int) -> bytes:
    """Читает тело потоком, не позволяя превысить limit байт."""
    length = response.headers.get("Content-Length")
    if length:
        try:
            declared = int(length)
        except ValueError:
            declared = None
        if declared is not None and declared > limit:
            raise DownloadRejected(tr("download_too_large", limit=limit))

    buffer = bytearray()
    for chunk in response.iter_content(DOWNLOAD_CHUNK_SIZE):
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise DownloadRejected(tr("download_too_large", limit=limit))
    return bytes(buffer)


def store_download(media_dir: Path, destination: Path, data: bytes) -> None:
    """Пишет через уникальный temp и os.replace, не следуя симлинкам."""
    media_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".md-img-local-",
        suffix=".part",
        dir=media_dir,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def extension_for_content_type(content_type: str) -> str:
    """Расширение по фиксированной таблице, без зависимости от ОС."""
    return IMAGE_CONTENT_TYPES.get(content_type.lower(), ".bin")


def canonical_url(url: str) -> str:
    """Убирает fragment и нормализует схему, хост и порт по умолчанию.

    Protocol-relative URL (``//host/path``) трактуется как HTTPS.
    """
    if url.startswith("//"):
        url = f"https:{url}"
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return url
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if not host:
        return url
    if port is not None and DEFAULT_PORTS.get(scheme) == port:
        port = None
    netloc = f"[{host}]" if ":" in host else host
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        netloc = f"{userinfo}@{netloc}"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))


def sanitize_text(value: str) -> str:
    """Заменяет управляющие символы, чтобы они не ломали вывод в терминале."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", value)


def mask_url(url: str) -> str:
    """Скрывает учётные данные и чувствительные query-параметры для логов."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return sanitize_text(url)[:LOG_URL_LIMIT]
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if port is not None:
        host = f"{host}:{port}"
    if parsed.username is not None or parsed.password is not None:
        host = f"***@{host}"
    query = parsed.query
    if query:
        parts = []
        for part in query.split("&"):
            name = part.partition("=")[0]
            lowered = name.lower()
            if any(marker in lowered for marker in SENSITIVE_QUERY_MARKERS):
                parts.append(f"{name}=***")
            else:
                parts.append(part)
        query = "&".join(parts)
    masked = sanitize_text(
        urlunsplit((parsed.scheme, host, parsed.path, query, ""))
    )
    if len(masked) > LOG_URL_LIMIT:
        masked = masked[: LOG_URL_LIMIT - 1] + "…"
    return masked


def safe_error(error: BaseException, url: str) -> str:
    """Убирает из текста ошибки исходный URL с возможными секретами."""
    text = sanitize_text(str(error))
    masked = mask_url(url)
    for candidate in (canonical_url(url), url):
        if candidate:
            text = text.replace(candidate, masked)
    return text


def resolve_host_ips(host: str) -> list[str]:
    """Резолвит хост через системный DNS и возвращает уникальные адреса."""
    addresses: list[str] = []
    for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


def is_blocked_address(address: str) -> bool:
    """True для всех адресов, кроме публичных глобально маршрутизируемых."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        parsed = mapped
    return (
        not parsed.is_global
        or parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def ensure_url_allowed(url: str, allow_private: bool = False) -> None:
    """Не даёт скачивать с приватных адресов, если это не разрешено явно."""
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise UrlBlocked(str(error)) from error
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlBlocked(tr("url_scheme_blocked", scheme=scheme))
    host = parsed.hostname
    if not host:
        raise UrlBlocked(tr("url_no_host"))
    if allow_private:
        return
    try:
        addresses = resolve_host_ips(host)
    except OSError as error:
        raise UrlBlocked(
            tr("url_resolve_failed", host=host, error=error)
        ) from error
    if not addresses:
        raise UrlBlocked(
            tr("url_resolve_failed", host=host, error=tr("url_no_host"))
        )
    for address in addresses:
        if is_blocked_address(address):
            raise UrlBlocked(
                tr("url_private_blocked", host=host, address=address)
            )


def filename_for_url(url: str, extension: str) -> str:
    canonical = canonical_url(url)
    parsed = urlparse(canonical)
    original_name = Path(unquote(parsed.path)).stem
    original_name = re.sub(r"[^\w-]+", "_", original_name)
    original_name = original_name.strip("._-") or "image"
    original_name = original_name[:FILENAME_STEM_LIMIT]
    if original_name.lower() in WINDOWS_RESERVED_NAMES:
        original_name = f"{original_name}_"
    url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[
        :URL_HASH_LENGTH
    ]
    return f"{original_name}-{url_hash}{extension}"


def relative_path_for_markdown(destination: Path, base_dir: Path) -> str:
    """Возвращает posix-путь относительно base_dir, безопасный для Markdown/HTML."""
    relative = Path(os.path.relpath(destination, base_dir)).as_posix()
    return quote(relative, safe="/")


def decode_markdown(data: bytes) -> tuple[str, str, bytes]:
    """Декодирует файл, сохраняя исходный BOM и переводы строк."""
    for bom, encoding in BOM_ENCODINGS:
        if data.startswith(bom):
            return data[len(bom):].decode(encoding), encoding, bom
    return data.decode("utf-8"), "utf-8", b""


def encode_markdown(text: str, encoding: str, bom: bytes) -> bytes:
    """Кодирует текст обратно в исходной кодировке с тем же BOM."""
    return bom + text.encode(encoding)


def make_backup(
    source_path: Path, force: bool = False
) -> tuple[Path, Path | None]:
    """Делает независимую копию файла в .orig, ротируя прежнюю.

    Возвращает путь копии и путь, куда была перемещена предыдущая копия.
    """
    backup_path = source_path.with_name(f"{source_path.name}.orig")
    rotated_path: Path | None = None
    if backup_path.exists():
        if force:
            backup_path.unlink()
        else:
            index = 1
            while True:
                candidate = source_path.with_name(
                    f"{source_path.name}.orig.{index}"
                )
                if not candidate.exists():
                    break
                index += 1
            os.replace(backup_path, candidate)
            rotated_path = candidate
    shutil.copy2(source_path, backup_path)
    return backup_path, rotated_path


class WriteError(Exception):
    """Ошибка безопасной записи, которую нужно показать без трейсбека."""


_WINDOWS_LOCK_OFFSET = 0x40000000


def write_markdown(
    source_path: Path,
    data: bytes,
    mode: str,
    *,
    force: bool = False,
    backup_path: Path | None = None,
) -> None:
    """Пишет результат в файл выбранным способом."""
    if mode == "atomic":
        _write_atomic(source_path, data)
    else:
        _write_in_place(
            source_path,
            data,
            force=force,
            backup_path=backup_path,
        )


def _write_atomic(source_path: Path, data: bytes) -> None:
    """Пишет во временный файл рядом и атомарно подменяет исходник."""
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{source_path.name}.",
        suffix=".tmp",
        dir=source_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(source_path, temp_path)
        os.replace(temp_path, source_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _sidecar_path(source_path: Path, kind: str) -> Path:
    return source_path.with_name(f".{source_path.name}.md-img-{kind}")


def _backup_label(backup_path: Path | None) -> str:
    return backup_path.name if backup_path else tr("no_backup_label")


def _file_snapshot(descriptor: int) -> tuple[int, int, int, int]:
    info = os.fstat(descriptor)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view):]


def _read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_file_sync(path: Path, data: bytes) -> None:
    with open(path, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _acquire_lock(descriptor: int, source_path: Path) -> None:
    """Берёт advisory lock; чужие процессы могут его игнорировать."""
    try:
        if sys.platform == "win32":
            import msvcrt

            # Блокировки Windows мандатные: лок на первом байте мешал бы
            # даже читать файл, поэтому запираем байт далеко за EOF.
            os.lseek(descriptor, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            finally:
                os.lseek(descriptor, 0, os.SEEK_SET)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise WriteError(
            tr("write_locked", path=source_path, error=error)
        ) from error


def _write_journal(
    journal_path: Path,
    source_path: Path,
    staged_path: Path,
    backup_path: Path | None,
    snapshot: tuple[int, int, int, int],
    data: bytes,
) -> None:
    device, inode, size, mtime_ns = snapshot
    payload = {
        "source": str(source_path),
        "staged": str(staged_path),
        "backup": str(backup_path) if backup_path else None,
        "st_dev": device,
        "st_ino": inode,
        "st_size": size,
        "st_mtime_ns": mtime_ns,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    journal = json.dumps(payload, ensure_ascii=False, indent=2)
    _write_file_sync(journal_path, journal.encode("utf-8"))


def _restore_from_backup(
    descriptor: int, backup_path: Path | None
) -> bool:
    """Возвращает исходное содержимое из .orig через тот же дескриптор."""
    if backup_path is None or not backup_path.exists():
        return False
    original = backup_path.read_bytes()
    os.lseek(descriptor, 0, os.SEEK_SET)
    _write_all(descriptor, original)
    os.ftruncate(descriptor, len(original))
    os.fsync(descriptor)
    return True


def _discard(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _open_for_writing(path: Path) -> int:
    flags = os.O_RDWR
    # Windows CRT открывает файл в текстовом режиме без O_BINARY.
    flags |= getattr(os, "O_BINARY", 0)
    return os.open(path, flags)


def _write_in_place(
    source_path: Path,
    data: bytes,
    *,
    force: bool,
    backup_path: Path | None,
) -> None:
    """Пишет в существующий файл, сохраняя inode, с journal и проверкой."""
    journal_path = _sidecar_path(source_path, "journal")
    staged_path = _sidecar_path(source_path, "new")
    if journal_path.exists():
        if not force:
            raise WriteError(
                tr(
                    "journal_found",
                    journal=journal_path.name,
                    backup=_backup_label(backup_path),
                )
            )
        _discard(journal_path, staged_path)

    descriptor = _open_for_writing(source_path)
    modified = False
    try:
        _acquire_lock(descriptor, source_path)
        snapshot = _file_snapshot(descriptor)
        _write_file_sync(staged_path, data)
        _write_journal(
            journal_path,
            source_path,
            staged_path,
            backup_path,
            snapshot,
            data,
        )
        if _file_snapshot(descriptor) != snapshot:
            raise WriteError(tr("write_conflict", path=source_path))

        os.lseek(descriptor, 0, os.SEEK_SET)
        modified = True
        _write_all(descriptor, data)
        os.ftruncate(descriptor, len(data))
        os.fsync(descriptor)
        digest = hashlib.sha256(_read_all(descriptor)).hexdigest()
        if digest != hashlib.sha256(data).hexdigest():
            raise WriteError(
                tr(
                    "write_verify_failed",
                    path=source_path,
                    backup=_backup_label(backup_path),
                )
            )
    except BaseException as error:
        if modified and not _restore_from_backup(descriptor, backup_path):
            _discard(journal_path, staged_path)
            raise WriteError(
                tr("write_no_recovery", path=source_path)
            ) from error
        _discard(journal_path, staged_path)
        raise
    else:
        _discard(journal_path, staged_path)
    finally:
        os.close(descriptor)


def _protect_fenced_code(text: str, stash: Callable[[str], str]) -> str:
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    index = 0
    while index < len(lines):
        opening = FENCE_RE.match(lines[index])
        if opening is None:
            result.append(lines[index])
            index += 1
            continue

        fence = opening.group(2)
        fence_char = fence[0]
        fence_length = len(fence)
        block = [lines[index]]
        index += 1
        while index < len(lines):
            block.append(lines[index])
            closing = FENCE_RE.match(lines[index])
            index += 1
            if (
                closing is not None
                and closing.group(2)[0] == fence_char
                and len(closing.group(2)) >= fence_length
                and not closing.group(3).strip()
            ):
                break
        result.append(stash("".join(block)))
    return "".join(result)


def protect_markdown_regions(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Прячет код и комментарии, чтобы regex не менял их содержимое."""
    regions: list[tuple[str, str]] = []

    def stash(value: str) -> str:
        token = f"\x00md-img-local:{len(regions)}\x00"
        # Переносы строк сохраняем, иначе следующая строка склеится с токеном.
        token += "\n" * value.count("\n")
        regions.append((token, value))
        return token

    text = _protect_fenced_code(text, stash)
    text = HTML_COMMENT_RE.sub(lambda match: stash(match.group(0)), text)
    text = INLINE_CODE_RE.sub(lambda match: stash(match.group(0)), text)
    text = ESCAPED_BANG_RE.sub(lambda match: stash(match.group(0)), text)
    return text, regions


def restore_markdown_regions(
    text: str, regions: Sequence[tuple[str, str]]
) -> str:
    """Возвращает защищённые участки; порядок обратный из-за вложенности."""
    for token, value in reversed(regions):
        text = text.replace(token, value)
    return text


def is_remote(url: str) -> bool:
    return url is not None and (
        url.startswith("//") or url.lower().startswith(("http://", "https://"))
    )


class Downloader:
    def __init__(
        self,
        media_dir: Path,
        base_dir: Path,
        session: requests.Session,
        proxy_label: str | None = None,
        allow_private: bool = False,
    ) -> None:
        self.media_dir = media_dir
        self.base_dir = base_dir
        self.session = session
        self.proxy_label = proxy_label
        self.allow_private = allow_private
        self.cache: dict[str, str] = {}
        self.downloaded = 0
        self.failed = 0

    def fetch(self, url: str) -> requests.Response:
        """Идёт по редиректам вручную, проверяя каждый адрес заново."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            ensure_url_allowed(current, self.allow_private)
            response = self.session.get(
                current,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
            if response.status_code not in REDIRECT_STATUSES:
                return response
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise UrlBlocked(tr("redirect_no_location"))
            current = urljoin(current, location)
        raise UrlBlocked(tr("redirect_too_many", limit=MAX_REDIRECTS))

    def localize(self, url: str) -> str:
        if not is_remote(url):
            return url
        canonical = canonical_url(url)
        if canonical in self.cache:
            cached = self.cache[canonical]
            return url if cached is None else cached
        masked = mask_url(canonical)
        result = url
        proxy_hint = (
            tr("proxy_hint", proxy=self.proxy_label) if self.proxy_label else ""
        )
        response = None
        try:
            response = self.fetch(canonical)
            response.raise_for_status()
            content_type = content_type_of(response)
            if content_type not in IMAGE_CONTENT_TYPES:
                raise DownloadRejected(
                    tr(
                        "download_wrong_type",
                        content_type=content_type or tr("content_type_missing"),
                    )
                )
            data = read_limited(response, MAX_DOWNLOAD_BYTES)
            extension = extension_for_content_type(content_type)
            filename = filename_for_url(canonical, extension)
            destination = self.media_dir / filename
            store_download(self.media_dir, destination, data)
            relative = relative_path_for_markdown(destination, self.base_dir)
            result = relative
            self.downloaded += 1
            print(tr("downloaded_file", url=masked, path=relative))
        except requests.RequestException as error:
            self.failed += 1
            print(
                tr(
                    "download_failed",
                    url=masked,
                    error=safe_error(error, canonical),
                    hint=proxy_hint,
                ),
                file=sys.stderr,
            )
        except DownloadRejected as error:
            self.failed += 1
            print(
                tr("download_failed", url=masked, error=error, hint=""),
                file=sys.stderr,
            )
        except OSError as error:
            self.failed += 1
            print(
                tr(
                    "save_failed",
                    url=masked,
                    error=safe_error(error, canonical),
                ),
                file=sys.stderr,
            )
        finally:
            if response is not None:
                response.close()
        self.cache[canonical] = None if result == url else result
        return result


@dataclass(frozen=True)
class RewriteResult:
    """Результат переписывания Markdown без записи на диск."""

    text: str
    found_urls: frozenset[str]


@dataclass(frozen=True)
class RunReport:
    """Итоги запуска для отчёта и кода возврата."""

    path: Path
    found: int
    downloaded: int
    failed: int

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def rewrite(text: str, downloader: Downloader) -> RewriteResult:
    """Заменяет удалённые ссылки на локальные, не трогая код и комментарии."""
    protected_text, protected_regions = protect_markdown_regions(text)

    found_urls: set[str] = set()

    def replace_inline(match: re.Match[str]) -> str:
        alt = match.group(1)
        url = match.group(2) or match.group(3)
        title = match.group(4) or ""
        if not is_remote(url):
            return match.group(0)
        found_urls.add(canonical_url(url))
        local = downloader.localize(url)
        if local == url:
            return match.group(0)
        return f"![{alt}]({local}{' ' + title if title else ''})"

    def replace_html(match: re.Match[str]) -> str:
        quote = match.group(2)
        url = match.group(3) if quote else match.group(4)
        if not is_remote(url):
            return match.group(0)
        found_urls.add(canonical_url(url))
        local = downloader.localize(url)
        if local == url:
            return match.group(0)
        prefix, suffix = match.group(1), match.group(5)
        if quote:
            return f"{prefix}{quote}{local}{quote}{suffix}"
        return f"{prefix}{local}{suffix}"

    def rewrite_srcset_value(value: str) -> tuple[str, bool]:
        """Переписывает URL в srcset, сохраняя дескрипторы (1x, 480w и т. п.)."""
        rewritten: list[str] = []
        changed = False
        for candidate in re.split(r",\s*", value):
            stripped = candidate.strip()
            if not stripped:
                continue
            parts = stripped.split(None, 1)
            url = parts[0]
            descriptor = f" {parts[1]}" if len(parts) > 1 else ""
            if is_remote(url):
                found_urls.add(canonical_url(url))
                local = downloader.localize(url)
                if local != url:
                    rewritten.append(f"{local}{descriptor}")
                    changed = True
                    continue
            rewritten.append(stripped)
        if not changed:
            return value, False
        return ", ".join(rewritten), True

    def replace_srcset(match: re.Match[str]) -> str:
        quote = match.group(2)
        value = match.group(3) if quote else match.group(4)
        rewritten, changed = rewrite_srcset_value(value)
        if not changed:
            return match.group(0)
        prefix, suffix = match.group(1), match.group(5)
        if quote:
            return f"{prefix}{quote}{rewritten}{quote}{suffix}"
        return f"{prefix}{rewritten}{suffix}"

    ref_defs: dict[str, tuple[str, str]] = {}
    for match in REF_DEF_RE.finditer(protected_text):
        url = match.group(2) or match.group(3)
        title = match.group(4) or ""
        if url:
            # CommonMark: при дубликатах побеждает первое определение.
            ref_defs.setdefault(match.group(1).lower(), (url, title))

    replaced_ref_keys: set[str] = set()

    def replace_ref_image(match: re.Match[str]) -> str:
        alt = match.group(1)
        key = (match.group(2) or alt).lower()
        definition = ref_defs.get(key)
        if definition is None:
            return match.group(0)
        url, title = definition
        if not is_remote(url):
            return match.group(0)
        found_urls.add(canonical_url(url))
        local = downloader.localize(url)
        if local == url:
            return match.group(0)
        replaced_ref_keys.add(key)
        return f"![{alt}]({local}{' ' + title if title else ''})"

    new_text = INLINE_IMAGE_RE.sub(replace_inline, protected_text)
    new_text = HTML_IMG_RE.sub(replace_html, new_text)
    new_text = HTML_SRCSET_RE.sub(replace_srcset, new_text)
    new_text = REF_IMAGE_RE.sub(replace_ref_image, new_text)

    def drop_used_definitions(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key not in replaced_ref_keys:
            return match.group(0)
        surrounding = new_text[: match.start()] + new_text[match.end():]
        # Сами определения содержат "[key]:" и не должны считаться использованием.
        surrounding = REF_DEF_RE.sub("", surrounding)
        if re.search(
            r"\[" + re.escape(match.group(1)) + r"\]",
            surrounding,
            re.IGNORECASE,
        ):
            return match.group(0)
        return ""

    new_text = REF_DEF_RE.sub(drop_used_definitions, new_text)
    new_text = restore_markdown_regions(new_text, protected_regions)
    return RewriteResult(new_text, frozenset(found_urls))


def configure_tls() -> None:
    """Подключает системное хранилище сертификатов вместо бандла certifi."""
    if ssl.SSLContext is truststore.SSLContext:
        return
    truststore.inject_into_ssl()


def configure_output() -> None:
    """Делает вывод читаемым при перенаправлении на любой консоли."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue


def build_parser() -> LocalizedArgumentParser:
    parser = LocalizedArgumentParser(
        description=tr("description"),
        formatter_class=LocalizedHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help=tr("help_flag"))
    parser.add_argument("markdown", type=Path, help=tr("help_markdown"))
    parser.add_argument(
        "--media",
        type=Path,
        default=None,
        help=tr("help_media"),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help=tr("help_no_backup"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=tr("help_force"),
    )
    parser.add_argument(
        "--write-mode",
        choices=("in-place", "atomic"),
        default="in-place",
        help=tr("help_write_mode"),
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help=tr("help_allow_private"),
    )
    parser.add_argument(
        "--proxy",
        default=None,
        metavar="URL",
        help=tr("help_proxy"),
    )
    parser.add_argument(
        "--user-agent",
        default=USER_AGENT,
        metavar="STRING",
        help=tr("help_user_agent"),
    )
    parser.add_argument(
        "--lang",
        choices=LANGUAGES,
        default=None,
        help=tr("help_lang"),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
        help=tr("help_version"),
    )
    return parser


def main() -> int:
    configure_tls()
    configure_output()
    set_language(detect_language(language_from_argv(sys.argv[1:])))

    parser = build_parser()
    args = parser.parse_args()

    try:
        return run(args, parser)
    except (OSError, ValueError) as error:
        parser.error(tr("unexpected_error", error=error))
    return 2


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.no_backup and not args.force and args.write_mode == "in-place":
        parser.error(tr("no_backup_requires_force"))

    try:
        proxy = parse_proxy(args.proxy)
        if proxy:
            ensure_socks_support(proxy)
    except ProxyConfigError as error:
        parser.error(str(error))

    proxy_label = mask_proxy(proxy) if proxy else None

    source_path = args.markdown.expanduser().resolve()
    if not source_path.is_file():
        parser.error(tr("file_not_found", path=source_path))

    if args.media:
        media_path = args.media.expanduser()
        if not media_path.is_absolute():
            # Относительный путь трактуется от заметки, а не от текущего каталога.
            media_path = source_path.parent / media_path
        media_dir = media_path.resolve()
    else:
        media_dir = source_path.parent / "media"
    if media_dir.exists() and not media_dir.is_dir():
        parser.error(tr("media_not_directory", path=media_dir))

    if proxy_label:
        print(tr("proxy_banner", proxy=proxy_label))

    session = build_session(proxy, args.user_agent)
    try:
        downloader = Downloader(
            media_dir,
            source_path.parent,
            session,
            proxy_label,
            allow_private=args.allow_private,
        )
        try:
            data = source_path.read_bytes()
        except OSError as error:
            parser.error(tr("read_error", path=source_path, error=error))
        try:
            text, encoding, bom = decode_markdown(data)
        except UnicodeDecodeError as error:
            parser.error(tr("encoding_error", path=source_path, error=error))
        try:
            report = process(
                args,
                source_path,
                downloader,
                text,
                encoding,
                bom,
            )
        except WriteError as error:
            parser.error(str(error))
        report_result(report)
        return report.exit_code
    finally:
        session.close()


def process(
    args: argparse.Namespace,
    source_path: Path,
    downloader: Downloader,
    text: str,
    encoding: str,
    bom: bytes,
) -> RunReport:
    result = rewrite(text, downloader)

    backup_path: Path | None = None
    if not args.no_backup:
        backup_path, rotated_path = make_backup(source_path, args.force)
        if rotated_path is not None:
            print(
                tr(
                    "backup_rotated",
                    backup=backup_path.name,
                    path=rotated_path.name,
                )
            )
        print(tr("backup", source=source_path.name, backup=backup_path.name))
    write_markdown(
        source_path,
        encode_markdown(result.text, encoding, bom),
        args.write_mode,
        force=args.force,
        backup_path=backup_path,
    )
    return RunReport(
        path=source_path,
        found=len(result.found_urls),
        downloaded=downloader.downloaded,
        failed=downloader.failed,
    )


def report_result(result: RunReport) -> None:
    print(tr("result", path=result.path))
    print(tr("found", count=result.found))
    print(tr("downloaded", count=result.downloaded))
    print(tr("failed", count=result.failed))


if __name__ == "__main__":
    sys.exit(main())
