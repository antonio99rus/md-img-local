# md-img-local

[Русская версия](README.md)

Download images referenced by a Markdown file into `media/` (or a directory of your choice) and rewrite the links to local paths.

Three link syntaxes are supported:

- inline: `![alt](https://example.com/img.png "title")`, including angle-bracket form `<url>`;
- reference-style: `![alt][id]` plus `[id]: https://example.com/img.png`;
- HTML: `<img src="https://example.com/img.png" ...>`.

The same URL is downloaded only once. Local links are left untouched.

## Requirements

- Python 3.10+;
- dependencies: [`requests`](https://pypi.org/project/requests/) (with the `socks` extra, required for SOCKS proxies), [`certifi`](https://pypi.org/project/certifi/), [`truststore`](https://pypi.org/project/truststore/).

## Installation

With `uv` (dependencies are declared in `pyproject.toml`):

```bash
uv sync
uv run python md-img-local.py --help
```

With `pip`:

```bash
pip install "requests[socks]" certifi truststore
```

## Usage

```bash
python md-img-local.py <file.md> [--media DIR] [--no-backup] [--proxy URL] [--lang en|ru]
```

| Argument | Description |
| --- | --- |
| `<file.md>` | Source Markdown file (required). |
| `--media DIR` | Directory for images; defaults to `media/` next to the Markdown file. |
| `--no-backup` | Do not create a `file.md.orig` backup. |
| `--proxy URL` | Download through a proxy, e.g. `socks5://127.0.0.1:3066`. |
| `--lang en\|ru` | Language of messages and help; defaults to the system locale. |
| `--version` | Print the program version. |

Examples:

```bash
# Default run
python md-img-local.py note.md

# Through a SOCKS5 proxy (DNS names are resolved locally)
python md-img-local.py note.md --proxy=socks5://127.0.0.1:3066

# Through a SOCKS5 proxy that resolves DNS names itself
python md-img-local.py note.md --proxy=socks5h://127.0.0.1:3066

# Through an HTTP proxy with authentication
python md-img-local.py note.md --proxy=http://user:password@proxy.example:3128
```

## Proxy

- Supported schemes: `http`, `https`, `socks4`, `socks4a`, `socks5`, `socks5h`.
- The port is required: `socks5://127.0.0.1:3066` (a URL without a port is an error).
- `socks5://` resolves names locally, `socks5h://` resolves them on the proxy side. Use `socks5h` when local DNS cannot resolve the required names.
- SOCKS proxies require PySocks: it is installed with `requests[socks]` (automatically via `uv sync`). Without it the program fails immediately with a clear message.
- An explicit `--proxy` takes precedence over the `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` environment variables — they are ignored when the flag is used. Without the flag the environment variables work as usual.
- A proxy password is never printed: it is replaced with `***` in logs.
- On connection errors the message includes a hint that the proxy may be unreachable.
- Proxies that intercept TLS (MITM) are not supported: certificates are verified against `certifi`, so such a proxy requires a custom CA (not implemented yet).

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

## How it works

1. The Markdown file is renamed to `file.md.orig` (unless `--no-backup` is given).
2. Image links are collected from the text (inline, reference-style, HTML).
3. Every unique image is downloaded into `media/`; the file name is `stem-<sha256(url)[:10]><ext>`.
4. Links in the text are replaced with local paths relative to the Markdown file.
5. The result is written back to the original file; a report is printed to stdout: how many images were found, downloaded and how many errors occurred.

If a download fails, the link is left as is and processing continues.

## Tests

```bash
uv sync                # also installs the dev dependencies (pytest, pytest-cov)
uv run pytest          # run the tests
uv run pytest --cov    # run with a coverage report
```

Without `uv`: `pip install pytest pytest-cov`, then `pytest`.

The tests live in `tests/` and cover proxy parsing, downloading, link rewriting (inline, reference-style, HTML), backups, the CLI, localization and integration scenarios with a local HTTP server and a SOCKS5 proxy.

## License

MIT, see [LICENSE](LICENSE).
