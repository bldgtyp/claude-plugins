"""Dependency-free PH-Navigator device login and MCP transport bridge."""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import os
import platform
import stat
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((PLUGIN_ROOT / "config" / "phn.json").read_text(encoding="utf-8"))
DEFAULT_API_URL = cast(str, CONFIG["api_url"])
DEFAULT_SCOPES = tuple(cast(list[str], CONFIG["scopes"]))
DEVICE_CONFIG = cast(dict[str, object], CONFIG["device"])
CREDENTIAL_FIELDS = cast(dict[str, str], DEVICE_CONFIG["credential_fields"])
TERMINAL_STATUSES = cast(dict[str, str], DEVICE_CONFIG["terminal_statuses"])
USER_AGENT = "bldgtyp-phn-agent/0.1.1"


class PhnAgentError(RuntimeError):
    """A safe, user-facing PH-Navigator agent error."""


class AuthorizationRequired(PhnAgentError):
    """The remote MCP endpoint rejected the stored credential."""


@dataclass(frozen=True)
class Credential:
    api_url: str
    token: str
    label: str
    issued: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class PersistentHttpTransport:
    """Keep one reusable HTTP connection per bridge worker thread."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _connections(
        self,
    ) -> dict[tuple[str, str, int | None], http.client.HTTPConnection]:
        connections = getattr(self._local, "connections", None)
        if connections is None:
            connections = {}
            self._local.connections = connections
        return cast(
            dict[tuple[str, str, int | None], http.client.HTTPConnection], connections
        )

    def _connection(
        self, parsed: urllib.parse.SplitResult, timeout: float
    ) -> http.client.HTTPConnection:
        hostname = parsed.hostname
        if hostname is None:
            raise PhnAgentError("PH-Navigator MCP URL has no host.")
        key = (parsed.scheme, hostname, parsed.port)
        connections = self._connections()
        connection = connections.get(key)
        if connection is None:
            connection_class = (
                http.client.HTTPSConnection
                if parsed.scheme == "https"
                else http.client.HTTPConnection
            )
            connection = connection_class(hostname, parsed.port, timeout=timeout)
            connections[key] = connection
        return connection

    def _discard(self, parsed: urllib.parse.SplitResult) -> None:
        hostname = parsed.hostname
        if hostname is None:
            return
        connection = self._connections().pop(
            (parsed.scheme, hostname, parsed.port), None
        )
        if connection is not None:
            connection.close()

    def request(
        self,
        url: str,
        *,
        payload: object,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            **headers,
        }
        current_url = _validated_url(url)
        original_origin = urllib.parse.urlsplit(current_url)[:2]
        for _redirect in range(3):
            parsed = urllib.parse.urlsplit(current_url)
            path = urllib.parse.urlunsplit(
                ("", "", parsed.path or "/", parsed.query, "")
            )
            connection = self._connection(parsed, timeout)
            try:
                connection.request("POST", path, body=body, headers=request_headers)
                response = connection.getresponse()
                result = HttpResponse(
                    status=response.status,
                    headers={
                        key.lower(): value for key, value in response.getheaders()
                    },
                    body=response.read(),
                )
            except (OSError, http.client.HTTPException) as exc:
                self._discard(parsed)
                raise PhnAgentError(f"Could not reach PH-Navigator: {exc}") from exc
            if result.status not in {307, 308}:
                return result
            location = result.headers.get("location")
            if not location:
                return result
            redirected_url = urllib.parse.urljoin(current_url, location)
            if urllib.parse.urlsplit(redirected_url)[:2] != original_origin:
                raise PhnAgentError(
                    "PH-Navigator refused a cross-origin redirect to protect the credential."
                )
            current_url = redirected_url
        raise PhnAgentError("PH-Navigator returned too many redirects.")


MCP_HTTP_TRANSPORT = PersistentHttpTransport()


def credentials_path() -> Path:
    configured = os.environ.get("PHN_CREDENTIALS_PATH")
    return Path(configured or cast(str, CONFIG["credentials_path"])).expanduser()


def _validated_url(value: object) -> str:
    if not isinstance(value, str):
        raise PhnAgentError("PH-Navigator URL must be a string.")
    parsed = urllib.parse.urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }
    if parsed.scheme != "https" and not (
        local_http and os.environ.get("PHN_ALLOW_INSECURE_LOCALHOST") == "1"
    ):
        raise PhnAgentError(
            "PH-Navigator URLs require HTTPS; local HTTP requires PHN_ALLOW_INSECURE_LOCALHOST=1."
        )
    if not parsed.netloc or parsed.username or parsed.password:
        raise PhnAgentError(
            "PH-Navigator URL must include a host and no embedded credentials."
        )
    return value.rstrip("/")


def load_credentials(path: Path) -> Credential:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        raise
    if mode & 0o077:
        raise PhnAgentError(
            f"Credential file permissions must be 0600, not {mode:04o}: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhnAgentError(
            f"Could not read PH-Navigator credentials at {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PhnAgentError(
            f"PH-Navigator credential file must contain a JSON object: {path}"
        )
    token = payload.get(CREDENTIAL_FIELDS["token"])
    label = payload.get(CREDENTIAL_FIELDS["label"])
    issued = payload.get(CREDENTIAL_FIELDS["issued"])
    if not all(isinstance(value, str) and value for value in (token, label, issued)):
        raise PhnAgentError(
            f"PH-Navigator credential file is missing token metadata: {path}"
        )
    return Credential(
        api_url=_validated_url(payload.get(CREDENTIAL_FIELDS["api_url"])),
        token=cast(str, token),
        label=cast(str, label),
        issued=cast(str, issued),
    )


def write_credentials(path: Path, *, api_url: str, token: str, label: str) -> None:
    """Atomically replace the credential file with owner-only permissions."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    payload = {
        CREDENTIAL_FIELDS["api_url"]: _validated_url(api_url),
        CREDENTIAL_FIELDS["token"]: token,
        CREDENTIAL_FIELDS["label"]: label,
        CREDENTIAL_FIELDS["issued"]: datetime.now(timezone.utc).isoformat(),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _json_payload(response: HttpResponse) -> dict[str, Any]:
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhnAgentError("PH-Navigator returned an invalid JSON response.") from exc
    if not isinstance(payload, dict):
        raise PhnAgentError("PH-Navigator returned a non-object JSON response.")
    return cast(dict[str, Any], payload)


def _post_json(url: str, payload: object) -> dict[str, Any]:
    response = MCP_HTTP_TRANSPORT.request(
        url,
        payload=payload,
        headers={"Accept": "application/json"},
        timeout=20,
    )
    if response.status < 200 or response.status >= 300:
        raise PhnAgentError(f"PH-Navigator request failed with HTTP {response.status}.")
    return _json_payload(response)


def default_label() -> str:
    client = os.environ.get("PHN_AGENT_CLIENT", "agent")
    return f"{platform.node() or 'Local machine'} ({client})"


def device_login(
    *,
    api_url: str,
    path: Path,
    label: str,
    scopes: Iterable[str] = DEFAULT_SCOPES,
    open_browser: bool = True,
    post_json: Callable[[str, object], dict[str, Any]] = _post_json,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] | None = None,
) -> Credential:
    """Run one browser-approved login without exposing the bearer token."""
    logger = log or (lambda message: print(message, file=sys.stderr, flush=True))
    api_url = _validated_url(api_url)
    started = post_json(
        f"{api_url}{cast(str, DEVICE_CONFIG['start_path'])}",
        {"label": label, "scopes": list(scopes)},
    )
    device_code = started.get("device_code")
    user_code = started.get("user_code")
    verification_url = started.get("verification_url")
    interval = started.get("interval")
    expires_in = started.get("expires_in")
    if not (
        isinstance(device_code, str)
        and isinstance(user_code, str)
        and isinstance(verification_url, str)
        and isinstance(interval, int)
        and interval > 0
        and isinstance(expires_in, int)
        and expires_in > 0
    ):
        raise PhnAgentError("PH-Navigator returned an invalid device-login request.")

    logger(f"Approve PH-Navigator agent access in your browser: {verification_url}")
    logger(f"User code: {user_code}")
    if open_browser:
        webbrowser.open(verification_url)

    deadline = monotonic() + expires_in
    current_interval = interval
    while monotonic() < deadline:
        sleep(current_interval)
        polled = post_json(
            f"{api_url}{cast(str, DEVICE_CONFIG['poll_path'])}",
            {"device_code": device_code},
        )
        status_value = polled.get("status")
        if status_value == TERMINAL_STATUSES["approved"]:
            token = polled.get("token")
            if not isinstance(token, str) or not token:
                raise PhnAgentError(
                    "PH-Navigator approved login without returning a token."
                )
            write_credentials(path, api_url=api_url, token=token, label=label)
            logger(f"PH-Navigator credentials saved to {path} (mode 0600).")
            return load_credentials(path)
        if status_value in set(cast(list[str], DEVICE_CONFIG["pending_statuses"])):
            next_interval = polled.get("interval")
            if not isinstance(next_interval, int) or next_interval <= 0:
                raise PhnAgentError(
                    "PH-Navigator returned an invalid polling interval."
                )
            current_interval = next_interval
            continue
        if status_value == TERMINAL_STATUSES["denied"]:
            raise PhnAgentError("Agent access was denied in PH-Navigator.")
        if status_value == TERMINAL_STATUSES["expired"]:
            raise PhnAgentError("Agent login expired; start it again.")
        raise PhnAgentError("PH-Navigator returned an unknown device-login status.")
    raise PhnAgentError("Agent login expired before approval.")


def ensure_credentials(path: Path, *, force_login: bool = False) -> Credential:
    if not force_login:
        try:
            return load_credentials(path)
        except FileNotFoundError:
            pass
    return device_login(
        api_url=os.environ.get("PHN_API_URL", DEFAULT_API_URL),
        path=path,
        label=os.environ.get("PHN_AGENT_LABEL", default_label()),
        open_browser=os.environ.get("PHN_NO_BROWSER") != "1",
    )


def _sse_messages(body: bytes) -> Iterator[str]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PhnAgentError("PH-Navigator returned invalid SSE text.") from exc
    data_lines: list[str] = []
    for line in [*text.splitlines(), ""]:
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())


def _response_messages(response: HttpResponse) -> Iterator[str]:
    if response.status == 202 or not response.body:
        return
    content_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type == "text/event-stream":
        yield from _sse_messages(response.body)
        return
    try:
        text = response.body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise PhnAgentError("PH-Navigator MCP returned an invalid response.") from exc
    yield text


def _jsonrpc_error(message: object, text: str, *, code: int = -32000) -> str | None:
    if not isinstance(message, dict) or "id" not in message:
        return None
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": code, "message": text},
        },
        separators=(",", ":"),
    )


def _send_mcp(
    message: object,
    credential: Credential,
    *,
    protocol_version: str | None,
    request: Callable[..., HttpResponse] | None = None,
) -> HttpResponse:
    endpoint = _validated_url(
        os.environ.get(
            "PHN_MCP_URL",
            f"{credential.api_url}{cast(str, CONFIG['mcp_path'])}",
        )
    )
    headers = {"Authorization": f"Bearer {credential.token}"}
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version
    requester = request or MCP_HTTP_TRANSPORT.request
    response = requester(endpoint, payload=message, headers=headers, timeout=90)
    if response.status == 401:
        raise AuthorizationRequired(
            "Stored PH-Navigator credentials are expired or revoked."
        )
    return response


def run_proxy(
    *,
    path: Path,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    request: Callable[..., HttpResponse] | None = None,
    credential_provider: Callable[[Path, bool], Credential] | None = None,
) -> None:
    """Bridge newline-delimited stdio JSON-RPC to stateless Streamable HTTP."""
    provider = credential_provider or (
        lambda credential_path, force: ensure_credentials(
            credential_path, force_login=force
        )
    )
    credential = provider(path, False)
    protocol_version: str | None = None
    credential_lock = threading.Lock()
    refresh_lock = threading.Lock()
    output_lock = threading.Lock()
    protocol_lock = threading.Lock()
    pending_slots = threading.Semaphore(8)

    def emit(response_message: str) -> None:
        with output_lock:
            print(response_message, file=stdout, flush=True)

    def handle(message: object, *, initialize: bool = False) -> None:
        nonlocal credential, protocol_version
        try:
            with credential_lock:
                request_credential = credential
            with protocol_lock:
                request_protocol = None if initialize else protocol_version
            try:
                response = _send_mcp(
                    message,
                    request_credential,
                    protocol_version=request_protocol,
                    request=request,
                )
            except AuthorizationRequired:
                with refresh_lock:
                    with credential_lock:
                        if credential.token == request_credential.token:
                            credential = provider(path, True)
                        request_credential = credential
                response = _send_mcp(
                    message,
                    request_credential,
                    protocol_version=request_protocol,
                    request=request,
                )
            if response.status < 200 or response.status >= 300:
                error = _jsonrpc_error(
                    message,
                    f"PH-Navigator MCP request failed with HTTP {response.status}.",
                )
                if error:
                    emit(error)
                return
            response_messages = list(_response_messages(response))
            if initialize:
                initialization_error = False
                for response_message in response_messages:
                    try:
                        payload = json.loads(response_message)
                    except json.JSONDecodeError as exc:
                        raise PhnAgentError(
                            "PH-Navigator initialization returned invalid JSON."
                        ) from exc
                    if isinstance(payload, dict) and "error" in payload:
                        initialization_error = True
                        break
                    result = (
                        payload.get("result") if isinstance(payload, dict) else None
                    )
                    negotiated = (
                        result.get("protocolVersion")
                        if isinstance(result, dict)
                        else None
                    )
                    if isinstance(negotiated, str):
                        with protocol_lock:
                            protocol_version = negotiated
                        break
                if not initialization_error and protocol_version is None:
                    raise PhnAgentError(
                        "PH-Navigator initialization did not negotiate an MCP protocol version."
                    )
            for response_message in response_messages:
                emit(response_message)
        except PhnAgentError as exc:
            error = _jsonrpc_error(message, str(exc))
            if error:
                emit(error)
        except Exception as exc:
            print(
                f"PH-Navigator MCP bridge worker failed: {type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
            error = _jsonrpc_error(message, "PH-Navigator MCP bridge failed locally.")
            if error:
                emit(error)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="phn-mcp"
    ) as executor:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                emit(
                    cast(
                        str,
                        _jsonrpc_error(
                            {"id": None}, "Invalid JSON-RPC input.", code=-32700
                        ),
                    )
                )
                continue
            method = message.get("method") if isinstance(message, dict) else None
            if method == "initialize":
                handle(message, initialize=True)
                continue
            if method == "notifications/initialized":
                handle(message)
                continue
            pending_slots.acquire()
            future = executor.submit(handle, message)
            future.add_done_callback(lambda _future: pending_slots.release())


def login_main() -> None:
    parser = argparse.ArgumentParser(
        description="Authorize this machine for PH-Navigator without copying a token."
    )
    parser.add_argument("--api", default=os.environ.get("PHN_API_URL", DEFAULT_API_URL))
    parser.add_argument(
        "--label", default=os.environ.get("PHN_AGENT_LABEL", default_label())
    )
    parser.add_argument("--credentials", type=Path, default=credentials_path())
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        device_login(
            api_url=args.api,
            path=args.credentials,
            label=args.label,
            open_browser=not args.no_browser,
        )
    except PhnAgentError as exc:
        raise SystemExit(f"PH-Navigator login failed: {exc}") from exc


def proxy_main() -> None:
    try:
        run_proxy(path=credentials_path())
    except (PhnAgentError, OSError) as exc:
        print(f"PH-Navigator MCP bridge failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
