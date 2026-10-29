from __future__ import annotations

import argparse
import codecs
import certifi
import hashlib
import json
import locale
import mimetypes
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import quote, urlparse, urlsplit, unquote

import requests

import truststore
truststore.inject_into_ssl()

INLINE_IMAGE_RE = re.compile(
    r'!\[([^\]]*)\]\(\s*(?:<([^>]+)>|(\S+?))'
    r'(?:\s+("(?:[^"\\]|\\.)*"|\'[^\']*\'))?\s*\)'
)
REF_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\[([^\]]*)\]')
HTML_IMG_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])(.*?)\2([^>]*>)',
    re.IGNORECASE,
)
REF_DEF_RE = re.compile(
    r'^[ \t]*\[([^\]]+)\]:[ \t]*(?:<([^>]+)>|([^\s]+))'
    r'(?:\s+(?:"[^"]*"|\'[^\']*\'|\([^)]*\)))?[ \t]*\r?\n?',
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

# UA = "markdown-image-downloader/1.0"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"

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
        "help_lang": "Language of messages and help: en or ru (default: system locale)",
        "help_version": "show program's version number and exit",
        "help_flag": "show this help message and exit",
        "usage_prefix": "usage: ",
        "positional_title": "positional arguments",
        "options_title": "options",
        "error_prefix": "error",
        "file_not_found": "file not found: {path}",
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
        "help_lang": (
            "Язык сообщений и справки: en или ru (по умолчанию — локаль системы)"
        ),
        "help_version": "показать версию программы и выйти",
        "help_flag": "показать эту справку и выйти",
        "usage_prefix": "использование: ",
        "positional_title": "позиционные аргументы",
        "options_title": "параметры",
        "error_prefix": "ошибка",
        "file_not_found": "файл не найден: {path}",
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
        "result": "\nРезультат: {path}",
        "found": "Найдено уникальных изображений: {count}",
        "downloaded": "Скачано: {count}",
        "failed": "Ошибок: {count}",
    },
}

_language = DEFAULT_LANGUAGE


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
    global _language
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language: {code}")
    _language = code


def tr(key: str, **kwargs: object) -> str:
    """Возвращает сообщение на текущем языке с откатом на английский."""
    template = MESSAGES.get(_language, {}).get(key) or MESSAGES[
        DEFAULT_LANGUAGE
    ].get(key)
    if template is None:
        return key
    return template.format(**kwargs)


def language_from_argv(argv: Sequence[str]) -> str | None:
    """Достаёт --lang до полного разбора, чтобы локализовать саму справку."""
    for index, argument in enumerate(argv):
        if argument == "--":
            return None
        if argument == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith("--lang="):
            return argument.split("=", 1)[1]
    return None


class LocalizedHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        return super().add_usage(usage, actions, groups, prefix=tr("usage_prefix"))

    def start_section(self, heading):
        titles = {
            "positional arguments": tr("positional_title"),
            "options": tr("options_title"),
        }
        return super().start_section(titles.get(heading, heading))


class LocalizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {tr('error_prefix')}: {message}\n")


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
                value=value,
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


def build_session(proxy: str | None) -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = UA
    session.max_redirects = MAX_REDIRECTS
    if proxy:
        # Явно указанный прокси должен главенствовать над HTTP_PROXY/HTTPS_PROXY/NO_PROXY.
        session.trust_env = False
        session.proxies.update({"http": proxy, "https": proxy})
    return session


class DownloadRejected(Exception):
    """Загрузка отклонена: размер, тип или отсутствие Content-Type."""


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


def extension_from_response(response: requests.Response, url: str) -> str:
    path = unquote(urlparse(url).path)
    suffix = Path(path).suffix.lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    extension = mimetypes.guess_extension(content_type)
    return extension or ".bin"


def filename_for_url(url: str, extension: str) -> str:
    parsed = urlparse(url)
    original_name = Path(unquote(parsed.path)).stem
    original_name = re.sub(r"[^a-zA-Zа-яА-Я0-9._-]+", "_", original_name)
    original_name = original_name.strip("._-") or "image"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
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
    return url is not None and url.lower().startswith(("http://", "https://"))


class Downloader:
    def __init__(
        self,
        media_dir: Path,
        base_dir: Path,
        session: requests.Session,
        proxy_label: str | None = None,
    ) -> None:
        self.media_dir = media_dir
        self.base_dir = base_dir
        self.session = session
        self.proxy_label = proxy_label
        self.cache: dict[str, str] = {}
        self.downloaded = 0
        self.failed = 0

    def localize(self, url: str) -> str:
        if not is_remote(url):
            return url
        if url in self.cache:
            return self.cache[url]
        result = url
        proxy_hint = (
            tr("proxy_hint", proxy=self.proxy_label) if self.proxy_label else ""
        )
        response = None
        try:
            response = self.session.get(
                url,
                stream=True,
                verify=certifi.where(),
                timeout=30,
            )
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
            extension = extension_from_response(response, url)
            filename = filename_for_url(url, extension)
            destination = self.media_dir / filename
            store_download(self.media_dir, destination, data)
            relative = relative_path_for_markdown(destination, self.base_dir)
            result = relative
            self.downloaded += 1
            print(tr("downloaded_file", url=url, path=relative))
        except requests.RequestException as error:
            self.failed += 1
            print(tr("download_failed", url=url, error=error, hint=proxy_hint))
        except DownloadRejected as error:
            self.failed += 1
            print(tr("download_failed", url=url, error=error, hint=""))
        except OSError as error:
            self.failed += 1
            print(tr("save_failed", url=url, error=error))
        finally:
            if response is not None:
                response.close()
        self.cache[url] = result
        return result


def main() -> None:
    set_language(detect_language(language_from_argv(sys.argv[1:])))

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
        "--proxy",
        default=None,
        metavar="URL",
        help=tr("help_proxy"),
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
    args = parser.parse_args()

    if args.lang:
        set_language(args.lang)

    if args.no_backup and not args.force and args.write_mode == "in-place":
        parser.error(tr("no_backup_requires_force"))

    try:
        proxy = parse_proxy(args.proxy)
        if proxy:
            ensure_socks_support(proxy)
    except ProxyConfigError as error:
        parser.error(str(error))

    proxy_label = mask_proxy(proxy) if proxy else None

    source_path = args.markdown.resolve()
    if not source_path.is_file():
        parser.error(tr("file_not_found", path=source_path))

    media_dir = (
        args.media.resolve()
        if args.media
        else source_path.parent / "media"
    )
    media_dir.mkdir(parents=True, exist_ok=True)

    if proxy_label:
        print(tr("proxy_banner", proxy=proxy_label))

    session = build_session(proxy)
    downloader = Downloader(media_dir, source_path.parent, session, proxy_label)
    try:
        text, encoding, bom = decode_markdown(source_path.read_bytes())
    except UnicodeDecodeError as error:
        parser.error(tr("encoding_error", path=source_path, error=error))
    protected_text, protected_regions = protect_markdown_regions(text)

    found_urls: set[str] = set()

    def replace_inline(match: re.Match[str]) -> str:
        alt = match.group(1)
        url = match.group(2) or match.group(3)
        title = match.group(4) or ""
        if not is_remote(url):
            return match.group(0)
        found_urls.add(url)
        local = downloader.localize(url)
        if local == url:
            return match.group(0)
        return f"![{alt}]({local}{' ' + title if title else ''})"

    def replace_html(match: re.Match[str]) -> str:
        url = match.group(3)
        if not is_remote(url):
            return match.group(0)
        found_urls.add(url)
        local = downloader.localize(url)
        if local == url:
            return match.group(0)
        prefix, quote, suffix = match.group(1), match.group(2), match.group(4)
        return f"{prefix}{quote}{local}{quote}{suffix}"

    ref_urls: dict[str, str] = {}
    for match in REF_DEF_RE.finditer(protected_text):
        url = match.group(2) or match.group(3)
        if url:
            ref_urls[match.group(1).lower()] = url

    replaced_ref_keys: set[str] = set()

    def replace_ref_image(match: re.Match[str]) -> str:
        alt = match.group(1)
        key = (match.group(2) or alt).lower()
        url = ref_urls.get(key)
        if not is_remote(url):
            return match.group(0)
        found_urls.add(url)
        local = downloader.localize(url)
        if local == url:
            return match.group(0)
        replaced_ref_keys.add(key)
        return f"![{alt}]({local})"

    new_text = INLINE_IMAGE_RE.sub(replace_inline, protected_text)
    new_text = HTML_IMG_RE.sub(replace_html, new_text)
    new_text = REF_IMAGE_RE.sub(replace_ref_image, new_text)

    def drop_used_definitions(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key not in replaced_ref_keys:
            return match.group(0)
        surrounding = new_text[: match.start()] + new_text[match.end():]
        if re.search(
            r"\[" + re.escape(match.group(1)) + r"\]",
            surrounding,
            re.IGNORECASE,
        ):
            return match.group(0)
        return ""

    new_text = REF_DEF_RE.sub(drop_used_definitions, new_text)
    new_text = restore_markdown_regions(new_text, protected_regions)

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
    try:
        write_markdown(
            source_path,
            encode_markdown(new_text, encoding, bom),
            args.write_mode,
            force=args.force,
            backup_path=backup_path,
        )
    except WriteError as error:
        parser.error(str(error))

    print(tr("result", path=source_path))
    print(tr("found", count=len(found_urls)))
    print(tr("downloaded", count=downloader.downloaded))
    print(tr("failed", count=downloader.failed))

    session.close()


if __name__ == "__main__":
    main()
