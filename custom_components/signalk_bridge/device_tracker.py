"""SignalK Bridge device_tracker platform.

Provides a device_tracker entity for the vessel self position,
updated from `navigation.position` SignalK deltas.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SignalK device tracker from a config entry."""
    hub = entry.runtime_data
    await hub.register_tracker_platform(async_add_entities)


class SignalKDeviceTracker(TrackerEntity):
    """Device tracker for vessel self position.

    Updated by the hub when navigation.position deltas arrive
    and the publish-policy engine approves the update.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:ferry"

    def __init__(
        self,
        hub: Any,
        entity_prefix: str,
        device_info: DeviceInfo,
        config_entry_id: str,
    ) -> None:
        """Initialize the device tracker."""
        self._hub = hub
        self._attr_unique_id = f"{entity_prefix}_vessel_position"
        self._attr_name = "Vessel Position"
        self._attr_device_info = device_info
        self._latitude: float | None = None
        self._longitude: float | None = None
        self._source_label: str = ""
        self._timestamp: str | None = None
        self._last_update: float = 0.0
        self._ready = False

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        return self._latitude

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        return self._longitude

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            "signalk_path": "navigation.position",
        }
        if self._source_label:
            attrs["signalk_source"] = self._source_label
        if self._timestamp:
            attrs["signalk_timestamp"] = self._timestamp
        return attrs

    @callback
    def update_position(
        self,
        latitude: float,
        longitude: float,
        source: str = "",
        timestamp: str | None = None,
    ) -> None:
        """Update the position from a SignalK delta.

        Called by the hub when the publish-policy engine approves.
        """
        if not self._ready:
            return

        self._latitude = latitude
        self._longitude = longitude
        self._source_label = source
        self._timestamp = timestamp
        self._last_update = time.monotonic()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Mark as ready."""
        self._ready = True

    async def async_will_remove_from_hass(self) -> None:
        """Mark as not ready."""
        self._ready = False
