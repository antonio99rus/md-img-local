from __future__ import annotations

import base64

import requests

# Минимальный валидный PNG 1x1.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
)

URL = "http://example.com/img.png"


class FakeResponse:
    def __init__(
        self,
        content: bytes = PNG_BYTES,
        headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Заменитель requests.Session: отдаёт заранее заданные ответы и пишет вызовы."""

    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.proxies: list[str | None] = []
        self.closed = False

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        result = self.responses.get(url)
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise requests.ConnectionError(f"нет ответа для {url}")
        return result  # type: ignore[return-value]

    def close(self) -> None:
        self.closed = True
