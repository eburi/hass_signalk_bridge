"""Tests for device_tracker.py — SignalKDeviceTracker entity."""

import pytest

from custom_components.signalk_bridge.device_tracker import (
    SignalKDeviceTracker,
    async_setup_entry,
)
from homeassistant.components.device_tracker import SourceType
from homeassistant.helpers.device_registry import DeviceInfo


def _make_device_info():
    return DeviceInfo(
        identifiers={("signalk_bridge", "test_vessel_self")},
        name="Vessel Self (test)",
    )


def _make_tracker(**kwargs):
    from unittest.mock import MagicMock
    hub = MagicMock()
    return SignalKDeviceTracker(
        hub=hub,
        entity_prefix=kwargs.get("entity_prefix", "signalk"),
        device_info=kwargs.get("device_info", _make_device_info()),
        config_entry_id=kwargs.get("config_entry_id", "test_entry"),
    )


# ===================================================================
# Initialization
# ===================================================================

class TestDeviceTrackerInit:
    def test_unique_id(self):
        tracker = _make_tracker()
        assert tracker._attr_unique_id == "signalk_vessel_position"

    def test_name(self):
        tracker = _make_tracker()
        assert tracker._attr_name == "Vessel Position"

    def test_icon(self):
        tracker = _make_tracker()
        assert tracker._attr_icon == "mdi:ferry"

    def test_should_poll_false(self):
        tracker = _make_tracker()
        assert tracker._attr_should_poll is False

    def test_custom_prefix(self):
        tracker = _make_tracker(entity_prefix="myboat")
        assert "myboat" in tracker._attr_unique_id

    def test_initial_state(self):
        tracker = _make_tracker()
        assert tracker.latitude is None
        assert tracker.longitude is None
        assert tracker._ready is False


# ===================================================================
# source_type
# ===================================================================

class TestSourceType:
    def test_source_type_is_gps(self):
        tracker = _make_tracker()
        assert tracker.source_type == SourceType.GPS


# ===================================================================
# update_position
# ===================================================================

class TestUpdatePosition:
    def test_update_before_ready_ignored(self):
        tracker = _make_tracker()
        assert tracker._ready is False
        tracker.update_position(51.5, -1.2, source="gps", timestamp="2024-01-01T00:00:00Z")
        assert tracker.latitude is None
        assert tracker.longitude is None

    def test_update_after_ready(self):
        tracker = _make_tracker()
        tracker._ready = True
        tracker.update_position(51.5, -1.2, source="gps", timestamp="2024-01-01T00:00:00Z")
        assert tracker.latitude == 51.5
        assert tracker.longitude == -1.2
        assert tracker._source_label == "gps"
        assert tracker._timestamp == "2024-01-01T00:00:00Z"

    def test_update_without_optional_params(self):
        tracker = _make_tracker()
        tracker._ready = True
        tracker.update_position(48.8566, 2.3522)
        assert tracker.latitude == 48.8566
        assert tracker.longitude == 2.3522
        assert tracker._source_label == ""
        assert tracker._timestamp is None

    def test_update_position_updates_last_update(self):
        tracker = _make_tracker()
        tracker._ready = True
        assert tracker._last_update == 0.0
        tracker.update_position(51.5, -1.2)
        assert tracker._last_update > 0.0


# ===================================================================
# extra_state_attributes
# ===================================================================

class TestExtraStateAttributes:
    def test_default_attributes(self):
        tracker = _make_tracker()
        attrs = tracker.extra_state_attributes
        assert attrs["signalk_path"] == "navigation.position"

    def test_attributes_with_source(self):
        tracker = _make_tracker()
        tracker._ready = True
        tracker.update_position(51.5, -1.2, source="n2k-gps")
        attrs = tracker.extra_state_attributes
        assert attrs["signalk_source"] == "n2k-gps"

    def test_attributes_with_timestamp(self):
        tracker = _make_tracker()
        tracker._ready = True
        tracker.update_position(51.5, -1.2, timestamp="2024-06-15T12:00:00Z")
        attrs = tracker.extra_state_attributes
        assert attrs["signalk_timestamp"] == "2024-06-15T12:00:00Z"

    def test_attributes_without_source(self):
        tracker = _make_tracker()
        attrs = tracker.extra_state_attributes
        assert "signalk_source" not in attrs

    def test_attributes_without_timestamp(self):
        tracker = _make_tracker()
        attrs = tracker.extra_state_attributes
        assert "signalk_timestamp" not in attrs


# ===================================================================
# async lifecycle
# ===================================================================

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_added_to_hass_sets_ready(self):
        tracker = _make_tracker()
        assert tracker._ready is False
        await tracker.async_added_to_hass()
        assert tracker._ready is True

    @pytest.mark.asyncio
    async def test_remove_from_hass_clears_ready(self):
        tracker = _make_tracker()
        await tracker.async_added_to_hass()
        assert tracker._ready is True
        await tracker.async_will_remove_from_hass()
        assert tracker._ready is False


# ===================================================================
# async_setup_entry
# ===================================================================

class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_registers_tracker_platform(self):
        from unittest.mock import MagicMock, AsyncMock
        from homeassistant.core import HomeAssistant
        from homeassistant.config_entries import ConfigEntry

        hass = HomeAssistant()
        entry = ConfigEntry(entry_id="test", data={})
        hub = MagicMock()
        hub.register_tracker_platform = AsyncMock()
        entry.runtime_data = hub

        mock_add_entities = MagicMock()
        await async_setup_entry(hass, entry, mock_add_entities)
        hub.register_tracker_platform.assert_called_once_with(mock_add_entities)
