"""Publish-policy engine for SignalK Bridge.

Controls when sensor state updates are published to Home Assistant.
Each domain has configurable:
- min_interval: Minimum seconds between HA state writes
- max_interval: Maximum seconds before a forced refresh
- deadband: Absolute change threshold that must be exceeded

An update is published when:
1. The value changed by more than the deadband AND min_interval has elapsed, OR
2. max_interval has elapsed (forced heartbeat refresh), OR
3. The update is flagged as immediate (alarm state transitions, availability changes)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from .const import PublishProfile, SignalKDomain

_LOGGER = logging.getLogger(__name__)


@dataclass
class DomainPolicy:
    """Publish policy for a single domain."""

    min_interval: float  # Minimum seconds between publishes
    max_interval: float  # Maximum seconds before forced refresh
    deadband: float  # Absolute value change threshold
    enabled_by_default: bool = True  # Whether new entities in this domain start enabled

    def copy(self) -> DomainPolicy:
        """Return a shallow copy."""
        return DomainPolicy(
            min_interval=self.min_interval,
            max_interval=self.max_interval,
            deadband=self.deadband,
            enabled_by_default=self.enabled_by_default,
        )


# ──────────────────────────────────────────────────────────────────────
# Default domain policies per publish profile
# ──────────────────────────────────────────────────────────────────────

# Conservative: minimize HA writes, good for Raspberry Pi
_CONSERVATIVE: dict[SignalKDomain, DomainPolicy] = {
    SignalKDomain.ALARM: DomainPolicy(
        min_interval=0.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=True,
    ),
    SignalKDomain.POSITION: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=25.0,
        enabled_by_default=True,
    ),
    SignalKDomain.NAVIGATION: DomainPolicy(
        min_interval=2.0, max_interval=60.0, deadband=0.5,
    ),
    SignalKDomain.WIND: DomainPolicy(
        min_interval=2.0, max_interval=60.0, deadband=0.5,
    ),
    SignalKDomain.ENVIRONMENT: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.1,
    ),
    SignalKDomain.TANK: DomainPolicy(
        min_interval=60.0, max_interval=600.0, deadband=0.5,
    ),
    SignalKDomain.BATTERY_DC: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.1,
    ),
    SignalKDomain.INVERTER_AC: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=0.5,
    ),
    SignalKDomain.ENGINE_PROPULSION: DomainPolicy(
        min_interval=5.0, max_interval=120.0, deadband=1.0,
    ),
    SignalKDomain.BILGE_PUMP: DomainPolicy(
        min_interval=0.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=True,
    ),
    SignalKDomain.WATERMAKER: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.5,
    ),
    SignalKDomain.COMMUNICATIONS: DomainPolicy(
        min_interval=60.0, max_interval=600.0, deadband=0.0,
    ),
    SignalKDomain.TIME: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=False,
    ),
    SignalKDomain.STATUS_METADATA: DomainPolicy(
        min_interval=30.0, max_interval=600.0, deadband=0.0,
        enabled_by_default=False,
    ),
    SignalKDomain.UNSUPPORTED_IGNORE: DomainPolicy(
        min_interval=60.0, max_interval=600.0, deadband=0.0,
        enabled_by_default=False,
    ),
}

# Balanced: moderate update rates
_BALANCED: dict[SignalKDomain, DomainPolicy] = {
    SignalKDomain.ALARM: DomainPolicy(
        min_interval=0.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=True,
    ),
    SignalKDomain.POSITION: DomainPolicy(
        min_interval=5.0, max_interval=60.0, deadband=10.0,
        enabled_by_default=True,
    ),
    SignalKDomain.NAVIGATION: DomainPolicy(
        min_interval=1.0, max_interval=30.0, deadband=0.3,
    ),
    SignalKDomain.WIND: DomainPolicy(
        min_interval=1.0, max_interval=30.0, deadband=0.3,
    ),
    SignalKDomain.ENVIRONMENT: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=0.05,
    ),
    SignalKDomain.TANK: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.3,
    ),
    SignalKDomain.BATTERY_DC: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=0.05,
    ),
    SignalKDomain.INVERTER_AC: DomainPolicy(
        min_interval=5.0, max_interval=60.0, deadband=0.3,
    ),
    SignalKDomain.ENGINE_PROPULSION: DomainPolicy(
        min_interval=2.0, max_interval=60.0, deadband=0.5,
    ),
    SignalKDomain.BILGE_PUMP: DomainPolicy(
        min_interval=0.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=True,
    ),
    SignalKDomain.WATERMAKER: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=0.3,
    ),
    SignalKDomain.COMMUNICATIONS: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.0,
    ),
    SignalKDomain.TIME: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=0.0,
        enabled_by_default=False,
    ),
    SignalKDomain.STATUS_METADATA: DomainPolicy(
        min_interval=10.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=False,
    ),
    SignalKDomain.UNSUPPORTED_IGNORE: DomainPolicy(
        min_interval=60.0, max_interval=600.0, deadband=0.0,
        enabled_by_default=False,
    ),
}

# Realtime: fastest updates, highest load
_REALTIME: dict[SignalKDomain, DomainPolicy] = {
    SignalKDomain.ALARM: DomainPolicy(
        min_interval=0.0, max_interval=120.0, deadband=0.0,
        enabled_by_default=True,
    ),
    SignalKDomain.POSITION: DomainPolicy(
        min_interval=2.0, max_interval=30.0, deadband=5.0,
        enabled_by_default=True,
    ),
    SignalKDomain.NAVIGATION: DomainPolicy(
        min_interval=0.5, max_interval=15.0, deadband=0.1,
    ),
    SignalKDomain.WIND: DomainPolicy(
        min_interval=0.5, max_interval=15.0, deadband=0.1,
    ),
    SignalKDomain.ENVIRONMENT: DomainPolicy(
        min_interval=5.0, max_interval=60.0, deadband=0.01,
    ),
    SignalKDomain.TANK: DomainPolicy(
        min_interval=15.0, max_interval=120.0, deadband=0.1,
    ),
    SignalKDomain.BATTERY_DC: DomainPolicy(
        min_interval=5.0, max_interval=60.0, deadband=0.02,
    ),
    SignalKDomain.INVERTER_AC: DomainPolicy(
        min_interval=2.0, max_interval=30.0, deadband=0.1,
    ),
    SignalKDomain.ENGINE_PROPULSION: DomainPolicy(
        min_interval=1.0, max_interval=30.0, deadband=0.2,
    ),
    SignalKDomain.BILGE_PUMP: DomainPolicy(
        min_interval=0.0, max_interval=120.0, deadband=0.0,
        enabled_by_default=True,
    ),
    SignalKDomain.WATERMAKER: DomainPolicy(
        min_interval=5.0, max_interval=60.0, deadband=0.1,
    ),
    SignalKDomain.COMMUNICATIONS: DomainPolicy(
        min_interval=10.0, max_interval=120.0, deadband=0.0,
    ),
    SignalKDomain.TIME: DomainPolicy(
        min_interval=5.0, max_interval=60.0, deadband=0.0,
        enabled_by_default=False,
    ),
    SignalKDomain.STATUS_METADATA: DomainPolicy(
        min_interval=5.0, max_interval=120.0, deadband=0.0,
        enabled_by_default=False,
    ),
    SignalKDomain.UNSUPPORTED_IGNORE: DomainPolicy(
        min_interval=30.0, max_interval=300.0, deadband=0.0,
        enabled_by_default=False,
    ),
}

PROFILE_DEFAULTS: dict[PublishProfile, dict[SignalKDomain, DomainPolicy]] = {
    PublishProfile.CONSERVATIVE: _CONSERVATIVE,
    PublishProfile.BALANCED: _BALANCED,
    PublishProfile.REALTIME: _REALTIME,
}


def get_default_policies(
    profile: PublishProfile | str = PublishProfile.CONSERVATIVE,
) -> dict[SignalKDomain, DomainPolicy]:
    """Get a fresh copy of default domain policies for a profile."""
    if isinstance(profile, str):
        profile = PublishProfile(profile)
    source = PROFILE_DEFAULTS.get(profile, _CONSERVATIVE)
    return {domain: policy.copy() for domain, policy in source.items()}


@dataclass
class PathState:
    """Tracks the publish state for a single path."""

    last_published_value: Any = None
    last_published_time: float = 0.0  # monotonic time
    last_received_value: Any = None
    last_received_time: float = 0.0


class PublishPolicyEngine:
    """Decides when to publish sensor state updates to HA.

    Maintains per-path state and applies domain-level policies to determine
    whether a new value should trigger an HA state write.
    """

    def __init__(
        self,
        profile: PublishProfile | str = PublishProfile.CONSERVATIVE,
    ) -> None:
        """Initialize with a base profile."""
        self._policies: dict[SignalKDomain, DomainPolicy] = get_default_policies(profile)
        self._path_states: dict[str, PathState] = {}
        self._profile = PublishProfile(profile) if isinstance(profile, str) else profile

    @property
    def profile(self) -> PublishProfile:
        """Return current base profile."""
        return self._profile

    @property
    def policies(self) -> dict[SignalKDomain, DomainPolicy]:
        """Return current domain policies (read-only reference)."""
        return self._policies

    def get_policy(self, domain: SignalKDomain) -> DomainPolicy:
        """Get the policy for a domain, falling back to conservative defaults."""
        return self._policies.get(domain, DomainPolicy(
            min_interval=30.0, max_interval=300.0, deadband=0.5,
        ))

    def set_policy(
        self,
        domain: SignalKDomain,
        *,
        min_interval: Optional[float] = None,
        max_interval: Optional[float] = None,
        deadband: Optional[float] = None,
        enabled_by_default: Optional[bool] = None,
    ) -> DomainPolicy:
        """Update the policy for a domain. Returns the updated policy."""
        current = self.get_policy(domain)
        self._policies[domain] = DomainPolicy(
            min_interval=min_interval if min_interval is not None else current.min_interval,
            max_interval=max_interval if max_interval is not None else current.max_interval,
            deadband=deadband if deadband is not None else current.deadband,
            enabled_by_default=(
                enabled_by_default if enabled_by_default is not None
                else current.enabled_by_default
            ),
        )
        return self._policies[domain]

    def reset_policy(self, domain: SignalKDomain) -> DomainPolicy:
        """Reset a domain's policy to the current profile's default."""
        defaults = PROFILE_DEFAULTS.get(self._profile, _CONSERVATIVE)
        default_policy = defaults.get(domain, DomainPolicy(
            min_interval=30.0, max_interval=300.0, deadband=0.5,
        ))
        self._policies[domain] = default_policy.copy()
        return self._policies[domain]

    def set_profile(self, profile: PublishProfile | str) -> None:
        """Switch to a different base profile, resetting all policies."""
        if isinstance(profile, str):
            profile = PublishProfile(profile)
        self._profile = profile
        self._policies = get_default_policies(profile)
        # Clear path states so everything re-evaluates fresh
        self._path_states.clear()

    def should_publish(
        self,
        path: str,
        domain: SignalKDomain,
        new_value: Any,
        *,
        immediate: bool = False,
        now: Optional[float] = None,
    ) -> bool:
        """Determine whether a new value should be published to HA.

        Args:
            path: Canonical SignalK path.
            domain: Classified domain for the path.
            new_value: The new value received from SignalK.
            immediate: Force immediate publish (e.g., alarm transitions).
            now: Override current time (for testing). Uses time.monotonic().

        Returns:
            True if the value should be published to HA state.
        """
        if now is None:
            now = time.monotonic()

        state = self._path_states.get(path)
        if state is None:
            # First time seeing this path — always publish
            self._path_states[path] = PathState(
                last_published_value=new_value,
                last_published_time=now,
                last_received_value=new_value,
                last_received_time=now,
            )
            return True

        # Always update received state
        state.last_received_value = new_value
        state.last_received_time = now

        # Immediate flag bypasses all throttling
        if immediate:
            state.last_published_value = new_value
            state.last_published_time = now
            return True

        policy = self.get_policy(domain)
        elapsed = now - state.last_published_time

        # Check max_interval (forced heartbeat refresh)
        if elapsed >= policy.max_interval:
            state.last_published_value = new_value
            state.last_published_time = now
            return True

        # Check min_interval gate
        if elapsed < policy.min_interval:
            return False

        # Check deadband (significant change)
        if self._exceeds_deadband(state.last_published_value, new_value, policy.deadband):
            state.last_published_value = new_value
            state.last_published_time = now
            return True

        return False

    def record_publish(self, path: str, value: Any, now: Optional[float] = None) -> None:
        """Record that a value was published (used for reconnect flood control)."""
        if now is None:
            now = time.monotonic()
        state = self._path_states.get(path)
        if state is None:
            self._path_states[path] = PathState(
                last_published_value=value,
                last_published_time=now,
                last_received_value=value,
                last_received_time=now,
            )
        else:
            state.last_published_value = value
            state.last_published_time = now

    def clear_path_states(self) -> None:
        """Clear all path states (e.g., on reconnect for controlled rebuild)."""
        self._path_states.clear()

    def get_path_state(self, path: str) -> Optional[PathState]:
        """Get the current publish state for a path (for debugging)."""
        return self._path_states.get(path)

    def dump_state(self) -> dict[str, Any]:
        """Dump the full engine state for debugging."""
        return {
            "profile": self._profile.value,
            "policies": {
                domain.value: {
                    "min_interval": policy.min_interval,
                    "max_interval": policy.max_interval,
                    "deadband": policy.deadband,
                    "enabled_by_default": policy.enabled_by_default,
                }
                for domain, policy in self._policies.items()
            },
            "tracked_paths": len(self._path_states),
        }

    @staticmethod
    def _exceeds_deadband(
        old_value: Any,
        new_value: Any,
        deadband: float,
    ) -> bool:
        """Check if the change exceeds the deadband threshold.

        For numeric values, checks absolute difference.
        For non-numeric values, checks equality.
        A deadband of 0.0 means any change is significant.
        """
        # Non-numeric or None: any change is significant
        if old_value is None or new_value is None:
            return old_value != new_value

        try:
            old_num = float(old_value)
            new_num = float(new_value)
        except (TypeError, ValueError):
            # Non-numeric: publish on any change
            return old_value != new_value

        if deadband <= 0.0:
            return old_num != new_num

        return abs(new_num - old_num) >= deadband
