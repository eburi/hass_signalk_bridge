"""Tests for sensor.py — sensor entity creation and value conversion (refactored API)."""

import math
import time
from unittest.mock import MagicMock

import pytest

from custom_components.signalk_bridge.classifier import ClassificationResult
from custom_components.signalk_bridge.const import SignalKDomain
from custom_components.signalk_bridge.sensor import (
    SignalKSensor,
    SignalKConnectionSensor,
    SignalKServerVersionSensor,
)


def _make_device_info():
    from homeassistant.helpers.device_registry import DeviceInfo

    return DeviceInfo(
        identifiers={("signalk_bridge", "test_vessel_self")},
        name="Vessel Self (test)",
    )


def _make_hub():
    hub = MagicMock()
    hub._entity_prefix = "signalk"
    hub.device_info = _make_device_info()
    return hub


def _make_classification(**kwargs):
    defaults = {
        "domain": SignalKDomain.NAVIGATION,
        "platform": "sensor",
        "enabled_by_default": True,
        "friendly_name": None,
        "icon": None,
    }
    defaults.update(kwargs)
    return ClassificationResult(**defaults)


def _make_sensor(
    path="test.path",
    meta=None,
    initial_value=None,
    classification=None,
    entity_prefix="sk",
    entity_enabled=True,
):
    if classification is None:
        classification = _make_classification()
    return SignalKSensor(
        hub=_make_hub(),
        path=path,
        classification=classification,
        initial_value=initial_value,
        meta=meta or {},
        entity_prefix=entity_prefix,
        device_info=_make_device_info(),
        config_entry_id="test_entry",
        entity_enabled=entity_enabled,
    )


# ===================================================================
# SignalKSensor init
# ===================================================================


class TestSignalKSensorInit:
    def test_basic_numeric_sensor(self):
        sensor = _make_sensor(
            path="navigation.speedOverGround",
            initial_value=5.14,
            meta={"units": "m/s"},
            classification=_make_classification(friendly_name="SOG"),
        )
        assert sensor._sk_path == "navigation.speedOverGround"
        assert sensor._attr_unique_id == "sk_navigation_speedOverGround"
        assert sensor._attr_native_value is not None

    def test_display_name_from_classification(self):
        sensor = _make_sensor(
            path="navigation.speedOverGround",
            initial_value=5.0,
            classification=_make_classification(friendly_name="Speed Over Ground"),
        )
        assert sensor._attr_name == "Speed Over Ground"

    def test_display_name_generated_from_path(self):
        sensor = _make_sensor(
            path="navigation.courseOverGroundTrue",
            initial_value=1.0,
            classification=_make_classification(friendly_name=None),
        )
        # Should use path_to_friendly_name
        assert "Course" in sensor._attr_name
        assert "Over" in sensor._attr_name

    def test_temperature_sensor(self):
        sensor = _make_sensor(
            path="environment.water.temperature",
            initial_value=295.15,
            meta={"units": "K"},
            classification=_make_classification(
                domain=SignalKDomain.ENVIRONMENT,
                friendly_name="Water Temperature",
            ),
        )
        assert sensor._attr_device_class == "temperature"
        assert sensor._attr_native_unit_of_measurement == "K"
        assert sensor._attr_native_value == 295.15

    def test_angle_sensor_converts_rad_to_deg(self):
        sensor = _make_sensor(
            path="navigation.headingMagnetic",
            initial_value=math.pi,
            meta={"units": "rad"},
            classification=_make_classification(friendly_name="Heading Magnetic"),
        )
        assert sensor._attr_native_unit_of_measurement == "°"
        assert abs(sensor._attr_native_value - 180.0) < 0.1

    def test_ratio_to_percent(self):
        sensor = _make_sensor(
            path="tanks.fuel.0.currentLevel",
            initial_value=0.75,
            meta={"units": "ratio"},
            classification=_make_classification(domain=SignalKDomain.TANK),
        )
        assert sensor._attr_native_unit_of_measurement == "%"
        assert abs(sensor._attr_native_value - 75.0) < 0.01

    def test_no_unit_sensor(self):
        sensor = _make_sensor(
            path="some.custom.path",
            initial_value="active",
        )
        assert sensor._attr_device_class is None
        assert sensor._attr_native_value == "active"

    def test_entity_enabled_default(self):
        sensor = _make_sensor(entity_enabled=True)
        assert sensor._attr_entity_registry_enabled_default is True

    def test_entity_disabled_default(self):
        sensor = _make_sensor(entity_enabled=False)
        assert sensor._attr_entity_registry_enabled_default is False

    def test_icon_from_classification(self):
        sensor = _make_sensor(
            classification=_make_classification(icon="mdi:compass"),
        )
        assert sensor._attr_icon == "mdi:compass"

    def test_icon_from_mapping_when_classification_has_none(self):
        sensor = _make_sensor(
            path="environment.depth.belowKeel",
            initial_value=10.0,
            meta={"units": "m"},
            classification=_make_classification(
                domain=SignalKDomain.ENVIRONMENT,
                icon=None,
            ),
        )
        # The mapping for depth paths has an icon
        if sensor._mapping.icon:
            assert sensor._attr_icon == sensor._mapping.icon


# ===================================================================
# Value conversion (_convert)
# ===================================================================


class TestSensorConvert:
    def test_none(self):
        s = _make_sensor()
        assert s._convert(None) is None

    def test_position_dict(self):
        s = _make_sensor()
        result = s._convert({"latitude": 51.123456, "longitude": -1.654321})
        assert "51.123456" in result
        assert "-1.654321" in result

    def test_attitude_dict(self):
        s = _make_sensor()
        result = s._convert({"roll": 0.1, "pitch": 0.2, "yaw": 0.0})
        assert "roll=" in result
        assert "pitch=" in result

    def test_generic_dict(self):
        s = _make_sensor()
        result = s._convert({"foo": "bar"})
        assert "foo" in result

    def test_string_passthrough(self):
        s = _make_sensor()
        assert s._convert("NMEA2000") == "NMEA2000"

    def test_bool_passthrough(self):
        s = _make_sensor()
        result = s._convert(True)
        assert result == 1.0  # bool is subclass of int


# ===================================================================
# publish_value (replaces update_value)
# ===================================================================


class TestSensorPublishValue:
    def test_publish_before_ready_is_ignored(self):
        sensor = _make_sensor(initial_value=1.0)
        assert sensor._ready is False
        sensor.publish_value(2.0, source="test", timestamp="2024-01-01T00:00:00Z")
        # Initial value from constructor, not overwritten
        assert sensor._attr_native_value == 1.0

    def test_publish_after_ready(self):
        sensor = _make_sensor(initial_value=1.0)
        sensor._ready = True
        sensor.publish_value(99.0, source="test_src", timestamp="2024-01-01T00:00:00Z")
        assert sensor._attr_native_value == 99.0
        assert sensor._source == "test_src"
        assert sensor._timestamp == "2024-01-01T00:00:00Z"

    def test_publish_updates_last_update(self):
        sensor = _make_sensor(initial_value=1.0)
        sensor._ready = True
        old_update = sensor._last_update
        sensor.publish_value(2.0)
        assert sensor._last_update > old_update


# ===================================================================
# update_meta
# ===================================================================


class TestSensorUpdateMeta:
    def test_update_meta_refreshes_mapping(self):
        sensor = _make_sensor(
            path="environment.something",
            initial_value=300.0,
        )
        assert sensor._attr_device_class is None
        sensor.update_meta({"units": "K"})
        assert sensor._mapping.device_class == "temperature"


# ===================================================================
# set_enabled
# ===================================================================


class TestSensorSetEnabled:
    def test_set_enabled_true(self):
        sensor = _make_sensor(entity_enabled=False)
        assert sensor._attr_entity_registry_enabled_default is False
        sensor.set_enabled(True)
        assert sensor._attr_entity_registry_enabled_default is True

    def test_set_enabled_false(self):
        sensor = _make_sensor(entity_enabled=True)
        sensor.set_enabled(False)
        assert sensor._attr_entity_registry_enabled_default is False


# ===================================================================
# extra_state_attributes
# ===================================================================


class TestExtraStateAttributes:
    def test_attributes_include_path(self):
        sensor = _make_sensor(
            path="navigation.sog",
            initial_value=5.0,
            meta={"units": "m/s", "description": "Speed over ground"},
        )
        attrs = sensor.extra_state_attributes
        assert attrs["signalk_path"] == "navigation.sog"
        assert attrs["signalk_units"] == "m/s"
        assert attrs["signalk_description"] == "Speed over ground"

    def test_attributes_include_domain(self):
        sensor = _make_sensor(
            classification=_make_classification(domain=SignalKDomain.WIND),
        )
        attrs = sensor.extra_state_attributes
        assert attrs["signalk_domain"] == SignalKDomain.WIND

    def test_attributes_without_meta(self):
        sensor = _make_sensor(
            path="custom.path",
            initial_value="x",
        )
        attrs = sensor.extra_state_attributes
        assert attrs["signalk_path"] == "custom.path"
        assert "signalk_units" not in attrs

    def test_attributes_with_source_and_timestamp(self):
        sensor = _make_sensor(initial_value=1.0)
        sensor._ready = True
        sensor.publish_value(2.0, source="gps", timestamp="2024-01-01T00:00:00Z")
        attrs = sensor.extra_state_attributes
        assert attrs["signalk_source"] == "gps"
        assert attrs["signalk_timestamp"] == "2024-01-01T00:00:00Z"


# ===================================================================
# availability (staleness)
# ===================================================================


class TestSensorAvailability:
    def test_available_when_not_ready(self):
        sensor = _make_sensor(initial_value=1)
        assert sensor.available is True

    def test_available_when_fresh(self):
        sensor = _make_sensor(initial_value=1)
        sensor._ready = True
        sensor._last_update = time.monotonic()
        assert sensor.available is True

    def test_unavailable_when_stale(self):
        from custom_components.signalk_bridge.const import STALE_TIMEOUT_S

        sensor = _make_sensor(initial_value=1)
        sensor._ready = True
        sensor._last_update = time.monotonic() - STALE_TIMEOUT_S - 60
        assert sensor.available is False


# ===================================================================
# signalk_path / classification properties
# ===================================================================


class TestProperties:
    def test_signalk_path(self):
        sensor = _make_sensor(path="navigation.courseOverGroundTrue")
        assert sensor.signalk_path == "navigation.courseOverGroundTrue"

    def test_classification(self):
        cls = _make_classification(domain=SignalKDomain.WIND)
        sensor = _make_sensor(classification=cls)
        assert sensor.classification.domain == SignalKDomain.WIND


# ===================================================================
# Diagnostic sensors
# ===================================================================


class TestConnectionSensor:
    def test_init(self):
        sensor = SignalKConnectionSensor(
            entity_prefix="sk",
            device_info=_make_device_info(),
        )
        assert sensor._attr_native_value == "disconnected"
        assert sensor._attr_name == "Connection Status"

    def test_set_status(self):
        sensor = SignalKConnectionSensor(
            entity_prefix="sk",
            device_info=_make_device_info(),
        )
        sensor.set_status("connected")
        assert sensor._attr_native_value == "connected"

    def test_unique_id(self):
        sensor = SignalKConnectionSensor(
            entity_prefix="myboat",
            device_info=_make_device_info(),
        )
        assert "myboat" in sensor._attr_unique_id


class TestServerVersionSensor:
    def test_init(self):
        sensor = SignalKServerVersionSensor(
            entity_prefix="sk",
            device_info=_make_device_info(),
        )
        assert sensor._attr_native_value == "unknown"

    def test_set_version(self):
        sensor = SignalKServerVersionSensor(
            entity_prefix="sk",
            device_info=_make_device_info(),
        )
        sensor.set_version("signalk-server 1.46.0")
        assert sensor._attr_native_value == "signalk-server 1.46.0"


# ===================================================================
# async lifecycle
# ===================================================================


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_added_to_hass(self):
        sensor = _make_sensor()
        assert sensor._ready is False
        await sensor.async_added_to_hass()
        assert sensor._ready is True

    @pytest.mark.asyncio
    async def test_removed_from_hass(self):
        sensor = _make_sensor()
        await sensor.async_added_to_hass()
        await sensor.async_will_remove_from_hass()
        assert sensor._ready is False
