"""Tests for config_flow.py — config flow steps and options flow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest

from custom_components.signalk_bridge.config_flow import (
    SignalKBridgeConfigFlow,
    OptionsFlowHandler,
    _check_signalk_addon,
    _get_addon_url,
    _is_hassio,
    _test_signalk_connection,
)
from custom_components.signalk_bridge.const import (
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_ENTITY_PREFIX,
    CONF_TOKEN,
    CONF_USE_ADDON,
    DEFAULT_BASE_URL,
    DEFAULT_ENTITY_PREFIX,
    DOMAIN,
    SIGNALK_ADDON_PORT,
    SIGNALK_ADDON_SLUG,
)


# ===================================================================
# Helper: _is_hassio
# ===================================================================

class TestIsHassio:
    def test_hassio_present(self):
        hass = MagicMock()
        hass.config.components = {"hassio", "other"}
        assert _is_hassio(hass) is True

    def test_hassio_absent(self):
        hass = MagicMock()
        hass.config.components = {"other"}
        assert _is_hassio(hass) is False


# ===================================================================
# Helper: _check_signalk_addon
# ===================================================================

class TestCheckSignalkAddon:
    @pytest.mark.asyncio
    async def test_no_hassio(self):
        hass = MagicMock()
        hass.config.components = set()
        result = await _check_signalk_addon(hass)
        assert result is None

    @pytest.mark.asyncio
    async def test_addon_running(self):
        hass = MagicMock()
        hass.config.components = {"hassio"}

        addon_info = {"state": "started", "hostname": "a0d7b954-signalk"}

        # Patch the hassio module's function that gets imported inside _check_signalk_addon
        import homeassistant.components.hassio as hassio_mod
        hassio_mod.async_get_addon_info = AsyncMock(return_value=addon_info)

        result = await _check_signalk_addon(hass)
        assert result is not None
        assert result["state"] == "started"

    @pytest.mark.asyncio
    async def test_addon_not_running(self):
        hass = MagicMock()
        hass.config.components = {"hassio"}

        # When addon info raises, returns None
        with patch(
            "homeassistant.components.hassio.async_get_addon_info",
            new_callable=AsyncMock,
            side_effect=Exception("not found"),
        ):
            result = await _check_signalk_addon(hass)
            assert result is None


# ===================================================================
# Helper: _get_addon_url
# ===================================================================

class TestGetAddonUrl:
    @pytest.mark.asyncio
    async def test_with_hostname(self):
        url = await _get_addon_url({"hostname": "a0d7b954-signalk", "ip_address": "172.30.32.1"})
        assert url == f"http://a0d7b954-signalk:{SIGNALK_ADDON_PORT}"

    @pytest.mark.asyncio
    async def test_with_ip_only(self):
        url = await _get_addon_url({"ip_address": "172.30.32.1"})
        assert url == f"http://172.30.32.1:{SIGNALK_ADDON_PORT}"

    @pytest.mark.asyncio
    async def test_no_host(self):
        url = await _get_addon_url({})
        assert url is None


# ===================================================================
# Helper: _test_signalk_connection
# ===================================================================

class TestTestSignalkConnection:
    @pytest.mark.asyncio
    async def test_connection_success(self):
        with patch(
            "custom_components.signalk_bridge.config_flow.SignalKClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.check_connection = AsyncMock(return_value=True)
            result = await _test_signalk_connection("http://host:3000")
            assert result is True

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        with patch(
            "custom_components.signalk_bridge.config_flow.SignalKClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.check_connection = AsyncMock(return_value=False)
            result = await _test_signalk_connection("http://bad-host:3000")
            assert result is False

    @pytest.mark.asyncio
    async def test_connection_exception(self):
        with patch(
            "custom_components.signalk_bridge.config_flow.SignalKClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.check_connection = AsyncMock(side_effect=Exception("timeout"))
            result = await _test_signalk_connection("http://bad-host:3000")
            assert result is False


# ===================================================================
# Config flow: user step
# ===================================================================

class TestConfigFlowUser:
    @pytest.mark.asyncio
    async def test_user_step_no_addon_goes_to_manual(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()

        with patch(
            "custom_components.signalk_bridge.config_flow._check_signalk_addon",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await flow.async_step_user(None)
            # Should go to manual_url step
            assert result["step_id"] == "manual_url"

    @pytest.mark.asyncio
    async def test_user_step_addon_available(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()

        addon_info = {"state": "started", "hostname": "signalk-host"}
        with patch(
            "custom_components.signalk_bridge.config_flow._check_signalk_addon",
            new_callable=AsyncMock,
            return_value=addon_info,
        ), patch(
            "custom_components.signalk_bridge.config_flow._get_addon_url",
            new_callable=AsyncMock,
            return_value="http://signalk-host:3000",
        ), patch(
            "custom_components.signalk_bridge.config_flow._test_signalk_connection",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await flow.async_step_user(None)
            # Should show choose_server form
            assert result["step_id"] == "choose_server"

    @pytest.mark.asyncio
    async def test_user_step_addon_unreachable(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()

        addon_info = {"state": "started", "hostname": "signalk-host"}
        with patch(
            "custom_components.signalk_bridge.config_flow._check_signalk_addon",
            new_callable=AsyncMock,
            return_value=addon_info,
        ), patch(
            "custom_components.signalk_bridge.config_flow._get_addon_url",
            new_callable=AsyncMock,
            return_value="http://signalk-host:3000",
        ), patch(
            "custom_components.signalk_bridge.config_flow._test_signalk_connection",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await flow.async_step_user(None)
            # Addon not reachable → go to manual
            assert result["step_id"] == "manual_url"


# ===================================================================
# Config flow: choose_server step
# ===================================================================

class TestConfigFlowChooseServer:
    @pytest.mark.asyncio
    async def test_choose_addon(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()
        flow._addon_url = "http://addon:3000"

        # Mock the auth step to just return a form
        with patch.object(flow, "async_step_auth", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = {"step_id": "auth"}
            result = await flow.async_step_choose_server({CONF_USE_ADDON: True})
            assert flow._base_url == "http://addon:3000"
            mock_auth.assert_called_once()

    @pytest.mark.asyncio
    async def test_choose_manual(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()

        with patch.object(flow, "async_step_manual_url", new_callable=AsyncMock) as mock_manual:
            mock_manual.return_value = {"step_id": "manual_url"}
            result = await flow.async_step_choose_server({CONF_USE_ADDON: False})
            mock_manual.assert_called_once()

    @pytest.mark.asyncio
    async def test_show_form(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_choose_server(None)
        assert result["step_id"] == "choose_server"


# ===================================================================
# Config flow: manual_url step
# ===================================================================

class TestConfigFlowManualUrl:
    @pytest.mark.asyncio
    async def test_show_form(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_manual_url(None)
        assert result["step_id"] == "manual_url"

    @pytest.mark.asyncio
    async def test_valid_url(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()

        with patch(
            "custom_components.signalk_bridge.config_flow._test_signalk_connection",
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(flow, "async_step_auth", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = {"step_id": "auth"}
            result = await flow.async_step_manual_url({
                CONF_BASE_URL: "http://myboat:3000/"
            })
            assert flow._base_url == "http://myboat:3000"  # trailing slash stripped
            mock_auth.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()

        with patch(
            "custom_components.signalk_bridge.config_flow._test_signalk_connection",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await flow.async_step_manual_url({
                CONF_BASE_URL: "http://unreachable:9999"
            })
            assert result["step_id"] == "manual_url"
            assert result["errors"]["base"] == "cannot_connect"


# ===================================================================
# Config flow: prefix step
# ===================================================================

class TestConfigFlowPrefix:
    @pytest.mark.asyncio
    async def test_show_form(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_prefix(None)
        assert result["step_id"] == "prefix"

    @pytest.mark.asyncio
    async def test_create_entry(self):
        flow = SignalKBridgeConfigFlow()
        flow.hass = MagicMock()
        flow._base_url = "http://boat:3000"
        flow._token = "jwt-token"
        flow._client_id = "cid"
        flow._addon_available = False

        result = await flow.async_step_prefix({CONF_ENTITY_PREFIX: "myboat"})
        assert result["type"] == "create_entry"
        assert result["data"][CONF_BASE_URL] == "http://boat:3000"
        assert result["data"][CONF_TOKEN] == "jwt-token"
        assert result["data"][CONF_ENTITY_PREFIX] == "myboat"


# ===================================================================
# Options flow
# ===================================================================

class TestOptionsFlow:
    @pytest.mark.asyncio
    async def test_show_form(self):
        flow = OptionsFlowHandler()
        flow.hass = MagicMock()
        flow.config_entry = MagicMock()
        flow.config_entry.data = {
            CONF_BASE_URL: "http://boat:3000",
            CONF_ENTITY_PREFIX: "sk",
        }
        result = await flow.async_step_init(None)
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_update_prefix(self):
        flow = OptionsFlowHandler()
        flow.hass = MagicMock()
        flow.hass.config_entries = MagicMock()
        flow.hass.config_entries.async_update_entry = MagicMock()
        flow.hass.config_entries.async_reload = AsyncMock()
        flow.config_entry = MagicMock()
        flow.config_entry.data = {
            CONF_BASE_URL: "http://boat:3000",
            CONF_ENTITY_PREFIX: "sk",
            CONF_TOKEN: "tok",
        }
        flow.config_entry.entry_id = "eid"

        result = await flow.async_step_init({
            CONF_BASE_URL: "http://boat:3000",  # unchanged
            CONF_ENTITY_PREFIX: "newprefix",
        })
        assert result["type"] == "create_entry"

    @pytest.mark.asyncio
    async def test_url_change_tested(self):
        flow = OptionsFlowHandler()
        flow.hass = MagicMock()
        flow.hass.config_entries = MagicMock()
        flow.config_entry = MagicMock()
        flow.config_entry.data = {
            CONF_BASE_URL: "http://old:3000",
            CONF_ENTITY_PREFIX: "sk",
        }

        with patch(
            "custom_components.signalk_bridge.config_flow._test_signalk_connection",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await flow.async_step_init({
                CONF_BASE_URL: "http://new:3000",
                CONF_ENTITY_PREFIX: "sk",
            })
            assert result["errors"][CONF_BASE_URL] == "cannot_connect"
