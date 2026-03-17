"""SignalK Bridge Integration for Home Assistant.

Connects to a SignalK server via WebSocket, classifies paths into
functional domains, applies per-domain publish policies to control
HA state write frequency, and creates entities dynamically.
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

from .classifier import (
    ClassificationResult,
    canonicalize_path,
    classify_path,
    is_ignored_path,
)
from .const import (
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_CREATE_DIAGNOSTIC_ENTITIES,
    CONF_ENABLE_NEW_SENSORS,
    CONF_ENTITY_PREFIX,
    CONF_LOG_IGNORED_PATHS,
    CONF_PUBLISH_PROFILE,
    CONF_TOKEN,
    DEFAULT_CREATE_DIAGNOSTIC_ENTITIES,
    DEFAULT_ENABLE_NEW_SENSORS,
    DEFAULT_ENTITY_PREFIX,
    DEFAULT_LOG_IGNORED_PATHS,
    DEFAULT_PUBLISH_PROFILE,
    DOMAIN,
    SignalKDomain,
)
from .publish_policy import DomainPolicy, PublishPolicyEngine
from .signalk_client import SignalKClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.DEVICE_TRACKER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Service names
SERVICE_PUT_VALUE = "put_value"
SERVICE_POST_DELTA = "post_delta"
SERVICE_SET_DOMAIN_POLICY = "set_domain_policy"
SERVICE_RESET_DOMAIN_POLICY = "reset_domain_policy"
SERVICE_SET_DISCOVERY_DEFAULTS = "set_discovery_defaults"
SERVICE_RESCAN_PATHS = "rescan_paths"
SERVICE_RECLASSIFY_PATHS = "reclassify_paths"
SERVICE_ENABLE_ENTITIES = "enable_entities"
SERVICE_DISABLE_ENTITIES = "disable_entities"
SERVICE_DUMP_RUNTIME_STATE = "dump_runtime_state"


# ──────────────────────────────────────────────────────────────────────
# Service schemas
# ──────────────────────────────────────────────────────────────────────

SERVICE_PUT_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Required("value"): vol.Any(cv.string, vol.Coerce(float), bool, dict, list),
    }
)

SERVICE_POST_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Required("value"): vol.Any(cv.string, vol.Coerce(float), bool, dict, list),
    }
)

SERVICE_SET_DOMAIN_POLICY_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): cv.string,
        vol.Optional("min_interval_seconds"): vol.Coerce(float),
        vol.Optional("max_interval_seconds"): vol.Coerce(float),
        vol.Optional("deadband"): vol.Coerce(float),
        vol.Optional("enabled_by_default"): cv.boolean,
    }
)

SERVICE_RESET_DOMAIN_POLICY_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): cv.string,
    }
)

SERVICE_SET_DISCOVERY_DEFAULTS_SCHEMA = vol.Schema(
    {
        vol.Optional("enable_new_sensors_by_default"): cv.boolean,
        vol.Optional("publish_profile"): cv.string,
        vol.Optional("log_ignored_paths"): cv.boolean,
    }
)

SERVICE_ENTITY_LIST_SCHEMA = vol.Schema(
    {
        vol.Required("entity_ids"): vol.Any(cv.string, [cv.string]),
    }
)

SERVICE_EMPTY_SCHEMA = vol.Schema({})


class SignalKHub:
    """Central hub managing the SignalK connection, classification, and entities.

    Architecture:
    1. SignalK WebSocket client streams deltas
    2. Delta parser extracts canonical paths
    3. Classifier assigns domain/platform/defaults per path
    4. Publish-policy engine gates which updates reach HA
    5. Entity registry creates/updates entities
    6. Runtime settings allow live adjustments via services
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

        # Runtime settings (from options, falling back to data)
        opts = {**entry.data, **entry.options}
        self._enable_new_sensors: bool = opts.get(
            CONF_ENABLE_NEW_SENSORS, DEFAULT_ENABLE_NEW_SENSORS
        )
        self._log_ignored_paths: bool = opts.get(
            CONF_LOG_IGNORED_PATHS, DEFAULT_LOG_IGNORED_PATHS
        )
        self._create_diagnostic: bool = opts.get(
            CONF_CREATE_DIAGNOSTIC_ENTITIES, DEFAULT_CREATE_DIAGNOSTIC_ENTITIES
        )

        # SignalK client
        self._client = SignalKClient(
            base_url=self._base_url,
            token=self._token,
            client_id=self._client_id,
        )

        # Publish-policy engine
        profile_name = opts.get(CONF_PUBLISH_PROFILE, DEFAULT_PUBLISH_PROFILE)
        self._policy_engine = PublishPolicyEngine(profile=profile_name)

        # Path registry / classification cache
        self._classifications: dict[str, ClassificationResult] = {}
        self._ignored_paths: set[str] = set()

        # In-memory latest-value store (canonical path → raw value)
        self._latest_values: dict[str, Any] = {}
        self._meta_cache: dict[str, dict[str, Any]] = {}

        # Entity tracking
        self._sensors: dict[str, Any] = {}  # path → SignalKSensor
        self._device_tracker: Any | None = None  # position device_tracker
        self._connection_sensor: Any | None = None
        self._version_sensor: Any | None = None

        # Platform callbacks
        self._sensor_add_entities: AddEntitiesCallback | None = None
        self._tracker_add_entities: AddEntitiesCallback | None = None

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

        # Reconnect state: when True, suppress initial burst
        self._is_reconnect = False

    # ──────────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────────

    @property
    def client(self) -> SignalKClient:
        """Return the SignalK client."""
        return self._client

    @property
    def device_info(self) -> DeviceInfo:
        """Return the vessel device info."""
        return self._device_info

    @property
    def policy_engine(self) -> PublishPolicyEngine:
        """Return the publish policy engine."""
        return self._policy_engine

    @property
    def classifications(self) -> dict[str, ClassificationResult]:
        """Return the classification cache (path → result)."""
        return self._classifications

    @property
    def ignored_paths(self) -> set[str]:
        """Return the set of ignored paths."""
        return self._ignored_paths

    @property
    def sensors(self) -> dict[str, Any]:
        """Return the sensor registry."""
        return self._sensors

    @property
    def enable_new_sensors(self) -> bool:
        """Return whether new sensors are enabled by default."""
        return self._enable_new_sensors

    @enable_new_sensors.setter
    def enable_new_sensors(self, value: bool) -> None:
        """Set whether new sensors are enabled by default."""
        self._enable_new_sensors = value

    @property
    def log_ignored_paths(self) -> bool:
        """Return whether ignored paths are logged."""
        return self._log_ignored_paths

    @log_ignored_paths.setter
    def log_ignored_paths(self, value: bool) -> None:
        """Set whether ignored paths are logged."""
        self._log_ignored_paths = value

    # ──────────────────────────────────────────────────────────────
    # Platform registration
    # ──────────────────────────────────────────────────────────────

    async def register_sensor_platform(
        self, async_add_entities: AddEntitiesCallback
    ) -> None:
        """Register the sensor platform's add_entities callback."""
        self._sensor_add_entities = async_add_entities

        # Create diagnostic sensors if enabled
        if self._create_diagnostic:
            from .sensor import SignalKConnectionSensor, SignalKServerVersionSensor

            self._connection_sensor = SignalKConnectionSensor(
                entity_prefix=self._entity_prefix,
                device_info=self._device_info,
            )
            self._version_sensor = SignalKServerVersionSensor(
                entity_prefix=self._entity_prefix,
                device_info=self._device_info,
            )
            async_add_entities([self._connection_sensor, self._version_sensor])

        # Start WebSocket if both platforms are ready, or if no tracker needed
        self._maybe_start_ws()

    async def register_tracker_platform(
        self, async_add_entities: AddEntitiesCallback
    ) -> None:
        """Register the device_tracker platform's add_entities callback."""
        self._tracker_add_entities = async_add_entities
        self._maybe_start_ws()

    def _maybe_start_ws(self) -> None:
        """Start the WebSocket task once all platforms have registered."""
        if self._ws_task is not None:
            return  # Already started
        if self._sensor_add_entities is None:
            return  # Wait for sensor platform
        if self._tracker_add_entities is None:
            return  # Wait for tracker platform

        self._ws_task = self.entry.async_create_background_task(
            self.hass,
            self._run_client(),
            "signalk_bridge_websocket",
        )

    # ──────────────────────────────────────────────────────────────
    # WebSocket lifecycle
    # ──────────────────────────────────────────────────────────────

    async def _run_client(self) -> None:
        """Run the SignalK client: authenticate then stream."""
        if self._connection_sensor:
            self._connection_sensor.set_status("connecting")

        # Authenticate if needed
        if self._token:
            valid = await self._client.validate_token()
            if not valid:
                _LOGGER.info("Stored token invalid, requesting new access")
                success = await self._client.authenticate()
                if success:
                    await self._save_token()
                else:
                    _LOGGER.warning("Auth failed, will try unauthenticated")
        else:
            try:
                data = await self._client.get_self_data()
                if not data:
                    _LOGGER.info("No data without auth, attempting authentication")
                    success = await self._client.authenticate()
                    if success:
                        await self._save_token()
            except Exception:
                pass

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

        server_info = self._client.server_info
        if self._version_sensor and server_info:
            version = server_info.get("version", "unknown")
            name = server_info.get("name", "")
            self._version_sensor.set_version(f"{name} {version}".strip())

        if server_info:
            self._device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{self._entity_prefix}_vessel_self")},
                name=f"Vessel Self ({self._entity_prefix})",
                manufacturer="SignalK",
                model="Vessel Self",
                sw_version=server_info.get("version"),
                configuration_url=self._base_url,
            )

        # On reconnect, clear path states so policies re-evaluate,
        # but don't flood HA with immediate writes
        if self._is_reconnect:
            _LOGGER.info("Reconnect: applying controlled state refresh")
            self._policy_engine.clear_path_states()
        self._is_reconnect = True

    async def _on_disconnect(self) -> None:
        """Called when WebSocket disconnects."""
        _LOGGER.warning("Disconnected from SignalK server")
        if self._connection_sensor:
            self._connection_sensor.set_status("disconnected")

    # ──────────────────────────────────────────────────────────────
    # Delta processing
    # ──────────────────────────────────────────────────────────────

    async def _on_delta(self, msg: dict[str, Any]) -> None:
        """Process a SignalK delta message."""
        updates = msg.get("updates", [])
        for update in updates:
            source_label = self._extract_source(update)
            timestamp = update.get("timestamp")

            # Value updates
            for item in update.get("values", []):
                raw_path = item.get("path", "")
                value = item.get("value")
                if not raw_path:
                    continue

                canonical = canonicalize_path(raw_path)
                await self._process_path(canonical, value, source_label, timestamp)

            # Meta updates
            for item in update.get("meta", []):
                path = item.get("path", "")
                meta_value = item.get("value", {})
                if path and isinstance(meta_value, dict):
                    canonical = canonicalize_path(path)
                    self._meta_cache[canonical] = meta_value
                    sensor = self._sensors.get(canonical)
                    if sensor is not None:
                        sensor.update_meta(meta_value)

    @staticmethod
    def _extract_source(update: dict[str, Any]) -> str:
        """Extract source label from a delta update."""
        source_data = update.get("source", {})
        if isinstance(source_data, dict):
            label = source_data.get("label", "")
        elif isinstance(source_data, str):
            label = source_data
        else:
            label = ""
        if not label:
            label = update.get("$source", "")
        return label

    async def _process_path(
        self,
        path: str,
        value: Any,
        source: str,
        timestamp: str | None,
    ) -> None:
        """Process a single canonical path/value from a delta."""
        # Always update latest-value store
        self._latest_values[path] = value

        # Check if path should be ignored
        if is_ignored_path(path):
            if path not in self._ignored_paths:
                self._ignored_paths.add(path)
                if self._log_ignored_paths:
                    _LOGGER.debug("Ignoring path (filtered): %s", path)
            return

        # Classify (cached)
        classification = self._classifications.get(path)
        if classification is None:
            classification = classify_path(path)
            self._classifications[path] = classification
            _LOGGER.debug(
                "Classified %s → domain=%s platform=%s enabled=%s",
                path,
                classification.domain,
                classification.platform,
                classification.enabled_by_default,
            )

        # Skip unsupported/ignored domain
        if classification.domain == SignalKDomain.UNSUPPORTED_IGNORE:
            if path not in self._ignored_paths:
                self._ignored_paths.add(path)
                if self._log_ignored_paths:
                    _LOGGER.debug("Ignoring path (unsupported): %s", path)
            return

        # Check publish policy — should we update HA?
        immediate = classification.domain == SignalKDomain.ALARM
        should_publish = self._policy_engine.should_publish(
            path,
            classification.domain,
            value,
            immediate=immediate,
        )

        # Device tracker special handling
        if (
            classification.platform == "device_tracker"
            and path == "navigation.position"
        ):
            await self._update_device_tracker(value, source, timestamp, should_publish)
            return

        # Sensor handling
        sensor = self._sensors.get(path)

        if sensor is None:
            # New path — create sensor entity
            if not self._sensor_add_entities:
                return

            meta = self._meta_cache.get(path, {})
            if not meta:
                meta = await self._client.get_path_meta(path)
                if meta:
                    self._meta_cache[path] = meta

            from .sensor import SignalKSensor

            # Determine if entity should be enabled
            policy = self._policy_engine.get_policy(classification.domain)
            entity_enabled = (
                self._enable_new_sensors
                and classification.enabled_by_default
                and policy.enabled_by_default
            )

            sensor = SignalKSensor(
                hub=self,
                path=path,
                classification=classification,
                initial_value=value,
                meta=meta,
                entity_prefix=self._entity_prefix,
                device_info=self._device_info,
                config_entry_id=self.entry.entry_id,
                entity_enabled=entity_enabled,
            )
            self._sensors[path] = sensor
            self._sensor_add_entities([sensor])
            _LOGGER.debug(
                "Created sensor: %s (domain=%s, enabled=%s)",
                path,
                classification.domain,
                entity_enabled,
            )
        elif should_publish:
            sensor.publish_value(value, source=source, timestamp=timestamp)

    async def _update_device_tracker(
        self,
        value: Any,
        source: str,
        timestamp: str | None,
        should_publish: bool,
    ) -> None:
        """Create or update the vessel self device_tracker."""
        if self._device_tracker is None:
            if not self._tracker_add_entities:
                return

            from .device_tracker import SignalKDeviceTracker

            self._device_tracker = SignalKDeviceTracker(
                hub=self,
                entity_prefix=self._entity_prefix,
                device_info=self._device_info,
                config_entry_id=self.entry.entry_id,
            )
            self._tracker_add_entities([self._device_tracker])
            _LOGGER.debug("Created device_tracker for vessel position")

        if should_publish and isinstance(value, dict):
            lat = value.get("latitude")
            lon = value.get("longitude")
            if lat is not None and lon is not None:
                self._device_tracker.update_position(
                    latitude=lat,
                    longitude=lon,
                    source=source,
                    timestamp=timestamp,
                )

    # ──────────────────────────────────────────────────────────────
    # Service handlers
    # ──────────────────────────────────────────────────────────────

    async def put_value(self, path: str, value: Any) -> dict[str, Any]:
        """PUT a value to a SignalK path."""
        return await self._client.put_value(path, value)

    async def post_delta(self, path: str, value: Any) -> bool:
        """POST a delta for a SignalK path."""
        return await self._client.post_delta(path, value)

    def set_domain_policy(
        self,
        domain: SignalKDomain,
        *,
        min_interval: float | None = None,
        max_interval: float | None = None,
        deadband: float | None = None,
        enabled_by_default: bool | None = None,
    ) -> DomainPolicy:
        """Update the publish policy for a domain."""
        return self._policy_engine.set_policy(
            domain,
            min_interval=min_interval,
            max_interval=max_interval,
            deadband=deadband,
            enabled_by_default=enabled_by_default,
        )

    def reset_domain_policy(self, domain: SignalKDomain) -> DomainPolicy:
        """Reset a domain's policy to profile defaults."""
        return self._policy_engine.reset_policy(domain)

    def reclassify_paths(self) -> int:
        """Reclassify all known paths. Returns count of reclassified paths."""
        count = 0
        paths = list(self._classifications.keys()) + list(self._ignored_paths)
        self._classifications.clear()
        self._ignored_paths.clear()

        for path in paths:
            if is_ignored_path(path):
                self._ignored_paths.add(path)
            else:
                new_class = classify_path(path)
                self._classifications[path] = new_class
            count += 1

        _LOGGER.info("Reclassified %d paths", count)
        return count

    def rescan_paths(self) -> dict[str, Any]:
        """Rescan all known paths from the latest-value store.

        Returns summary of newly discovered paths.
        """
        new_paths: list[str] = []
        for path in self._latest_values:
            if path not in self._classifications and path not in self._ignored_paths:
                if is_ignored_path(path):
                    self._ignored_paths.add(path)
                else:
                    classification = classify_path(path)
                    self._classifications[path] = classification
                    new_paths.append(path)

        _LOGGER.info("Rescan found %d new classifiable paths", len(new_paths))
        return {
            "new_paths": new_paths,
            "total_classified": len(self._classifications),
            "total_ignored": len(self._ignored_paths),
        }

    def dump_runtime_state(self) -> dict[str, Any]:
        """Dump full runtime state for debugging."""
        return {
            "connection": {
                "connected": self._client.connected,
                "base_url": self._base_url,
                "self_context": self._client.self_context,
            },
            "discovery": {
                "enable_new_sensors_by_default": self._enable_new_sensors,
                "log_ignored_paths": self._log_ignored_paths,
            },
            "policy_engine": self._policy_engine.dump_state(),
            "paths": {
                "total_values_received": len(self._latest_values),
                "classified": len(self._classifications),
                "ignored": len(self._ignored_paths),
                "sensors_created": len(self._sensors),
                "device_tracker_exists": self._device_tracker is not None,
            },
            "domains": {
                domain.value: {
                    "paths": [
                        p
                        for p, c in self._classifications.items()
                        if c.domain == domain
                    ],
                }
                for domain in SignalKDomain
                if domain != SignalKDomain.UNSUPPORTED_IGNORE
            },
            "ignored_paths": sorted(self._ignored_paths)[:50],  # Cap for readability
        }

    async def stop(self) -> None:
        """Stop the hub and clean up."""
        await self._client.stop()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass


# ──────────────────────────────────────────────────────────────────────
# Integration setup / teardown
# ──────────────────────────────────────────────────────────────────────


def _get_hub(hass: HomeAssistant) -> SignalKHub | None:
    """Get the first active hub from config entries."""
    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        hub: SignalKHub | None = getattr(entry, "runtime_data", None)
        if hub:
            return hub
    return None


def _get_all_hubs(hass: HomeAssistant) -> list[SignalKHub]:
    """Get all active hubs."""
    hubs: list[SignalKHub] = []
    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        hub: SignalKHub | None = getattr(entry, "runtime_data", None)
        if hub:
            hubs.append(hub)
    return hubs


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the SignalK Bridge integration (global one-time setup)."""
    _LOGGER.info("Setting up SignalK Bridge integration")

    # ── PUT / POST services ──

    async def handle_put_value(call: ServiceCall) -> None:
        path = call.data["path"]
        value = call.data["value"]
        for hub in _get_all_hubs(hass):
            result = await hub.put_value(path, value)
            _LOGGER.debug("PUT %s = %s: %s", path, value, result)

    async def handle_post_delta(call: ServiceCall) -> None:
        path = call.data["path"]
        value = call.data["value"]
        for hub in _get_all_hubs(hass):
            result = await hub.post_delta(path, value)
            _LOGGER.debug("POST delta %s = %s: %s", path, value, result)

    # ── Domain policy services ──

    async def handle_set_domain_policy(call: ServiceCall) -> None:
        domain_str = call.data["domain"]
        try:
            domain = SignalKDomain(domain_str)
        except ValueError:
            _LOGGER.error("Unknown domain: %s", domain_str)
            return
        for hub in _get_all_hubs(hass):
            policy = hub.set_domain_policy(
                domain,
                min_interval=call.data.get("min_interval_seconds"),
                max_interval=call.data.get("max_interval_seconds"),
                deadband=call.data.get("deadband"),
                enabled_by_default=call.data.get("enabled_by_default"),
            )
            _LOGGER.info("Updated policy for %s: %s", domain, policy)

    async def handle_reset_domain_policy(call: ServiceCall) -> None:
        domain_str = call.data["domain"]
        try:
            domain = SignalKDomain(domain_str)
        except ValueError:
            _LOGGER.error("Unknown domain: %s", domain_str)
            return
        for hub in _get_all_hubs(hass):
            policy = hub.reset_domain_policy(domain)
            _LOGGER.info("Reset policy for %s: %s", domain, policy)

    # ── Discovery services ──

    async def handle_set_discovery_defaults(call: ServiceCall) -> None:
        for hub in _get_all_hubs(hass):
            if "enable_new_sensors_by_default" in call.data:
                hub.enable_new_sensors = call.data["enable_new_sensors_by_default"]
            if "publish_profile" in call.data:
                hub.policy_engine.set_profile(call.data["publish_profile"])
            if "log_ignored_paths" in call.data:
                hub.log_ignored_paths = call.data["log_ignored_paths"]
            _LOGGER.info(
                "Updated discovery defaults: enable_new=%s, profile=%s, log_ignored=%s",
                hub.enable_new_sensors,
                hub.policy_engine.profile,
                hub.log_ignored_paths,
            )

    async def handle_rescan_paths(call: ServiceCall) -> None:
        for hub in _get_all_hubs(hass):
            result = hub.rescan_paths()
            _LOGGER.info("Rescan result: %s", result)

    async def handle_reclassify_paths(call: ServiceCall) -> None:
        for hub in _get_all_hubs(hass):
            count = hub.reclassify_paths()
            _LOGGER.info("Reclassified %d paths", count)

    # ── Entity enable/disable services ──

    async def handle_enable_entities(call: ServiceCall) -> None:
        entity_ids = call.data["entity_ids"]
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        for hub in _get_all_hubs(hass):
            for eid in entity_ids:
                for path, sensor in hub.sensors.items():
                    if hasattr(sensor, "entity_id") and sensor.entity_id == eid:
                        sensor.set_enabled(True)
                        _LOGGER.info("Enabled entity: %s", eid)

    async def handle_disable_entities(call: ServiceCall) -> None:
        entity_ids = call.data["entity_ids"]
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        for hub in _get_all_hubs(hass):
            for eid in entity_ids:
                for path, sensor in hub.sensors.items():
                    if hasattr(sensor, "entity_id") and sensor.entity_id == eid:
                        sensor.set_enabled(False)
                        _LOGGER.info("Disabled entity: %s", eid)

    # ── Debug service ──

    async def handle_dump_runtime_state(call: ServiceCall) -> None:
        for hub in _get_all_hubs(hass):
            state = hub.dump_runtime_state()
            _LOGGER.info("Runtime state dump: %s", state)
            # Also fire event so automations/devtools can consume
            hass.bus.async_fire(
                f"{DOMAIN}_runtime_state",
                state,
            )

    # ── Register all services ──

    services = [
        (SERVICE_PUT_VALUE, handle_put_value, SERVICE_PUT_SCHEMA),
        (SERVICE_POST_DELTA, handle_post_delta, SERVICE_POST_SCHEMA),
        (
            SERVICE_SET_DOMAIN_POLICY,
            handle_set_domain_policy,
            SERVICE_SET_DOMAIN_POLICY_SCHEMA,
        ),
        (
            SERVICE_RESET_DOMAIN_POLICY,
            handle_reset_domain_policy,
            SERVICE_RESET_DOMAIN_POLICY_SCHEMA,
        ),
        (
            SERVICE_SET_DISCOVERY_DEFAULTS,
            handle_set_discovery_defaults,
            SERVICE_SET_DISCOVERY_DEFAULTS_SCHEMA,
        ),
        (SERVICE_RESCAN_PATHS, handle_rescan_paths, SERVICE_EMPTY_SCHEMA),
        (SERVICE_RECLASSIFY_PATHS, handle_reclassify_paths, SERVICE_EMPTY_SCHEMA),
        (SERVICE_ENABLE_ENTITIES, handle_enable_entities, SERVICE_ENTITY_LIST_SCHEMA),
        (SERVICE_DISABLE_ENTITIES, handle_disable_entities, SERVICE_ENTITY_LIST_SCHEMA),
        (SERVICE_DUMP_RUNTIME_STATE, handle_dump_runtime_state, SERVICE_EMPTY_SCHEMA),
    ]

    for name, handler, schema in services:
        hass.services.async_register(DOMAIN, name, handler, schema=schema)

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

    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP,
            lambda event: hass.async_create_task(hub.stop()),
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a SignalK Bridge config entry."""
    _LOGGER.info("Unloading SignalK Bridge entry: %s", entry.title)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hub: SignalKHub | None = getattr(entry, "runtime_data", None)
    if hub:
        await hub.stop()

    return unload_ok
