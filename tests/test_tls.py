from __future__ import annotations

import functools
import http.server
import ipaddress
import ssl
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from helpers import PNG_BYTES, URL

# Запоминаем настоящий класс до возможной инъекции truststore.
SERVER_CONTEXT = ssl.SSLContext


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: A002 - подпись из стандартной библиотеки
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Неудачное рукопожатие с недоверенным сертификатом — ожидаемый сценарий.
        pass


@pytest.fixture
def injected_tls(script):
    """Включает truststore и возвращает глобальные ссылки после теста."""
    import requests.adapters
    import urllib3.util.ssl_ as urllib3_ssl

    original_ssl = ssl.SSLContext
    original_urllib3 = urllib3_ssl.SSLContext
    original_preloaded = getattr(requests.adapters, "_preloaded_ssl_context", None)
    script.configure_tls()
    try:
        yield
    finally:
        ssl.SSLContext = original_ssl
        urllib3_ssl.SSLContext = original_urllib3
        if original_preloaded is None:
            if hasattr(requests.adapters, "_preloaded_ssl_context"):
                delattr(requests.adapters, "_preloaded_ssl_context")
        else:
            requests.adapters._preloaded_ssl_context = original_preloaded


def make_self_signed_cert(tmp_path: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture
def self_signed_server(tmp_path: Path):
    pytest.importorskip("cryptography")
    cert_path, key_path = make_self_signed_cert(tmp_path)
    root = tmp_path / "site"
    root.mkdir()
    (root / "img.png").write_bytes(PNG_BYTES)

    context = SERVER_CONTEXT(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    handler = functools.partial(QuietHandler, directory=str(root))
    server = QuietServer(("127.0.0.1", 0), handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}/img.png"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_configure_tls_injects_system_store(script, injected_tls):
    assert ssl.SSLContext is script.truststore.SSLContext


def test_configure_tls_is_idempotent(script, injected_tls):
    script.configure_tls()
    script.configure_tls()

    assert ssl.SSLContext is script.truststore.SSLContext


def test_main_configures_tls(
    script, monkeypatch, run_main, tmp_path, fake_session
):
    calls: list[bool] = []
    monkeypatch.setattr(script, "configure_tls", lambda: calls.append(True))
    path = tmp_path / "note.md"
    path.write_text(f"![a]({URL})\n", encoding="utf-8")

    assert run_main(path) == 0
    assert calls == [True]


def test_untrusted_certificate_is_rejected(injected_tls, self_signed_server):
    with pytest.raises(requests.exceptions.SSLError):
        requests.get(self_signed_server, verify=True, timeout=10)
