from __future__ import annotations

import argparse
import certifi
import hashlib
import locale
import mimetypes
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse, urlsplit, unquote

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

VERSION = "1.2.0"

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
        "downloaded_file": "[OK] {url} -> {path}",
        "download_failed": "[ERROR] Failed to download {url}: {error}{hint}",
        "save_failed": "[ERROR] Failed to save {url}: {error}",
        "proxy_hint": " (proxy {proxy} unreachable?)",
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
        "downloaded_file": "[OK] {url} -> {path}",
        "download_failed": "[ERROR] Не удалось скачать {url}: {error}{hint}",
        "save_failed": "[ERROR] Не удалось сохранить {url}: {error}",
        "proxy_hint": " (прокси {proxy} недоступен?)",
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
    if proxy:
        # Явно указанный прокси должен главенствовать над HTTP_PROXY/HTTPS_PROXY/NO_PROXY.
        session.trust_env = False
        session.proxies.update({"http": proxy, "https": proxy})
    return session


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
        try:
            response = self.session.get(
                url,
                verify=certifi.where(),
                timeout=30,
            )
            response.raise_for_status()
            extension = extension_from_response(response, url)
            filename = filename_for_url(url, extension)
            destination = self.media_dir / filename
            destination.write_bytes(response.content)
            relative = Path(os.path.relpath(destination, self.base_dir)).as_posix()
            result = relative
            self.downloaded += 1
            print(tr("downloaded_file", url=url, path=relative))
        except requests.RequestException as error:
            self.failed += 1
            print(tr("download_failed", url=url, error=error, hint=proxy_hint))
        except OSError as error:
            self.failed += 1
            print(tr("save_failed", url=url, error=error))
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
    text = source_path.read_text(encoding="utf-8")

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
    for match in REF_DEF_RE.finditer(text):
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

    new_text = INLINE_IMAGE_RE.sub(replace_inline, text)
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

    backup_path = source_path.with_name(f"{source_path.name}.orig")
    if not args.no_backup:
        source_path.replace(backup_path)
        print(tr("backup", source=source_path.name, backup=backup_path.name))
    source_path.write_text(new_text, encoding="utf-8")

    print(tr("result", path=source_path))
    print(tr("found", count=len(found_urls)))
    print(tr("downloaded", count=downloader.downloaded))
    print(tr("failed", count=downloader.failed))

    session.close()


if __name__ == "__main__":
    main()
