"""Constants for the SignalK Bridge integration."""

from enum import StrEnum

DOMAIN = "signalk_bridge"

# Config keys
CONF_BASE_URL = "base_url"
CONF_ENTITY_PREFIX = "entity_prefix"
CONF_USE_ADDON = "use_addon"
CONF_TOKEN = "token"
CONF_CLIENT_ID = "client_id"
CONF_ENABLE_NEW_SENSORS = "enable_new_sensors_by_default"
CONF_PUBLISH_PROFILE = "publish_profile"
CONF_LOG_IGNORED_PATHS = "log_ignored_paths"
CONF_CREATE_DIAGNOSTIC_ENTITIES = "create_diagnostic_entities"

# SignalK App (Addon) slug — the SignalK HA App
SIGNALK_ADDON_SLUG = "a0d7b954_signalk"
SIGNALK_ADDON_PORT = 3000

# Default values
DEFAULT_ENTITY_PREFIX = "signalk"
DEFAULT_BASE_URL = "http://localhost:3000"
DEFAULT_ENABLE_NEW_SENSORS = False
DEFAULT_PUBLISH_PROFILE = "conservative"
DEFAULT_LOG_IGNORED_PATHS = False
DEFAULT_CREATE_DIAGNOSTIC_ENTITIES = True

# SignalK API paths
SK_API_DISCOVERY = "/signalk"
SK_API_SELF = "/signalk/v1/api/vessels/self"
SK_API_ACCESS_REQUESTS = "/signalk/v1/access/requests"
SK_WS_STREAM = "/signalk/v1/stream"

# Auth
AUTH_DEVICE_DESCRIPTION = "Home Assistant SignalK Bridge"
AUTH_POLL_INTERVAL_S = 5.0

# Stale entity timeout (seconds)
STALE_TIMEOUT_S = 600  # 10 minutes


class SignalKDomain(StrEnum):
    """Functional domains for SignalK path classification."""

    ALARM = "alarm"
    POSITION = "position"
    NAVIGATION = "navigation"
    WIND = "wind"
    ENVIRONMENT = "environment"
    TANK = "tank"
    BATTERY_DC = "battery_dc"
    INVERTER_AC = "inverter_ac"
    ENGINE_PROPULSION = "engine_propulsion"
    BILGE_PUMP = "bilge_pump"
    WATERMAKER = "watermaker"
    COMMUNICATIONS = "communications"
    TIME = "time"
    STATUS_METADATA = "status_metadata"
    UNSUPPORTED_IGNORE = "unsupported_ignore"


class PublishProfile(StrEnum):
    """Publish profile presets."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    REALTIME = "realtime"
