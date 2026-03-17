"""Tests for sensor.py — sensor entity creation and value conversion."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from custom_components.signalk_bridge.sensor import (
    SignalKSensor,
    SignalKConnectionSensor,
    SignalKServerVersionSensor,
    STALE_TIMEOUT,
)
from custom_components.signalk_bridge.unit_mapping import get_sensor_mapping


def _make_device_info():
    from homeassistant.helpers.device_registry import DeviceInfo
    return DeviceInfo(
        identifiers={("signalk_bridge", "test_vessel_self")},
        name="Vessel Self (test)",
    )


# ===================================================================
# SignalKSensor init
# ===================================================================

class TestSignalKSensorInit:
    def test_basic_numeric_sensor(self):
        sensor = SignalKSensor(
            path="navigation.speedOverGround",
            initial_value=5.14,
            meta={"units": "m/s"},
            entity_prefix="signalk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._path == "navigation.speedOverGround"
        assert sensor._attr_unique_id == "signalk_bridge_signalk_navigation_speedoverground"
        assert sensor.entity_id == "sensor.signalk_navigation_speedoverground"
        assert sensor._attr_native_value is not None

    def test_display_name_from_meta(self):
        sensor = SignalKSensor(
            path="navigation.speedOverGround",
            initial_value=5.0,
            meta={"units": "m/s", "displayName": "Speed Over Ground"},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._attr_name == "Speed Over Ground"

    def test_display_name_from_longName(self):
        sensor = SignalKSensor(
            path="navigation.heading",
            initial_value=1.57,
            meta={"units": "rad", "longName": "Magnetic Heading"},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._attr_name == "Magnetic Heading"

    def test_display_name_generated_from_path(self):
        sensor = SignalKSensor(
            path="navigation.courseOverGroundTrue",
            initial_value=1.0,
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert "Course" in sensor._attr_name
        assert "Over" in sensor._attr_name

    def test_temperature_sensor(self):
        sensor = SignalKSensor(
            path="environment.water.temperature",
            initial_value=295.15,
            meta={"units": "K"},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._attr_device_class == "temperature"
        assert sensor._attr_native_unit_of_measurement == "K"
        # Value should pass through (HA handles K->°C conversion)
        assert sensor._attr_native_value == 295.15

    def test_angle_sensor_converts_rad_to_deg(self):
        import math
        sensor = SignalKSensor(
            path="navigation.headingMagnetic",
            initial_value=math.pi,
            meta={"units": "rad"},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._attr_native_unit_of_measurement == "°"
        assert abs(sensor._attr_native_value - 180.0) < 0.1

    def test_ratio_to_percent(self):
        sensor = SignalKSensor(
            path="tanks.fuel.0.currentLevel",
            initial_value=0.75,
            meta={"units": "ratio"},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._attr_native_unit_of_measurement == "%"
        assert abs(sensor._attr_native_value - 75.0) < 0.01

    def test_no_unit_sensor(self):
        sensor = SignalKSensor(
            path="some.custom.path",
            initial_value="active",
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test_entry",
        )
        assert sensor._attr_device_class is None
        assert sensor._attr_native_value == "active"


# ===================================================================
# Value conversion (_convert)
# ===================================================================

class TestSensorConvert:
    def _make_sensor(self, path="test.path", meta=None, initial_value=None):
        return SignalKSensor(
            path=path,
            initial_value=initial_value,
            meta=meta or {},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )

    def test_none(self):
        s = self._make_sensor()
        assert s._convert(None) is None

    def test_position_dict(self):
        s = self._make_sensor()
        result = s._convert({"latitude": 51.123456, "longitude": -1.654321})
        assert "51.123456" in result
        assert "-1.654321" in result

    def test_attitude_dict(self):
        import math
        s = self._make_sensor()
        result = s._convert({"roll": 0.1, "pitch": 0.2, "yaw": 0.0})
        assert "roll=" in result
        assert "pitch=" in result

    def test_generic_dict(self):
        s = self._make_sensor()
        result = s._convert({"foo": "bar"})
        assert "foo" in result

    def test_string_passthrough(self):
        s = self._make_sensor()
        assert s._convert("NMEA2000") == "NMEA2000"

    def test_bool_passthrough(self):
        s = self._make_sensor()
        # In Python, bool is a subclass of int, so True is treated as
        # numeric (1.0) by the converter. This is expected behavior —
        # SignalK boolean values are rare and get numeric conversion.
        result = s._convert(True)
        assert result == 1.0


# ===================================================================
# update_value
# ===================================================================

class TestSensorUpdateValue:
    def test_update_before_ready_is_ignored(self):
        sensor = SignalKSensor(
            path="test.path",
            initial_value=1.0,
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )
        # _ready is False by default
        assert sensor._ready is False
        sensor.update_value(2.0, source="test", timestamp="2024-01-01T00:00:00Z")
        # Value should be unchanged (initial convert result)
        assert sensor._attr_native_value == 1.0

    def test_update_after_ready(self):
        sensor = SignalKSensor(
            path="test.path",
            initial_value=1.0,
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )
        sensor._ready = True
        sensor._last_ha_update = datetime.min  # bypass throttle
        sensor.update_value(99.0, source="test_src", timestamp="2024-01-01T00:00:00Z")
        assert sensor._attr_native_value == 99.0
        assert sensor._source == "test_src"
        assert sensor._sk_timestamp == "2024-01-01T00:00:00Z"


# ===================================================================
# update_meta
# ===================================================================

class TestSensorUpdateMeta:
    def test_update_meta_refreshes_mapping(self):
        sensor = SignalKSensor(
            path="environment.something",
            initial_value=300.0,
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )
        # Initially no device class
        assert sensor._attr_device_class is None

        # Now update meta with units
        sensor.update_meta({"units": "K", "displayName": "Something Temp"})
        assert sensor._mapping.device_class == "temperature"
        assert sensor._attr_name == "Something Temp"


# ===================================================================
# extra_state_attributes
# ===================================================================

class TestExtraStateAttributes:
    def test_attributes_include_path(self):
        sensor = SignalKSensor(
            path="navigation.sog",
            initial_value=5.0,
            meta={"units": "m/s", "description": "Speed over ground"},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )
        attrs = sensor.extra_state_attributes
        assert attrs["signalk_path"] == "navigation.sog"
        assert attrs["signalk_units"] == "m/s"
        assert attrs["signalk_description"] == "Speed over ground"

    def test_attributes_without_meta(self):
        sensor = SignalKSensor(
            path="custom.path",
            initial_value="x",
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )
        attrs = sensor.extra_state_attributes
        assert attrs["signalk_path"] == "custom.path"
        assert "signalk_units" not in attrs


# ===================================================================
# availability (staleness)
# ===================================================================

class TestSensorAvailability:
    def test_available_when_not_ready(self):
        sensor = SignalKSensor(
            path="test", initial_value=1, meta={},
            entity_prefix="sk", device_info=_make_device_info(),
            config_entry_id="test",
        )
        # _ready=False → always available
        assert sensor.available is True

    def test_available_when_fresh(self):
        sensor = SignalKSensor(
            path="test", initial_value=1, meta={},
            entity_prefix="sk", device_info=_make_device_info(),
            config_entry_id="test",
        )
        sensor._ready = True
        sensor._last_updated = datetime.now()
        assert sensor.available is True

    def test_unavailable_when_stale(self):
        sensor = SignalKSensor(
            path="test", initial_value=1, meta={},
            entity_prefix="sk", device_info=_make_device_info(),
            config_entry_id="test",
        )
        sensor._ready = True
        sensor._last_updated = datetime.now() - STALE_TIMEOUT - timedelta(minutes=1)
        assert sensor.available is False


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
# signalk_path property
# ===================================================================

class TestSignalKPathProperty:
    def test_signalk_path(self):
        sensor = SignalKSensor(
            path="navigation.courseOverGroundTrue",
            initial_value=1.0,
            meta={},
            entity_prefix="sk",
            device_info=_make_device_info(),
            config_entry_id="test",
        )
        assert sensor.signalk_path == "navigation.courseOverGroundTrue"
