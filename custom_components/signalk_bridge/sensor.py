"""SignalK Bridge sensor platform.

Sensors are created dynamically as SignalK delta updates arrive.
Each sensor maps to a single canonical SignalK path and belongs to
the vessel self device.

Throttling is NOT done here — the publish-policy engine in the hub
decides whether a value update should be published. The sensor's
`publish_value` method is only called when the policy engine approves.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .classifier import ClassificationResult, path_to_friendly_name
from .const import DOMAIN, STALE_TIMEOUT_S
from .unit_mapping import SensorMapping, convert_value, get_sensor_mapping

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SignalK sensors from a config entry."""
    hub = entry.runtime_data
    await hub.register_sensor_platform(async_add_entities)


class SignalKSensor(SensorEntity):
    """A sensor representing a single canonical SignalK path.

    Created dynamically by the hub when a new path is first seen.
    The hub's publish-policy engine determines when `publish_value`
    is called — this sensor does NOT do its own throttling.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hub: Any,  # SignalKHub (avoid circular import)
        path: str,
        classification: ClassificationResult,
        initial_value: Any,
        meta: dict[str, Any],
        entity_prefix: str,
        device_info: DeviceInfo,
        config_entry_id: str,
        entity_enabled: bool = True,
    ) -> None:
        """Initialize the sensor."""
        self._hub = hub
        self._sk_path = path
        self._classification = classification
        self._meta = meta
        self._source: str = ""
        self._timestamp: str | None = None
        self._last_update: float = 0.0
        self._ready = False

        # Entity properties
        self._attr_unique_id = f"{entity_prefix}_{path.replace('.', '_')}"
        self._attr_device_info = device_info
        self._attr_entity_registry_enabled_default = entity_enabled

        # Determine name from classification or path
        if classification.friendly_name:
            self._attr_name = classification.friendly_name
        else:
            self._attr_name = path_to_friendly_name(path)

        # Icon from classification
        if classification.icon:
            self._attr_icon = classification.icon

        # Look up sensor mapping for units / device class
        sk_units = meta.get("units", "")
        self._mapping = get_sensor_mapping(path, sk_units)

        if self._mapping.device_class is not None:
            self._attr_device_class = self._mapping.device_class
        if self._mapping.state_class is not None:
            self._attr_state_class = self._mapping.state_class
        if self._mapping.native_unit is not None:
            self._attr_native_unit_of_measurement = self._mapping.native_unit
        if self._mapping.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                self._mapping.suggested_display_precision
            )
        # Icon from mapping if not set by classification
        if self._mapping.icon and not classification.icon:
            self._attr_icon = self._mapping.icon

        # Set initial value
        self._attr_native_value = self._convert(initial_value)
        self._last_update = time.monotonic()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with SK metadata."""
        attrs: dict[str, Any] = {
            "signalk_path": self._sk_path,
        }
        if self._meta.get("units"):
            attrs["signalk_units"] = self._meta["units"]
        if self._meta.get("description"):
            attrs["signalk_description"] = self._meta["description"]
        if self._source:
            attrs["signalk_source"] = self._source
        if self._timestamp:
            attrs["signalk_timestamp"] = self._timestamp
        if self._classification:
            attrs["signalk_domain"] = self._classification.domain
        return attrs

    @property
    def available(self) -> bool:
        """Return True if recently updated."""
        if not self._ready:
            return True
        if self._last_update == 0.0:
            return True
        return (time.monotonic() - self._last_update) < STALE_TIMEOUT_S

    @property
    def signalk_path(self) -> str:
        """Return the SignalK path."""
        return self._sk_path

    @property
    def classification(self) -> ClassificationResult:
        """Return the classification result."""
        return self._classification

    def _convert(self, value: Any) -> Any:
        """Convert a raw SignalK value to the HA-appropriate format."""
        if value is None:
            return None

        # Dict values: position, attitude, other objects
        if isinstance(value, dict):
            if "latitude" in value and "longitude" in value:
                lat = value["latitude"]
                lon = value["longitude"]
                return f"{lat:.6f}, {lon:.6f}"
            if "roll" in value or "pitch" in value or "yaw" in value:
                parts = []
                for key in ("roll", "pitch", "yaw"):
                    if key in value:
                        deg = convert_value(value[key], self._mapping) or 0.0
                        parts.append(f"{key}={deg:.1f}°")
                return " ".join(parts)
            return str(value)

        # Numeric conversion
        if isinstance(value, (int, float)):
            return convert_value(value, self._mapping)

        # String/other passthrough
        return value

    @callback
    def publish_value(
        self,
        value: Any,
        source: str = "",
        timestamp: str | None = None,
    ) -> None:
        """Publish a new value to HA state.

        Called by the hub ONLY when the publish-policy engine approves.
        No throttling needed here.
        """
        if not self._ready:
            return

        self._source = source
        self._timestamp = timestamp
        self._last_update = time.monotonic()
        self._attr_native_value = self._convert(value)
        self.async_write_ha_state()

    @callback
    def update_meta(self, meta: dict[str, Any]) -> None:
        """Update metadata for this sensor."""
        self._meta.update(meta)
        sk_units = meta.get("units", self._meta.get("units", ""))
        if sk_units:
            self._mapping = get_sensor_mapping(self._sk_path, sk_units)

    @callback
    def set_enabled(self, enabled: bool) -> None:
        """Set the entity enabled state (from service call)."""
        self._attr_entity_registry_enabled_default = enabled

    async def async_added_to_hass(self) -> None:
        """Mark entity as ready when added to HA."""
        self._ready = True

    async def async_will_remove_from_hass(self) -> None:
        """Mark entity as not ready when removed."""
        self._ready = False


class SignalKConnectionSensor(SensorEntity):
    """Diagnostic sensor showing SignalK connection status."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entity_prefix: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize."""
        self._attr_unique_id = f"{entity_prefix}_connection_status"
        self._attr_name = "Connection Status"
        self._attr_icon = "mdi:lan-connect"
        self._attr_device_info = device_info
        self._attr_native_value = "disconnected"

    @callback
    def set_status(self, status: str) -> None:
        """Update the connection status."""
        self._attr_native_value = status
        if self.hass:
            self.async_write_ha_state()


class SignalKServerVersionSensor(SensorEntity):
    """Diagnostic sensor showing SignalK server version."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entity_prefix: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize."""
        self._attr_unique_id = f"{entity_prefix}_server_version"
        self._attr_name = "Server Version"
        self._attr_icon = "mdi:information-outline"
        self._attr_device_info = device_info
        self._attr_native_value = "unknown"

    @callback
    def set_version(self, version: str) -> None:
        """Update the server version."""
        self._attr_native_value = version
        if self.hass:
            self.async_write_ha_state()
