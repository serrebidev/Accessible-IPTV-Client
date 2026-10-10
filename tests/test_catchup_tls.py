"""Catch-up discovery must work when a Windows server omits its issuer cert."""

import datetime
import http.server
import ssl
import sys
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

import catchup_direct

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows certificate-chain validation")


@pytest.fixture
def archive(tmp_path, monkeypatch, request):
    import truststore

    now = datetime.datetime.now(datetime.timezone.utc)
    root_key, issuer_key, leaf_key = [rsa.generate_private_key(65537, 2048) for _ in range(3)]

    def certificate(name, key, signer_name, signer_key, ca, aia=None):
        builder = (x509.CertificateBuilder()
                   .subject_name(name).issuer_name(signer_name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(minutes=5))
                   .not_valid_after(now + datetime.timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer_key.public_key()),
                                  critical=False)
                   .add_extension(x509.KeyUsage(not ca, False, not ca, False, False, ca, ca, False, False),
                                  critical=True))
        if not ca:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        if aia:
            builder = builder.add_extension(x509.AuthorityInformationAccess([
                x509.AccessDescription(AuthorityInformationAccessOID.CA_ISSUERS,
                                       x509.UniformResourceIdentifier(aia))]), False)
        return builder.sign(signer_key, hashes.SHA256())

    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Catch-up test root")])
    issuer_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Catch-up test issuer")])
    root = certificate(root_name, root_key, root_name, root_key, True)
    issuer = certificate(issuer_name, issuer_key, root_name, root_key, True)

    class Issuer(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            data = issuer.public_bytes(serialization.Encoding.DER)
            self.send_response(200)
            self.send_header("Content-Type", "application/pkix-cert")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    requests = []

    class Media(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            requests.append((self.command, self.path))
            self.send_response(405 if self.path == "/ranged.mp4" else 302 if self.path == "/play" else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", "1")
            self.send_header("Location", "/archive/timeshift.ts")
            self.end_headers()

        def do_GET(self):
            requests.append((self.command, self.path))
            assert self.headers.get("Range") == "bytes=0-0"
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", "1")
            self.end_headers()
            try:
                self.wfile.write(b"x")
            except OSError:
                pass  # The probe closes as soon as it has the headers.

    issuer_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Issuer)
    media_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Media)
    issuer_url = "http://127.0.0.1:%d/issuer.der" % issuer_server.server_port
    leaf = certificate(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]),
                       leaf_key, issuer_name, issuer_key, False, issuer_url)
    cert_file, key_file = tmp_path / "leaf.pem", tmp_path / "leaf.key"
    # Only the leaf is served, just like the real archive server.
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,
                                              serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_file, key_file)
    media_server.socket = server_context.wrap_socket(media_server.socket, server_side=True)
    root_pem = root.public_bytes(serialization.Encoding.PEM).decode()
    original_default = ssl.create_default_context
    original_native = truststore.SSLContext

    def openssl_context(*_args, **_kwargs):
        return original_default(cadata=root_pem)

    def native_context(protocol):
        context = original_native(protocol)
        if getattr(request, "param", "trusted") != "untrusted":
            context.load_verify_locations(cadata=root_pem)
        return context

    monkeypatch.setattr(ssl, "create_default_context", openssl_context)
    monkeypatch.setattr(ssl, "_create_default_https_context", openssl_context)
    monkeypatch.setattr(truststore, "SSLContext", native_context)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (issuer_server, media_server)]
    for thread in threads:
        thread.start()
    try:
        yield "https://localhost:%d" % media_server.server_port, requests
    finally:
        for server in (media_server, issuer_server):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()


@pytest.mark.parametrize("path", ["/direct.mp4", "/ranged.mp4"])
def test_direct_probe_fetches_missing_intermediate(archive, path):
    base, requests = archive
    assert catchup_direct.probe_direct_url(base + path)
    if path == "/ranged.mp4":
        assert requests == [("HEAD", path), ("GET", path)]


def test_redirect_probe_fetches_missing_intermediate_without_opening_stream(archive):
    base, requests = archive
    assert catchup_direct._next_hop(base + "/play", {}, 6) == (base + "/archive/timeshift.ts", False)
    assert requests == [("HEAD", "/play")]


def test_probe_still_rejects_wrong_hostname(archive):
    base, requests = archive
    assert not catchup_direct.probe_direct_url(base.replace("localhost", "127.0.0.1") + "/direct.mp4")
    assert requests == []


@pytest.mark.parametrize("archive", ["untrusted"], indirect=True)
def test_probe_still_rejects_untrusted_certificate(archive):
    base, requests = archive
    assert not catchup_direct.probe_direct_url(base + "/direct.mp4")
    assert requests == []
