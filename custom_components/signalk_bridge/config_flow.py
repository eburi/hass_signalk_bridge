"""Config flow for SignalK Bridge integration.

Flow:
1. Check if SignalK HA App (addon) is installed and running.
   - If yes, offer to use it (via ingress on port 3000).
   - If no, go straight to manual URL entry.
2. Allow user to enter a custom SignalK server base URL.
3. Test connectivity to the chosen server.
4. Authenticate via device access request flow.
5. Allow user to set an entity ID prefix.
6. Create config entry.

Options flow exposes:
- enable_new_sensors_by_default
- publish_profile (conservative / balanced / realtime)
- domain-level policy overrides for key domains
- log_ignored_paths
- create_diagnostic_entities
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BASE_URL,
    CONF_CLIENT_ID,
    CONF_CREATE_DIAGNOSTIC_ENTITIES,
    CONF_ENABLE_NEW_SENSORS,
    CONF_ENTITY_PREFIX,
    CONF_LOG_IGNORED_PATHS,
    CONF_PUBLISH_PROFILE,
    CONF_TOKEN,
    CONF_USE_ADDON,
    DEFAULT_BASE_URL,
    DEFAULT_CREATE_DIAGNOSTIC_ENTITIES,
    DEFAULT_ENABLE_NEW_SENSORS,
    DEFAULT_ENTITY_PREFIX,
    DEFAULT_LOG_IGNORED_PATHS,
    DEFAULT_PUBLISH_PROFILE,
    DOMAIN,
    SIGNALK_ADDON_PORT,
    SIGNALK_ADDON_SLUG,
    PublishProfile,
)
from .signalk_client import SignalKClient

_LOGGER = logging.getLogger(__name__)


def _is_hassio(hass) -> bool:
    """Check if we're running on a Supervisor-managed system."""
    return "hassio" in hass.config.components


async def _check_signalk_addon(hass) -> dict[str, Any] | None:
    """Check if the SignalK addon is installed and running."""
    if not _is_hassio(hass):
        return None

    try:
        from homeassistant.components.hassio import async_get_addon_info

        addon_info = await async_get_addon_info(hass, SIGNALK_ADDON_SLUG)
        if addon_info and addon_info.get("state") == "started":
            _LOGGER.debug("SignalK addon found and running: %s", addon_info)
            return addon_info
    except Exception as exc:
        _LOGGER.debug("Could not check SignalK addon: %s", exc)

    return None


async def _get_addon_url(addon_info: dict[str, Any]) -> str | None:
    """Derive the SignalK base URL from addon info."""
    hostname = addon_info.get("hostname")
    ip_address = addon_info.get("ip_address")
    host = hostname or ip_address
    if host:
        return f"http://{host}:{SIGNALK_ADDON_PORT}"
    return None


async def _test_signalk_connection(base_url: str) -> bool:
    """Test if a SignalK server is reachable at the given URL."""
    client = SignalKClient(base_url=base_url)
    try:
        return await client.check_connection()
    except Exception:
        return False


class SignalKBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SignalK Bridge."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._base_url: str | None = None
        self._addon_available = False
        self._addon_url: str | None = None
        self._token: str | None = None
        self._client_id: str | None = None
        self._entity_prefix: str = DEFAULT_ENTITY_PREFIX
        self._access_href: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        addon_info = await _check_signalk_addon(self.hass)

        if addon_info:
            self._addon_url = await _get_addon_url(addon_info)
            if self._addon_url:
                if await _test_signalk_connection(self._addon_url):
                    self._addon_available = True
                    return await self.async_step_choose_server()

        return await self.async_step_manual_url()

    async def async_step_choose_server(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let user choose between the detected addon and a custom server."""
        if user_input is not None:
            use_addon = user_input.get(CONF_USE_ADDON, True)
            if use_addon:
                self._base_url = self._addon_url
                return await self.async_step_auth()
            else:
                return await self.async_step_manual_url()

        return self.async_show_form(
            step_id="choose_server",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USE_ADDON, default=True): bool,
                }
            ),
        )

    async def async_step_manual_url(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual URL entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            if await _test_signalk_connection(base_url):
                self._base_url = base_url
                return await self.async_step_auth()
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual_url",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                }
            ),
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle authentication with SignalK."""
        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._base_url is not None
            client = SignalKClient(
                base_url=self._base_url,
                token=self._token,
                client_id=self._client_id,
            )

            try:
                data = await client.get_self_data()
                if data:
                    self._token = client.token
                    self._client_id = client.client_id
                    return await self.async_step_prefix()
            except Exception:
                pass

            try:
                if await client.authenticate():
                    self._token = client.token
                    self._client_id = client.client_id
                    return await self.async_step_prefix()
                else:
                    errors["base"] = "auth_failed"
            except Exception as exc:
                _LOGGER.error("Authentication error: %s", exc)
                errors["base"] = "auth_failed"

        assert self._base_url is not None
        client = SignalKClient(base_url=self._base_url)
        self._client_id = client.client_id

        try:
            data = await client.get_self_data()
            if data:
                return await self.async_step_prefix()
        except Exception:
            pass

        try:
            url = f"{self._base_url}/signalk/v1/access/requests"
            import httpx

            body = {
                "clientId": self._client_id,
                "description": "Home Assistant SignalK Bridge",
                "permissions": "readwrite",
            }
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                resp = await http_client.post(url, json=body)
                if resp.status_code in (200, 202):
                    data = resp.json()
                    self._access_href = data.get("href", "")
                    _LOGGER.info("Access request submitted: href=%s", self._access_href)
        except Exception as exc:
            _LOGGER.warning("Could not submit access request: %s", exc)

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"base_url": self._base_url},
        )

    async def async_step_prefix(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow user to set an entity ID prefix."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._entity_prefix = user_input.get(
                CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX
            )

            await self.async_set_unique_id(self._base_url)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"SignalK ({self._base_url})",
                data={
                    CONF_BASE_URL: self._base_url,
                    CONF_TOKEN: self._token,
                    CONF_CLIENT_ID: self._client_id,
                    CONF_ENTITY_PREFIX: self._entity_prefix,
                    CONF_USE_ADDON: (
                        self._addon_available and self._base_url == self._addon_url
                    ),
                },
            )

        return self.async_show_form(
            step_id="prefix",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENTITY_PREFIX, default=DEFAULT_ENTITY_PREFIX
                    ): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for SignalK Bridge.

    Exposes:
    - enable_new_sensors_by_default (default false)
    - publish_profile (conservative / balanced / realtime)
    - log_ignored_paths
    - create_diagnostic_entities
    - base_url (with connection test on change)
    - entity_prefix
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Main options menu."""
        if user_input is not None:
            return await self.async_step_general(user_input)

        # Merge current data + options for defaults
        opts = {**self.config_entry.data, **self.config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_BASE_URL): str,
                        vol.Required(CONF_ENTITY_PREFIX): str,
                        vol.Required(CONF_ENABLE_NEW_SENSORS): bool,
                        vol.Required(CONF_PUBLISH_PROFILE): vol.In(
                            {
                                PublishProfile.CONSERVATIVE: "Conservative (lowest load)",
                                PublishProfile.BALANCED: "Balanced",
                                PublishProfile.REALTIME: "Realtime (highest load)",
                            }
                        ),
                        vol.Required(CONF_LOG_IGNORED_PATHS): bool,
                        vol.Required(CONF_CREATE_DIAGNOSTIC_ENTITIES): bool,
                    }
                ),
                {
                    CONF_BASE_URL: opts.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                    CONF_ENTITY_PREFIX: opts.get(
                        CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX
                    ),
                    CONF_ENABLE_NEW_SENSORS: opts.get(
                        CONF_ENABLE_NEW_SENSORS, DEFAULT_ENABLE_NEW_SENSORS
                    ),
                    CONF_PUBLISH_PROFILE: opts.get(
                        CONF_PUBLISH_PROFILE, DEFAULT_PUBLISH_PROFILE
                    ),
                    CONF_LOG_IGNORED_PATHS: opts.get(
                        CONF_LOG_IGNORED_PATHS, DEFAULT_LOG_IGNORED_PATHS
                    ),
                    CONF_CREATE_DIAGNOSTIC_ENTITIES: opts.get(
                        CONF_CREATE_DIAGNOSTIC_ENTITIES,
                        DEFAULT_CREATE_DIAGNOSTIC_ENTITIES,
                    ),
                },
            ),
        )

    async def async_step_general(self, user_input: dict[str, Any]) -> FlowResult:
        """Process general options."""
        errors: dict[str, str] = {}

        new_url = user_input.get(CONF_BASE_URL, self.config_entry.data[CONF_BASE_URL])

        # Test connection if URL changed
        if new_url != self.config_entry.data[CONF_BASE_URL]:
            if not await _test_signalk_connection(new_url):
                errors[CONF_BASE_URL] = "cannot_connect"

        if errors:
            # Re-show form with errors
            return self.async_show_form(
                step_id="init",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        {
                            vol.Required(CONF_BASE_URL): str,
                            vol.Required(CONF_ENTITY_PREFIX): str,
                            vol.Required(CONF_ENABLE_NEW_SENSORS): bool,
                            vol.Required(CONF_PUBLISH_PROFILE): vol.In(
                                {
                                    PublishProfile.CONSERVATIVE: "Conservative (lowest load)",
                                    PublishProfile.BALANCED: "Balanced",
                                    PublishProfile.REALTIME: "Realtime (highest load)",
                                }
                            ),
                            vol.Required(CONF_LOG_IGNORED_PATHS): bool,
                            vol.Required(CONF_CREATE_DIAGNOSTIC_ENTITIES): bool,
                        }
                    ),
                    user_input,
                ),
                errors=errors,
            )

        # Update config entry data (URL, prefix)
        new_data = dict(self.config_entry.data)
        new_data[CONF_BASE_URL] = new_url
        new_data[CONF_ENTITY_PREFIX] = user_input.get(
            CONF_ENTITY_PREFIX,
            self.config_entry.data.get(CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX),
        )
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # Save options
        options = {
            CONF_ENABLE_NEW_SENSORS: user_input.get(
                CONF_ENABLE_NEW_SENSORS, DEFAULT_ENABLE_NEW_SENSORS
            ),
            CONF_PUBLISH_PROFILE: user_input.get(
                CONF_PUBLISH_PROFILE, DEFAULT_PUBLISH_PROFILE
            ),
            CONF_LOG_IGNORED_PATHS: user_input.get(
                CONF_LOG_IGNORED_PATHS, DEFAULT_LOG_IGNORED_PATHS
            ),
            CONF_CREATE_DIAGNOSTIC_ENTITIES: user_input.get(
                CONF_CREATE_DIAGNOSTIC_ENTITIES, DEFAULT_CREATE_DIAGNOSTIC_ENTITIES
            ),
        }

        # Reload if URL or key settings changed
        needs_reload = new_url != self.config_entry.data.get(
            CONF_BASE_URL
        ) or user_input.get(CONF_PUBLISH_PROFILE) != self.config_entry.options.get(
            CONF_PUBLISH_PROFILE
        )

        result = self.async_create_entry(title="", data=options)

        if needs_reload:
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        return result
