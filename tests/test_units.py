"""Conversion and arithmetic behaviour of the quantity types."""

from __future__ import annotations

import pytest

from backpacking.units import (
    Distance,
    Duration,
    Energy,
    Mass,
    Volume,
    caloric_density,
    speed_mph,
)


class TestDistance:
    def test_a_mile_is_the_statute_mile(self) -> None:
        assert Distance.miles(1.0).in_meters == pytest.approx(1609.344)

    def test_round_trips_through_every_unit(self) -> None:
        d = Distance.miles(2650.0)
        assert d.in_miles == pytest.approx(2650.0)
        assert Distance.kilometers(d.in_kilometers).in_miles == pytest.approx(2650.0)
        assert Distance.feet(d.in_feet).in_miles == pytest.approx(2650.0)
        assert Distance.meters(d.in_meters).in_miles == pytest.approx(2650.0)

    def test_feet_conversion_matches_the_survey_constant(self) -> None:
        assert Distance.feet(5280.0).in_miles == pytest.approx(1.0)

    def test_addition_and_subtraction_stay_distances(self) -> None:
        total = Distance.miles(12.0) + Distance.miles(6.5)
        assert isinstance(total, Distance)
        assert total.in_miles == pytest.approx(18.5)
        assert (total - Distance.miles(0.5)).in_miles == pytest.approx(18.0)

    def test_scaling_works_from_either_side(self) -> None:
        assert (Distance.miles(3.0) * 2).in_miles == pytest.approx(6.0)
        assert (2 * Distance.miles(3.0)).in_miles == pytest.approx(6.0)

    def test_dividing_two_distances_gives_a_ratio(self) -> None:
        ratio = Distance.miles(10.0) / Distance.miles(4.0)
        assert isinstance(ratio, float)
        assert ratio == pytest.approx(2.5)

    def test_dividing_by_a_scalar_gives_a_distance(self) -> None:
        part = Distance.miles(10.0) / 4
        assert isinstance(part, Distance)
        assert part.in_miles == pytest.approx(2.5)

    def test_ordering_and_equality(self) -> None:
        assert Distance.miles(1.0) < Distance.kilometers(2.0)
        assert Distance.miles(1.0) == Distance.feet(5280.0)
        assert max(Distance.miles(4.0), Distance.miles(9.0)).in_miles == pytest.approx(9.0)

    def test_zero_is_falsey_and_a_real_distance_is_truthy(self) -> None:
        assert not Distance.zero()
        assert Distance.feet(1.0)

    def test_negation_and_absolute_value(self) -> None:
        assert (-Distance.miles(3.0)).in_miles == pytest.approx(-3.0)
        assert abs(Distance.miles(-3.0)).in_miles == pytest.approx(3.0)

    def test_mixing_kinds_is_refused(self) -> None:
        with pytest.raises(TypeError, match="convert explicitly"):
            Distance.miles(1.0) + Mass.pounds(1.0)  # type: ignore[operator]

    def test_repr_reads_in_miles(self) -> None:
        assert repr(Distance.miles(4.25)) == "Distance(4.250 mi)"

    def test_nan_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            Distance(float("nan"))


class TestMass:
    def test_pound_and_ounce_constants(self) -> None:
        assert Mass.pounds(1.0).in_ounces == pytest.approx(16.0)
        assert Mass.ounces(16.0).in_grams == pytest.approx(453.59237)

    def test_kilogram_round_trip(self) -> None:
        m = Mass.kilograms(7.4)
        assert m.in_kilograms == pytest.approx(7.4)
        assert Mass.grams(m.in_grams).in_pounds == pytest.approx(m.in_pounds)

    def test_a_base_weight_sums(self) -> None:
        pack = Mass.ounces(31.0)
        quilt = Mass.ounces(21.5)
        shelter = Mass.ounces(18.0)
        base = pack + quilt + shelter
        assert base.in_pounds == pytest.approx(4.40625)

    def test_repr_reads_in_pounds(self) -> None:
        assert repr(Mass.pounds(9.5)) == "Mass(9.500 lb)"


class TestVolume:
    def test_bear_canister_capacity_in_litres(self) -> None:
        bv500 = Volume.cubic_inches(700.0)
        assert bv500.in_liters == pytest.approx(11.47, abs=0.01)

    def test_litre_and_millilitre_agree(self) -> None:
        assert Volume.liters(2.0).in_milliliters == pytest.approx(2000.0)

    def test_fluid_ounces_convert(self) -> None:
        assert Volume.fluid_ounces(33.814).in_liters == pytest.approx(1.0, abs=1e-4)

    def test_volumes_subtract(self) -> None:
        left = Volume.cubic_inches(700.0) - Volume.cubic_inches(180.0)
        assert left.in_cubic_inches == pytest.approx(520.0)


class TestDuration:
    def test_hours_minutes_seconds_agree(self) -> None:
        assert Duration.hours(1.5).in_minutes == pytest.approx(90.0)
        assert Duration.minutes(90.0).in_seconds == pytest.approx(5400.0)

    @pytest.mark.parametrize(
        ("hours", "expected"),
        [(0.0, "0:00"), (1.0, "1:00"), (7.25, "7:15"), (11.5, "11:30"), (0.75, "0:45")],
    )
    def test_clock_rendering(self, hours: float, expected: str) -> None:
        assert Duration.hours(hours).as_clock() == expected

    def test_clock_rounds_to_the_nearest_minute(self) -> None:
        assert Duration.seconds(89.0).as_clock() == "0:01"
        assert Duration.seconds(91.0).as_clock() == "0:02"

    def test_repr_uses_the_clock(self) -> None:
        assert repr(Duration.hours(9.5)) == "Duration(9:30)"


class TestDerivedHelpers:
    def test_speed_in_miles_per_hour(self) -> None:
        mph = speed_mph(Distance.miles(21.0), Duration.hours(7.0))
        assert mph == pytest.approx(3.0)

    def test_speed_refuses_zero_duration(self) -> None:
        with pytest.raises(ValueError, match="duration must be positive"):
            speed_mph(Distance.miles(1.0), Duration.zero())

    def test_caloric_density_of_a_typical_resupply(self) -> None:
        density = caloric_density(Energy.kilocalories(3600.0), Mass.ounces(28.0))
        assert density == pytest.approx(128.57, abs=0.01)

    def test_caloric_density_refuses_zero_mass(self) -> None:
        with pytest.raises(ValueError, match="mass must be positive"):
            caloric_density(Energy.kilocalories(100.0), Mass.zero())

    def test_energy_repr_is_whole_kilocalories(self) -> None:
        assert repr(Energy.kilocalories(3250.4)) == "Energy(3250 kcal)"
