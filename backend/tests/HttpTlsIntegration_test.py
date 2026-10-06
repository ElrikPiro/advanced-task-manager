"""Loopback integration checks for the HTTPS API listener."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import socket
import ssl
import subprocess
import tempfile
import unittest
import uuid
import warnings
from pathlib import Path
from typing import AsyncIterator, Iterator
from unittest.mock import Mock, patch

import aiohttp
from aiohttp import ClientSession, TCPConnector

from src.FileBroker import FileBroker
from src.MutationCoordinator import MutationCoordinator
from src.NotificationHistoryStore import NotificationHistoryStore
from src.api.ProblemDetails import safe_detail
from src.domain.errors import ValidationError
from src.SafeDiagnostics import format_safe_exception_diagnostic
from src.wrappers.HttpUserCommService import HttpUserCommService
from src.wrappers.Messaging import IAgent


class _Certificates:
    """Create disposable local roots and server certificates with OpenSSL."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ca_key = root / "test-root.key"
        self.ca_cert = root / "test-root.pem"
        self.retired_ca_key = root / "retired-root.key"
        self.retired_ca_cert = root / "retired-root.pem"
        self.encrypted_key = root / "encrypted-server.key"
        self._create_ca("test-root", self.ca_key, self.ca_cert)
        self._create_ca("retired-root", self.retired_ca_key, self.retired_ca_cert)
        self._create_encrypted_key()

        self.valid_chain, self.valid_key = self._issue_server("valid", "IP:127.0.0.1,DNS:localhost")
        self.wrong_san_chain, self.wrong_san_key = self._issue_server(
            "wrong-san", "DNS:wrong.invalid"
        )
        self.expired_chain, self.expired_key = self._issue_expired_server()

    @staticmethod
    def _run(*arguments: str) -> None:
        subprocess.run(
            ["openssl", *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    @staticmethod
    def _restrict_key(path: Path) -> None:
        path.chmod(0o600)

    def _create_encrypted_key(self) -> None:
        self._run(
            "genpkey",
            "-algorithm",
            "RSA",
            "-aes-256-cbc",
            "-pass",
            "pass:temporary-test-passphrase",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(self.encrypted_key),
        )
        self._restrict_key(self.encrypted_key)

    def _create_ca(self, name: str, key: Path, certificate: Path) -> None:
        self._run(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "30",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            f"/CN=Local-{name}",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        )
        self._restrict_key(key)

    def _issue_server(self, name: str, subject_alt_name: str) -> tuple[Path, Path]:
        key = self.root / f"{name}.key"
        csr = self.root / f"{name}.csr"
        certificate = self.root / f"{name}.pem"
        extensions = self.root / f"{name}.ext"
        chain = self.root / f"{name}-chain.pem"
        self._run(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            f"/CN={name}",
        )
        self._restrict_key(key)
        extensions.write_text(
            "\n".join(
                (
                    "basicConstraints=critical,CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                    "extendedKeyUsage=serverAuth",
                    f"subjectAltName={subject_alt_name}",
                )
            ),
            encoding="ascii",
        )
        self._run(
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(self.ca_cert),
            "-CAkey",
            str(self.ca_key),
            "-CAcreateserial",
            "-days",
            "2",
            "-sha256",
            "-out",
            str(certificate),
            "-extfile",
            str(extensions),
        )
        chain.write_bytes(certificate.read_bytes() + self.ca_cert.read_bytes())
        return chain, key

    def _issue_expired_server(self) -> tuple[Path, Path]:
        name = "expired"
        key = self.root / f"{name}.key"
        csr = self.root / f"{name}.csr"
        certificate = self.root / f"{name}.pem"
        chain = self.root / f"{name}-chain.pem"
        extensions = self.root / f"{name}.ext"
        self._run(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            "/CN=expired",
        )
        self._restrict_key(key)
        extensions.write_text(
            "\n".join(
                (
                    "basicConstraints=critical,CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                    "extendedKeyUsage=serverAuth",
                    "subjectAltName=IP:127.0.0.1,DNS:localhost",
                )
            ),
            encoding="ascii",
        )
        (self.root / "newcerts").mkdir()
        database = self.root / "index.txt"
        database.write_text("", encoding="ascii")
        serial = self.root / "ca.serial"
        serial.write_text("2000\n", encoding="ascii")
        config = self.root / "openssl-ca.cnf"
        config.write_text(
            "\n".join(
                (
                    "[ ca ]",
                    "default_ca = local_ca",
                    "[ local_ca ]",
                    f"database = {database}",
                    f"new_certs_dir = {self.root / 'newcerts'}",
                    f"certificate = {self.ca_cert}",
                    f"private_key = {self.ca_key}",
                    f"serial = {serial}",
                    "default_md = sha256",
                    "default_days = 2",
                    "policy = policy_any",
                    "unique_subject = no",
                    "[ policy_any ]",
                    "commonName = supplied",
                    "[ server_cert ]",
                    "basicConstraints = critical,CA:FALSE",
                    "keyUsage = critical,digitalSignature,keyEncipherment",
                    "extendedKeyUsage = serverAuth",
                    "subjectAltName = IP:127.0.0.1,DNS:localhost",
                )
            ),
            encoding="ascii",
        )
        self._run(
            "ca",
            "-batch",
            "-notext",
            "-config",
            str(config),
            "-in",
            str(csr),
            "-out",
            str(certificate),
            "-startdate",
            "20200101000000Z",
            "-enddate",
            "20200102000000Z",
            "-extensions",
            "server_cert",
        )
        chain.write_bytes(certificate.read_bytes() + self.ca_cert.read_bytes())
        return chain, key


class HttpTlsIntegrationTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory(prefix="tls-loopback-")
        cls.certificates = _Certificates(Path(cls.temporary_directory.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def setUp(self) -> None:
        self.agent = Mock(spec=IAgent)
        self.agent.id = "tls-test-agent"
        self.agent.name = "TLS integration test"
        self.agent.description = "Loopback only"
        self.application = Mock()
        self.token = "local-test-secret-token"
        self.data_directory = tempfile.TemporaryDirectory(prefix="tls-history-")
        self.data_path = Path(self.data_directory.name) / "data"
        self.appdata_path = Path(self.data_directory.name) / "appdata"
        self.vault_path = Path(self.data_directory.name) / "vault"
        self.data_path.mkdir()
        self.appdata_path.mkdir()
        self.vault_path.mkdir()
        self.mutation_coordinator = MutationCoordinator()
        self.file_broker = FileBroker(
            str(self.data_path),
            str(self.appdata_path),
            str(self.vault_path),
            mutation_coordinator=self.mutation_coordinator,
        )
        self.notification_history_store = NotificationHistoryStore(
            self.file_broker,
            self.mutation_coordinator,
            self.token,
        )

    def service_with_tls_paths(self, chain: Path, key: Path) -> HttpUserCommService:
        return HttpUserCommService(
            url="127.0.0.1",
            port=0,
            token=self.token,
            chat_id=1,
            agent=self.agent,
            tls_cert_chain_path=str(chain),
            tls_private_key_path=str(key),
            application_service=self.application,
            notification_history_store=self.notification_history_store,
        )

    def tearDown(self) -> None:
        self.mutation_coordinator.close()
        self.data_directory.cleanup()

    @contextlib.asynccontextmanager
    async def listener(
        self,
        chain: Path | None = None,
        key: Path | None = None,
        application: Mock | None = None,
    ) -> AsyncIterator[tuple[HttpUserCommService, str]]:
        service = HttpUserCommService(
            url="127.0.0.1",
            port=0,
            token=self.token,
            chat_id=1,
            agent=self.agent,
            tls_cert_chain_path=str(chain) if chain is not None else None,
            tls_private_key_path=str(key) if key is not None else None,
            application_service=application or self.application,
            notification_history_store=self.notification_history_store,
        )
        await service.initialize()
        try:
            server_socket = service.site._server.sockets[0]
            port = server_socket.getsockname()[1]
            yield service, f"https://127.0.0.1:{port}"
        finally:
            await service.shutdown()

    @staticmethod
    def client_context(cafile: Path | None = None) -> ssl.SSLContext:
        if cafile is None:
            return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(cafile))

    async def test_missing_tls_certificate_keeps_safe_cause_and_binds_no_server(self) -> None:
        missing_chain = Path(self.temporary_directory.name) / "missing-chain-secret-path.pem"
        service = self.service_with_tls_paths(missing_chain, self.certificates.valid_key)

        with self.assertRaises(RuntimeError) as captured:
            await service.initialize()

        error = captured.exception
        diagnostic = format_safe_exception_diagnostic(error)
        self.assertIsInstance(error.__cause__, FileNotFoundError)
        self.assertIn("RuntimeError>FileNotFoundError", diagnostic)
        self.assertNotIn(str(missing_chain), diagnostic)
        self.assertNotIn(self.token, diagnostic)
        self.assertFalse(hasattr(service, "server"))

    async def test_mismatched_tls_key_keeps_safe_cause_and_binds_no_server(self) -> None:
        service = self.service_with_tls_paths(
            self.certificates.wrong_san_chain,
            self.certificates.valid_key,
        )

        with self.assertRaises(RuntimeError) as captured:
            await service.initialize()

        error = captured.exception
        diagnostic = format_safe_exception_diagnostic(error)
        self.assertIsInstance(error.__cause__, ssl.SSLError)
        self.assertIn("RuntimeError>SSLError", diagnostic)
        self.assertNotIn(str(self.certificates.wrong_san_chain), diagnostic)
        self.assertNotIn(str(self.certificates.valid_key), diagnostic)
        self.assertNotIn(self.token, diagnostic)
        self.assertFalse(hasattr(service, "server"))

    @contextlib.contextmanager
    def captured_protocol_logs(self) -> Iterator[io.StringIO]:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        loggers = [
            logging.getLogger("asyncio"),
            logging.getLogger("aiohttp.server"),
            logging.getLogger("aiohttp.access"),
            logging.getLogger("aiohttp.web_protocol"),
        ]
        previous = [(logger, logger.level, logger.propagate) for logger in loggers]
        for logger in loggers:
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
        try:
            yield stream
        finally:
            for logger, level, propagate in previous:
                logger.removeHandler(handler)
                logger.setLevel(level)
                logger.propagate = propagate
            handler.close()

    async def assert_handshake_rejected(
        self,
        chain: Path,
        key: Path,
        client_context: ssl.SSLContext,
    ) -> None:
        async with self.listener(chain, key) as (_service, base_url):
            connector = TCPConnector(ssl=client_context)
            with self.captured_protocol_logs() as logs:
                try:
                    async with ClientSession(connector=connector) as session:
                        await session.get(
                            f"{base_url}/api/v1",
                            headers={"Authorization": f"Bearer {self.token}"},
                        )
                except (aiohttp.ClientError, ssl.SSLError):
                    self.assertNotIn(self.token, logs.getvalue())
                    return
        self.fail("TLS peer accepted a certificate the client should reject")

    async def test_trusted_https_bearer_policy_cors_and_protocol_versions(self) -> None:
        certs = self.certificates
        async with self.listener(certs.valid_chain, certs.valid_key) as (_service, base_url):
            for version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
                if version == ssl.TLSVersion.TLSv1_3 and not ssl.HAS_TLSv1_3:
                    continue
                context = self.client_context(certs.ca_cert)
                context.minimum_version = version
                context.maximum_version = version
                connector = TCPConnector(ssl=context)
                async with ClientSession(connector=connector) as session:
                    async with session.get(
                        f"{base_url}/api/v1",
                        headers={
                            "Authorization": f"Bearer {self.token}",
                            "Origin": "https://caller.invalid",
                        },
                    ) as response:
                        # Pinning both client protocol bounds proves each TLS
                        # version completed a real loopback handshake.
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
                        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
                        self.assertEqual((await response.json())["version"], "1")

            for headers in (
                {"Authorization": "Bearer wrong-token"},
                {},
            ):
                context = self.client_context(certs.ca_cert)
                async with ClientSession(connector=TCPConnector(ssl=context)) as session:
                    async with session.get(f"{base_url}/api/v1", headers=headers) as response:
                        problem = await response.json()
                        self.assertEqual(response.status, 401)
                        self.assertEqual(response.headers["WWW-Authenticate"], 'Bearer realm="api"')
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
                        self.assertEqual(response.headers["X-Request-ID"], problem["requestId"])
                        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

            context = self.client_context(certs.ca_cert)
            async with ClientSession(connector=TCPConnector(ssl=context)) as session:
                async with session.options(
                    f"{base_url}/api/v1/tasks",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Origin": "https://caller.invalid",
                        "Access-Control-Request-Method": "GET",
                    },
                ) as response:
                    self.assertEqual(response.status, 405)
                    self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    async def test_old_tls_protocol_is_rejected(self) -> None:
        if not hasattr(ssl.TLSVersion, "TLSv1_1"):
            self.skipTest("This Python build does not expose TLS 1.1")
        certs = self.certificates
        async with self.listener(certs.valid_chain, certs.valid_key) as (_service, base_url):
            context = self.client_context(certs.ca_cert)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                context.minimum_version = ssl.TLSVersion.TLSv1_1
                context.maximum_version = ssl.TLSVersion.TLSv1_1
                context.set_ciphers("DEFAULT:@SECLEVEL=0")
            connector = TCPConnector(ssl=context)
            with self.captured_protocol_logs() as logs:
                with self.assertRaises((aiohttp.ClientError, ssl.SSLError)):
                    async with ClientSession(connector=connector) as session:
                        await session.get(
                            f"{base_url}/api/v1",
                            headers={"Authorization": f"Bearer {self.token}"},
                        )
                self.assertNotIn(self.token, logs.getvalue())

    async def test_untrusted_expired_wrong_san_and_retired_anchor_are_rejected(self) -> None:
        certs = self.certificates
        await self.assert_handshake_rejected(
            certs.valid_chain,
            certs.valid_key,
            self.client_context(),
        )
        await self.assert_handshake_rejected(
            certs.expired_chain,
            certs.expired_key,
            self.client_context(certs.ca_cert),
        )
        await self.assert_handshake_rejected(
            certs.wrong_san_chain,
            certs.wrong_san_key,
            self.client_context(certs.ca_cert),
        )
        await self.assert_handshake_rejected(
            certs.valid_chain,
            certs.valid_key,
            self.client_context(certs.retired_ca_cert),
        )

    async def test_plain_http_cannot_reach_read_or_mutation_handlers(self) -> None:
        certs = self.certificates
        async with self.listener(certs.valid_chain, certs.valid_key) as (_service, base_url):
            host, port = base_url.removeprefix("https://").rsplit(":", 1)
            plain_url = f"http://{host}:{port}"
            with self.captured_protocol_logs() as logs:
                async with ClientSession(connector=TCPConnector(ssl=False)) as session:
                    with self.assertRaises(aiohttp.ClientError):
                        await session.get(
                            f"{plain_url}/api/v1/tasks",
                            headers={"Authorization": f"Bearer {self.token}"},
                        )
                    with self.assertRaises(aiohttp.ClientError):
                        await session.post(
                            f"{plain_url}/api/v1/operations",
                            headers={
                                "Authorization": f"Bearer {self.token}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "id": "f4e32e00-f1c2-49c1-bf4b-9c10a58f6174",
                                "type": "create-task",
                                "target": {"kind": "tasks"},
                                "parameters": {"description": "must not be created"},
                            },
                        )
                self.assertNotIn(self.token, logs.getvalue())
        self.application.query_tasks.assert_not_called()
        self.application.submit_operation_async.assert_not_called()

    async def test_sslkeylogfile_does_not_export_session_secrets(self) -> None:
        certs = self.certificates
        keylog = Path(self.temporary_directory.name) / "environment-keylog.log"
        captured: list[ssl.SSLContext] = []
        service = HttpUserCommService(
            url="127.0.0.1",
            port=0,
            token=self.token,
            chat_id=1,
            agent=self.agent,
            tls_cert_chain_path=str(certs.valid_chain),
            tls_private_key_path=str(certs.valid_key),
            application_service=self.application,
            notification_history_store=self.notification_history_store,
        )
        factory = service._new_tls_context
        client_context = self.client_context(certs.ca_cert)

        def capture_context() -> ssl.SSLContext:
            context = factory()
            captured.append(context)
            return context

        with patch.dict(os.environ, {"SSLKEYLOGFILE": str(keylog)}):
            with patch.object(service, "_new_tls_context", side_effect=capture_context):
                await service.initialize()
            server_socket = service.site._server.sockets[0]
            port = server_socket.getsockname()[1]
            async with ClientSession(connector=TCPConnector(ssl=client_context)) as session:
                async with session.get(
                    f"https://127.0.0.1:{port}/api/v1",
                    headers={"Authorization": f"Bearer {self.token}"},
                ) as response:
                    self.assertEqual(response.status, 200)
            await service.shutdown()

        self.assertEqual(len(captured), 1)
        self.assertIsNone(captured[0].keylog_filename)
        self.assertFalse(keylog.exists())

    async def test_invalid_tls_material_fails_before_a_listener_exists(self) -> None:
        certs = self.certificates
        with tempfile.TemporaryDirectory(prefix="tls-invalid-") as temporary_directory:
            invalid = Path(temporary_directory)
            bad_certificate = invalid / "bad.pem"
            bad_key = invalid / "bad.key"
            bad_certificate.write_text("not a certificate", encoding="ascii")
            bad_key.write_text("not a private key", encoding="ascii")
            key_for_other_certificate = invalid / "other.key"
            key_for_other_certificate.write_bytes(certs.wrong_san_key.read_bytes())
            key_for_other_certificate.chmod(0o600)
            cases: tuple[tuple[Path | None, Path | None], ...] = (
                (None, certs.valid_key),
                (certs.valid_chain, None),
                (bad_certificate, bad_key),
                (certs.valid_chain, key_for_other_certificate),
                (certs.valid_chain, certs.encrypted_key),
            )
            for chain, key in cases:
                with self.subTest(chain=chain, key=key):
                    with socket.socket() as probe:
                        probe.bind(("127.0.0.1", 0))
                        port = probe.getsockname()[1]
                    service = HttpUserCommService(
                        url="127.0.0.1",
                        port=port,
                        token=self.token,
                        chat_id=1,
                        agent=self.agent,
                        tls_cert_chain_path=str(chain) if chain is not None else None,
                        tls_private_key_path=str(key) if key is not None else None,
                        application_service=self.application,
                        notification_history_store=self.notification_history_store,
                    )
                    with self.assertRaises(RuntimeError):
                        await service.initialize()
                    self.assertFalse(hasattr(service, "site"))
                    with self.assertRaises(OSError):
                        await asyncio.open_connection("127.0.0.1", port)

    async def test_problem_and_log_text_redact_exact_token_and_safe_marker(self) -> None:
        error_text = (
            f"provider failed for Bearer {self.token}; "
            "reference https://internal.invalid/path?credential=hidden"
        )
        application = Mock()
        application.query_tasks.side_effect = ValidationError(error_text)
        certs = self.certificates
        output = io.StringIO()
        error_output = io.StringIO()
        async with self.listener(certs.valid_chain, certs.valid_key, application) as (
            _service,
            base_url,
        ):
            context = self.client_context(certs.ca_cert)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
                async with ClientSession(connector=TCPConnector(ssl=context)) as session:
                    async with session.get(
                        f"{base_url}/api/v1/tasks",
                        headers={"Authorization": f"Bearer {self.token}"},
                    ) as response:
                        body = await response.text()
                        self.assertEqual(response.status, 400)
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(self.token, body + output.getvalue() + error_output.getvalue())
        self.assertNotIn("internal.invalid", body)
        self.assertEqual(safe_detail("[redactado]", "[redactado]"), "[redactado]")
        self.assertNotIn(self.token, safe_detail(self.token, self.token))
        self.assertEqual(Path(certs.valid_key).stat().st_mode & 0o777, 0o600)

    async def test_malformed_tls_request_does_not_log_exact_token(self) -> None:
        certs = self.certificates
        async with self.listener(certs.valid_chain, certs.valid_key) as (_service, base_url):
            port = int(base_url.rsplit(":", 1)[1])
            context = self.client_context(certs.ca_cert)
            with self.captured_protocol_logs() as logs:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1",
                    port,
                    ssl=context,
                    server_hostname="localhost",
                )
                raw_request = (
                    f"GET /api/v1/tasks?token={self.token} HTTP/1.1\r\n"
                    "Host: 127.0.0.1\r\n"
                    f"Authorization: Bearer {self.token}\x01\r\n\r\n"
                ).encode("ascii")
                writer.write(raw_request)
                await writer.drain()
                reply = await asyncio.wait_for(reader.read(4096), timeout=3)
                writer.close()
                await writer.wait_closed()
            header_block, separator, response_body = reply.partition(b"\r\n\r\n")
            self.assertTrue(separator)
            response_lines = header_block.split(b"\r\n")
            self.assertIn(b" 400 ", response_lines[0])
            response_headers = {
                name.strip().lower(): value.strip()
                for line in response_lines[1:]
                if b":" in line
                for name, value in [line.split(b":", 1)]
            }
            self.assertEqual(response_headers.get(b"cache-control"), b"no-store")
            request_id = response_headers.get(b"x-request-id")
            self.assertIsNotNone(request_id)
            assert request_id is not None
            decoded_request_id = request_id.decode("ascii")
            parsed_request_id = uuid.UUID(decoded_request_id)
            self.assertEqual(len(parsed_request_id.hex), 32)
            self.assertTrue(
                response_headers.get(b"content-type", b"").startswith(b"text/plain")
            )
            self.assertEqual(response_body.strip(), b"Invalid HTTP request")
            self.assertNotIn(self.token.encode("ascii"), reply)
            self.assertNotIn(self.token, logs.getvalue())
            self.application.query_tasks.assert_not_called()
            self.application.submit_operation_async.assert_not_called()


if __name__ == "__main__":
    unittest.main()
