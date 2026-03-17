"""SignalK WebSocket client with device access authentication.

Handles the full lifecycle:
1. Discovery: Probe /signalk endpoint to find API and WS URLs.
2. Authentication: Device access request flow (clientId + polling).
3. WebSocket: Connect, subscribe to all self paths, stream deltas.
4. Reconnection: Exponential backoff on failures.
5. Sending: PUT/POST deltas back to SignalK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

import httpx
import websockets

from .const import (
    AUTH_DEVICE_DESCRIPTION,
    AUTH_POLL_INTERVAL_S,
    SK_API_ACCESS_REQUESTS,
    SK_API_DISCOVERY,
    SK_API_SELF,
    SK_WS_STREAM,
)

_LOGGER = logging.getLogger(__name__)

# Reconnect delays with exponential backoff (seconds)
RECONNECT_DELAYS = [1, 2, 5, 10, 30]


class SignalKAuthError(Exception):
    """Raised when authentication fails permanently."""


class SignalKConnectionError(Exception):
    """Raised when we cannot connect to SignalK."""


class SignalKClient:
    """Async SignalK WebSocket client with authentication.

    Usage::

        client = SignalKClient(base_url="http://localhost:3000")
        await client.authenticate()
        await client.run(on_delta=my_callback)
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        client_id: str | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: SignalK server base URL (e.g. http://localhost:3000).
            token: Pre-existing JWT token (from config entry storage).
            client_id: Pre-existing client ID (from config entry storage).
        """
        # Normalize base URL
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client_id = client_id or str(uuid.uuid4())
        self._ws: Optional[Any] = None
        self._self_context: str = "vessels.self"
        self._connected = False
        self._stop_event = asyncio.Event()
        self._server_info: dict[str, Any] = {}

        # Callbacks
        self._on_delta: Optional[Callable] = None
        self._on_connect: Optional[Callable] = None
        self._on_disconnect: Optional[Callable] = None

    @property
    def base_url(self) -> str:
        """Return the base URL."""
        return self._base_url

    @property
    def token(self) -> str | None:
        """Return the current auth token."""
        return self._token

    @property
    def client_id(self) -> str:
        """Return the client ID."""
        return self._client_id

    @property
    def connected(self) -> bool:
        """Return whether we have an active WebSocket connection."""
        return self._connected

    @property
    def server_info(self) -> dict[str, Any]:
        """Return server info from the hello message."""
        return self._server_info

    @property
    def self_context(self) -> str:
        """Return the vessel self context string."""
        return self._self_context

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover(self) -> dict[str, Any]:
        """Probe the /signalk discovery endpoint.

        Returns the discovery JSON, or raises SignalKConnectionError.
        """
        url = f"{self._base_url}{SK_API_DISCOVERY}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                _LOGGER.debug("Discovery response: %s", data)
                return data
        except Exception as exc:
            raise SignalKConnectionError(
                f"Cannot reach SignalK at {url}: {exc}"
            ) from exc

    async def check_connection(self) -> bool:
        """Quick connectivity check against the SignalK discovery endpoint."""
        try:
            await self.discover()
            return True
        except SignalKConnectionError:
            return False

    # ------------------------------------------------------------------
    # Authentication (Device Access Request flow)
    # ------------------------------------------------------------------

    async def validate_token(self) -> bool:
        """Check whether the stored token is still valid."""
        if not self._token:
            return False

        url = f"{self._base_url}{SK_API_SELF}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if resp.status_code == 200:
                    _LOGGER.debug("Token is valid")
                    return True
                _LOGGER.debug("Token validation returned %d", resp.status_code)
                return False
        except Exception as exc:
            _LOGGER.warning("Token validation error: %s", exc)
            return False

    async def request_device_access(self) -> str | None:
        """Request device access and poll until approved/denied.

        Returns the JWT token on approval, or None on denial/timeout.
        This will block until the user approves the request in the
        SignalK admin UI.
        """
        url = f"{self._base_url}{SK_API_ACCESS_REQUESTS}"
        body = {
            "clientId": self._client_id,
            "description": AUTH_DEVICE_DESCRIPTION,
            "permissions": "readwrite",
        }

        _LOGGER.info(
            "Requesting device access at %s (clientId=%s)",
            url,
            self._client_id,
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=body)
                if resp.status_code not in (200, 202):
                    _LOGGER.error(
                        "Access request failed: HTTP %d — %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return None

                data = resp.json()
                href = data.get("href", "")
                if not href:
                    _LOGGER.error("No href in access request response: %s", data)
                    return None

                _LOGGER.info(
                    "Access request submitted (state=%s). "
                    "Approve in SignalK Admin UI → Security → Access Requests",
                    data.get("state"),
                )
        except Exception as exc:
            _LOGGER.error("Failed to submit access request: %s", exc)
            return None

        # Poll for approval
        return await self._poll_access_request(href)

    async def _poll_access_request(self, href: str) -> str | None:
        """Poll an access request until COMPLETED."""
        poll_url = f"{self._base_url}{href}"
        elapsed = 0.0

        while not self._stop_event.is_set():
            await asyncio.sleep(AUTH_POLL_INTERVAL_S)
            elapsed += AUTH_POLL_INTERVAL_S

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(poll_url)
                    if resp.status_code != 200:
                        _LOGGER.debug(
                            "Access poll returned HTTP %d, retrying…",
                            resp.status_code,
                        )
                        continue

                    data = resp.json()
                    state = data.get("state", "")

                    if state == "PENDING":
                        if int(elapsed) % 60 == 0:
                            _LOGGER.info(
                                "Waiting for access approval (%.0fs elapsed)…",
                                elapsed,
                            )
                        continue

                    if state == "COMPLETED":
                        access_req = data.get("accessRequest", {})
                        permission = access_req.get("permission", "")
                        token = access_req.get("token")

                        if permission == "APPROVED" and token:
                            _LOGGER.info("Device access APPROVED")
                            return token
                        if permission == "DENIED":
                            _LOGGER.error("Device access DENIED")
                            return None

                        _LOGGER.error("Unexpected result: permission=%s", permission)
                        return None

            except Exception as exc:
                _LOGGER.warning("Access poll error: %s — will retry", exc)

        return None

    async def authenticate(self) -> bool:
        """Run the full auth flow: validate existing token or request new access.

        Returns True if we have a valid token.
        """
        # Try existing token
        if self._token and await self.validate_token():
            return True

        self._token = None

        # Request new device access
        token = await self.request_device_access()
        if token:
            self._token = token
            return True

        return False

    # ------------------------------------------------------------------
    # REST API helpers
    # ------------------------------------------------------------------

    async def get_self_data(self) -> dict[str, Any]:
        """GET /signalk/v1/api/vessels/self — full vessel self data tree."""
        url = f"{self._base_url}{SK_API_SELF}"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            _LOGGER.error("Failed to get self data: %s", exc)
            return {}

    async def get_path_meta(self, path: str) -> dict[str, Any]:
        """GET metadata for a specific path from the REST API."""
        # Convert dotted path to URL path
        url_path = path.replace(".", "/")
        url = f"{self._base_url}{SK_API_SELF}/{url_path}/meta"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
                return {}
        except Exception:
            return {}

    async def put_value(self, path: str, value: Any) -> dict[str, Any]:
        """PUT a value to a SignalK path via REST API."""
        url_path = path.replace(".", "/")
        url = f"{self._base_url}{SK_API_SELF}/{url_path}"
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        body = {"value": value}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(url, json=body, headers=headers)
                return {
                    "status": resp.status_code,
                    "body": resp.json() if resp.text else {},
                }
        except Exception as exc:
            _LOGGER.error("PUT %s failed: %s", path, exc)
            return {"status": 500, "error": str(exc)}

    async def post_delta(self, path: str, value: Any) -> bool:
        """Send a delta update for a path via WebSocket (preferred) or REST.

        This is used when setting a sensor value from HA to push it
        back to SignalK as a delta for that path.
        """
        delta = {
            "context": "vessels.self",
            "updates": [
                {
                    "source": {
                        "label": "homeassistant.signalk_bridge",
                        "type": "signalk",
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "values": [{"path": path, "value": value}],
                }
            ],
        }

        # Try WebSocket first
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps(delta))
                _LOGGER.debug("Sent delta via WS for %s", path)
                return True
            except Exception as exc:
                _LOGGER.warning(
                    "WS delta send failed for %s: %s — falling back to REST",
                    path,
                    exc,
                )

        # Fallback to REST API delta endpoint
        url = f"{self._base_url}/signalk/v1/api/vessels/self/{path.replace('.', '/')}"
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(url, json={"value": value}, headers=headers)
                if resp.status_code in (200, 202):
                    _LOGGER.debug("Sent value via REST PUT for %s", path)
                    return True
                _LOGGER.error("REST PUT for %s returned %d", path, resp.status_code)
                return False
        except Exception as exc:
            _LOGGER.error("REST PUT for %s failed: %s", path, exc)
            return False

    # ------------------------------------------------------------------
    # WebSocket streaming
    # ------------------------------------------------------------------

    async def run(
        self,
        on_delta: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
        on_connect: Callable[[], Coroutine[Any, Any, None]] | None = None,
        on_disconnect: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Main run loop: connect, subscribe, stream deltas.

        Reconnects with exponential backoff on failures.
        Runs until stop() is called.
        """
        self._on_delta = on_delta
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        delay_index = 0

        while not self._stop_event.is_set():
            try:
                await self._connect_and_stream()
                _LOGGER.info("WebSocket closed, will reconnect")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.warning("SignalK WebSocket error: %s", exc)

            self._connected = False
            self._ws = None
            if self._on_disconnect:
                try:
                    await self._on_disconnect()
                except Exception:
                    pass

            if self._stop_event.is_set():
                break

            delay = RECONNECT_DELAYS[min(delay_index, len(RECONNECT_DELAYS) - 1)]
            _LOGGER.info("Reconnecting in %ds…", delay)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                break  # stop was called during delay
            except asyncio.TimeoutError:
                pass
            delay_index = min(delay_index + 1, len(RECONNECT_DELAYS) - 1)

    async def _connect_and_stream(self) -> None:
        """Single connection lifecycle."""
        ws_url = self._build_ws_url()
        extra_headers: dict[str, str] = {}
        if self._token:
            extra_headers["Authorization"] = f"Bearer {self._token}"

        _LOGGER.info("Connecting to SignalK WebSocket at %s", ws_url)

        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
            additional_headers=extra_headers if extra_headers else None,
        ) as ws:
            self._ws = ws

            # 1. Receive hello message
            hello_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            hello = json.loads(hello_raw)
            _LOGGER.info(
                "Connected to %s (version %s)",
                hello.get("name", "unknown"),
                hello.get("version", "unknown"),
            )
            self._server_info = hello
            if "self" in hello and hello["self"]:
                self._self_context = hello["self"]

            # 2. Subscribe to all self paths with wildcard
            sub_msg = json.dumps(
                {
                    "context": "vessels.self",
                    "subscribe": [
                        {
                            "path": "*",
                            "period": 1000,
                            "format": "delta",
                            "policy": "ideal",
                            "minPeriod": 200,
                        }
                    ],
                }
            )
            await ws.send(sub_msg)
            _LOGGER.debug("Subscribed to all self paths")

            self._connected = True

            if self._on_connect:
                await self._on_connect()

            # 3. Stream deltas
            async for raw_msg in ws:
                if self._stop_event.is_set():
                    break
                try:
                    msg = json.loads(raw_msg)
                    await self._handle_message(msg)
                except json.JSONDecodeError:
                    _LOGGER.warning("Invalid JSON from SignalK: %s", raw_msg[:100])

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Process a received WebSocket message (delta or meta)."""
        if "updates" not in msg:
            return

        context = msg.get("context", "vessels.self")

        # Only process vessel self data (future: handle other vessels)
        if not self._is_self_context(context):
            return

        if self._on_delta:
            await self._on_delta(msg)

    def _is_self_context(self, context: str) -> bool:
        """Check if a context refers to vessel self."""
        if context in ("vessels.self", "self"):
            return True
        if self._self_context and context == self._self_context:
            return True
        return False

    def _build_ws_url(self) -> str:
        """Build the WebSocket URL from the base URL."""
        # Convert http(s) to ws(s)
        ws_base = self._base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        return f"{ws_base}{SK_WS_STREAM}?subscribe=none"

    async def stop(self) -> None:
        """Signal the client to stop and close the WebSocket."""
        _LOGGER.info("Stopping SignalK client")
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
