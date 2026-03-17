"""Tests for classifier.py — 4-layer SignalK path classification."""

from custom_components.signalk_bridge.classifier import (
    EXACT_MATCHES,
    PREFIX_RULES,
    ClassificationResult,
    canonicalize_path,
    classify_path,
    is_ignored_path,
    path_to_friendly_name,
)
from custom_components.signalk_bridge.const import SignalKDomain


# ===================================================================
# canonicalize_path
# ===================================================================


class TestCanonicalizePath:
    def test_vessels_self_prefix(self):
        assert (
            canonicalize_path("vessels.self.navigation.position")
            == "navigation.position"
        )

    def test_vessels_urn_imo_prefix(self):
        assert (
            canonicalize_path(
                "vessels.urn:mrn:imo:mmsi:123456789.navigation.speedOverGround"
            )
            == "navigation.speedOverGround"
        )

    def test_vessels_urn_signalk_prefix(self):
        assert (
            canonicalize_path(
                "vessels.urn:mrn:signalk:uuid:abc123.environment.depth.belowKeel"
            )
            == "environment.depth.belowKeel"
        )

    def test_no_prefix(self):
        assert canonicalize_path("navigation.position") == "navigation.position"

    def test_empty_string(self):
        assert canonicalize_path("") == ""

    def test_single_segment(self):
        assert canonicalize_path("name") == "name"

    def test_vessels_self_only(self):
        """After stripping 'vessels.self.', nothing is left — but this is an edge case."""
        result = canonicalize_path("vessels.self.")
        assert result == ""


# ===================================================================
# is_ignored_path
# ===================================================================


class TestIsIgnoredPath:
    def test_values_branch(self):
        assert is_ignored_path("navigation.speedOverGround.values.nmea2000") is True

    def test_meta_branch(self):
        assert is_ignored_path("navigation.speedOverGround.meta.units") is True

    def test_values_leaf(self):
        assert is_ignored_path("navigation.speedOverGround.values") is True

    def test_meta_leaf(self):
        assert is_ignored_path("navigation.speedOverGround.meta") is True

    def test_normal_path_not_ignored(self):
        assert is_ignored_path("navigation.speedOverGround") is False

    def test_empty_path(self):
        assert is_ignored_path("") is False

    def test_path_with_meta_in_name(self):
        """'meta' in a segment name (not as branch) should NOT be ignored."""
        assert is_ignored_path("navigation.metadata") is False

    def test_path_with_values_in_name(self):
        """'values' in a segment name that also matches pattern IS ignored."""
        # ".values." as a whole segment match — this matches the regex
        assert is_ignored_path("foo.values.bar") is True


# ===================================================================
# classify_path — Layer 1: Exact matches
# ===================================================================


class TestClassifyExactMatch:
    def test_navigation_position(self):
        result = classify_path("navigation.position")
        assert result.domain == SignalKDomain.POSITION
        assert result.platform == "device_tracker"
        assert result.enabled_by_default is True

    def test_navigation_sog(self):
        result = classify_path("navigation.speedOverGround")
        assert result.domain == SignalKDomain.NAVIGATION
        assert result.enabled_by_default is True
        assert result.friendly_name == "SOG"

    def test_navigation_stw(self):
        result = classify_path("navigation.speedThroughWater")
        assert result.domain == SignalKDomain.NAVIGATION

    def test_wind_apparent_angle(self):
        result = classify_path("environment.wind.angleApparent")
        assert result.domain == SignalKDomain.WIND
        assert result.friendly_name == "Apparent Wind Angle"

    def test_wind_speed_true(self):
        result = classify_path("environment.wind.speedTrue")
        assert result.domain == SignalKDomain.WIND

    def test_depth_below_keel(self):
        result = classify_path("environment.depth.belowKeel")
        assert result.domain == SignalKDomain.ENVIRONMENT
        assert result.icon == "mdi:waves-arrow-up"

    def test_water_temperature(self):
        result = classify_path("environment.water.temperature")
        assert result.domain == SignalKDomain.ENVIRONMENT
        assert result.friendly_name == "Water Temperature"

    def test_heading_magnetic(self):
        result = classify_path("navigation.headingMagnetic")
        assert result.domain == SignalKDomain.NAVIGATION
        assert result.friendly_name == "Heading Magnetic"

    def test_cog_true(self):
        result = classify_path("navigation.courseOverGroundTrue")
        assert result.domain == SignalKDomain.NAVIGATION
        assert result.friendly_name == "COG True"

    def test_rudder_angle(self):
        result = classify_path("steering.rudderAngle")
        assert result.domain == SignalKDomain.STATUS_METADATA

    def test_autopilot_state(self):
        result = classify_path("steering.autopilot.state")
        assert result.domain == SignalKDomain.STATUS_METADATA
        assert result.enabled_by_default is True

    def test_vessel_name(self):
        result = classify_path("name")
        assert result.domain == SignalKDomain.STATUS_METADATA
        assert result.enabled_by_default is False

    def test_mmsi(self):
        result = classify_path("mmsi")
        assert result.domain == SignalKDomain.STATUS_METADATA

    def test_navigation_datetime(self):
        result = classify_path("navigation.datetime")
        assert result.domain == SignalKDomain.TIME
        assert result.enabled_by_default is False

    def test_all_exact_matches_are_classification_results(self):
        """Sanity check: every exact match value is a ClassificationResult."""
        for path, result in EXACT_MATCHES.items():
            assert isinstance(result, ClassificationResult), f"{path}"
            assert isinstance(result.domain, SignalKDomain), f"{path}"


# ===================================================================
# classify_path — Layer 2: Prefix rules
# ===================================================================


class TestClassifyPrefixRules:
    def test_notifications_ais_ignored(self):
        result = classify_path("notifications.ais.someTarget")
        assert result.domain == SignalKDomain.UNSUPPORTED_IGNORE

    def test_notifications_alarm(self):
        result = classify_path("notifications.engine.overTemperature")
        assert result.domain == SignalKDomain.ALARM

    def test_gnss_position(self):
        result = classify_path("navigation.gnss.satellites")
        assert result.domain == SignalKDomain.POSITION
        assert result.enabled_by_default is False

    def test_tanks_prefix(self):
        result = classify_path("tanks.fuel.0.currentLevel")
        assert result.domain == SignalKDomain.TANK

    def test_tank_prefix(self):
        result = classify_path("tank.freshWater.1.currentLevel")
        assert result.domain == SignalKDomain.TANK

    def test_electrical_batteries(self):
        result = classify_path("electrical.batteries.house.voltage")
        assert result.domain == SignalKDomain.BATTERY_DC

    def test_electrical_solar(self):
        result = classify_path("electrical.solar.panel1.current")
        assert result.domain == SignalKDomain.BATTERY_DC

    def test_electrical_inverters(self):
        result = classify_path("electrical.inverters.main.power")
        assert result.domain == SignalKDomain.INVERTER_AC

    def test_electrical_ac(self):
        result = classify_path("electrical.ac.shore.voltage")
        assert result.domain == SignalKDomain.INVERTER_AC

    def test_electrical_shore_power(self):
        result = classify_path("electrical.shorePower.status")
        assert result.domain == SignalKDomain.INVERTER_AC

    def test_propulsion(self):
        result = classify_path("propulsion.port.revolutions")
        assert result.domain == SignalKDomain.ENGINE_PROPULSION

    def test_bilge(self):
        result = classify_path("bilge.forward.level")
        assert result.domain == SignalKDomain.BILGE_PUMP

    def test_watermaker(self):
        result = classify_path("watermaker.production")
        assert result.domain == SignalKDomain.WATERMAKER

    def test_communication(self):
        result = classify_path("communication.dsc.data")
        assert result.domain == SignalKDomain.COMMUNICATIONS

    def test_design(self):
        result = classify_path("design.length.overall")
        assert result.domain == SignalKDomain.STATUS_METADATA

    def test_environment_wind_prefix(self):
        """Prefix rules should catch wind paths not in exact matches."""
        result = classify_path("environment.wind.gustSpeed")
        assert result.domain == SignalKDomain.WIND

    def test_environment_sunlight(self):
        result = classify_path("environment.sunlight.times.sunrise")
        assert result.domain == SignalKDomain.TIME

    def test_environment_inside_prefix(self):
        """A path under environment.inside. not in exact matches."""
        result = classify_path("environment.inside.salon.temperature")
        assert result.domain == SignalKDomain.ENVIRONMENT

    def test_steering_autopilot_generic(self):
        result = classify_path("steering.autopilot.mode")
        assert result.domain == SignalKDomain.STATUS_METADATA

    def test_noforeignland(self):
        result = classify_path("noforeignland.position")
        assert result.domain == SignalKDomain.COMMUNICATIONS


# ===================================================================
# classify_path — Layer 3: Heuristics
# ===================================================================


class TestClassifyHeuristics:
    def test_suffix_estimated_time_of_arrival(self):
        """Suffix heuristic only fires for paths NOT caught by prefix rules.
        Use a path with no matching prefix/segment."""
        result = classify_path("custom.vendor.estimatedTimeOfArrival")
        assert result.domain == SignalKDomain.TIME
        assert result.enabled_by_default is False

    def test_suffix_time_to_go(self):
        result = classify_path("custom.vendor.route.timeToGo")
        assert result.domain == SignalKDomain.TIME

    def test_suffix_start_time(self):
        result = classify_path("custom.vendor.process.startTime")
        assert result.domain == SignalKDomain.TIME

    def test_prefix_takes_priority_over_suffix(self):
        """Prefix rules (Layer 2) beat suffix heuristics (Layer 3).
        navigation.* matches prefix before .estimatedTimeOfArrival suffix."""
        result = classify_path(
            "navigation.courseRhumbline.nextPoint.estimatedTimeOfArrival"
        )
        assert result.domain == SignalKDomain.NAVIGATION

        result2 = classify_path("propulsion.port.oilPressure.startTime")
        assert result2.domain == SignalKDomain.ENGINE_PROPULSION

    def test_segment_navigation_fallback(self):
        """A navigation.* path not caught by exact or prefix → segment heuristic."""
        result = classify_path("navigation.someObscurePath")
        assert result.domain == SignalKDomain.NAVIGATION
        assert result.enabled_by_default is False

    def test_segment_environment_fallback(self):
        result = classify_path("environment.someUnknownSensor")
        assert result.domain == SignalKDomain.ENVIRONMENT

    def test_segment_electrical_fallback(self):
        result = classify_path("electrical.unknownDevice.value")
        # electrical.unknownDevice.value doesn't match any prefix rule
        # but the first segment "electrical" maps to BATTERY_DC
        # Wait — actually "electrical.unknownDevice." would not match any prefix.
        # The segment heuristic maps "electrical" → BATTERY_DC
        assert result.domain == SignalKDomain.BATTERY_DC

    def test_segment_sensors_fallback(self):
        result = classify_path("sensors.customSensor.value")
        assert result.domain == SignalKDomain.STATUS_METADATA

    def test_segment_performance_fallback(self):
        """Performance paths not caught by prefix rules."""
        result = classify_path("performance.someMetric")
        assert result.domain == SignalKDomain.NAVIGATION


# ===================================================================
# classify_path — Layer 4: Fallback
# ===================================================================


class TestClassifyFallback:
    def test_completely_unknown_path(self):
        result = classify_path("completely.unknown.path")
        assert result.domain == SignalKDomain.UNSUPPORTED_IGNORE

    def test_single_unknown_segment(self):
        result = classify_path("foobar")
        assert result.domain == SignalKDomain.UNSUPPORTED_IGNORE

    def test_empty_path(self):
        result = classify_path("")
        assert result.domain == SignalKDomain.UNSUPPORTED_IGNORE


# ===================================================================
# path_to_friendly_name
# ===================================================================


class TestPathToFriendlyName:
    def test_speed_over_ground(self):
        name = path_to_friendly_name("navigation.speedOverGround")
        assert name == "Speed Over Ground"

    def test_wind_speed_apparent(self):
        name = path_to_friendly_name("environment.wind.speedApparent")
        assert "Wind" in name
        assert "Speed" in name

    def test_strips_navigation_prefix(self):
        name = path_to_friendly_name("navigation.headingMagnetic")
        assert not name.startswith("Navigation")

    def test_strips_environment_prefix(self):
        name = path_to_friendly_name("environment.depth.belowKeel")
        assert not name.startswith("Environment")

    def test_propulsion_path(self):
        name = path_to_friendly_name("propulsion.port.revolutions")
        assert "Port" in name
        assert "Revolutions" in name

    def test_single_segment(self):
        name = path_to_friendly_name("something")
        assert name == "Something"

    def test_deep_path(self):
        name = path_to_friendly_name("environment.inside.salon.temperature")
        assert "Inside" in name
        assert "Salon" in name
        assert "Temperature" in name

    def test_camel_case_splitting(self):
        name = path_to_friendly_name("navigation.courseOverGroundTrue")
        assert "Course" in name
        assert "Over" in name
        assert "Ground" in name
        assert "True" in name

    def test_empty_path(self):
        name = path_to_friendly_name("")
        assert name == ""

    def test_electrical_batteries_path(self):
        name = path_to_friendly_name("electrical.batteries.house.voltage")
        assert "Batteries" in name
        assert "House" in name
        assert "Voltage" in name


# ===================================================================
# Classification caching integrity
# ===================================================================


class TestClassificationIntegrity:
    def test_same_path_gives_same_result(self):
        """Verify deterministic classification."""
        r1 = classify_path("navigation.speedOverGround")
        r2 = classify_path("navigation.speedOverGround")
        assert r1 == r2
        assert r1.domain == r2.domain
        assert r1.platform == r2.platform

    def test_exact_match_takes_priority_over_prefix(self):
        """navigation.headingMagnetic should hit exact match, not prefix."""
        result = classify_path("navigation.headingMagnetic")
        # Exact match has friendly_name set
        assert result.friendly_name == "Heading Magnetic"

    def test_prefix_rules_order_matters(self):
        """notifications.ais.* should hit the ignore rule before the alarm catch-all."""
        result = classify_path("notifications.ais.target123")
        assert result.domain == SignalKDomain.UNSUPPORTED_IGNORE

        result2 = classify_path("notifications.engine.overtemp")
        assert result2.domain == SignalKDomain.ALARM

    def test_all_domains_represented_in_exact_or_prefix(self):
        """Every non-UNSUPPORTED domain should be reachable."""
        reachable_domains = set()

        for result in EXACT_MATCHES.values():
            reachable_domains.add(result.domain)

        for rule in PREFIX_RULES:
            reachable_domains.add(rule.result.domain)

        for domain in SignalKDomain:
            if domain != SignalKDomain.UNSUPPORTED_IGNORE:
                assert domain in reachable_domains, f"Domain {domain} not reachable"
