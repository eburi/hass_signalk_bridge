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
    CONF_ENTITY_PREFIX,
    CONF_TOKEN,
    CONF_USE_ADDON,
    DEFAULT_BASE_URL,
    DEFAULT_ENTITY_PREFIX,
    DOMAIN,
    SIGNALK_ADDON_PORT,
    SIGNALK_ADDON_SLUG,
)
from .signalk_client import SignalKClient

_LOGGER = logging.getLogger(__name__)


def _is_hassio(hass) -> bool:
    """Check if we're running on a Supervisor-managed system."""
    return "hassio" in hass.config.components


async def _check_signalk_addon(hass) -> dict[str, Any] | None:
    """Check if the SignalK addon is installed and running.

    Returns addon info dict if running, None otherwise.
    """
    if not _is_hassio(hass):
        return None

    try:
        # Use the hassio component to get addon info
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
    # The addon container is accessible via its hostname on the HA network
    hostname = addon_info.get("hostname")
    ip_address = addon_info.get("ip_address")

    # Try hostname first (e.g. "a0d7b954-signalk"), then IP
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step.

        Check for SignalK addon and offer choices.
        """
        # Check if addon is available
        addon_info = await _check_signalk_addon(self.hass)

        if addon_info:
            self._addon_url = await _get_addon_url(addon_info)
            if self._addon_url:
                # Test if addon is actually reachable
                if await _test_signalk_connection(self._addon_url):
                    self._addon_available = True
                    return await self.async_step_choose_server()

        # No addon available, go straight to manual entry
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
                    vol.Required(
                        CONF_BASE_URL, default=DEFAULT_BASE_URL
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle authentication with SignalK.

        Initiate device access request and inform user to approve it.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # User clicked "Submit" — check if token was obtained
            assert self._base_url is not None
            client = SignalKClient(
                base_url=self._base_url,
                token=self._token,
                client_id=self._client_id,
            )

            # First check if no auth is required (open server)
            try:
                data = await client.get_self_data()
                if data:
                    # Server is open (no auth needed) or token is valid
                    self._token = client.token
                    self._client_id = client.client_id
                    return await self.async_step_prefix()
            except Exception:
                pass

            # Try to authenticate
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

        # First visit to this step — try to see if auth is even required
        assert self._base_url is not None
        client = SignalKClient(base_url=self._base_url)
        self._client_id = client.client_id

        # Check if server allows unauthenticated access
        try:
            data = await client.get_self_data()
            if data:
                # No auth required — skip to prefix
                return await self.async_step_prefix()
        except Exception:
            pass

        # Auth is required — submit an access request
        try:
            # Submit the request (non-blocking — just registers it)
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
                    _LOGGER.info(
                        "Access request submitted: href=%s", self._access_href
                    )
        except Exception as exc:
            _LOGGER.warning("Could not submit access request: %s", exc)

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "base_url": self._base_url,
            },
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

            # Check for duplicate entries with same URL
            await self.async_set_unique_id(self._base_url)
            self._abort_if_unique_id_configured()

            # Create the entry
            return self.async_create_entry(
                title=f"SignalK ({self._base_url})",
                data={
                    CONF_BASE_URL: self._base_url,
                    CONF_TOKEN: self._token,
                    CONF_CLIENT_ID: self._client_id,
                    CONF_ENTITY_PREFIX: self._entity_prefix,
                    CONF_USE_ADDON: self._addon_available
                    and self._base_url == self._addon_url,
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
    """Handle options flow for SignalK Bridge."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            new_url = user_input.get(
                CONF_BASE_URL, self.config_entry.data[CONF_BASE_URL]
            )
            new_prefix = user_input.get(
                CONF_ENTITY_PREFIX, self.config_entry.data.get(
                    CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX
                )
            )

            # Test connection if URL changed
            if new_url != self.config_entry.data[CONF_BASE_URL]:
                if not await _test_signalk_connection(new_url):
                    errors[CONF_BASE_URL] = "cannot_connect"

            if not errors:
                new_data = dict(self.config_entry.data)
                new_data[CONF_BASE_URL] = new_url
                new_data[CONF_ENTITY_PREFIX] = new_prefix
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        current_data = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_BASE_URL): str,
                        vol.Required(CONF_ENTITY_PREFIX): str,
                    }
                ),
                {
                    CONF_BASE_URL: current_data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                    CONF_ENTITY_PREFIX: current_data.get(
                        CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX
                    ),
                },
            ),
            errors=errors,
        )
