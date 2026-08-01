from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "plugins" / "bldgtyp" / "lib"

sys.path.insert(0, str(LIB))

from phn_agent import (  # noqa: E402
    Credential,
    HttpResponse,
    PersistentHttpTransport,
    PhnAgentError,
    _response_messages,
    _validated_url,
    device_login,
    load_credentials,
    run_proxy,
    write_credentials,
)


class CredentialTests(unittest.TestCase):
    def test_write_credentials_is_owner_only_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "credentials.json"
            write_credentials(
                path,
                api_url="https://api.example.test/",
                token="test-token",
                label="Test machine",
            )

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            credential = load_credentials(path)
            self.assertEqual(credential.api_url, "https://api.example.test")
            self.assertEqual(credential.token, "test-token")

    def test_load_rejects_group_readable_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            write_credentials(
                path,
                api_url="https://api.example.test",
                token="test-token",
                label="Test machine",
            )
            path.chmod(0o640)

            with self.assertRaisesRegex(PhnAgentError, "0600"):
                load_credentials(path)


class DeviceLoginTests(unittest.TestCase):
    def test_pending_login_redeems_once_without_logging_token(self) -> None:
        responses = iter(
            [
                {
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://www.example.test/approve-agent?code=ABCD-EFGH",
                    "interval": 1,
                    "expires_in": 30,
                },
                {"status": "authorization_pending", "interval": 1},
                {
                    "status": "approved",
                    "token": "test-token",
                    "token_record": {"label": "Test machine"},
                },
            ]
        )
        calls: list[tuple[str, object]] = []
        logs: list[str] = []

        def post_json(url: str, payload: object) -> dict[str, object]:
            calls.append((url, payload))
            return next(responses)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            credential = device_login(
                api_url="https://api.example.test",
                path=path,
                label="Test machine",
                open_browser=False,
                post_json=post_json,
                sleep=lambda _seconds: None,
                monotonic=lambda: 0,
                log=logs.append,
            )

            self.assertEqual(credential.token, "test-token")
            self.assertEqual(len(calls), 3)
            self.assertNotIn("test-token", "\n".join(logs))


class TransportTests(unittest.TestCase):
    def test_non_local_http_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(PhnAgentError, "require HTTPS"):
            _validated_url("http://api.example.test")

    def test_local_http_requires_explicit_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PhnAgentError, "local HTTP requires"):
                _validated_url("http://127.0.0.1:8000")
        with patch.dict(os.environ, {"PHN_ALLOW_INSECURE_LOCALHOST": "1"}, clear=True):
            self.assertEqual(
                _validated_url("http://127.0.0.1:8000/"),
                "http://127.0.0.1:8000",
            )

    def test_persistent_transport_preserves_post_and_auth_on_307(self) -> None:
        class Response:
            def __init__(self, status: int, headers: list[tuple[str, str]]) -> None:
                self.status = status
                self._headers = headers

            def getheaders(self) -> list[tuple[str, str]]:
                return self._headers

            def read(self) -> bytes:
                return b"{}"

        class Connection:
            def __init__(self) -> None:
                self.requests: list[tuple[str, str, dict[str, str]]] = []
                self.responses = iter(
                    [
                        Response(307, [("Location", "/mcp/")]),
                        Response(200, []),
                    ]
                )

            def request(
                self,
                method: str,
                path: str,
                *,
                body: bytes,
                headers: dict[str, str],
            ) -> None:
                self.requests.append((method, path, headers))

            def getresponse(self) -> Response:
                return next(self.responses)

        transport = PersistentHttpTransport()
        connection = Connection()
        with patch.object(transport, "_connection", return_value=connection):
            response = transport.request(
                "https://api.example.test/mcp",
                payload={"jsonrpc": "2.0"},
                headers={"Authorization": "Bearer test-token"},
                timeout=1,
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(
            [(method, path) for method, path, _headers in connection.requests],
            [("POST", "/mcp"), ("POST", "/mcp/")],
        )
        self.assertTrue(
            all(
                headers["Authorization"] == "Bearer test-token"
                for _method, _path, headers in connection.requests
            )
        )

    def test_persistent_transport_never_replays_an_indeterminate_post(self) -> None:
        transport = PersistentHttpTransport()

        class Connection:
            request_count = 0

            def request(self, *_args: object, **_kwargs: object) -> None:
                self.request_count += 1

            def getresponse(self) -> object:
                raise OSError("connection dropped after request")

        connection = Connection()
        with (
            patch.object(transport, "_connection", return_value=connection),
            patch.object(transport, "_discard") as discard,
            self.assertRaisesRegex(PhnAgentError, "Could not reach"),
        ):
            transport.request(
                "https://api.example.test/mcp",
                payload={"jsonrpc": "2.0"},
                headers={"Authorization": "Bearer test-token"},
                timeout=1,
            )

        self.assertEqual(connection.request_count, 1)
        discard.assert_called_once()

    def test_sse_response_emits_each_jsonrpc_message(self) -> None:
        response = HttpResponse(
            200,
            {"content-type": "text/event-stream; charset=utf-8"},
            b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
        )
        self.assertEqual(
            list(_response_messages(response)), ['{"jsonrpc":"2.0","id":1,"result":{}}']
        )

    def test_proxy_forwards_bearer_without_printing_it(self) -> None:
        requests: list[tuple[str, object, dict[str, str]]] = []
        credential = Credential("https://api.example.test", "test-token", "Test", "now")

        def provider(_path: Path, _force: bool) -> Credential:
            return credential

        def request(
            url: str, *, payload: object, headers: dict[str, str], timeout: float
        ) -> HttpResponse:
            requests.append((url, payload, headers))
            return HttpResponse(
                200,
                {"content-type": "application/json"},
                b'{"jsonrpc":"2.0","id":1,"result":{}}',
            )

        stdout = io.StringIO()
        run_proxy(
            path=Path("unused"),
            stdin=io.StringIO('{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'),
            stdout=stdout,
            request=request,
            credential_provider=provider,
        )

        self.assertEqual(requests[0][0], "https://api.example.test/mcp")
        self.assertEqual(requests[0][2]["Authorization"], "Bearer test-token")
        self.assertNotIn("test-token", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["id"], 1)

    def test_proxy_reauthorizes_once_after_401(self) -> None:
        force_values: list[bool] = []
        credentials = {
            False: Credential(
                "https://api.example.test", "old-token", "Test", "before"
            ),
            True: Credential("https://api.example.test", "new-token", "Test", "after"),
        }

        def provider(_path: Path, force: bool) -> Credential:
            force_values.append(force)
            return credentials[force]

        def request(
            _url: str, *, payload: object, headers: dict[str, str], timeout: float
        ) -> HttpResponse:
            if headers["Authorization"] == "Bearer old-token":
                return HttpResponse(401, {"content-type": "application/json"}, b"{}")
            return HttpResponse(202, {}, b"")

        run_proxy(
            path=Path("unused"),
            stdin=io.StringIO(
                '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            ),
            stdout=io.StringIO(),
            request=request,
            credential_provider=provider,
        )
        self.assertEqual(force_values, [False, True])

    def test_proxy_uses_the_server_negotiated_protocol_version(self) -> None:
        headers_by_method: dict[str, dict[str, str]] = {}
        credential = Credential("https://api.example.test", "test-token", "Test", "now")

        def request(
            _url: str, *, payload: object, headers: dict[str, str], timeout: float
        ) -> HttpResponse:
            self.assertIsInstance(payload, dict)
            method = payload["method"]  # type: ignore[index]
            headers_by_method[method] = headers
            if method == "initialize":
                return HttpResponse(
                    200,
                    {"content-type": "application/json"},
                    b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}',
                )
            return HttpResponse(202, {}, b"")

        run_proxy(
            path=Path("unused"),
            stdin=io.StringIO(
                '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                '"params":{"protocolVersion":"2025-06-18"}}\n'
                '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            ),
            stdout=io.StringIO(),
            request=request,
            credential_provider=lambda _path, _force: credential,
        )

        self.assertNotIn("MCP-Protocol-Version", headers_by_method["initialize"])
        self.assertEqual(
            headers_by_method["notifications/initialized"]["MCP-Protocol-Version"],
            "2024-11-05",
        )

    def test_proxy_runs_independent_tool_calls_concurrently(self) -> None:
        credential = Credential("https://api.example.test", "test-token", "Test", "now")
        barrier = threading.Barrier(2)
        active = 0
        maximum_active = 0
        lock = threading.Lock()

        def request(
            _url: str, *, payload: object, headers: dict[str, str], timeout: float
        ) -> HttpResponse:
            nonlocal active, maximum_active
            self.assertIsInstance(payload, dict)
            message = payload  # type: ignore[assignment]
            if message["method"] == "initialize":
                return HttpResponse(
                    200,
                    {"content-type": "application/json"},
                    b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}',
                )
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            barrier.wait(timeout=2)
            with lock:
                active -= 1
            body = json.dumps(
                {"jsonrpc": "2.0", "id": message["id"], "result": {}}
            ).encode()
            return HttpResponse(200, {"content-type": "application/json"}, body)

        stdout = io.StringIO()
        run_proxy(
            path=Path("unused"),
            stdin=io.StringIO(
                '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
                '{"jsonrpc":"2.0","id":2,"method":"tools/call"}\n'
                '{"jsonrpc":"2.0","id":3,"method":"tools/call"}\n'
            ),
            stdout=stdout,
            request=request,
            credential_provider=lambda _path, _force: credential,
        )

        self.assertEqual(maximum_active, 2)
        self.assertEqual(
            {json.loads(line)["id"] for line in stdout.getvalue().splitlines()},
            {1, 2, 3},
        )

    def test_proxy_relays_initialization_error_unchanged(self) -> None:
        credential = Credential("https://api.example.test", "test-token", "Test", "now")
        server_error = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32602, "message": "Unsupported protocol"},
        }

        stdout = io.StringIO()
        run_proxy(
            path=Path("unused"),
            stdin=io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'),
            stdout=stdout,
            request=lambda *_args, **_kwargs: HttpResponse(
                200,
                {"content-type": "application/json"},
                json.dumps(server_error).encode(),
            ),
            credential_provider=lambda _path, _force: credential,
        )

        self.assertEqual(json.loads(stdout.getvalue()), server_error)

    def test_proxy_translates_unexpected_worker_failure(self) -> None:
        credential = Credential("https://api.example.test", "test-token", "Test", "now")
        stdout = io.StringIO()

        with patch("sys.stderr", new=io.StringIO()):
            run_proxy(
                path=Path("unused"),
                stdin=io.StringIO('{"jsonrpc":"2.0","id":7,"method":"tools/list"}\n'),
                stdout=stdout,
                request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("boom")
                ),
                credential_provider=lambda _path, _force: credential,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["id"], 7)
        self.assertEqual(payload["error"]["code"], -32000)
        self.assertEqual(
            payload["error"]["message"], "PH-Navigator MCP bridge failed locally."
        )

    def test_invalid_stdio_json_uses_parse_error_code(self) -> None:
        credential = Credential("https://api.example.test", "test-token", "Test", "now")
        stdout = io.StringIO()
        run_proxy(
            path=Path("unused"),
            stdin=io.StringIO("not-json\n"),
            stdout=stdout,
            credential_provider=lambda _path, _force: credential,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["id"], None)
        self.assertEqual(payload["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
