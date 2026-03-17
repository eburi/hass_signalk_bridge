"""Tests for __init__.py — Hub, services, setup/teardown."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest

from custom_components.signalk_bridge import (
    SignalKHub,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    SERVICE_PUT_VALUE,
    SERVICE_POST_DELTA,
    PLATFORMS,
)
from custom_components.signalk_bridge.const import (
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_ENTITY_PREFIX,
    CONF_TOKEN,
    DOMAIN,
)


def _make_entry(data=None):
    from homeassistant.config_entries import ConfigEntry
    return ConfigEntry(
        entry_id="test_entry_id",
        data=data or {
            CONF_BASE_URL: "http://localhost:3000",
            CONF_TOKEN: "test-token",
            CONF_CLIENT_ID: "test-client-id",
            CONF_ENTITY_PREFIX: "signalk",
        },
        title="Test SignalK",
    )


def _make_hass():
    from homeassistant.core import HomeAssistant
    hass = HomeAssistant()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services = MagicMock()
    hass.bus = MagicMock()
    return hass


# ===================================================================
# Hub initialization
# ===================================================================

class TestHubInit:
    def test_hub_creates_client(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)

        assert hub.client is not None
        assert hub.client.base_url == "http://localhost:3000"
        assert hub.client.token == "test-token"
        assert hub.client.client_id == "test-client-id"

    def test_hub_device_info(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)

        di = hub.device_info
        assert ("signalk_bridge", "signalk_vessel_self") in di["identifiers"]

    def test_hub_default_prefix(self):
        entry = _make_entry(data={
            CONF_BASE_URL: "http://localhost:3000",
        })
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        # Should use DEFAULT_ENTITY_PREFIX
        assert "signalk" in hub._entity_prefix


# ===================================================================
# Delta processing
# ===================================================================

class TestDeltaProcessing:
    @pytest.mark.asyncio
    async def test_new_path_creates_sensor(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)

        added_entities = []
        hub._async_add_entities = lambda entities: added_entities.extend(entities)
        hub._client.get_path_meta = AsyncMock(return_value={})

        delta = {
            "updates": [
                {
                    "source": {"label": "nmea2000"},
                    "timestamp": "2024-01-01T00:00:00Z",
                    "values": [
                        {"path": "navigation.speedOverGround", "value": 5.0},
                    ],
                }
            ]
        }

        await hub._on_delta(delta)

        assert len(added_entities) == 1
        assert added_entities[0].signalk_path == "navigation.speedOverGround"
        assert "navigation.speedOverGround" in hub._sensors

    @pytest.mark.asyncio
    async def test_existing_path_updates_sensor(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)

        added = []
        hub._async_add_entities = lambda entities: added.extend(entities)
        hub._client.get_path_meta = AsyncMock(return_value={})

        # First delta — creates sensor
        await hub._on_delta({
            "updates": [{"values": [{"path": "nav.sog", "value": 1.0}]}]
        })
        assert len(added) == 1
        sensor = added[0]

        # Make sensor ready
        sensor._ready = True
        from datetime import datetime
        sensor._last_ha_update = datetime.min

        # Second delta — updates same sensor
        await hub._on_delta({
            "updates": [{"values": [{"path": "nav.sog", "value": 2.0}]}]
        })
        assert len(added) == 1  # no new entities
        assert sensor._attr_native_value == 2.0

    @pytest.mark.asyncio
    async def test_meta_update_cached(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._async_add_entities = MagicMock()

        delta = {
            "updates": [
                {
                    "meta": [
                        {
                            "path": "navigation.sog",
                            "value": {"units": "m/s", "description": "Speed OG"},
                        }
                    ],
                }
            ]
        }
        await hub._on_delta(delta)
        assert "navigation.sog" in hub._meta_cache
        assert hub._meta_cache["navigation.sog"]["units"] == "m/s"

    @pytest.mark.asyncio
    async def test_empty_path_ignored(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._async_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta({
            "updates": [{"values": [{"path": "", "value": 1.0}]}]
        })
        assert len(hub._sensors) == 0

    @pytest.mark.asyncio
    async def test_no_add_entities_returns_early(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._async_add_entities = None

        # Should not crash
        await hub._on_delta({
            "updates": [{"values": [{"path": "nav.sog", "value": 1.0}]}]
        })


# ===================================================================
# Hub put/post
# ===================================================================

class TestHubServices:
    @pytest.mark.asyncio
    async def test_put_value(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._client.put_value = AsyncMock(return_value={"status": 200})

        result = await hub.put_value("propulsion.port.rpm", 1500)
        assert result["status"] == 200
        hub._client.put_value.assert_called_once_with("propulsion.port.rpm", 1500)

    @pytest.mark.asyncio
    async def test_post_delta(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._client.post_delta = AsyncMock(return_value=True)

        result = await hub.post_delta("nav.sog", 5.5)
        assert result is True


# ===================================================================
# Hub stop
# ===================================================================

class TestHubStop:
    @pytest.mark.asyncio
    async def test_stop_calls_client_stop(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._client.stop = AsyncMock()
        hub._ws_task = None

        await hub.stop()
        hub._client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._client.stop = AsyncMock()

        # Create a fake task
        async def long_running():
            await asyncio.sleep(100)

        hub._ws_task = asyncio.create_task(long_running())
        await hub.stop()
        assert hub._ws_task.cancelled() or hub._ws_task.done()


# ===================================================================
# async_setup (service registration)
# ===================================================================

class TestAsyncSetup:
    @pytest.mark.asyncio
    async def test_services_registered(self):
        hass = _make_hass()
        result = await async_setup(hass, {})
        assert result is True
        # Two services should be registered
        assert hass.services.async_register.call_count == 2
        call_args = [c[0] for c in hass.services.async_register.call_args_list]
        domains = [a[0] for a in call_args]
        services = [a[1] for a in call_args]
        assert all(d == DOMAIN for d in domains)
        assert SERVICE_PUT_VALUE in services
        assert SERVICE_POST_DELTA in services


# ===================================================================
# async_setup_entry
# ===================================================================

class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_creates_hub(self):
        hass = _make_hass()
        entry = _make_entry()

        result = await async_setup_entry(hass, entry)
        assert result is True
        assert entry.runtime_data is not None
        assert isinstance(entry.runtime_data, SignalKHub)

    @pytest.mark.asyncio
    async def test_forwards_platforms(self):
        hass = _make_hass()
        entry = _make_entry()

        await async_setup_entry(hass, entry)
        hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            entry, PLATFORMS
        )


# ===================================================================
# async_unload_entry
# ===================================================================

class TestAsyncUnloadEntry:
    @pytest.mark.asyncio
    async def test_unload(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = SignalKHub(hass, entry)
        hub._client.stop = AsyncMock()
        entry.runtime_data = hub

        result = await async_unload_entry(hass, entry)
        assert result is True
        hub._client.stop.assert_called_once()


# ===================================================================
# Source parsing in deltas
# ===================================================================

class TestDeltaSourceParsing:
    @pytest.mark.asyncio
    async def test_source_dict(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._async_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta({
            "updates": [{
                "source": {"label": "n2k-gateway"},
                "values": [{"path": "nav.sog", "value": 5.0}],
            }]
        })
        # Sensor was created — just verify no crash

    @pytest.mark.asyncio
    async def test_source_string(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._async_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta({
            "updates": [{
                "source": "serial-gps",
                "values": [{"path": "nav.pos", "value": {"latitude": 51.0, "longitude": -1.0}}],
            }]
        })

    @pytest.mark.asyncio
    async def test_dollar_source(self):
        entry = _make_entry()
        hass = _make_hass()
        hub = SignalKHub(hass, entry)
        hub._async_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta({
            "updates": [{
                "$source": "nmea0183.GP",
                "values": [{"path": "nav.heading", "value": 1.57}],
            }]
        })
