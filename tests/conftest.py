"""Shared test fixtures for signalk_bridge tests."""

import sys
import os

# Ensure the HA stubs are loaded before any custom_components import
import tests.ha_stub  # noqa: F401

# Make custom_components importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
