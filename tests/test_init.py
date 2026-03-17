"""Tests for __init__.py — Hub, services, setup/teardown (refactored architecture)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.signalk_bridge import (
    SignalKHub,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    SERVICE_PUT_VALUE,
    SERVICE_POST_DELTA,
    SERVICE_SET_DOMAIN_POLICY,
    SERVICE_RESET_DOMAIN_POLICY,
    SERVICE_SET_DISCOVERY_DEFAULTS,
    SERVICE_RESCAN_PATHS,
    SERVICE_RECLASSIFY_PATHS,
    SERVICE_DUMP_RUNTIME_STATE,
    PLATFORMS,
)
from custom_components.signalk_bridge.const import (
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_ENABLE_NEW_SENSORS,
    CONF_ENTITY_PREFIX,
    CONF_PUBLISH_PROFILE,
    CONF_TOKEN,
    PublishProfile,
    SignalKDomain,
)


def _make_entry(data=None, options=None):
    from homeassistant.config_entries import ConfigEntry

    return ConfigEntry(
        entry_id="test_entry_id",
        data=data
        or {
            CONF_BASE_URL: "http://localhost:3000",
            CONF_TOKEN: "test-token",
            CONF_CLIENT_ID: "test-client-id",
            CONF_ENTITY_PREFIX: "signalk",
        },
        title="Test SignalK",
        options=options or {},
    )


def _make_hass():
    from homeassistant.core import HomeAssistant

    hass = HomeAssistant()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[])
    hass.services = MagicMock()
    hass.bus = MagicMock()
    return hass


def _make_hub(hass=None, entry=None):
    if hass is None:
        hass = _make_hass()
    if entry is None:
        entry = _make_entry()
    return SignalKHub(hass, entry)


# ===================================================================
# Hub initialization
# ===================================================================


class TestHubInit:
    def test_hub_creates_client(self):
        hub = _make_hub()
        assert hub.client is not None
        assert hub.client.base_url == "http://localhost:3000"
        assert hub.client.token == "test-token"
        assert hub.client.client_id == "test-client-id"

    def test_hub_device_info(self):
        hub = _make_hub()
        di = hub.device_info
        assert ("signalk_bridge", "signalk_vessel_self") in di["identifiers"]

    def test_hub_default_prefix(self):
        entry = _make_entry(data={CONF_BASE_URL: "http://localhost:3000"})
        hub = _make_hub(entry=entry)
        assert "signalk" in hub._entity_prefix

    def test_hub_has_policy_engine(self):
        hub = _make_hub()
        assert hub.policy_engine is not None
        assert hub.policy_engine.profile == PublishProfile.CONSERVATIVE

    def test_hub_custom_profile(self):
        entry = _make_entry(
            data={CONF_BASE_URL: "http://localhost:3000", CONF_TOKEN: "tok"},
            options={CONF_PUBLISH_PROFILE: "realtime"},
        )
        hub = _make_hub(entry=entry)
        assert hub.policy_engine.profile == PublishProfile.REALTIME

    def test_hub_enable_new_sensors_default_false(self):
        hub = _make_hub()
        assert hub.enable_new_sensors is False

    def test_hub_enable_new_sensors_from_options(self):
        entry = _make_entry(
            data={CONF_BASE_URL: "http://localhost:3000"},
            options={CONF_ENABLE_NEW_SENSORS: True},
        )
        hub = _make_hub(entry=entry)
        assert hub.enable_new_sensors is True

    def test_hub_classifications_empty_initially(self):
        hub = _make_hub()
        assert len(hub.classifications) == 0

    def test_hub_sensors_empty_initially(self):
        hub = _make_hub()
        assert len(hub.sensors) == 0


# ===================================================================
# Platform registration
# ===================================================================


class TestPlatformRegistration:
    @pytest.mark.asyncio
    async def test_sensor_platform_registration(self):
        hub = _make_hub()
        mock_add = MagicMock()
        await hub.register_sensor_platform(mock_add)
        assert hub._sensor_add_entities is mock_add

    @pytest.mark.asyncio
    async def test_tracker_platform_registration(self):
        hub = _make_hub()
        mock_add = MagicMock()
        await hub.register_tracker_platform(mock_add)
        assert hub._tracker_add_entities is mock_add

    @pytest.mark.asyncio
    async def test_ws_not_started_until_both_platforms_ready(self):
        hub = _make_hub()
        # Only register sensor platform
        await hub.register_sensor_platform(MagicMock())
        assert hub._ws_task is None  # Not started yet

    @pytest.mark.asyncio
    async def test_diagnostic_sensors_created(self):
        hub = _make_hub()
        added = []

        def mock_add(entities):
            added.extend(entities)

        await hub.register_sensor_platform(mock_add)
        # Should have 2 diagnostic sensors (connection + version)
        assert len(added) == 2


# ===================================================================
# Delta processing
# ===================================================================


class TestDeltaProcessing:
    @pytest.mark.asyncio
    async def test_new_path_creates_sensor(self):
        hub = _make_hub()
        hub._enable_new_sensors = True  # Enable so entities get created

        added_sensors = []
        hub._sensor_add_entities = lambda entities: added_sensors.extend(entities)
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        delta = {
            "updates": [
                {
                    "source": {"label": "nmea2000"},
                    "timestamp": "2024-01-01T00:00:00Z",
                    "values": [{"path": "navigation.speedOverGround", "value": 5.0}],
                }
            ]
        }

        await hub._on_delta(delta)

        assert len(added_sensors) == 1
        assert added_sensors[0].signalk_path == "navigation.speedOverGround"
        assert "navigation.speedOverGround" in hub._sensors

    @pytest.mark.asyncio
    async def test_existing_path_updates_sensor_when_policy_allows(self):
        hub = _make_hub()
        hub._enable_new_sensors = True

        added = []
        hub._sensor_add_entities = lambda entities: added.extend(entities)
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        # First delta — creates sensor
        await hub._on_delta(
            {
                "updates": [
                    {"values": [{"path": "navigation.speedOverGround", "value": 1.0}]}
                ]
            }
        )
        assert len(added) == 1
        sensor = added[0]
        sensor._ready = True

        # Second delta — updates (policy engine will evaluate)
        await hub._on_delta(
            {
                "updates": [
                    {"values": [{"path": "navigation.speedOverGround", "value": 99.0}]}
                ]
            }
        )
        assert len(added) == 1  # no new entities

    @pytest.mark.asyncio
    async def test_position_path_creates_device_tracker(self):
        hub = _make_hub()
        hub._enable_new_sensors = True

        sensor_added = []
        tracker_added = []
        hub._sensor_add_entities = lambda e: sensor_added.extend(e)
        hub._tracker_add_entities = lambda e: tracker_added.extend(e)
        hub._client.get_path_meta = AsyncMock(return_value={})

        delta = {
            "updates": [
                {
                    "values": [
                        {
                            "path": "navigation.position",
                            "value": {"latitude": 51.5, "longitude": -1.2},
                        }
                    ],
                }
            ]
        }

        await hub._on_delta(delta)
        assert len(tracker_added) == 1
        assert hub._device_tracker is not None

    @pytest.mark.asyncio
    async def test_meta_update_cached(self):
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()

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
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta({"updates": [{"values": [{"path": "", "value": 1.0}]}]})
        assert len(hub._sensors) == 0

    @pytest.mark.asyncio
    async def test_ignored_path_tracked(self):
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()

        await hub._on_delta(
            {
                "updates": [
                    {"values": [{"path": "navigation.sog.values.nmea", "value": 5.0}]}
                ]
            }
        )
        assert "navigation.sog.values.nmea" in hub.ignored_paths

    @pytest.mark.asyncio
    async def test_unsupported_path_ignored(self):
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()

        await hub._on_delta(
            {
                "updates": [
                    {"values": [{"path": "completely.unknown.thing", "value": 42}]}
                ]
            }
        )
        assert "completely.unknown.thing" in hub.ignored_paths
        assert len(hub.sensors) == 0

    @pytest.mark.asyncio
    async def test_no_add_entities_returns_early(self):
        hub = _make_hub()
        hub._sensor_add_entities = None
        hub._tracker_add_entities = None

        # Should not crash
        await hub._on_delta(
            {"updates": [{"values": [{"path": "navigation.sog", "value": 1.0}]}]}
        )

    @pytest.mark.asyncio
    async def test_latest_values_always_updated(self):
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta(
            {"updates": [{"values": [{"path": "navigation.sog", "value": 5.0}]}]}
        )
        assert hub._latest_values["navigation.sog"] == 5.0

    @pytest.mark.asyncio
    async def test_classification_cached(self):
        hub = _make_hub()
        hub._enable_new_sensors = True
        hub._sensor_add_entities = lambda e: None
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta(
            {
                "updates": [
                    {"values": [{"path": "navigation.speedOverGround", "value": 5.0}]}
                ]
            }
        )
        assert "navigation.speedOverGround" in hub.classifications
        c = hub.classifications["navigation.speedOverGround"]
        assert c.domain == SignalKDomain.NAVIGATION


# ===================================================================
# Hub put/post
# ===================================================================


class TestHubServices:
    @pytest.mark.asyncio
    async def test_put_value(self):
        hub = _make_hub()
        hub._client.put_value = AsyncMock(return_value={"status": 200})
        result = await hub.put_value("propulsion.port.rpm", 1500)
        assert result["status"] == 200
        hub._client.put_value.assert_called_once_with("propulsion.port.rpm", 1500)

    @pytest.mark.asyncio
    async def test_post_delta(self):
        hub = _make_hub()
        hub._client.post_delta = AsyncMock(return_value=True)
        result = await hub.post_delta("nav.sog", 5.5)
        assert result is True


# ===================================================================
# Domain policy services
# ===================================================================


class TestDomainPolicyServices:
    def test_set_domain_policy(self):
        hub = _make_hub()
        policy = hub.set_domain_policy(
            SignalKDomain.NAVIGATION,
            min_interval=0.5,
            deadband=0.1,
        )
        assert policy.min_interval == 0.5
        assert policy.deadband == 0.1

    def test_reset_domain_policy(self):
        hub = _make_hub()
        hub.set_domain_policy(SignalKDomain.NAVIGATION, min_interval=99.0)
        policy = hub.reset_domain_policy(SignalKDomain.NAVIGATION)
        assert policy.min_interval != 99.0  # Reset to default


# ===================================================================
# Reclassify / rescan
# ===================================================================


class TestReclassifyRescan:
    def test_reclassify_paths(self):
        hub = _make_hub()
        hub._classifications["navigation.sog"] = MagicMock()
        hub._classifications["environment.wind.speedApparent"] = MagicMock()
        hub._ignored_paths.add("something.values.x")

        count = hub.reclassify_paths()
        assert count == 3  # 2 classified + 1 ignored

    def test_rescan_paths(self):
        hub = _make_hub()
        hub._latest_values["navigation.speedOverGround"] = 5.0
        hub._latest_values["environment.wind.speedApparent"] = 10.0
        hub._latest_values["foo.values.bar"] = 1.0  # ignored

        result = hub.rescan_paths()
        assert result["total_classified"] >= 2
        assert result["total_ignored"] >= 1


# ===================================================================
# dump_runtime_state
# ===================================================================


class TestDumpRuntimeState:
    def test_dump_structure(self):
        hub = _make_hub()
        state = hub.dump_runtime_state()
        assert "connection" in state
        assert "discovery" in state
        assert "policy_engine" in state
        assert "paths" in state
        assert "domains" in state

    def test_dump_connection_info(self):
        hub = _make_hub()
        state = hub.dump_runtime_state()
        assert state["connection"]["base_url"] == "http://localhost:3000"

    def test_dump_discovery_info(self):
        hub = _make_hub()
        state = hub.dump_runtime_state()
        assert state["discovery"]["enable_new_sensors_by_default"] is False


# ===================================================================
# Hub stop
# ===================================================================


class TestHubStop:
    @pytest.mark.asyncio
    async def test_stop_calls_client_stop(self):
        hub = _make_hub()
        hub._client.stop = AsyncMock()
        hub._ws_task = None
        await hub.stop()
        hub._client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        hub = _make_hub()
        hub._client.stop = AsyncMock()

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
        # 10 services should be registered
        assert hass.services.async_register.call_count == 10
        call_args = [c[0] for c in hass.services.async_register.call_args_list]
        service_names = [a[1] for a in call_args]
        assert SERVICE_PUT_VALUE in service_names
        assert SERVICE_POST_DELTA in service_names
        assert SERVICE_SET_DOMAIN_POLICY in service_names
        assert SERVICE_RESET_DOMAIN_POLICY in service_names
        assert SERVICE_SET_DISCOVERY_DEFAULTS in service_names
        assert SERVICE_RESCAN_PATHS in service_names
        assert SERVICE_RECLASSIFY_PATHS in service_names
        assert SERVICE_DUMP_RUNTIME_STATE in service_names


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

    @pytest.mark.asyncio
    async def test_platforms_include_device_tracker(self):
        from homeassistant.const import Platform

        assert Platform.DEVICE_TRACKER in PLATFORMS
        assert Platform.SENSOR in PLATFORMS


# ===================================================================
# async_unload_entry
# ===================================================================


class TestAsyncUnloadEntry:
    @pytest.mark.asyncio
    async def test_unload(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = _make_hub(hass=hass, entry=entry)
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
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta(
            {
                "updates": [
                    {
                        "source": {"label": "n2k-gateway"},
                        "values": [{"path": "navigation.sog", "value": 5.0}],
                    }
                ]
            }
        )
        # Should not crash

    @pytest.mark.asyncio
    async def test_source_string(self):
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta(
            {
                "updates": [
                    {
                        "source": "serial-gps",
                        "values": [
                            {
                                "path": "navigation.position",
                                "value": {"latitude": 51.0, "longitude": -1.0},
                            }
                        ],
                    }
                ]
            }
        )

    @pytest.mark.asyncio
    async def test_dollar_source(self):
        hub = _make_hub()
        hub._sensor_add_entities = MagicMock()
        hub._tracker_add_entities = MagicMock()
        hub._client.get_path_meta = AsyncMock(return_value={})

        await hub._on_delta(
            {
                "updates": [
                    {
                        "$source": "nmea0183.GP",
                        "values": [
                            {"path": "navigation.headingMagnetic", "value": 1.57}
                        ],
                    }
                ]
            }
        )

    def test_extract_source_dict(self):
        result = SignalKHub._extract_source({"source": {"label": "n2k"}})
        assert result == "n2k"

    def test_extract_source_string(self):
        result = SignalKHub._extract_source({"source": "serial-gps"})
        assert result == "serial-gps"

    def test_extract_source_dollar(self):
        result = SignalKHub._extract_source({"$source": "nmea0183.GP"})
        assert result == "nmea0183.GP"

    def test_extract_source_empty(self):
        result = SignalKHub._extract_source({})
        assert result == ""


# ===================================================================
# Enable/disable sensors property
# ===================================================================


class TestHubProperties:
    def test_enable_new_sensors_setter(self):
        hub = _make_hub()
        assert hub.enable_new_sensors is False
        hub.enable_new_sensors = True
        assert hub.enable_new_sensors is True

    def test_log_ignored_paths_setter(self):
        hub = _make_hub()
        assert hub.log_ignored_paths is False
        hub.log_ignored_paths = True
        assert hub.log_ignored_paths is True
