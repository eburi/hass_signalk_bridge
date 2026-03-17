"""Tests for signalk_client.py — async client with mocked HTTP/WS."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from custom_components.signalk_bridge.signalk_client import (
    SignalKClient,
    SignalKAuthError,
    SignalKConnectionError,
)


# ===================================================================
# Initialization
# ===================================================================

class TestClientInit:
    def test_default_init(self):
        c = SignalKClient(base_url="http://localhost:3000")
        assert c.base_url == "http://localhost:3000"
        assert c.token is None
        assert c.client_id  # auto-generated UUID
        assert c.connected is False

    def test_with_token(self):
        c = SignalKClient(base_url="http://host:3000", token="abc123")
        assert c.token == "abc123"

    def test_with_client_id(self):
        c = SignalKClient(base_url="http://host:3000", client_id="my-id")
        assert c.client_id == "my-id"

    def test_trailing_slash_stripped(self):
        c = SignalKClient(base_url="http://host:3000/")
        assert c.base_url == "http://host:3000"


# ===================================================================
# Discovery
# ===================================================================

class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discover_success(self):
        c = SignalKClient(base_url="http://host:3000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"endpoints": {"v1": {}}}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await c.discover()
            assert "endpoints" in result

    @pytest.mark.asyncio
    async def test_discover_failure_raises(self):
        c = SignalKClient(base_url="http://host:3000")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(SignalKConnectionError):
                await c.discover()

    @pytest.mark.asyncio
    async def test_check_connection_success(self):
        c = SignalKClient(base_url="http://host:3000")
        c.discover = AsyncMock(return_value={"endpoints": {}})
        assert await c.check_connection() is True

    @pytest.mark.asyncio
    async def test_check_connection_failure(self):
        c = SignalKClient(base_url="http://host:3000")
        c.discover = AsyncMock(side_effect=SignalKConnectionError("nope"))
        assert await c.check_connection() is False


# ===================================================================
# Token validation
# ===================================================================

class TestValidateToken:
    @pytest.mark.asyncio
    async def test_no_token_returns_false(self):
        c = SignalKClient(base_url="http://host:3000")
        assert await c.validate_token() is False

    @pytest.mark.asyncio
    async def test_valid_token(self):
        c = SignalKClient(base_url="http://host:3000", token="good-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await c.validate_token() is True

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        c = SignalKClient(base_url="http://host:3000", token="bad-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await c.validate_token() is False

    @pytest.mark.asyncio
    async def test_token_validation_network_error(self):
        c = SignalKClient(base_url="http://host:3000", token="token")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            assert await c.validate_token() is False


# ===================================================================
# REST API helpers
# ===================================================================

def _mock_http_client(mock_resp):
    """Create a patched httpx.AsyncClient that returns mock_resp."""
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.put.return_value = mock_resp
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestGetSelfData:
    @pytest.mark.asyncio
    async def test_success(self):
        c = SignalKClient(base_url="http://host:3000", token="tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "My Vessel", "mmsi": "123456"}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as cls:
            cls.return_value = _mock_http_client(mock_resp)
            cls.return_value.get.return_value = mock_resp
            cls.return_value.__aenter__ = AsyncMock(return_value=cls.return_value)
            result = await c.get_self_data()
            assert result["name"] == "My Vessel"

    @pytest.mark.asyncio
    async def test_failure_returns_empty(self):
        c = SignalKClient(base_url="http://host:3000")

        with patch("httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("fail")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            cls.return_value = mock_client

            result = await c.get_self_data()
            assert result == {}


class TestGetPathMeta:
    @pytest.mark.asyncio
    async def test_success(self):
        c = SignalKClient(base_url="http://host:3000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"units": "K", "description": "Water temp"}

        with patch("httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            cls.return_value = mock_client

            result = await c.get_path_meta("environment.water.temperature")
            assert result["units"] == "K"

    @pytest.mark.asyncio
    async def test_not_found_returns_empty(self):
        c = SignalKClient(base_url="http://host:3000")
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            cls.return_value = mock_client

            result = await c.get_path_meta("nonexistent.path")
            assert result == {}


class TestPutValue:
    @pytest.mark.asyncio
    async def test_put_value(self):
        c = SignalKClient(base_url="http://host:3000", token="tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"state":"COMPLETED"}'
        mock_resp.json.return_value = {"state": "COMPLETED"}

        with patch("httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.put.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            cls.return_value = mock_client

            result = await c.put_value("propulsion.port.revolutions", 1500)
            assert result["status"] == 200


class TestPostDelta:
    @pytest.mark.asyncio
    async def test_post_delta_via_ws(self):
        """When WS is connected, delta is sent through it."""
        c = SignalKClient(base_url="http://host:3000")
        c._connected = True
        c._ws = AsyncMock()
        c._ws.send = AsyncMock()

        result = await c.post_delta("navigation.speedOverGround", 5.2)
        assert result is True
        c._ws.send.assert_called_once()

        # Verify the sent JSON
        sent = json.loads(c._ws.send.call_args[0][0])
        assert sent["context"] == "vessels.self"
        assert sent["updates"][0]["values"][0]["path"] == "navigation.speedOverGround"
        assert sent["updates"][0]["values"][0]["value"] == 5.2

    @pytest.mark.asyncio
    async def test_post_delta_rest_fallback(self):
        """When WS is not connected, falls back to REST PUT."""
        c = SignalKClient(base_url="http://host:3000", token="tok")
        c._connected = False
        c._ws = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.put.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            cls.return_value = mock_client

            result = await c.post_delta("some.path", 42)
            assert result is True

    @pytest.mark.asyncio
    async def test_post_delta_ws_failure_falls_back(self):
        """WS send fails → should fall back to REST."""
        c = SignalKClient(base_url="http://host:3000", token="tok")
        c._connected = True
        c._ws = AsyncMock()
        c._ws.send = AsyncMock(side_effect=Exception("WS broken"))

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.put.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            cls.return_value = mock_client

            result = await c.post_delta("some.path", 42)
            assert result is True


# ===================================================================
# WebSocket URL building
# ===================================================================

class TestBuildWsUrl:
    def test_http_to_ws(self):
        c = SignalKClient(base_url="http://host:3000")
        url = c._build_ws_url()
        assert url.startswith("ws://")
        assert "subscribe=none" in url

    def test_https_to_wss(self):
        c = SignalKClient(base_url="https://host:3000")
        url = c._build_ws_url()
        assert url.startswith("wss://")

    def test_contains_stream_path(self):
        c = SignalKClient(base_url="http://host:3000")
        url = c._build_ws_url()
        assert "/signalk/v1/stream" in url


# ===================================================================
# Self context matching
# ===================================================================

class TestSelfContext:
    def test_vessels_self(self):
        c = SignalKClient(base_url="http://host:3000")
        assert c._is_self_context("vessels.self") is True

    def test_self(self):
        c = SignalKClient(base_url="http://host:3000")
        assert c._is_self_context("self") is True

    def test_custom_self_context(self):
        c = SignalKClient(base_url="http://host:3000")
        c._self_context = "vessels.urn:mrn:imo:mmsi:123456789"
        assert c._is_self_context("vessels.urn:mrn:imo:mmsi:123456789") is True

    def test_other_vessel(self):
        c = SignalKClient(base_url="http://host:3000")
        assert c._is_self_context("vessels.urn:mrn:imo:mmsi:999999") is False


# ===================================================================
# Message handling
# ===================================================================

class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_delta_dispatched(self):
        c = SignalKClient(base_url="http://host:3000")
        received = []
        c._on_delta = AsyncMock(side_effect=lambda msg: received.append(msg))

        msg = {
            "context": "vessels.self",
            "updates": [
                {"values": [{"path": "navigation.sog", "value": 5.0}]}
            ],
        }
        await c._handle_message(msg)
        assert len(received) == 1
        assert received[0] == msg

    @pytest.mark.asyncio
    async def test_non_self_context_ignored(self):
        c = SignalKClient(base_url="http://host:3000")
        c._on_delta = AsyncMock()

        msg = {
            "context": "vessels.urn:mrn:imo:mmsi:999999",
            "updates": [
                {"values": [{"path": "navigation.sog", "value": 3.0}]}
            ],
        }
        await c._handle_message(msg)
        c._on_delta.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_updates_ignored(self):
        c = SignalKClient(base_url="http://host:3000")
        c._on_delta = AsyncMock()
        await c._handle_message({"hello": "world"})
        c._on_delta.assert_not_called()


# ===================================================================
# Stop
# ===================================================================

class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_event(self):
        c = SignalKClient(base_url="http://host:3000")
        assert not c._stop_event.is_set()
        await c.stop()
        assert c._stop_event.is_set()
        assert c.connected is False

    @pytest.mark.asyncio
    async def test_stop_closes_ws(self):
        c = SignalKClient(base_url="http://host:3000")
        c._ws = AsyncMock()
        c._ws.close = AsyncMock()
        c._connected = True
        await c.stop()
        c._ws.close.assert_called_once()


# ===================================================================
# Authentication flow
# ===================================================================

class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_existing_valid_token(self):
        c = SignalKClient(base_url="http://host:3000", token="valid")
        c.validate_token = AsyncMock(return_value=True)

        result = await c.authenticate()
        assert result is True
        assert c.token == "valid"

    @pytest.mark.asyncio
    async def test_invalid_token_requests_new(self):
        c = SignalKClient(base_url="http://host:3000", token="expired")
        c.validate_token = AsyncMock(return_value=False)
        c.request_device_access = AsyncMock(return_value="new-token")

        result = await c.authenticate()
        assert result is True
        assert c.token == "new-token"

    @pytest.mark.asyncio
    async def test_auth_fails(self):
        c = SignalKClient(base_url="http://host:3000", token="expired")
        c.validate_token = AsyncMock(return_value=False)
        c.request_device_access = AsyncMock(return_value=None)

        result = await c.authenticate()
        assert result is False
