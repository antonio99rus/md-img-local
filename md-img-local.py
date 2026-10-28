from __future__ import annotations

import argparse
import certifi
import hashlib
import mimetypes
import os
import re
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

VERSION = "1.1.0"

# UA = "markdown-image-downloader/1.0"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"

PROXY_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")


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
        raise ProxyConfigError("адрес прокси не должен содержать пробелов")

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in PROXY_SCHEMES:
        raise ProxyConfigError(
            f"неподдерживаемый адрес прокси {value!r}: ожидается схема "
            f"{', '.join(PROXY_SCHEMES)}, например socks5://127.0.0.1:3066"
        )
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ProxyConfigError(f"некорректный адрес прокси: {error}") from error
    if not host:
        raise ProxyConfigError("в адресе прокси не указан хост")
    if port is None:
        raise ProxyConfigError(
            "в адресе прокси не указан порт, например socks5://127.0.0.1:3066"
        )
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ProxyConfigError("в адресе прокси допустимы только схема, хост и порт")

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
        raise ProxyConfigError(
            "для socks-прокси нужен PySocks: установите зависимости "
            'командой "uv sync" или "pip install \'requests[socks]\'"'
        ) from error


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
            f" (прокси {self.proxy_label} недоступен?)" if self.proxy_label else ""
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
            print(f"[OK] {url} -> {relative}")
        except requests.RequestException as error:
            self.failed += 1
            print(f"[ERROR] Не удалось скачать {url}: {error}{proxy_hint}")
        except OSError as error:
            self.failed += 1
            print(f"[ERROR] Не удалось сохранить {url}: {error}")
        self.cache[url] = result
        return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Скачивает изображения из Markdown-файла в media/ и заменяет ссылки на локальные",
    )
    parser.add_argument("markdown", type=Path, help="Исходный Markdown-файл")
    parser.add_argument(
        "--media",
        type=Path,
        default=None,
        help="Каталог для изображений; по умолчанию media рядом с Markdown-файлом",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Не создавать резервную копию файла.md.orig",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        metavar="URL",
        help=(
            "Прокси для скачивания: http, https, socks4, socks4a, socks5, socks5h "
            "(порт обязателен), например socks5://127.0.0.1:3066. "
            "При указании прокси переменные HTTP_PROXY, HTTPS_PROXY и NO_PROXY игнорируются"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    args = parser.parse_args()

    try:
        proxy = parse_proxy(args.proxy)
        if proxy:
            ensure_socks_support(proxy)
    except ProxyConfigError as error:
        parser.error(str(error))

    proxy_label = mask_proxy(proxy) if proxy else None

    source_path = args.markdown.resolve()
    if not source_path.is_file():
        parser.error(f"файл не найден: {source_path}")

    media_dir = (
        args.media.resolve()
        if args.media
        else source_path.parent / "media"
    )
    media_dir.mkdir(parents=True, exist_ok=True)

    if proxy_label:
        print(f"[PROXY] {proxy_label}")

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
        print(f"[BACKUP] {source_path.name} -> {backup_path.name}")
    source_path.write_text(new_text, encoding="utf-8")

    print(f"\nРезультат: {source_path}")
    print(f"Найдено уникальных изображений: {len(found_urls)}")
    print(f"Скачано: {downloader.downloaded}")
    print(f"Ошибок: {downloader.failed}")

    session.close()


if __name__ == "__main__":
    main()
