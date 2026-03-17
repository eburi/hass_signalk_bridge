# SignalK Bridge for Home Assistant

<p align="center">
  <img src="brand/icon.svg" alt="SignalK Bridge Logo" width="200" height="200">
</p>

<p align="center">
  <strong>Bridge your vessel's SignalK data into Home Assistant — smartly.</strong>
</p>

<p align="center">
  <a href="https://github.com/eburi/hass_signalk_bridge/actions/workflows/validate.yml">
    <img src="https://github.com/eburi/hass_signalk_bridge/actions/workflows/validate.yml/badge.svg" alt="Validate">
  </a>
  <a href="https://github.com/eburi/hass_signalk_bridge/actions/workflows/lint.yml">
    <img src="https://github.com/eburi/hass_signalk_bridge/actions/workflows/lint.yml/badge.svg" alt="Lint">
  </a>
  <a href="https://github.com/hacs/integration">
    <img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS">
  </a>
  <a href="https://github.com/eburi/hass_signalk_bridge/releases">
    <img src="https://img.shields.io/github/v/release/eburi/hass_signalk_bridge" alt="GitHub Release">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/github/license/eburi/hass_signalk_bridge" alt="License">
  </a>
</p>

---

## What is this?

**SignalK Bridge** is a Home Assistant custom integration that connects to a [SignalK](https://signalk.org/) server via WebSocket and creates HA entities for your vessel's data — navigation, environment, electrical, tanks, engine, and more.

Unlike naive approaches that mirror every SignalK delta directly into HA state writes (which will overwhelm a Raspberry Pi), SignalK Bridge uses a **smart publish-policy layer** that coalesces updates per functional domain, respecting configurable intervals and deadbands. This keeps Home Assistant responsive even on resource-constrained hardware.

### Key Features

- **WebSocket push** — real-time delta stream, no polling
- **Smart path classification** — 4-layer classifier assigns each SignalK path to one of 14 functional domains
- **Publish-policy engine** — per-domain min/max intervals and deadband thresholds prevent HA flooding
- **3 publish profiles** — Conservative (default, lowest load), Balanced, Realtime
- **Device tracker** — vessel position as a native `device_tracker` entity for map display
- **10 services** — control values, tune policies, manage entities, all from Developer Tools
- **Auto-discovery** — new paths are detected and classified automatically
- **Vessel self only** — ignores AIS targets and other vessels (architecture ready for future expansion)
- **New entities disabled by default** — `enable_new_sensors_by_default` defaults to `false`
- **SignalK HA add-on detection** — auto-detects the SignalK add-on, or connect to any SignalK server manually
- **Device Access auth flow** — built-in authentication via SignalK's device access request protocol

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) and select **Custom repositories**
3. Add `https://github.com/eburi/hass_signalk_bridge` with category **Integration**
4. Search for "SignalK Bridge" and click **Download**
5. Restart Home Assistant

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eburi&repository=hass_signalk_bridge&category=integration)

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/eburi/hass_signalk_bridge/releases)
2. Extract `signalk_bridge` into `config/custom_components/signalk_bridge/`
3. Restart Home Assistant

---

## Configuration

### Setup Flow

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **SignalK Bridge**
3. The integration will:
   - Check for the SignalK HA add-on (`a0d7b954_signalk`) and offer to use it
   - Or let you enter a manual URL (e.g., `http://192.168.1.100:3000`)
4. If needed, the device access auth flow will guide you through granting access on the SignalK server
5. Choose an entity prefix (default: `signalk`)

### Options (Settings > Devices & Services > SignalK Bridge > Configure)

| Option | Default | Description |
|--------|---------|-------------|
| **Base URL** | `http://localhost:3000` | SignalK server URL |
| **Entity Prefix** | `signalk` | Prefix for all entity IDs (e.g., `sensor.signalk_speed_over_ground`) |
| **Enable New Sensors By Default** | `false` | Whether newly discovered entities start enabled |
| **Publish Profile** | `conservative` | Base throttling profile: `conservative`, `balanced`, or `realtime` |
| **Log Ignored Paths** | `false` | Log paths classified as unsupported/ignored |
| **Create Diagnostic Entities** | `true` | Create connection status and server version sensors |

---

## How It Works

### Architecture

```
SignalK Server
    │
    ▼ WebSocket delta stream
┌─────────────────────────────┐
│  SignalK Client              │  Connects, authenticates, receives deltas
├─────────────────────────────┤
│  Path Canonicalizer          │  Strips vessels.self.*, ignores .values.* / .meta.*
├─────────────────────────────┤
│  4-Layer Classifier          │  Exact → Prefix → Heuristic → Fallback
│  → 14 functional domains     │
├─────────────────────────────┤
│  Publish-Policy Engine       │  Per-domain: min_interval, max_interval, deadband
│  → 3 profiles                │
├─────────────────────────────┤
│  Entity Factory              │  Creates sensors + device_tracker dynamically
├─────────────────────────────┤
│  Home Assistant              │  State writes only when policy allows
└─────────────────────────────┘
```

### Functional Domains

Each SignalK path is classified into one of these domains, each with its own publish policy:

| Domain | Examples | Description |
|--------|----------|-------------|
| `alarm` | `notifications.*` (non-AIS) | Alarms — always immediate |
| `position` | `navigation.position` | GPS position — device_tracker |
| `navigation` | `navigation.speedOverGround`, `navigation.courseOverGroundTrue` | Speed, heading, course |
| `wind` | `environment.wind.speedApparent`, `environment.wind.angleApparent` | Wind data |
| `environment` | `environment.depth.belowKeel`, `environment.water.temperature` | Depth, water, weather |
| `tank` | `tanks.fuel.main.currentLevel` | Fuel, water, waste tanks |
| `battery_dc` | `electrical.batteries.house.voltage` | Batteries, solar, DC |
| `inverter_ac` | `electrical.inverters.main.ac.power` | Inverters, shore power, AC |
| `engine_propulsion` | `propulsion.port.revolutions` | Engine RPM, oil pressure, temperature |
| `bilge_pump` | `bilge.main.pumpRunning` | Bilge pumps |
| `watermaker` | `watermaker.production.rate` | Watermaker |
| `communications` | `communication.dsc.*` | Comms, DSC |
| `time` | `environment.sunlight.times.sunrise` | Sun/moon times, ETAs |
| `status_metadata` | `name`, `design.*`, `mmsi` | Vessel metadata |

### Publish Profiles

Profiles control how aggressively the integration throttles state writes:

| Profile | Best For | Navigation min/max | Wind min/max | Environment min/max |
|---------|----------|-------------------|-------------|-------------------|
| **Conservative** | Raspberry Pi, logging | 5s / 60s | 5s / 30s | 30s / 300s |
| **Balanced** | General use | 2s / 30s | 2s / 15s | 10s / 120s |
| **Realtime** | Dashboards, racing | 1s / 10s | 1s / 5s | 5s / 60s |

**How the policy works:**

1. **First value** — always published immediately
2. **min_interval** — no updates faster than this (coalescing)
3. **deadband** — numeric changes smaller than this are suppressed
4. **max_interval** — forced refresh even if value hasn't changed (heartbeat)
5. **Alarms** — always bypass throttling

---

## Entity Examples

Once connected, entities are created dynamically as SignalK paths are received:

| Entity ID | Type | Description |
|-----------|------|-------------|
| `device_tracker.signalk_vessel_position` | Device Tracker | Vessel location on the map |
| `sensor.signalk_speed_over_ground` | Sensor | SOG in knots |
| `sensor.signalk_course_over_ground_true` | Sensor | COG in degrees |
| `sensor.signalk_depth_below_keel` | Sensor | Depth in meters |
| `sensor.signalk_wind_speed_apparent` | Sensor | AWS in knots |
| `sensor.signalk_wind_angle_apparent` | Sensor | AWA in degrees |
| `sensor.signalk_water_temperature` | Sensor | Water temp in °C |
| `sensor.signalk_batteries_house_voltage` | Sensor | House bank voltage |
| `sensor.signalk_connection_status` | Diagnostic | WebSocket connection state |
| `sensor.signalk_server_version` | Diagnostic | SignalK server version |

> **Note:** New entities are created **disabled** by default. Enable them in the entity registry or use the `enable_entities` service.

---

## Services

All 10 services are available in **Developer Tools > Services** with full field selectors.

### `signalk_bridge.put_value`

Send a PUT request to set a value on the SignalK server.

```yaml
service: signalk_bridge.put_value
data:
  path: "electrical.switches.bank1.1.state"
  value: 1
```

**Use cases:** Toggle switches, set autopilot heading, control relays.

### `signalk_bridge.post_delta`

Send a delta update via WebSocket (falls back to REST).

```yaml
service: signalk_bridge.post_delta
data:
  path: "environment.inside.mainCabin.temperature"
  value: 295.15
```

### `signalk_bridge.set_domain_policy`

Tune the publish policy for a specific domain at runtime.

```yaml
# Make navigation updates faster for a racing dashboard
service: signalk_bridge.set_domain_policy
data:
  domain: "navigation"
  min_interval_seconds: 1.0
  max_interval_seconds: 10.0
  deadband: 0.01
```

```yaml
# Reduce battery update frequency to save resources
service: signalk_bridge.set_domain_policy
data:
  domain: "battery_dc"
  min_interval_seconds: 30.0
  max_interval_seconds: 300.0
  deadband: 0.1
```

### `signalk_bridge.reset_domain_policy`

Reset a domain's policy back to the current profile defaults.

```yaml
service: signalk_bridge.reset_domain_policy
data:
  domain: "navigation"
```

### `signalk_bridge.set_discovery_defaults`

Change global settings at runtime without restart.

```yaml
# Switch to realtime profile for active sailing
service: signalk_bridge.set_discovery_defaults
data:
  publish_profile: "realtime"
  enable_new_sensors_by_default: true
```

```yaml
# Switch to conservative when docked
service: signalk_bridge.set_discovery_defaults
data:
  publish_profile: "conservative"
  log_ignored_paths: false
```

### `signalk_bridge.rescan_paths`

Discover and classify any new SignalK paths from the in-memory cache.

```yaml
service: signalk_bridge.rescan_paths
```

### `signalk_bridge.reclassify_paths`

Re-run the classifier on all known paths (useful after integration updates).

```yaml
service: signalk_bridge.reclassify_paths
```

### `signalk_bridge.enable_entities`

Enable one or more SignalK entities.

```yaml
service: signalk_bridge.enable_entities
data:
  entity_ids:
    - sensor.signalk_speed_over_ground
    - sensor.signalk_depth_below_keel
    - sensor.signalk_wind_speed_apparent
```

### `signalk_bridge.disable_entities`

Disable one or more SignalK entities.

```yaml
service: signalk_bridge.disable_entities
data:
  entity_ids:
    - sensor.signalk_navigation_datetime
```

### `signalk_bridge.dump_runtime_state`

Dump full runtime state to the log and fire a `signalk_bridge_runtime_state` event.

```yaml
service: signalk_bridge.dump_runtime_state
```

This outputs:
- Connection status and server info
- Current publish profile and all domain policies
- All classified paths and their domains
- Ignored/unsupported path list
- Sensor counts and latest values

---

## Automation Examples

### Switch to realtime profile when sailing

```yaml
automation:
  - alias: "SignalK Realtime When Sailing"
    trigger:
      - platform: numeric_state
        entity_id: sensor.signalk_speed_over_ground
        above: 2
    action:
      - service: signalk_bridge.set_discovery_defaults
        data:
          publish_profile: "realtime"

  - alias: "SignalK Conservative When Docked"
    trigger:
      - platform: numeric_state
        entity_id: sensor.signalk_speed_over_ground
        below: 0.5
        for: "00:10:00"
    action:
      - service: signalk_bridge.set_discovery_defaults
        data:
          publish_profile: "conservative"
```

### Anchor watch alarm

```yaml
automation:
  - alias: "Anchor Watch"
    trigger:
      - platform: geo_location
        source: device_tracker.signalk_vessel_position
        zone: zone.anchorage
        event: leave
    action:
      - service: notify.mobile_app
        data:
          title: "Anchor Watch"
          message: "Vessel has left the anchorage zone!"
```

### Low battery alert

```yaml
automation:
  - alias: "Low House Battery"
    trigger:
      - platform: numeric_state
        entity_id: sensor.signalk_batteries_house_voltage
        below: 12.0
    action:
      - service: notify.mobile_app
        data:
          title: "Battery Warning"
          message: "House battery voltage is {{ states('sensor.signalk_batteries_house_voltage') }}V"
```

---

## Unit Conversion

SignalK uses SI units internally. The integration automatically converts to user-friendly units:

| SignalK Unit | Converted To | Examples |
|-------------|-------------|---------|
| Kelvin (K) | °C | Water temperature, cabin temperature |
| Radians (rad) | Degrees (°) | Wind angle, heading, COG |
| m/s | knots (kn) | SOG, STW, wind speed |
| Pascals (Pa) | hPa | Atmospheric pressure |
| Ratio (0-1) | Percentage (%) | Tank levels, battery SOC |
| Joules (J) | Wh | Energy |
| Coulombs (C) | Ah | Battery capacity |

---

## Debugging

### Enable debug logging

Add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.signalk_bridge: debug
```

### Dump runtime state

Call `signalk_bridge.dump_runtime_state` from Developer Tools to get a full snapshot of:
- Connection status
- Active publish profile and per-domain policies
- All classified paths
- Ignored paths
- Sensor counts

### Log ignored paths

Enable via **Options > Log Ignored Paths** to see which SignalK paths are being dropped and why.

---

## Requirements

- Home Assistant 2024.1 or newer
- A running [SignalK server](https://signalk.org/) (v1.x or v2.x)
- Network connectivity between HA and the SignalK server

### Tested With

- Home Assistant OS on Raspberry Pi 4
- SignalK server via the [HA SignalK add-on](https://github.com/signalk/signalk-server)
- SignalK server standalone on Linux

---

## Development

```bash
git clone https://github.com/eburi/hass_signalk_bridge.git
cd hass_signalk_bridge
python3 -m venv .venv
source .venv/bin/activate
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

Tests use HA stubs (no full HA installation required). See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

[MIT](LICENSE) -- Copyright (c) 2025 [@eburi](https://github.com/eburi)
