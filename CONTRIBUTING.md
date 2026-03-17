# Contributing to SignalK Bridge

Thanks for your interest in contributing to SignalK Bridge for Home Assistant!

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/eburi/hass_signalk_bridge.git
   cd hass_signalk_bridge
   ```

2. Create a virtual environment and install test dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install pytest pytest-asyncio
   ```

3. Run the test suite:
   ```bash
   python -m pytest tests/ -v
   ```

## Test Architecture

Tests use a **stub-based approach** in `tests/ha_stub.py` that replaces the
full Home Assistant core with minimal stand-ins. This allows tests to run
without installing Home Assistant (which requires C extensions not available
in all environments).

The stubs cover: `homeassistant.core`, `homeassistant.config_entries`,
`homeassistant.components.sensor`, `homeassistant.components.device_tracker`,
`homeassistant.helpers.*`, `voluptuous`, `httpx`, and `websockets`.

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the test suite and ensure all tests pass
5. Commit with a descriptive message
6. Push and open a pull request

## Reporting Issues

Please use [GitHub Issues](https://github.com/eburi/hass_signalk_bridge/issues)
and include:
- Home Assistant version
- SignalK server version
- Relevant log output (set logger for `custom_components.signalk_bridge` to `debug`)
- Steps to reproduce

## Code Style

- Follow existing patterns in the codebase
- Use type hints
- Keep imports organized (stdlib, third-party, HA, local)
