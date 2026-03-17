"""Constants for the SignalK Bridge integration."""

DOMAIN = "signalk_bridge"

# Config keys
CONF_BASE_URL = "base_url"
CONF_ENTITY_PREFIX = "entity_prefix"
CONF_USE_ADDON = "use_addon"
CONF_TOKEN = "token"
CONF_CLIENT_ID = "client_id"

# SignalK App (Addon) slug — the SignalK HA App
SIGNALK_ADDON_SLUG = "a0d7b954_signalk"
SIGNALK_ADDON_PORT = 3000

# Default values
DEFAULT_ENTITY_PREFIX = "signalk"
DEFAULT_BASE_URL = "http://localhost:3000"

# SignalK API paths
SK_API_DISCOVERY = "/signalk"
SK_API_SELF = "/signalk/v1/api/vessels/self"
SK_API_ACCESS_REQUESTS = "/signalk/v1/access/requests"
SK_WS_STREAM = "/signalk/v1/stream"

# Auth
AUTH_DEVICE_DESCRIPTION = "Home Assistant SignalK Bridge"
AUTH_POLL_INTERVAL_S = 5.0
