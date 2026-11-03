# md-img-local

[Русская версия](README.md)

Downloads images referenced by a Markdown file into `media/` (or a directory of your choice) and rewrites the links to local paths.

Three link syntaxes are supported:

- inline: `![alt](https://example.com/img.png "title")`, including the angle-bracket form `<url>`;
- reference-style: `![alt][id]` plus `[id]: https://example.com/img.png`; if a reference is defined more than once, the first definition wins and its title is preserved;
- HTML: `<img src="https://example.com/img.png" ...>` with quoted or unquoted `src`, `srcset` on `<img>` and `<source>`, and `<source src>` inside `<picture>`.

Protocol-relative URLs (`//cdn.example/img.png`) are treated as HTTPS. Images inside fenced code blocks, inline code, HTML comments and escaped `\![...]` are left untouched. The same canonical URL is downloaded only once; local links are not modified.

## Requirements

- Python 3.10+;
- [`requests`](https://pypi.org/project/requests/) with the `socks` extra (required for SOCKS proxies);
- [`markdown-it-py`](https://pypi.org/project/markdown-it-py/) for CommonMark block detection;
- [`truststore`](https://pypi.org/project/truststore/) for TLS verification against the operating system trust store.

## Installation

With `uv` (dependencies are declared in `pyproject.toml`):

```bash
uv sync
uv run python md-img-local.py --help
```

With `pip`:

```bash
pip install "requests[socks]" markdown-it-py truststore
```

## Usage

```bash
python md-img-local.py <file.md> [options]
```

| Argument | Description |
| --- | --- |
| `<file.md>` | Source Markdown file (required). |
| `--media DIR` | Directory for images. Defaults to `media/` next to the Markdown file. A relative path is resolved from the directory of the Markdown file; `~` is expanded. |
| `--no-backup` | Do not create a `file.md.orig` backup. With `in-place` this also requires `--force`; with `atomic` it is allowed on its own. |
| `--force` | Overwrite an existing `file.md.orig` instead of rotating it, allow `--no-backup` with `in-place`, and discard a leftover write journal. |
| `--write-mode in-place\|atomic` | How to write the result. `in-place` is the default and preserves the file inode and hardlinks; `atomic` replaces the file through a temporary file. |
| `--allow-private` | Allow downloads from private, loopback and link-local addresses. Disabled by default to prevent SSRF. |
| `--proxy URL` | Download through a proxy, e.g. `socks5://127.0.0.1:3066`. An explicit proxy overrides the proxy environment variables. |
| `--user-agent STRING` | `User-Agent` header for downloads. Defaults to `md-img-local/<version>`. |
| `--lang en\|ru` | Language of messages and help. Defaults to the system locale. |
| `--verbose` | Print full URLs in logs instead of masked ones. Proxy passwords are still masked. |
| `--version` | Print the program version. |
| `-h, --help` | Show help and exit. |

Examples:

```bash
# Default run
python md-img-local.py note.md

# Custom image directory
python md-img-local.py note.md --media "my images"

# Atomic write without a backup
python md-img-local.py note.md --write-mode atomic --no-backup

# Through a SOCKS5 proxy (DNS names are resolved locally)
python md-img-local.py note.md --proxy=socks5://127.0.0.1:3066

# Through a SOCKS5 proxy that resolves DNS names itself
python md-img-local.py note.md --proxy=socks5h://127.0.0.1:3066
```

## How it works

1. The Markdown file is read as bytes. UTF-8, UTF-16 and UTF-32 (with a BOM) are supported; the original BOM and line endings are preserved.
2. Code blocks (fenced and indented, detected by `markdown-it-py`), inline code, HTML comments and escaped `!` are masked so examples are never rewritten or downloaded.
3. Image links are collected and canonicalized: the fragment is removed, the scheme and host are lowercased, and default ports are dropped. Query strings are preserved; protocol-relative URLs are treated as HTTPS.
4. Every unique image is downloaded into `media/`; the directory is created lazily on the first successful download.
5. Links are replaced with POSIX-style paths relative to the Markdown file. Spaces and special characters are percent-encoded for Markdown and HTML; `srcset` descriptors such as `1x` and `480w` are preserved.
6. A backup is created (unless disabled), then the result is written back using the selected write mode.
7. A report is printed to stdout: unique images found, downloaded, and errors.

If a download fails, its link is left as is and processing continues.

### Download rules

- Maximum size: 20 MiB per image, checked against both `Content-Length` and the streamed body.
- Allowed types: PNG, JPEG, GIF, WebP, BMP, TIFF, AVIF and ICO. SVG and unknown types are rejected.
- Redirects are followed manually, at most 5, and every target is checked again.
- Private, loopback, link-local, reserved, multicast and unspecified addresses are rejected unless `--allow-private` is given.
- Connect timeout is 10 seconds, read timeout is 30 seconds. GET requests are retried twice on `429`, `500`, `502`, `503` and `504`.
- File names are `stem-<sha256(url)[:16]><ext>`. The stem is sanitized and limited to 80 characters; the extension comes from the response `Content-Type`, not from the URL.

### Backup and write modes

- The backup is an independent copy named `file.md.orig`. An existing backup is rotated to `file.md.orig.1`, `file.md.orig.2`, and so on. With `--force` the existing `file.md.orig` is overwritten.
- `in-place` (default) keeps the inode, hardlinks, permissions, ACLs and alternate data streams. A journal and a staged copy are written first; concurrent modification is detected, the result is verified by hash, and a failed write is restored from the backup. Readers may briefly see partial content.
- `atomic` writes a temporary file in the same directory, calls `fsync`, copies the file metadata and replaces the source with `os.replace`. The result is atomic, but the inode changes and hardlinks are detached.
- A successful run leaves the `.orig` backup in place; remove it manually when it is no longer needed.

## Output and exit codes

- `[OK]`, `[BACKUP]` and the final report go to stdout; `[ERROR]` messages and configuration errors go to stderr.
- Exit code `0`: success.
- Exit code `1`: at least one image could not be downloaded or saved.
- Exit code `2`: configuration, input or local I/O error (missing file, bad proxy, unsupported encoding, write error, and so on).

URLs in logs are masked by default: credentials and sensitive query parameters are replaced, and control characters are neutralized. Pass `--verbose` to print full URLs; control characters are still neutralized, and proxy passwords are always masked.

## Proxy

- Supported schemes: `http`, `https`, `socks4`, `socks4a`, `socks5`, `socks5h`.
- The port is required: `socks5://127.0.0.1:3066` (a URL without a port is an error).
- `socks5://` resolves names locally, `socks5h://` resolves them on the proxy side. Use `socks5h` when local DNS cannot resolve the required names.
- SOCKS proxies require PySocks; it is installed with `requests[socks]` (automatically via `uv sync`). Without it the program fails immediately with a clear message.
- An explicit `--proxy` takes precedence over `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` — they are ignored when the flag is used. Without the flag the environment variables work as usual.
- A proxy password is never printed: it is replaced with `***` in logs.
- On connection errors the message includes a hint that the proxy may be unreachable.

## TLS

Certificates are always verified. `truststore` uses the operating system trust store, so corporate TLS-inspecting proxies work when their CA is installed system-wide. A server with an untrusted certificate is rejected.

## Localization

Messages and `--help` are available in English and Russian. The language is chosen in this order:

1. `--lang ru|en`;
2. the `MD_IMG_LOCAL_LANG` environment variable;
3. `LC_ALL`, `LC_MESSAGES`, `LANG`, `LANGUAGE`;
4. the OS locale (on Windows, the UI language);
5. English as the fallback.

```bash
python md-img-local.py note.md --lang=ru
MD_IMG_LOCAL_LANG=ru python md-img-local.py note.md
```

The Russian documentation is in [README.md](README.md).

## Known limitations

- Links are parsed with regular expressions. `srcset` candidates follow the HTML parsing rules, so URLs containing commas are supported. `<source src>` is handled only inside `<picture>`; outside it, `<source>` is treated as audio/video markup, not an image.
- Every remote candidate in `srcset` is downloaded, including all listed resolutions.
- Images are downloaded sequentially.

## Tests

```bash
uv sync                # also installs the dev dependencies (pytest, pytest-cov, ruff, mypy)
uv run pytest          # run the tests
uv run pytest --cov    # run with a coverage report
uv run ruff check .    # run the linter
uv run mypy            # run the type checker
```

Without `uv`: `pip install pytest pytest-cov`, then `pytest`. On Python 3.10 the dev dependencies also install `tomli` for reading `pyproject.toml` in the tests.

The tests live in `tests/` and cover link rewriting (inline, reference-style, HTML, protected code and comments), encoding and line endings, backup rotation and write modes, download limits and content types, SSRF and secret masking, TLS with a self-signed certificate, CLI exit codes, localization, and integration scenarios with a local HTTP server and a SOCKS5 proxy.

## License

MIT, see [LICENSE](LICENSE).
