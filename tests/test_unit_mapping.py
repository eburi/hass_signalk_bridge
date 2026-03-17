"""Tests for unit_mapping.py — pure logic, no HA runtime needed."""

from custom_components.signalk_bridge.unit_mapping import (
    SensorMapping,
    convert_value,
    get_sensor_mapping,
    path_to_friendly_name,
    UNIT_MAPPING,
    PATH_OVERRIDES,
    _match_path_pattern,
)


# ===================================================================
# convert_value
# ===================================================================


class TestConvertValue:
    def test_none_returns_none(self):
        mapping = SensorMapping(conversion_factor=100.0)
        assert convert_value(None, mapping) is None

    def test_no_conversion(self):
        mapping = SensorMapping()
        assert convert_value(42.0, mapping) == 42.0

    def test_conversion_factor(self):
        mapping = SensorMapping(conversion_factor=100.0)
        assert convert_value(0.5, mapping) == 50.0

    def test_conversion_offset(self):
        mapping = SensorMapping(conversion_offset=-273.15)
        result = convert_value(300.0, mapping)
        assert abs(result - 26.85) < 0.01

    def test_factor_and_offset(self):
        mapping = SensorMapping(conversion_factor=2.0, conversion_offset=10.0)
        assert convert_value(5.0, mapping) == 20.0  # 5*2 + 10

    def test_integer_input(self):
        mapping = SensorMapping(conversion_factor=100.0)
        result = convert_value(1, mapping)
        assert result == 100.0
        assert isinstance(result, float)

    def test_non_numeric_passthrough(self):
        mapping = SensorMapping(conversion_factor=100.0)
        assert convert_value("hello", mapping) == "hello"

    def test_rad_to_degrees(self):
        mapping = UNIT_MAPPING["rad"]
        import math

        result = convert_value(math.pi, mapping)
        assert abs(result - 180.0) < 0.01

    def test_ratio_to_percent(self):
        mapping = UNIT_MAPPING["ratio"]
        assert convert_value(0.75, mapping) == 75.0

    def test_joule_to_wh(self):
        mapping = UNIT_MAPPING["J"]
        result = convert_value(3600.0, mapping)
        assert abs(result - 1.0) < 0.001

    def test_coulomb_to_ah(self):
        mapping = UNIT_MAPPING["C"]
        result = convert_value(3600.0, mapping)
        assert abs(result - 1.0) < 0.001


# ===================================================================
# get_sensor_mapping
# ===================================================================


class TestGetSensorMapping:
    def test_kelvin_unit(self):
        m = get_sensor_mapping("some.random.temp", "K")
        assert m.device_class == "temperature"
        assert m.native_unit == "K"

    def test_meters_per_second(self):
        m = get_sensor_mapping("navigation.someSpeed", "m/s")
        assert m.device_class == "speed"
        assert m.native_unit == "m/s"

    def test_radians(self):
        m = get_sensor_mapping("navigation.heading", "rad")
        assert m.native_unit == "°"
        assert m.conversion_factor is not None

    def test_pascal(self):
        m = get_sensor_mapping("some.pressure", "Pa")
        assert m.device_class == "pressure"

    def test_voltage(self):
        m = get_sensor_mapping("electrical.batteries.house.voltage", "V")
        assert m.device_class == "voltage"

    def test_unknown_unit_returns_default(self):
        m = get_sensor_mapping("some.path", "foobar_unit")
        assert m.device_class is None
        assert m.conversion_factor is None

    def test_no_unit_returns_default(self):
        m = get_sensor_mapping("some.path", None)
        assert m.device_class is None

    def test_exact_path_override_takes_priority(self):
        m = get_sensor_mapping("environment.wind.speedApparent", "m/s")
        assert m.device_class == "wind_speed"

    def test_wildcard_path_override(self):
        m = get_sensor_mapping(
            "electrical.batteries.house.capacity.stateOfCharge", "ratio"
        )
        assert m.device_class == "battery"
        assert m.native_unit == "%"

    def test_humidity_path_override(self):
        m = get_sensor_mapping("environment.outside.relativeHumidity", "ratio")
        assert m.device_class == "humidity"

    def test_depth_path_override(self):
        m = get_sensor_mapping("environment.depth.belowKeel", "m")
        assert m.device_class == "distance"
        assert m.icon == "mdi:waves-arrow-up"

    def test_atmospheric_pressure_override(self):
        m = get_sensor_mapping("environment.outside.pressure", "Pa")
        assert m.device_class == "atmospheric_pressure"

    def test_sog_override(self):
        m = get_sensor_mapping("navigation.speedOverGround", "m/s")
        assert m.icon == "mdi:speedometer"


# ===================================================================
# _match_path_pattern
# ===================================================================


class TestMatchPathPattern:
    def test_exact_match(self):
        assert _match_path_pattern("a.b.c", "a.b.c") is True

    def test_no_match(self):
        assert _match_path_pattern("a.b.c", "a.b.d") is False

    def test_wildcard(self):
        assert _match_path_pattern("a.x.c", "a.*.c") is True

    def test_wildcard_no_match_length(self):
        assert _match_path_pattern("a.b", "a.*.c") is False

    def test_multiple_wildcards(self):
        assert _match_path_pattern("a.x.y.c", "a.*.*.c") is True

    def test_battery_soc_pattern(self):
        assert (
            _match_path_pattern(
                "electrical.batteries.house.capacity.stateOfCharge",
                "electrical.batteries.*.capacity.stateOfCharge",
            )
            is True
        )

    def test_battery_soc_different_id(self):
        assert (
            _match_path_pattern(
                "electrical.batteries.starter.capacity.stateOfCharge",
                "electrical.batteries.*.capacity.stateOfCharge",
            )
            is True
        )


# ===================================================================
# path_to_friendly_name
# ===================================================================


class TestPathToFriendlyName:
    def test_speed_over_ground(self):
        name = path_to_friendly_name("navigation.speedOverGround")
        assert name == "Speed Over Ground"

    def test_wind_speed(self):
        name = path_to_friendly_name("environment.wind.speedApparent")
        assert "Wind" in name
        assert "Speed" in name

    def test_strips_common_prefix(self):
        name = path_to_friendly_name("navigation.heading")
        # should NOT start with "Navigation"
        assert not name.startswith("Navigation")

    def test_propulsion(self):
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

    def test_camelCase_splitting(self):
        name = path_to_friendly_name("navigation.courseOverGroundTrue")
        assert "Course" in name
        assert "Over" in name
        assert "Ground" in name
        assert "True" in name


# ===================================================================
# UNIT_MAPPING completeness
# ===================================================================


class TestUnitMappingCompleteness:
    """Ensure all unit mappings are well-formed."""

    def test_all_unit_mappings_are_sensor_mappings(self):
        for unit, mapping in UNIT_MAPPING.items():
            assert isinstance(mapping, SensorMapping), f"{unit} is not SensorMapping"

    def test_all_path_overrides_are_sensor_mappings(self):
        for path, mapping in PATH_OVERRIDES.items():
            assert isinstance(mapping, SensorMapping), f"{path} is not SensorMapping"

    def test_ratio_has_percent_conversion(self):
        m = UNIT_MAPPING["ratio"]
        assert m.conversion_factor == 100.0
        assert m.native_unit == "%"

    def test_rad_conversion_approximately_correct(self):
        import math

        m = UNIT_MAPPING["rad"]
        expected = 180.0 / math.pi
        assert abs(m.conversion_factor - expected) < 0.0001
