"""Sensor platform for SignalK Bridge.

Dynamically creates sensors as SignalK delta values arrive.
Each SignalK path becomes an HA sensor entity under the vessel self device.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

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

from .const import CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX, DOMAIN
from .unit_mapping import (
    SensorMapping,
    convert_value,
    get_sensor_mapping,
    path_to_friendly_name,
)

_LOGGER = logging.getLogger(__name__)

# How long before a sensor is marked unavailable if no updates received
STALE_TIMEOUT = timedelta(minutes=10)

# Throttle state updates to HA (minimum interval between writes)
MIN_UPDATE_INTERVAL = timedelta(seconds=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SignalK Bridge sensors from a config entry."""
    hub = entry.runtime_data
    await hub.register_sensor_platform(async_add_entities)


class SignalKSensor(SensorEntity):
    """Representation of a SignalK path as a HomeAssistant sensor.

    Each instance corresponds to a single SignalK path (e.g.
    'navigation.speedOverGround') and is dynamically created when
    that path is first seen in a delta update.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        path: str,
        initial_value: Any,
        meta: dict[str, Any],
        entity_prefix: str,
        device_info: DeviceInfo,
        config_entry_id: str,
    ) -> None:
        """Initialize the sensor.

        Args:
            path: SignalK dotted path (e.g. 'navigation.speedOverGround').
            initial_value: First value received for this path.
            meta: SignalK metadata dict (units, description, displayName, etc.).
            entity_prefix: User-configured prefix for entity IDs.
            device_info: DeviceInfo for the parent vessel device.
            config_entry_id: The config entry ID this sensor belongs to.
        """
        self._path = path
        self._meta = meta
        self._entity_prefix = entity_prefix
        self._last_updated = datetime.now()
        self._last_ha_update = datetime.min
        self._ready = False

        # Determine SK unit from meta
        sk_units = meta.get("units")

        # Get the mapping for this path/unit
        self._mapping: SensorMapping = get_sensor_mapping(path, sk_units)

        # Unique ID: prefix + path (dots replaced with underscores)
        safe_path = path.replace(".", "_").lower()
        self._attr_unique_id = f"{DOMAIN}_{entity_prefix}_{safe_path}"

        # Entity ID will be: sensor.<prefix>_<path_underscored>
        self.entity_id = f"sensor.{entity_prefix}_{safe_path}"

        # Name: Use meta displayName if available, else generate from path
        display_name = meta.get("displayName") or meta.get("longName")
        if display_name:
            self._attr_name = display_name
        else:
            self._attr_name = path_to_friendly_name(path)

        # Device class and state class from mapping
        if self._mapping.device_class:
            self._attr_device_class = self._mapping.device_class

        if self._mapping.state_class:
            self._attr_state_class = self._mapping.state_class

        # Native unit from mapping
        if self._mapping.native_unit:
            self._attr_native_unit_of_measurement = self._mapping.native_unit

        # Icon override
        if self._mapping.icon:
            self._attr_icon = self._mapping.icon

        # Display precision
        if self._mapping.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                self._mapping.suggested_display_precision
            )

        # Device info — parent vessel device
        self._attr_device_info = device_info

        # Set initial value
        self._raw_value = initial_value
        self._attr_native_value = self._convert(initial_value)

        # Extra state attributes
        self._source = None
        self._sk_timestamp = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            "signalk_path": self._path,
        }
        if self._meta.get("units"):
            attrs["signalk_units"] = self._meta["units"]
        if self._meta.get("description"):
            attrs["signalk_description"] = self._meta["description"]
        if self._source:
            attrs["signalk_source"] = self._source
        if self._sk_timestamp:
            attrs["signalk_timestamp"] = self._sk_timestamp
        return attrs

    @property
    def available(self) -> bool:
        """Return True if the sensor has received data recently."""
        if not self._ready:
            return True
        return (datetime.now() - self._last_updated) < STALE_TIMEOUT

    @property
    def signalk_path(self) -> str:
        """Return the SignalK path this sensor represents."""
        return self._path

    def _convert(self, value: Any) -> Any:
        """Convert a raw SignalK value to the HA native value.

        Handles:
        - Numeric values with conversion factors (e.g. rad -> deg)
        - Object values (e.g. position {latitude, longitude}) -> string
        - String/enum values -> pass-through
        - None -> None
        """
        if value is None:
            return None

        # Handle object/dict values (position, attitude, etc.)
        if isinstance(value, dict):
            # For position, format as "lat, lon"
            if "latitude" in value and "longitude" in value:
                lat = round(value["latitude"], 6)
                lon = round(value["longitude"], 6)
                return f"{lat}, {lon}"
            # For attitude, format as a readable string
            if "roll" in value or "pitch" in value or "yaw" in value:
                parts = []
                for key in ("roll", "pitch", "yaw"):
                    if key in value and value[key] is not None:
                        deg = round(value[key] * 57.2957795131, 1)
                        parts.append(f"{key}={deg}°")
                return " ".join(parts)
            # Generic dict: serialize to string
            return str(value)

        # Handle numeric values
        if isinstance(value, (int, float)):
            return convert_value(value, self._mapping)

        # String/bool/other: pass through
        return value

    @callback
    def update_value(
        self,
        value: Any,
        source: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        """Update the sensor value from a SignalK delta.

        Called by the hub when a new delta arrives for this path.
        Respects throttling to avoid overwhelming HA.
        """
        if not self._ready:
            return

        self._raw_value = value
        self._last_updated = datetime.now()
        if source:
            self._source = source
        if timestamp:
            self._sk_timestamp = timestamp

        new_value = self._convert(value)

        # Throttle updates
        now = datetime.now()
        if (now - self._last_ha_update) < MIN_UPDATE_INTERVAL:
            # Still update the internal value, just don't push to HA
            self._attr_native_value = new_value
            return

        old_value = self._attr_native_value
        self._attr_native_value = new_value

        if new_value != old_value or (now - self._last_ha_update) > timedelta(
            minutes=1
        ):
            self._last_ha_update = now
            self.async_write_ha_state()

    @callback
    def update_meta(self, meta: dict[str, Any]) -> None:
        """Update sensor metadata from a SignalK meta delta."""
        self._meta.update(meta)

        # Re-check mapping with potentially new units
        sk_units = self._meta.get("units")
        self._mapping = get_sensor_mapping(self._path, sk_units)

        # Update display name if meta provides one
        display_name = meta.get("displayName") or meta.get("longName")
        if display_name:
            self._attr_name = display_name

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to HA."""
        await super().async_added_to_hass()
        self._ready = True

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is about to be removed from HA."""
        await super().async_will_remove_from_hass()
        self._ready = False


class SignalKConnectionSensor(SensorEntity):
    """Diagnostic sensor showing the connection status to SignalK."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entity_prefix: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the connection status sensor."""
        self._attr_unique_id = f"{DOMAIN}_{entity_prefix}_connection_status"
        self.entity_id = f"sensor.{entity_prefix}_connection_status"
        self._attr_name = "Connection Status"
        self._attr_icon = "mdi:connection"
        self._attr_native_value = "disconnected"
        self._attr_device_info = device_info

    @callback
    def set_status(self, status: str) -> None:
        """Update the connection status."""
        self._attr_native_value = status
        if self.hass:
            self.async_write_ha_state()


class SignalKServerVersionSensor(SensorEntity):
    """Diagnostic sensor showing the SignalK server version."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entity_prefix: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the server version sensor."""
        self._attr_unique_id = f"{DOMAIN}_{entity_prefix}_server_version"
        self.entity_id = f"sensor.{entity_prefix}_server_version"
        self._attr_name = "Server Version"
        self._attr_icon = "mdi:information-outline"
        self._attr_native_value = "unknown"
        self._attr_device_info = device_info

    @callback
    def set_version(self, version: str) -> None:
        """Update the server version."""
        self._attr_native_value = version
        if self.hass:
            self.async_write_ha_state()
