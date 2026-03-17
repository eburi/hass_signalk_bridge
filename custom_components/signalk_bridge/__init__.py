"""SignalK Bridge Integration for Home Assistant.

Connects to a SignalK server (local addon or remote) via WebSocket,
receives delta updates, and creates sensors dynamically for all
vessel self paths. Also provides services to PUT/POST values back
to SignalK.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_ENTITY_PREFIX,
    CONF_TOKEN,
    CONF_USE_ADDON,
    DEFAULT_ENTITY_PREFIX,
    DOMAIN,
)
from .sensor import (
    SignalKConnectionSensor,
    SignalKSensor,
    SignalKServerVersionSensor,
)
from .signalk_client import SignalKClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Service names
SERVICE_PUT_VALUE = "put_value"
SERVICE_POST_DELTA = "post_delta"

# Service schemas
SERVICE_PUT_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Required("value"): vol.Any(
            cv.string, vol.Coerce(float), bool, dict, list
        ),
    }
)

SERVICE_POST_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Required("value"): vol.Any(
            cv.string, vol.Coerce(float), bool, dict, list
        ),
    }
)


class SignalKHub:
    """Central hub managing the SignalK connection and sensor lifecycle.

    This is the core of the integration. It:
    - Manages the SignalK client (connection, auth, WebSocket).
    - Processes delta updates and creates/updates sensors.
    - Holds references to all sensors by path.
    - Provides methods for services (PUT/POST).
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the hub."""
        self.hass = hass
        self.entry = entry

        # Config
        self._base_url: str = entry.data[CONF_BASE_URL]
        self._token: str | None = entry.data.get(CONF_TOKEN)
        self._client_id: str | None = entry.data.get(CONF_CLIENT_ID)
        self._entity_prefix: str = entry.data.get(
            CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX
        )

        # SignalK client
        self._client = SignalKClient(
            base_url=self._base_url,
            token=self._token,
            client_id=self._client_id,
        )

        # Sensor tracking
        self._sensors: dict[str, SignalKSensor] = {}
        self._async_add_entities: AddEntitiesCallback | None = None
        self._meta_cache: dict[str, dict[str, Any]] = {}

        # Diagnostic sensors
        self._connection_sensor: SignalKConnectionSensor | None = None
        self._version_sensor: SignalKServerVersionSensor | None = None

        # Device info for vessel self
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._entity_prefix}_vessel_self")},
            name=f"Vessel Self ({self._entity_prefix})",
            manufacturer="SignalK",
            model="Vessel Self",
            configuration_url=self._base_url,
        )

        # Background task handle
        self._ws_task: asyncio.Task | None = None
        self._auth_task: asyncio.Task | None = None

    @property
    def client(self) -> SignalKClient:
        """Return the SignalK client."""
        return self._client

    @property
    def device_info(self) -> DeviceInfo:
        """Return the vessel device info."""
        return self._device_info

    async def register_sensor_platform(
        self, async_add_entities: AddEntitiesCallback
    ) -> None:
        """Called by sensor.py to register the add_entities callback.

        Also creates diagnostic sensors and starts the WebSocket connection.
        """
        self._async_add_entities = async_add_entities

        # Create diagnostic sensors
        self._connection_sensor = SignalKConnectionSensor(
            entity_prefix=self._entity_prefix,
            device_info=self._device_info,
        )
        self._version_sensor = SignalKServerVersionSensor(
            entity_prefix=self._entity_prefix,
            device_info=self._device_info,
        )
        async_add_entities([self._connection_sensor, self._version_sensor])

        # Start the WebSocket connection in a background task
        self._ws_task = self.entry.async_create_background_task(
            self.hass,
            self._run_client(),
            "signalk_bridge_websocket",
        )

    async def _run_client(self) -> None:
        """Run the SignalK client: authenticate then stream."""
        # Update connection status
        if self._connection_sensor:
            self._connection_sensor.set_status("connecting")

        # Authenticate if we have or need a token
        if self._token:
            valid = await self._client.validate_token()
            if not valid:
                _LOGGER.info("Stored token invalid, requesting new access")
                success = await self._client.authenticate()
                if success:
                    # Save new token to config entry
                    await self._save_token()
                else:
                    _LOGGER.warning(
                        "Authentication failed, will try unauthenticated"
                    )
        else:
            # Try to see if server needs auth
            try:
                data = await self._client.get_self_data()
                if not data:
                    # Might need auth — try device access request
                    _LOGGER.info("No data without auth, attempting authentication")
                    success = await self._client.authenticate()
                    if success:
                        await self._save_token()
            except Exception:
                pass

        # Start WebSocket streaming
        await self._client.run(
            on_delta=self._on_delta,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )

    async def _save_token(self) -> None:
        """Persist the current token and client_id to the config entry."""
        new_data = dict(self.entry.data)
        new_data[CONF_TOKEN] = self._client.token
        new_data[CONF_CLIENT_ID] = self._client.client_id
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    async def _on_connect(self) -> None:
        """Called when WebSocket connects."""
        _LOGGER.info("Connected to SignalK server")
        if self._connection_sensor:
            self._connection_sensor.set_status("connected")

        # Update server version from hello message
        server_info = self._client.server_info
        if self._version_sensor and server_info:
            version = server_info.get("version", "unknown")
            name = server_info.get("name", "")
            self._version_sensor.set_version(f"{name} {version}".strip())

        # Update device info with server details
        if server_info:
            self._device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{self._entity_prefix}_vessel_self")},
                name=f"Vessel Self ({self._entity_prefix})",
                manufacturer="SignalK",
                model="Vessel Self",
                sw_version=server_info.get("version"),
                configuration_url=self._base_url,
            )

    async def _on_disconnect(self) -> None:
        """Called when WebSocket disconnects."""
        _LOGGER.warning("Disconnected from SignalK server")
        if self._connection_sensor:
            self._connection_sensor.set_status("disconnected")

    async def _on_delta(self, msg: dict[str, Any]) -> None:
        """Process a SignalK delta message.

        Creates new sensors for paths we haven't seen before,
        and updates existing sensors with new values.
        """
        if not self._async_add_entities:
            return

        updates = msg.get("updates", [])
        for update in updates:
            source_label = ""
            source_data = update.get("source", {})
            if isinstance(source_data, dict):
                source_label = source_data.get("label", "")
            elif isinstance(source_data, str):
                source_label = source_data
            # Also check $source
            if not source_label:
                source_label = update.get("$source", "")

            timestamp = update.get("timestamp")

            # Handle value updates
            values = update.get("values", [])
            for item in values:
                path = item.get("path", "")
                value = item.get("value")

                if not path:
                    continue

                await self._process_value(path, value, source_label, timestamp)

            # Handle meta updates
            meta_items = update.get("meta", [])
            for item in meta_items:
                path = item.get("path", "")
                meta_value = item.get("value", {})
                if path and isinstance(meta_value, dict):
                    self._meta_cache[path] = meta_value
                    # Update existing sensor meta if it exists
                    if path in self._sensors:
                        self._sensors[path].update_meta(meta_value)

    async def _process_value(
        self,
        path: str,
        value: Any,
        source: str,
        timestamp: str | None,
    ) -> None:
        """Process a single path/value from a delta update."""
        # Handle nested object values (e.g., position, attitude)
        # These come as dicts — we create a single sensor for the parent
        # path with the dict as value, rather than expanding sub-keys.

        sensor = self._sensors.get(path)

        if sensor is None:
            # New path — create a sensor
            meta = self._meta_cache.get(path, {})

            # Try to fetch meta from server if not cached
            if not meta:
                meta = await self._client.get_path_meta(path)
                if meta:
                    self._meta_cache[path] = meta

            sensor = SignalKSensor(
                path=path,
                initial_value=value,
                meta=meta,
                entity_prefix=self._entity_prefix,
                device_info=self._device_info,
                config_entry_id=self.entry.entry_id,
            )
            self._sensors[path] = sensor
            if self._async_add_entities is not None:
                self._async_add_entities([sensor])
            _LOGGER.debug("Created sensor for path: %s", path)
        else:
            # Existing sensor — update value
            sensor.update_value(value, source=source, timestamp=timestamp)

    async def put_value(self, path: str, value: Any) -> dict[str, Any]:
        """PUT a value to a SignalK path (service handler)."""
        return await self._client.put_value(path, value)

    async def post_delta(self, path: str, value: Any) -> bool:
        """POST a delta for a SignalK path (service handler)."""
        return await self._client.post_delta(path, value)

    async def stop(self) -> None:
        """Stop the hub and clean up."""
        await self._client.stop()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass


# ------------------------------------------------------------------
# Integration setup / teardown
# ------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the SignalK Bridge integration (global one-time setup).

    Registers services that work across all config entries.
    """
    _LOGGER.info("Setting up SignalK Bridge integration")

    async def handle_put_value(call: ServiceCall) -> None:
        """Handle the signalk_bridge.put_value service call."""
        path = call.data["path"]
        value = call.data["value"]

        # Find all config entries for this domain and send to all active hubs
        entries = hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            hub: SignalKHub | None = getattr(entry, "runtime_data", None)
            if hub:
                result = await hub.put_value(path, value)
                _LOGGER.debug(
                    "PUT %s = %s via %s: %s",
                    path,
                    value,
                    entry.title,
                    result,
                )

    async def handle_post_delta(call: ServiceCall) -> None:
        """Handle the signalk_bridge.post_delta service call."""
        path = call.data["path"]
        value = call.data["value"]

        entries = hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            hub: SignalKHub | None = getattr(entry, "runtime_data", None)
            if hub:
                result = await hub.post_delta(path, value)
                _LOGGER.debug(
                    "POST delta %s = %s via %s: %s",
                    path,
                    value,
                    entry.title,
                    result,
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PUT_VALUE,
        handle_put_value,
        schema=SERVICE_PUT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_POST_DELTA,
        handle_post_delta,
        schema=SERVICE_POST_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SignalK Bridge from a config entry."""
    _LOGGER.info(
        "Setting up SignalK Bridge entry: %s (url=%s)",
        entry.title,
        entry.data.get(CONF_BASE_URL),
    )

    hub = SignalKHub(hass, entry)
    entry.runtime_data = hub

    # Listen for HA stop to clean up
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP,
            lambda event: hass.async_create_task(hub.stop()),
        )
    )

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a SignalK Bridge config entry."""
    _LOGGER.info("Unloading SignalK Bridge entry: %s", entry.title)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Stop the hub
    hub: SignalKHub | None = getattr(entry, "runtime_data", None)
    if hub:
        await hub.stop()

    return unload_ok
