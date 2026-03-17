"""Smart path classifier for SignalK paths.

Classifies canonical SignalK paths into functional domains using a 4-layer
matching strategy: exact match → prefix match → segment heuristic → fallback.

The classifier determines:
- Which functional domain a path belongs to
- Suggested HA platform (sensor, device_tracker, binary_sensor)
- Whether the entity should be enabled by default
- Which publish profile to use
- Suggested entity metadata
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .const import SignalKDomain

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    """Result of classifying a SignalK path."""

    domain: SignalKDomain
    platform: str = "sensor"  # sensor, device_tracker, binary_sensor
    enabled_by_default: bool = True
    publish_profile: str = "default"  # domain default
    friendly_name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# Layer 1: Exact path matches
# ──────────────────────────────────────────────────────────────────────

EXACT_MATCHES: dict[str, ClassificationResult] = {
    "navigation.position": ClassificationResult(
        domain=SignalKDomain.POSITION,
        platform="device_tracker",
        enabled_by_default=True,
        friendly_name="Vessel Position",
        icon="mdi:crosshairs-gps",
    ),
    "navigation.datetime": ClassificationResult(
        domain=SignalKDomain.TIME,
        enabled_by_default=False,
        friendly_name="Navigation Datetime",
        icon="mdi:clock-outline",
    ),
    "navigation.courseOverGroundTrue": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="COG True",
        icon="mdi:compass",
    ),
    "navigation.courseOverGroundMagnetic": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="COG Magnetic",
        icon="mdi:compass",
    ),
    "navigation.headingMagnetic": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="Heading Magnetic",
        icon="mdi:compass",
    ),
    "navigation.headingTrue": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="Heading True",
        icon="mdi:compass",
    ),
    "navigation.speedOverGround": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="SOG",
        icon="mdi:speedometer",
    ),
    "navigation.speedThroughWater": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="STW",
        icon="mdi:speedometer",
    ),
    "navigation.rateOfTurn": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=False,
        friendly_name="Rate of Turn",
        icon="mdi:rotate-right",
    ),
    "navigation.log": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="Log",
        icon="mdi:counter",
    ),
    "navigation.trip.log": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=True,
        friendly_name="Trip Log",
        icon="mdi:counter",
    ),
    "navigation.magneticVariation": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=False,
        friendly_name="Magnetic Variation",
        icon="mdi:magnet",
    ),
    "navigation.leewayAngle": ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        enabled_by_default=False,
        friendly_name="Leeway Angle",
        icon="mdi:angle-acute",
    ),
    "environment.wind.angleApparent": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="Apparent Wind Angle",
        icon="mdi:weather-windy",
    ),
    "environment.wind.speedApparent": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="Apparent Wind Speed",
        icon="mdi:weather-windy",
    ),
    "environment.wind.angleTrueWater": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="True Wind Angle (Water)",
        icon="mdi:weather-windy",
    ),
    "environment.wind.directionTrue": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="True Wind Direction",
        icon="mdi:weather-windy",
    ),
    "environment.wind.speedTrue": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="True Wind Speed",
        icon="mdi:weather-windy",
    ),
    "environment.depth.belowKeel": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Depth Below Keel",
        icon="mdi:waves-arrow-up",
    ),
    "environment.depth.belowSurface": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Depth Below Surface",
        icon="mdi:waves-arrow-up",
    ),
    "environment.depth.belowTransducer": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Depth Below Transducer",
        icon="mdi:waves-arrow-up",
    ),
    "environment.water.temperature": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Water Temperature",
        icon="mdi:thermometer-water",
    ),
    "environment.inside.temperature": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Inside Temperature",
        icon="mdi:thermometer",
    ),
    "environment.inside.humidity": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Inside Humidity",
        icon="mdi:water-percent",
    ),
    "environment.inside.pressure": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=True,
        friendly_name="Inside Pressure",
        icon="mdi:gauge",
    ),
    "environment.heave": ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=False,
        friendly_name="Heave",
        icon="mdi:wave",
    ),
    "steering.rudderAngle": ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=True,
        friendly_name="Rudder Angle",
        icon="mdi:steering",
    ),
    "steering.autopilot.state": ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=True,
        friendly_name="Autopilot State",
        icon="mdi:robot",
    ),
    "steering.autopilot.target.headingMagnetic": ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=True,
        friendly_name="Autopilot Target Heading",
        icon="mdi:compass",
    ),
    "steering.autopilot.target.windAngleApparent": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="Autopilot Target Wind Angle",
        icon="mdi:weather-windy",
    ),
    "performance.targetAngle": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=True,
        friendly_name="Target Angle",
        icon="mdi:angle-acute",
    ),
    "performance.gybeAngle": ClassificationResult(
        domain=SignalKDomain.WIND,
        enabled_by_default=False,
        friendly_name="Gybe Angle",
        icon="mdi:angle-acute",
    ),
    "name": ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=False,
        friendly_name="Vessel Name",
        icon="mdi:ferry",
    ),
    "mmsi": ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=False,
        friendly_name="MMSI",
        icon="mdi:identifier",
    ),
    "communication.callsignVhf": ClassificationResult(
        domain=SignalKDomain.COMMUNICATIONS,
        enabled_by_default=False,
        friendly_name="VHF Callsign",
        icon="mdi:radio-handheld",
    ),
}


# ──────────────────────────────────────────────────────────────────────
# Layer 2: Prefix-based rules (checked in order, first match wins)
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PrefixRule:
    """A prefix-matching rule for path classification."""

    prefix: str
    result: ClassificationResult


PREFIX_RULES: list[PrefixRule] = [
    # ── Ignore rules (must come before catch-all domain rules) ──
    PrefixRule("notifications.ais.", ClassificationResult(
        domain=SignalKDomain.UNSUPPORTED_IGNORE)),
    PrefixRule("sensors.ais.", ClassificationResult(
        domain=SignalKDomain.UNSUPPORTED_IGNORE)),
    PrefixRule("notifications.security.accessRequest.", ClassificationResult(
        domain=SignalKDomain.UNSUPPORTED_IGNORE)),

    # ── Alarm ──
    PrefixRule("notifications.", ClassificationResult(
        domain=SignalKDomain.ALARM,
        enabled_by_default=True,
        icon="mdi:alert",
    )),

    # ── Position / GNSS ──
    PrefixRule("navigation.gnss.", ClassificationResult(
        domain=SignalKDomain.POSITION,
        enabled_by_default=False,
        icon="mdi:satellite-variant",
    )),

    # ── Navigation ──
    PrefixRule("navigation.heading", ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        icon="mdi:compass",
    )),
    PrefixRule("navigation.course", ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        icon="mdi:navigation",
    )),
    PrefixRule("navigation.speed", ClassificationResult(
        domain=SignalKDomain.NAVIGATION,
        icon="mdi:speedometer",
    )),

    # ── Wind ──
    PrefixRule("environment.wind.", ClassificationResult(
        domain=SignalKDomain.WIND,
        icon="mdi:weather-windy",
    )),
    PrefixRule("steering.autopilot.target.wind", ClassificationResult(
        domain=SignalKDomain.WIND,
        icon="mdi:weather-windy",
    )),
    PrefixRule("performance.target", ClassificationResult(
        domain=SignalKDomain.WIND,
        icon="mdi:angle-acute",
    )),
    PrefixRule("performance.gybe", ClassificationResult(
        domain=SignalKDomain.WIND,
        icon="mdi:angle-acute",
    )),

    # ── Environment ──
    PrefixRule("environment.depth.", ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        icon="mdi:waves-arrow-up",
    )),
    PrefixRule("environment.water.", ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        icon="mdi:water",
    )),
    PrefixRule("environment.current.", ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        icon="mdi:current-dc",
    )),
    PrefixRule("environment.inside.", ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        icon="mdi:home-thermometer",
    )),
    PrefixRule("environment.outside.", ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        icon="mdi:weather-partly-cloudy",
    )),
    PrefixRule("environment.sunlight.", ClassificationResult(
        domain=SignalKDomain.TIME,
        enabled_by_default=False,
        icon="mdi:weather-sunny",
    )),
    PrefixRule("environment.moon.", ClassificationResult(
        domain=SignalKDomain.ENVIRONMENT,
        enabled_by_default=False,
        icon="mdi:moon-waning-crescent",
    )),

    # ── Tank ──
    PrefixRule("tanks.", ClassificationResult(
        domain=SignalKDomain.TANK,
        icon="mdi:gauge",
    )),
    PrefixRule("tank.", ClassificationResult(
        domain=SignalKDomain.TANK,
        icon="mdi:gauge",
    )),

    # ── Battery / DC (must come before general electrical catch-all) ──
    PrefixRule("electrical.batteries.", ClassificationResult(
        domain=SignalKDomain.BATTERY_DC,
        icon="mdi:battery",
    )),
    PrefixRule("electrical.dc.", ClassificationResult(
        domain=SignalKDomain.BATTERY_DC,
        icon="mdi:flash",
    )),
    PrefixRule("electrical.solar.", ClassificationResult(
        domain=SignalKDomain.BATTERY_DC,
        icon="mdi:solar-panel",
    )),
    PrefixRule("electrical.alternators.", ClassificationResult(
        domain=SignalKDomain.BATTERY_DC,
        icon="mdi:engine",
    )),

    # ── Inverter / AC ──
    PrefixRule("electrical.inverters.", ClassificationResult(
        domain=SignalKDomain.INVERTER_AC,
        icon="mdi:power-plug",
    )),
    PrefixRule("electrical.ac.", ClassificationResult(
        domain=SignalKDomain.INVERTER_AC,
        icon="mdi:power-plug",
    )),
    PrefixRule("electrical.shorePower.", ClassificationResult(
        domain=SignalKDomain.INVERTER_AC,
        icon="mdi:power-plug",
    )),
    PrefixRule("electrical.generators.", ClassificationResult(
        domain=SignalKDomain.INVERTER_AC,
        icon="mdi:engine",
    )),

    # ── Engine / propulsion ──
    PrefixRule("propulsion.", ClassificationResult(
        domain=SignalKDomain.ENGINE_PROPULSION,
        icon="mdi:engine",
    )),
    PrefixRule("engines.", ClassificationResult(
        domain=SignalKDomain.ENGINE_PROPULSION,
        icon="mdi:engine",
    )),

    # ── Bilge / pump ──
    PrefixRule("bilge.", ClassificationResult(
        domain=SignalKDomain.BILGE_PUMP,
        icon="mdi:water-pump",
    )),
    PrefixRule("pumps.", ClassificationResult(
        domain=SignalKDomain.BILGE_PUMP,
        icon="mdi:water-pump",
    )),

    # ── Watermaker ──
    PrefixRule("watermaker.", ClassificationResult(
        domain=SignalKDomain.WATERMAKER,
        icon="mdi:water-plus",
    )),
    PrefixRule("watermakers.", ClassificationResult(
        domain=SignalKDomain.WATERMAKER,
        icon="mdi:water-plus",
    )),

    # ── Communications ──
    PrefixRule("communication.", ClassificationResult(
        domain=SignalKDomain.COMMUNICATIONS,
        enabled_by_default=False,
        icon="mdi:radio-handheld",
    )),
    PrefixRule("noforeignland.", ClassificationResult(
        domain=SignalKDomain.COMMUNICATIONS,
        enabled_by_default=False,
        icon="mdi:earth",
    )),

    # ── Status / metadata ──
    PrefixRule("design.", ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=False,
        icon="mdi:information-outline",
    )),
    PrefixRule("electrical.displays.", ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=False,
        icon="mdi:monitor",
    )),
    PrefixRule("entertainment.", ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=False,
        icon="mdi:music",
    )),
    PrefixRule("steering.autopilot.", ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        enabled_by_default=True,
        icon="mdi:robot",
    )),
    PrefixRule("steering.", ClassificationResult(
        domain=SignalKDomain.STATUS_METADATA,
        icon="mdi:steering",
    )),
]


# ──────────────────────────────────────────────────────────────────────
# Layer 3: Segment-based heuristic patterns
# ──────────────────────────────────────────────────────────────────────

# Patterns that match anywhere in the path (suffix / contains)
SUFFIX_HEURISTICS: list[tuple[str, SignalKDomain]] = [
    (".estimatedTimeOfArrival", SignalKDomain.TIME),
    (".timeToGo", SignalKDomain.TIME),
    (".startTime", SignalKDomain.TIME),
]

# Segment-based heuristics: if the first segment matches
SEGMENT_HEURISTICS: dict[str, SignalKDomain] = {
    "navigation": SignalKDomain.NAVIGATION,
    "environment": SignalKDomain.ENVIRONMENT,
    "electrical": SignalKDomain.BATTERY_DC,  # generic electrical fallback
    "propulsion": SignalKDomain.ENGINE_PROPULSION,
    "tanks": SignalKDomain.TANK,
    "tank": SignalKDomain.TANK,
    "performance": SignalKDomain.NAVIGATION,
    "sensors": SignalKDomain.STATUS_METADATA,
}


# ──────────────────────────────────────────────────────────────────────
# Ignore patterns (applied before classification)
# ──────────────────────────────────────────────────────────────────────

# Regex patterns for paths that should always be ignored
_IGNORE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.values\."),      # source-specific fanout
    re.compile(r"\.meta\."),        # metadata branches
    re.compile(r"\.values$"),       # .values leaf
    re.compile(r"\.meta$"),         # .meta leaf
]

# Vessel prefix patterns to strip during canonicalization
_VESSEL_PREFIX_RE = re.compile(
    r"^vessels\.(?:self|urn:mrn:(?:imo|signalk):[\w:]+)\."
)

# CamelCase splitter for friendly names
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Top-level prefixes to strip for friendly names
_FRIENDLY_NAME_STRIP_PREFIXES = {
    "navigation", "environment", "electrical", "propulsion", "tanks",
    "notifications", "steering", "communication", "design", "sails",
    "performance", "entertainment", "sensors", "bilge", "pumps",
    "watermaker", "watermakers", "noforeignland", "tank",
}


def canonicalize_path(path: str) -> str:
    """Strip vessel prefixes and normalize a SignalK path.

    Converts 'vessels.self.navigation.position' → 'navigation.position'
    and 'vessels.urn:mrn:imo:mmsi:123456789.navigation.position' →
    'navigation.position'.
    """
    return _VESSEL_PREFIX_RE.sub("", path)


def is_ignored_path(path: str) -> bool:
    """Check if a path should be ignored (values/meta branches, etc)."""
    for pattern in _IGNORE_PATTERNS:
        if pattern.search(path):
            return True
    return False


def classify_path(path: str) -> ClassificationResult:
    """Classify a canonical SignalK path into a functional domain.

    Uses a 4-layer matching strategy:
    1. Exact path match
    2. Prefix-based rules (first match wins)
    3. Segment/suffix heuristics
    4. Fallback to unsupported_ignore
    """
    # Layer 1: Exact match
    result = EXACT_MATCHES.get(path)
    if result is not None:
        return result

    # Layer 2: Prefix rules (order matters)
    for rule in PREFIX_RULES:
        if path.startswith(rule.prefix):
            return rule.result

    # Layer 3a: Suffix heuristics
    for suffix, domain in SUFFIX_HEURISTICS:
        if path.endswith(suffix):
            return ClassificationResult(
                domain=domain,
                enabled_by_default=False,
                icon="mdi:clock-outline",
            )

    # Layer 3b: First-segment heuristic
    first_segment = path.split(".")[0] if "." in path else path
    domain = SEGMENT_HEURISTICS.get(first_segment)
    if domain is not None:
        return ClassificationResult(
            domain=domain,
            enabled_by_default=False,
        )

    # Layer 4: Fallback
    return ClassificationResult(domain=SignalKDomain.UNSUPPORTED_IGNORE)


def path_to_friendly_name(path: str) -> str:
    """Convert a dotted SignalK path to a human-readable name.

    'navigation.speedOverGround' → 'Speed Over Ground'
    'environment.depth.belowKeel' → 'Depth Below Keel'
    'electrical.batteries.house.voltage' → 'Batteries House Voltage'
    """
    segments = path.split(".")
    # Strip known top-level prefixes
    if segments and segments[0] in _FRIENDLY_NAME_STRIP_PREFIXES:
        segments = segments[1:]

    if not segments:
        return path

    words: list[str] = []
    for seg in segments:
        # Split camelCase
        parts = _CAMEL_RE.split(seg)
        words.extend(p.capitalize() for p in parts if p)

    return " ".join(words) if words else path
