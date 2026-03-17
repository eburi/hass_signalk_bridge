# SignalK Bridge

Home Assistant custom integration that connects to a SignalK server via WebSocket, dynamically creates sensors for all vessel self paths, and provides services to write values back to SignalK.

## Features

- **Automatic Discovery**: Detects if the SignalK HA App addon is installed and offers to use it
- **Dynamic Sensors**: Automatically creates sensors as SignalK data arrives — no need to configure each path
- **Unit Conversion**: Converts SignalK SI units (K, rad, m/s, Pa) to HA-native units (°C, °, knots, hPa)
- **WebSocket Streaming**: Real-time delta updates with automatic reconnection
- **Device Access Auth**: Supports SignalK's device authentication flow
- **Write Back**: Services to PUT/POST values to SignalK paths
- **Diagnostic Sensors**: Connection status and server version

## Installation

### Option 1: HACS

Add this repository as a custom repository in HACS, then install "SignalK Bridge".

### Option 2: Manual

Copy the `signalk_bridge` folder into your Home Assistant `custom_components` directory:

```
custom_components/signalk_bridge/
├── __init__.py
├── config_flow.py
├── const.py
├── manifest.json
├── sensor.py
├── services.yaml
├── signalk_client.py
├── strings.json
├── translations/
└── unit_mapping.py
```

Restart Home Assistant.

## Configuration

Go to **Settings → Devices & Services → Add Integration** and select "SignalK Bridge".

1. **Choose Server**: If the SignalK addon is detected, you can use it automatically or enter a custom URL
2. **Authentication**: If required, follow the device access request flow to approve HA
3. **Entity Prefix**: Set a prefix for entity IDs (default: `signalk`)

## Entities

All SignalK paths under `vessels.self` become sensors under a single "Vessel Self" device. Example sensors:

| SignalK Path | HA Entity |
|---|---|
| `navigation.speedOverGround` | sensor.signalk_navigation_speedoverground |
| `environment.wind.speedTrue` | sensor.signalk_environment_wind_speedtrue |
| `navigation.position` | sensor.signalk_navigation_position |

Object values (position, attitude) are formatted as strings.

## Services

### `signalk_bridge.put_value`

PUT a value to a SignalK path via REST API.

```yaml
service: signalk_bridge.put_value
data:
  path: "propulsion.port.revolutions"
  value: 1500
```

### `signalk_bridge.post_delta`

POST a delta to SignalK via WebSocket.

```yaml
service: signalk_bridge.post_delta
data:
  path: "navigation.speedThroughWater"
  value: 5.5
```

Both services accept any valid SignalK path and value type (number, string, boolean, object).

## Supported Units

SignalK uses SI units. This integration converts them:

| SignalK | Converted To |
|---|---|
| K (Kelvin) | °C/°F (via HA) |
| rad | ° |
| m/s | knots/kmh (via HA) |
| Pa | hPa (via HA) |
| ratio (0-1) | % |
| J | Wh |
| C (Coulomb) | Ah |

## Requirements

- Home Assistant 2024.x+
- Python 3.11+
- `websockets>=12.0`
- `httpx>=0.25.0`

## License

MIT
