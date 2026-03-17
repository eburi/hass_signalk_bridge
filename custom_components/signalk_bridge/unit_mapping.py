"""Mapping from SignalK units and paths to HomeAssistant sensor types.

SignalK always uses SI units. This module maps those to the appropriate
HomeAssistant SensorDeviceClass, native unit, and SensorStateClass so
that HA can handle display conversion (e.g. K -> °C) automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)


@dataclass(frozen=True)
class SensorMapping:
    """Describes how to present a SignalK value as an HA sensor."""

    device_class: Optional[SensorDeviceClass] = None
    state_class: Optional[SensorStateClass] = SensorStateClass.MEASUREMENT
    native_unit: Optional[str] = None
    # If set, apply this conversion to the raw SI value before passing to HA.
    # HA handles display conversion from native_unit to user-preferred unit,
    # but we need to convert from SK's SI unit to HA's expected native unit
    # in some cases (e.g. rad -> °).
    conversion_factor: Optional[float] = None
    conversion_offset: Optional[float] = None
    icon: Optional[str] = None
    suggested_display_precision: Optional[int] = None


# ---------------------------------------------------------------------------
# Mapping by SignalK unit string (from meta.units)
# ---------------------------------------------------------------------------
UNIT_MAPPING: dict[str, SensorMapping] = {
    # Temperature: SK uses Kelvin, HA expects K for SensorDeviceClass.TEMPERATURE
    # HA will auto-convert K to user-preferred unit (°C/°F)
    "K": SensorMapping(
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.KELVIN,
        suggested_display_precision=1,
    ),
    # Speed: SK uses m/s
    "m/s": SensorMapping(
        device_class=SensorDeviceClass.SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
    ),
    # Angles: SK uses radians — convert to degrees for HA
    "rad": SensorMapping(
        native_unit="°",
        conversion_factor=57.2957795131,  # 180/π
        suggested_display_precision=1,
        icon="mdi:angle-acute",
    ),
    # Angular velocity: rad/s -> °/s
    "rad/s": SensorMapping(
        native_unit="°/s",
        conversion_factor=57.2957795131,
        suggested_display_precision=2,
        icon="mdi:rotate-right",
    ),
    # Pressure: SK uses Pascal
    "Pa": SensorMapping(
        device_class=SensorDeviceClass.PRESSURE,
        native_unit=UnitOfPressure.PA,
        suggested_display_precision=0,
    ),
    # Distance/Depth: SK uses meters
    "m": SensorMapping(
        device_class=SensorDeviceClass.DISTANCE,
        native_unit=UnitOfLength.METERS,
        suggested_display_precision=1,
    ),
    # Voltage
    "V": SensorMapping(
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
    ),
    # Current
    "A": SensorMapping(
        device_class=SensorDeviceClass.CURRENT,
        native_unit=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
    ),
    # Frequency: SK uses Hz (e.g. engine revolutions)
    "Hz": SensorMapping(
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit=UnitOfFrequency.HERTZ,
        suggested_display_precision=1,
    ),
    # Ratio: 0-1 values (humidity, SoC, engine load, tank level)
    # Convert to percentage
    "ratio": SensorMapping(
        native_unit=PERCENTAGE,
        conversion_factor=100.0,
        suggested_display_precision=1,
    ),
    # Energy: SK uses Joules — HA expects Wh for ENERGY device class
    "J": SensorMapping(
        device_class=SensorDeviceClass.ENERGY,
        native_unit=UnitOfEnergy.WATT_HOUR,
        conversion_factor=1.0 / 3600.0,  # J -> Wh
        suggested_display_precision=1,
    ),
    # Volume: SK uses m³
    "m3": SensorMapping(
        native_unit=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        icon="mdi:cup-water",
    ),
    # Volume flow: SK uses m³/s
    "m3/s": SensorMapping(
        native_unit="m³/s",
        suggested_display_precision=4,
        icon="mdi:water-pump",
    ),
    # Illuminance
    "Lux": SensorMapping(
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit="lx",
        suggested_display_precision=0,
    ),
    # Time/Duration: SK uses seconds
    "s": SensorMapping(
        device_class=SensorDeviceClass.DURATION,
        native_unit=UnitOfTime.SECONDS,
        suggested_display_precision=0,
    ),
    # Coulomb (charge)
    "C": SensorMapping(
        native_unit="Ah",
        conversion_factor=1.0 / 3600.0,  # C -> Ah
        suggested_display_precision=1,
        icon="mdi:battery-charging",
    ),
    # Density
    "kg/m3": SensorMapping(
        native_unit="kg/m³",
        suggested_display_precision=2,
        icon="mdi:air-filter",
    ),
}


# ---------------------------------------------------------------------------
# Path-based overrides: Some paths need specific device classes or icons
# that can't be inferred from units alone.
# ---------------------------------------------------------------------------
PATH_OVERRIDES: dict[str, SensorMapping] = {
    # Battery state of charge: ratio -> battery percentage
    "electrical.batteries.*.capacity.stateOfCharge": SensorMapping(
        device_class=SensorDeviceClass.BATTERY,
        native_unit=PERCENTAGE,
        conversion_factor=100.0,
        suggested_display_precision=0,
    ),
    # Humidity
    "environment.outside.relativeHumidity": SensorMapping(
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit=PERCENTAGE,
        conversion_factor=100.0,
        suggested_display_precision=1,
    ),
    "environment.inside.*.relativeHumidity": SensorMapping(
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit=PERCENTAGE,
        conversion_factor=100.0,
        suggested_display_precision=1,
    ),
    # Wind speed — use WIND_SPEED device class
    "environment.wind.speedApparent": SensorMapping(
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
    ),
    "environment.wind.speedTrue": SensorMapping(
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
    ),
    "environment.wind.speedOverGround": SensorMapping(
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
    ),
    # Atmospheric pressure — use ATMOSPHERIC_PRESSURE
    "environment.outside.pressure": SensorMapping(
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit=UnitOfPressure.PA,
        suggested_display_precision=0,
    ),
    # Depth sensors — use icon
    "environment.depth.belowKeel": SensorMapping(
        device_class=SensorDeviceClass.DISTANCE,
        native_unit=UnitOfLength.METERS,
        suggested_display_precision=1,
        icon="mdi:waves-arrow-up",
    ),
    "environment.depth.belowTransducer": SensorMapping(
        device_class=SensorDeviceClass.DISTANCE,
        native_unit=UnitOfLength.METERS,
        suggested_display_precision=1,
        icon="mdi:waves-arrow-up",
    ),
    "environment.depth.belowSurface": SensorMapping(
        device_class=SensorDeviceClass.DISTANCE,
        native_unit=UnitOfLength.METERS,
        suggested_display_precision=1,
        icon="mdi:waves-arrow-up",
    ),
    # Navigation
    "navigation.speedOverGround": SensorMapping(
        device_class=SensorDeviceClass.SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        icon="mdi:speedometer",
    ),
    "navigation.speedThroughWater": SensorMapping(
        device_class=SensorDeviceClass.SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        icon="mdi:speedometer",
    ),
}


def _match_path_pattern(path: str, pattern: str) -> bool:
    """Match a SignalK path against a pattern with * wildcards."""
    path_parts = path.split(".")
    pattern_parts = pattern.split(".")
    if len(path_parts) != len(pattern_parts):
        return False
    for pp, pat in zip(path_parts, pattern_parts):
        if pat == "*":
            continue
        if pp != pat:
            return False
    return True


def get_sensor_mapping(
    path: str,
    sk_units: str | None = None,
) -> SensorMapping:
    """Determine the best HA sensor mapping for a given SignalK path and unit.

    1. Check path-specific overrides first (exact path, then wildcard patterns).
    2. Fall back to unit-based mapping.
    3. Return a bare default mapping if nothing matches.
    """
    # Check exact path override
    if path in PATH_OVERRIDES:
        return PATH_OVERRIDES[path]

    # Check wildcard pattern overrides
    for pattern, mapping in PATH_OVERRIDES.items():
        if "*" in pattern and _match_path_pattern(path, pattern):
            return mapping

    # Fall back to unit-based mapping
    if sk_units and sk_units in UNIT_MAPPING:
        return UNIT_MAPPING[sk_units]

    # Default: no device class, treat as generic measurement
    return SensorMapping()


def convert_value(
    value: float | int | None,
    mapping: SensorMapping,
) -> float | int | None:
    """Apply conversion factor and/or offset to a raw SignalK SI value."""
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        return value

    result = float(value)
    if mapping.conversion_factor is not None:
        result *= mapping.conversion_factor
    if mapping.conversion_offset is not None:
        result += mapping.conversion_offset
    return result


def path_to_friendly_name(path: str) -> str:
    """Convert a SignalK path to a human-friendly sensor name.

    e.g. 'navigation.speedOverGround' -> 'Speed Over Ground'
         'environment.wind.speedApparent' -> 'Wind Speed Apparent'
         'propulsion.port.revolutions' -> 'Port Revolutions'
    """
    parts = path.split(".")

    # Remove common prefixes that are redundant
    if parts and parts[0] in (
        "navigation",
        "environment",
        "electrical",
        "propulsion",
        "tanks",
        "notifications",
        "steering",
        "communication",
        "design",
        "sails",
        "performance",
    ):
        parts = parts[1:]

    # Convert camelCase to words
    result_parts = []
    for part in parts:
        words = []
        current_word = []
        for char in part:
            if char.isupper() and current_word:
                words.append("".join(current_word))
                current_word = [char]
            else:
                current_word.append(char)
        if current_word:
            words.append("".join(current_word))
        result_parts.append(" ".join(w.capitalize() for w in words))

    return " ".join(result_parts)
