"""Stub out homeassistant packages so tests can import the custom component
without installing the full HA core (which needs C extensions like ciso8601).

This module is loaded by conftest.py before any test imports.
"""

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helper: create a fake module and register it in sys.modules
# ---------------------------------------------------------------------------

def _make_module(name: str, attrs: dict | None = None) -> types.ModuleType:
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------------------
# homeassistant.const  (enums / constants used by integration)
# ---------------------------------------------------------------------------

class _StrEnum(str):
    """Minimal StrEnum stand-in."""
    pass

# Unit classes — each just holds class-level string constants
class UnitOfTemperature:
    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"

class UnitOfSpeed:
    METERS_PER_SECOND = "m/s"
    KILOMETERS_PER_HOUR = "km/h"
    KNOTS = "kn"

class UnitOfPressure:
    PA = "Pa"
    HPA = "hPa"
    MBAR = "mbar"

class UnitOfLength:
    METERS = "m"
    KILOMETERS = "km"

class UnitOfElectricPotential:
    VOLT = "V"

class UnitOfElectricCurrent:
    AMPERE = "A"

class UnitOfFrequency:
    HERTZ = "Hz"

class UnitOfEnergy:
    WATT_HOUR = "Wh"
    KILO_WATT_HOUR = "kWh"

class UnitOfTime:
    SECONDS = "s"

class UnitOfVolume:
    CUBIC_METERS = "m³"
    LITERS = "L"

PERCENTAGE = "%"

class EntityCategory:
    DIAGNOSTIC = "diagnostic"

class Platform:
    SENSOR = "sensor"

EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"


ha_const = _make_module("homeassistant.const", {
    "UnitOfTemperature": UnitOfTemperature,
    "UnitOfSpeed": UnitOfSpeed,
    "UnitOfPressure": UnitOfPressure,
    "UnitOfLength": UnitOfLength,
    "UnitOfElectricPotential": UnitOfElectricPotential,
    "UnitOfElectricCurrent": UnitOfElectricCurrent,
    "UnitOfFrequency": UnitOfFrequency,
    "UnitOfEnergy": UnitOfEnergy,
    "UnitOfTime": UnitOfTime,
    "UnitOfVolume": UnitOfVolume,
    "PERCENTAGE": PERCENTAGE,
    "EntityCategory": EntityCategory,
    "Platform": Platform,
    "EVENT_HOMEASSISTANT_STOP": EVENT_HOMEASSISTANT_STOP,
})


# ---------------------------------------------------------------------------
# homeassistant.components.sensor
# ---------------------------------------------------------------------------

class SensorDeviceClass:
    TEMPERATURE = "temperature"
    SPEED = "speed"
    WIND_SPEED = "wind_speed"
    PRESSURE = "pressure"
    ATMOSPHERIC_PRESSURE = "atmospheric_pressure"
    DISTANCE = "distance"
    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    ENERGY = "energy"
    DURATION = "duration"
    BATTERY = "battery"
    HUMIDITY = "humidity"
    ILLUMINANCE = "illuminance"

class SensorStateClass:
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"

class SensorEntity:
    """Minimal SensorEntity stand-in."""
    _attr_should_poll = True
    _attr_has_entity_name = False
    _attr_native_value = None
    _attr_device_info = None
    _attr_unique_id = None
    _attr_name = None
    _attr_device_class = None
    _attr_state_class = None
    _attr_native_unit_of_measurement = None
    _attr_icon = None
    _attr_suggested_display_precision = None
    _attr_entity_category = None
    entity_id = None
    hass = None

    @property
    def extra_state_attributes(self):
        return {}

    @property
    def available(self):
        return True

    def async_write_ha_state(self):
        pass

    async def async_added_to_hass(self):
        pass

    async def async_will_remove_from_hass(self):
        pass


_make_module("homeassistant")
_make_module("homeassistant.components", {})
_make_module("homeassistant.components.sensor", {
    "SensorDeviceClass": SensorDeviceClass,
    "SensorEntity": SensorEntity,
    "SensorStateClass": SensorStateClass,
})
_make_module("homeassistant.components.hassio", {
    "async_get_addon_info": MagicMock(),
})


# ---------------------------------------------------------------------------
# homeassistant.core
# ---------------------------------------------------------------------------

class HomeAssistant:
    """Minimal HA stand-in."""
    def __init__(self):
        self.config = MagicMock()
        self.config.components = set()
        self.bus = MagicMock()
        self.services = MagicMock()
        self.config_entries = MagicMock()

    def async_create_task(self, coro):
        pass


class ServiceCall:
    def __init__(self, domain="", service="", data=None):
        self.domain = domain
        self.service = service
        self.data = data or {}


def callback(func):
    """No-op decorator matching HA's @callback."""
    return func


_make_module("homeassistant.core", {
    "HomeAssistant": HomeAssistant,
    "ServiceCall": ServiceCall,
    "callback": callback,
    "Event": MagicMock,
})


# ---------------------------------------------------------------------------
# homeassistant.config_entries
# ---------------------------------------------------------------------------

class ConfigEntry:
    """Minimal ConfigEntry stand-in."""
    def __init__(self, entry_id="test_entry_id", data=None, title="Test", options=None):
        self.entry_id = entry_id
        self.data = data or {}
        self.title = title
        self.options = options or {}
        self.runtime_data = None

    def async_on_unload(self, func):
        pass

    def async_create_background_task(self, hass, coro, name):
        import asyncio
        return asyncio.ensure_future(coro)


class ConfigFlow:
    """Minimal ConfigFlow stand-in."""
    VERSION = 1
    hass = None
    _unique_id = None

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    async def async_set_unique_id(self, uid):
        self._unique_id = uid

    def _abort_if_unique_id_configured(self):
        pass

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    @staticmethod
    def async_get_options_flow(config_entry):
        return None


class OptionsFlow:
    """Minimal OptionsFlow stand-in."""
    hass = None
    config_entry = None

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def add_suggested_values_to_schema(self, schema, values):
        return schema


_make_module("homeassistant.config_entries", {
    "ConfigEntry": ConfigEntry,
    "ConfigFlow": ConfigFlow,
    "OptionsFlow": OptionsFlow,
})

# Also make 'config_entries' importable as `from homeassistant import config_entries`
ha_mod = sys.modules["homeassistant"]
ha_mod.config_entries = sys.modules["homeassistant.config_entries"]


# ---------------------------------------------------------------------------
# homeassistant.data_entry_flow
# ---------------------------------------------------------------------------

class FlowResult(dict):
    pass

_make_module("homeassistant.data_entry_flow", {
    "FlowResult": FlowResult,
})


# ---------------------------------------------------------------------------
# homeassistant.helpers.*
# ---------------------------------------------------------------------------

_make_module("homeassistant.helpers", {})

# config_validation — cv.string etc.
class _CV:
    @staticmethod
    def string(val):
        return str(val)

_make_module("homeassistant.helpers.config_validation", {
    "string": _CV.string,
})

# For `import homeassistant.helpers.config_validation as cv`
ha_helpers = sys.modules["homeassistant.helpers"]
ha_helpers.config_validation = sys.modules["homeassistant.helpers.config_validation"]


class DeviceInfo(dict):
    """Minimal DeviceInfo stand-in."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)

_make_module("homeassistant.helpers.device_registry", {
    "DeviceInfo": DeviceInfo,
})

# AddEntitiesCallback type
from typing import Callable, Iterable
AddEntitiesCallback = Callable

_make_module("homeassistant.helpers.entity_platform", {
    "AddEntitiesCallback": AddEntitiesCallback,
})

_make_module("homeassistant.helpers.typing", {
    "ConfigType": dict,
})
