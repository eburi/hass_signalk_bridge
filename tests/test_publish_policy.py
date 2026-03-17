"""Tests for publish_policy.py — policy engine, profiles, deadband, intervals."""

from custom_components.signalk_bridge.const import PublishProfile, SignalKDomain
from custom_components.signalk_bridge.publish_policy import (
    DomainPolicy,
    PublishPolicyEngine,
    PROFILE_DEFAULTS,
    get_default_policies,
)


# ===================================================================
# DomainPolicy
# ===================================================================


class TestDomainPolicy:
    def test_create(self):
        p = DomainPolicy(min_interval=1.0, max_interval=60.0, deadband=0.5)
        assert p.min_interval == 1.0
        assert p.max_interval == 60.0
        assert p.deadband == 0.5
        assert p.enabled_by_default is True

    def test_copy(self):
        p = DomainPolicy(
            min_interval=2.0, max_interval=120.0, deadband=0.1, enabled_by_default=False
        )
        c = p.copy()
        assert c.min_interval == 2.0
        assert c.max_interval == 120.0
        assert c.deadband == 0.1
        assert c.enabled_by_default is False
        assert c is not p


# ===================================================================
# Profile defaults
# ===================================================================


class TestProfileDefaults:
    def test_all_profiles_exist(self):
        for profile in PublishProfile:
            assert profile in PROFILE_DEFAULTS

    def test_all_domains_have_policy_per_profile(self):
        for profile in PublishProfile:
            policies = PROFILE_DEFAULTS[profile]
            for domain in SignalKDomain:
                assert domain in policies, f"{domain} missing from {profile}"

    def test_conservative_is_strictest(self):
        """Conservative should have higher min_intervals than realtime for same domain."""
        con = PROFILE_DEFAULTS[PublishProfile.CONSERVATIVE]
        rt = PROFILE_DEFAULTS[PublishProfile.REALTIME]
        for domain in SignalKDomain:
            if domain == SignalKDomain.ALARM:
                continue  # Alarms are always 0.0
            assert con[domain].min_interval >= rt[domain].min_interval, (
                f"{domain}: conservative min_interval {con[domain].min_interval} "
                f"< realtime {rt[domain].min_interval}"
            )

    def test_get_default_policies_returns_copies(self):
        p1 = get_default_policies(PublishProfile.CONSERVATIVE)
        p2 = get_default_policies(PublishProfile.CONSERVATIVE)
        # Should be equal but not the same objects
        assert (
            p1[SignalKDomain.NAVIGATION].min_interval
            == p2[SignalKDomain.NAVIGATION].min_interval
        )
        assert p1[SignalKDomain.NAVIGATION] is not p2[SignalKDomain.NAVIGATION]

    def test_get_default_policies_string_input(self):
        p = get_default_policies("balanced")
        assert (
            p[SignalKDomain.NAVIGATION].min_interval
            == PROFILE_DEFAULTS[PublishProfile.BALANCED][
                SignalKDomain.NAVIGATION
            ].min_interval
        )

    def test_alarm_always_immediate(self):
        """Alarm domain should have min_interval=0 across all profiles."""
        for profile in PublishProfile:
            assert PROFILE_DEFAULTS[profile][SignalKDomain.ALARM].min_interval == 0.0


# ===================================================================
# PublishPolicyEngine — initialization
# ===================================================================


class TestEngineInit:
    def test_default_profile(self):
        engine = PublishPolicyEngine()
        assert engine.profile == PublishProfile.CONSERVATIVE

    def test_custom_profile(self):
        engine = PublishPolicyEngine(profile=PublishProfile.REALTIME)
        assert engine.profile == PublishProfile.REALTIME

    def test_string_profile(self):
        engine = PublishPolicyEngine(profile="balanced")
        assert engine.profile == PublishProfile.BALANCED


# ===================================================================
# should_publish — first value always publishes
# ===================================================================


class TestShouldPublishFirstValue:
    def test_first_value_always_publishes(self):
        engine = PublishPolicyEngine()
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0
        )
        assert result is True

    def test_first_value_stores_state(self):
        engine = PublishPolicyEngine()
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        state = engine.get_path_state("nav.sog")
        assert state is not None
        assert state.last_published_value == 5.0
        assert state.last_published_time == 100.0


# ===================================================================
# should_publish — min_interval gate
# ===================================================================


class TestShouldPublishMinInterval:
    def test_within_min_interval_blocked(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Navigation min_interval is 2.0 for conservative
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        # 1 second later — within min_interval
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 10.0, now=101.0
        )
        assert result is False

    def test_past_min_interval_with_change(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Navigation: min_interval=2.0, deadband=0.5
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        # 3 seconds later, value changed by 1.0 (> deadband 0.5)
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 6.0, now=103.0
        )
        assert result is True


# ===================================================================
# should_publish — deadband
# ===================================================================


class TestShouldPublishDeadband:
    def test_change_below_deadband_blocked(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Navigation: min_interval=2.0, deadband=0.5
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        # Past min_interval but change < deadband
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 5.3, now=103.0
        )
        assert result is False

    def test_change_at_deadband_publishes(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        # Exactly at deadband (0.5)
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 5.5, now=103.0
        )
        assert result is True

    def test_zero_deadband_any_change_publishes(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Alarm domain has deadband=0.0
        engine.should_publish("alarm.test", SignalKDomain.ALARM, "normal", now=100.0)
        result = engine.should_publish(
            "alarm.test", SignalKDomain.ALARM, "critical", now=100.1
        )
        assert result is True

    def test_non_numeric_change(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Status metadata: min_interval=30.0, deadband=0.0
        engine.should_publish(
            "status.test", SignalKDomain.STATUS_METADATA, "idle", now=100.0
        )
        # Past min_interval, string changed
        result = engine.should_publish(
            "status.test", SignalKDomain.STATUS_METADATA, "active", now=131.0
        )
        assert result is True

    def test_non_numeric_no_change_blocked(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        engine.should_publish(
            "status.test", SignalKDomain.STATUS_METADATA, "idle", now=100.0
        )
        # Same value, past min_interval but before max_interval
        result = engine.should_publish(
            "status.test", SignalKDomain.STATUS_METADATA, "idle", now=131.0
        )
        assert result is False


# ===================================================================
# should_publish — max_interval (heartbeat)
# ===================================================================


class TestShouldPublishMaxInterval:
    def test_max_interval_forces_publish(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Navigation: max_interval=60.0
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        # Same value, well past max_interval
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 5.0, now=161.0
        )
        assert result is True

    def test_just_before_max_interval_blocked(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Navigation: max_interval=60.0, deadband=0.5
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        # Same value (no deadband exceed), just before max_interval
        result = engine.should_publish(
            "nav.sog", SignalKDomain.NAVIGATION, 5.0, now=159.0
        )
        assert result is False


# ===================================================================
# should_publish — immediate flag
# ===================================================================


class TestShouldPublishImmediate:
    def test_immediate_bypasses_throttle(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        engine.should_publish("alarm.fire", SignalKDomain.ALARM, "normal", now=100.0)
        # Immediate flag — publish even within min_interval
        result = engine.should_publish(
            "alarm.fire",
            SignalKDomain.ALARM,
            "critical",
            immediate=True,
            now=100.001,
        )
        assert result is True

    def test_immediate_updates_state(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        engine.should_publish("alarm.fire", SignalKDomain.ALARM, "normal", now=100.0)
        engine.should_publish(
            "alarm.fire",
            SignalKDomain.ALARM,
            "critical",
            immediate=True,
            now=101.0,
        )
        state = engine.get_path_state("alarm.fire")
        assert state.last_published_value == "critical"
        assert state.last_published_time == 101.0


# ===================================================================
# set_policy / reset_policy
# ===================================================================


class TestSetResetPolicy:
    def test_set_policy_partial(self):
        engine = PublishPolicyEngine()
        original = engine.get_policy(SignalKDomain.NAVIGATION)
        result = engine.set_policy(SignalKDomain.NAVIGATION, min_interval=0.1)
        assert result.min_interval == 0.1
        assert result.max_interval == original.max_interval  # unchanged
        assert result.deadband == original.deadband  # unchanged

    def test_set_policy_full(self):
        engine = PublishPolicyEngine()
        result = engine.set_policy(
            SignalKDomain.WIND,
            min_interval=0.5,
            max_interval=30.0,
            deadband=0.1,
            enabled_by_default=False,
        )
        assert result.min_interval == 0.5
        assert result.max_interval == 30.0
        assert result.deadband == 0.1
        assert result.enabled_by_default is False

    def test_reset_policy(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        # Modify
        engine.set_policy(SignalKDomain.NAVIGATION, min_interval=99.0)
        assert engine.get_policy(SignalKDomain.NAVIGATION).min_interval == 99.0
        # Reset
        result = engine.reset_policy(SignalKDomain.NAVIGATION)
        default = PROFILE_DEFAULTS[PublishProfile.CONSERVATIVE][
            SignalKDomain.NAVIGATION
        ]
        assert result.min_interval == default.min_interval

    def test_set_policy_for_unknown_domain_uses_fallback(self):
        """get_policy for a domain not in the map should return a fallback."""
        engine = PublishPolicyEngine()
        # UNSUPPORTED_IGNORE should always be in the map, but let's test get_policy
        policy = engine.get_policy(SignalKDomain.UNSUPPORTED_IGNORE)
        assert policy is not None
        assert policy.min_interval >= 0


# ===================================================================
# set_profile
# ===================================================================


class TestSetProfile:
    def test_switch_profile(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        engine.should_publish("test", SignalKDomain.NAVIGATION, 1.0, now=100.0)
        assert engine.get_path_state("test") is not None

        engine.set_profile(PublishProfile.REALTIME)
        assert engine.profile == PublishProfile.REALTIME
        # Path states should be cleared
        assert engine.get_path_state("test") is None

    def test_switch_profile_string(self):
        engine = PublishPolicyEngine()
        engine.set_profile("balanced")
        assert engine.profile == PublishProfile.BALANCED

    def test_policies_updated_after_profile_switch(self):
        engine = PublishPolicyEngine(profile=PublishProfile.CONSERVATIVE)
        con_nav = engine.get_policy(SignalKDomain.NAVIGATION)
        engine.set_profile(PublishProfile.REALTIME)
        rt_nav = engine.get_policy(SignalKDomain.NAVIGATION)
        assert rt_nav.min_interval < con_nav.min_interval


# ===================================================================
# clear_path_states
# ===================================================================


class TestClearPathStates:
    def test_clear(self):
        engine = PublishPolicyEngine()
        engine.should_publish("a", SignalKDomain.NAVIGATION, 1.0, now=100.0)
        engine.should_publish("b", SignalKDomain.WIND, 2.0, now=100.0)
        assert engine.get_path_state("a") is not None
        assert engine.get_path_state("b") is not None

        engine.clear_path_states()
        assert engine.get_path_state("a") is None
        assert engine.get_path_state("b") is None

    def test_after_clear_next_value_publishes(self):
        engine = PublishPolicyEngine()
        engine.should_publish("a", SignalKDomain.NAVIGATION, 1.0, now=100.0)
        engine.clear_path_states()
        # Should publish as "first value"
        result = engine.should_publish("a", SignalKDomain.NAVIGATION, 1.0, now=101.0)
        assert result is True


# ===================================================================
# record_publish
# ===================================================================


class TestRecordPublish:
    def test_record_publish_new_path(self):
        engine = PublishPolicyEngine()
        engine.record_publish("nav.sog", 5.0, now=100.0)
        state = engine.get_path_state("nav.sog")
        assert state is not None
        assert state.last_published_value == 5.0

    def test_record_publish_existing_path(self):
        engine = PublishPolicyEngine()
        engine.should_publish("nav.sog", SignalKDomain.NAVIGATION, 5.0, now=100.0)
        engine.record_publish("nav.sog", 6.0, now=105.0)
        state = engine.get_path_state("nav.sog")
        assert state.last_published_value == 6.0
        assert state.last_published_time == 105.0


# ===================================================================
# dump_state
# ===================================================================


class TestDumpState:
    def test_dump_state_structure(self):
        engine = PublishPolicyEngine(profile=PublishProfile.BALANCED)
        engine.should_publish("a", SignalKDomain.NAVIGATION, 1.0, now=100.0)
        engine.should_publish("b", SignalKDomain.WIND, 2.0, now=100.0)

        state = engine.dump_state()
        assert state["profile"] == "balanced"
        assert "policies" in state
        assert state["tracked_paths"] == 2
        assert SignalKDomain.NAVIGATION.value in state["policies"]

    def test_dump_policy_structure(self):
        engine = PublishPolicyEngine()
        state = engine.dump_state()
        nav_policy = state["policies"][SignalKDomain.NAVIGATION.value]
        assert "min_interval" in nav_policy
        assert "max_interval" in nav_policy
        assert "deadband" in nav_policy
        assert "enabled_by_default" in nav_policy


# ===================================================================
# _exceeds_deadband edge cases
# ===================================================================


class TestExceedsDeadband:
    def test_none_old_value(self):
        result = PublishPolicyEngine._exceeds_deadband(None, 5.0, 0.5)
        assert result is True

    def test_none_new_value(self):
        result = PublishPolicyEngine._exceeds_deadband(5.0, None, 0.5)
        assert result is True

    def test_both_none(self):
        result = PublishPolicyEngine._exceeds_deadband(None, None, 0.5)
        assert result is False

    def test_numeric_within_deadband(self):
        result = PublishPolicyEngine._exceeds_deadband(5.0, 5.3, 0.5)
        assert result is False

    def test_numeric_at_deadband(self):
        result = PublishPolicyEngine._exceeds_deadband(5.0, 5.5, 0.5)
        assert result is True

    def test_numeric_beyond_deadband(self):
        result = PublishPolicyEngine._exceeds_deadband(5.0, 6.0, 0.5)
        assert result is True

    def test_zero_deadband_same_value(self):
        result = PublishPolicyEngine._exceeds_deadband(5.0, 5.0, 0.0)
        assert result is False

    def test_zero_deadband_different_value(self):
        result = PublishPolicyEngine._exceeds_deadband(5.0, 5.001, 0.0)
        assert result is True

    def test_string_values_different(self):
        result = PublishPolicyEngine._exceeds_deadband("foo", "bar", 0.5)
        assert result is True

    def test_string_values_same(self):
        result = PublishPolicyEngine._exceeds_deadband("foo", "foo", 0.5)
        assert result is False

    def test_bool_treated_as_numeric(self):
        """Python bool is subclass of int, so True=1.0, False=0.0."""
        result = PublishPolicyEngine._exceeds_deadband(True, False, 0.5)
        assert result is True  # abs(1.0 - 0.0) = 1.0 >= 0.5
