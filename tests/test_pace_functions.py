"""The published pace models, checked against their own published figures."""

from __future__ import annotations

import pytest

from backpacking.errors import PaceModelError
from backpacking.pace.functions import (
    MAX_MODELLED_GRADE,
    grade_from,
    langmuir_correction,
    munter_time,
    munter_units,
    naismith_langmuir_time,
    naismith_time,
    tobler_speed_kmh,
    tobler_speed_mph,
    tobler_time,
)
from backpacking.units import Distance, Duration


class TestTobler:
    def test_peaks_on_a_gentle_descent(self) -> None:
        assert tobler_speed_kmh(-0.05) == pytest.approx(6.0)

    def test_the_peak_is_the_global_maximum(self) -> None:
        grades = [g / 100.0 for g in range(-50, 51)]
        assert max(grades, key=tobler_speed_kmh) == pytest.approx(-0.05)

    def test_level_ground_is_just_under_the_peak(self) -> None:
        assert tobler_speed_kmh(0.0) == pytest.approx(5.037, abs=0.001)

    def test_a_ten_percent_climb(self) -> None:
        assert tobler_speed_kmh(0.10) == pytest.approx(3.549, abs=0.001)

    def test_a_thirty_percent_climb_is_a_crawl(self) -> None:
        assert tobler_speed_kmh(0.30) < 2.0

    def test_speed_falls_away_either_side_of_the_peak(self) -> None:
        assert tobler_speed_kmh(-0.30) < tobler_speed_kmh(-0.05)
        assert tobler_speed_kmh(0.30) < tobler_speed_kmh(-0.05)

    def test_miles_per_hour_agrees_with_kilometres(self) -> None:
        assert tobler_speed_mph(0.0) == pytest.approx(
            Distance.kilometers(tobler_speed_kmh(0.0)).in_miles
        )

    def test_flat_walking_is_about_three_miles_an_hour(self) -> None:
        assert tobler_speed_mph(0.0) == pytest.approx(3.13, abs=0.01)

    def test_time_scales_with_distance(self) -> None:
        short = tobler_time(Distance.miles(1.0), 0.05)
        far = tobler_time(Distance.miles(4.0), 0.05)
        assert far.in_hours == pytest.approx(short.in_hours * 4.0)

    def test_an_unwalkable_grade_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="beyond what a walking model"):
            tobler_speed_kmh(MAX_MODELLED_GRADE + 0.1)

    def test_a_nan_grade_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="not a number"):
            tobler_speed_kmh(float("nan"))


class TestNaismith:
    def test_flat_ground_is_three_miles_an_hour(self) -> None:
        assert naismith_time(Distance.miles(9.0), Distance.zero()).in_hours == pytest.approx(3.0)

    def test_two_thousand_feet_adds_an_hour(self) -> None:
        assert naismith_time(Distance.zero(), Distance.feet(2000)).in_hours == pytest.approx(1.0)

    def test_the_two_terms_add(self) -> None:
        estimate = naismith_time(Distance.miles(6.0), Distance.feet(3000))
        assert estimate.in_hours == pytest.approx(2.0 + 1.5)

    def test_a_negative_gain_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="magnitude"):
            naismith_time(Distance.miles(1.0), Distance.feet(-100))


class TestLangmuir:
    def test_a_gentle_descent_saves_time(self) -> None:
        saved = langmuir_correction(Distance.feet(2000), -0.08)
        assert saved.in_minutes == pytest.approx(-20.0)

    def test_a_steep_descent_costs_time(self) -> None:
        cost = langmuir_correction(Distance.feet(2000), -0.30)
        assert cost.in_minutes == pytest.approx(20.0)

    def test_the_middle_band_is_a_wash(self) -> None:
        assert langmuir_correction(Distance.feet(2000), -0.17).in_minutes == pytest.approx(0.0)

    def test_climbing_gets_no_correction(self) -> None:
        assert langmuir_correction(Distance.feet(2000), 0.10).in_seconds == pytest.approx(0.0)

    def test_a_negative_loss_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="magnitude"):
            langmuir_correction(Distance.feet(-10), -0.1)


class TestNaismithLangmuir:
    def test_a_pure_climb_matches_plain_naismith(self) -> None:
        combined = naismith_langmuir_time(Distance.miles(4.0), Distance.feet(2000), Distance.zero())
        plain = naismith_time(Distance.miles(4.0), Distance.feet(2000))
        assert combined.in_hours == pytest.approx(plain.in_hours)

    def test_a_gentle_descent_comes_in_under_flat_time(self) -> None:
        combined = naismith_langmuir_time(Distance.miles(6.0), Distance.zero(), Distance.feet(1500))
        assert combined.in_hours < 2.0

    def test_a_steep_descent_comes_in_over_flat_time(self) -> None:
        combined = naismith_langmuir_time(Distance.miles(2.0), Distance.zero(), Distance.feet(3000))
        assert combined.in_hours > 2.0 / 3.0

    def test_the_result_never_goes_negative(self) -> None:
        combined = naismith_langmuir_time(Distance.miles(0.1), Distance.zero(), Distance.feet(4000))
        assert combined.in_seconds >= 0.0


class TestMunter:
    def test_units_add_horizontal_and_vertical(self) -> None:
        units = munter_units(Distance.kilometers(10.0), Distance.meters(500), Distance.zero())
        assert units == pytest.approx(15.0)

    def test_descent_counts_towards_the_units(self) -> None:
        units = munter_units(Distance.kilometers(4.0), Distance.zero(), Distance.meters(600))
        assert units == pytest.approx(10.0)

    def test_an_uphill_leg_uses_the_uphill_rate(self) -> None:
        estimate = munter_time(Distance.kilometers(10.0), Distance.meters(500), Distance.zero())
        assert estimate.in_hours == pytest.approx(15.0 / 4.0)

    def test_a_downhill_leg_uses_the_downhill_rate(self) -> None:
        estimate = munter_time(Distance.kilometers(4.0), Distance.zero(), Distance.meters(600))
        assert estimate.in_hours == pytest.approx(10.0 / 10.0)

    def test_a_flat_leg_uses_the_flat_rate(self) -> None:
        estimate = munter_time(Distance.kilometers(12.0), Distance.zero(), Distance.zero())
        assert estimate.in_hours == pytest.approx(2.0)

    def test_an_even_up_and_down_leg_uses_the_flat_rate(self) -> None:
        estimate = munter_time(Distance.kilometers(6.0), Distance.meters(300), Distance.meters(300))
        assert estimate.in_hours == pytest.approx(12.0 / 6.0)

    def test_negative_vertical_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="magnitudes"):
            munter_units(Distance.kilometers(1.0), Distance.meters(-10), Distance.zero())


class TestGradeFrom:
    def test_rise_over_run(self) -> None:
        assert grade_from(Distance.meters(1000), Distance.meters(100)) == pytest.approx(0.1)

    def test_a_descent_is_negative(self) -> None:
        assert grade_from(Distance.meters(1000), Distance.meters(-50)) == pytest.approx(-0.05)

    def test_zero_distance_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="zero distance"):
            grade_from(Distance.zero(), Distance.meters(10))


class TestTheModelsDisagree:
    """The point of keeping three: they bracket the truth rather than agree."""

    def test_naismith_and_tobler_stay_within_an_hour_on_a_steady_climb(self) -> None:
        distance = Distance.miles(6.0)
        gain = Distance.feet(3400)
        naismith = naismith_time(distance, gain).in_hours
        tobler = tobler_time(distance, grade_from(distance, gain)).in_hours
        assert abs(naismith - tobler) < 1.0

    def test_munter_is_the_conservative_one_on_a_climb(self) -> None:
        distance = Distance.miles(6.0)
        gain = Distance.feet(3400)
        munter = munter_time(distance, gain, Distance.zero()).in_hours
        naismith = naismith_time(distance, gain).in_hours
        assert munter > naismith
        assert munter == pytest.approx(5.0, abs=0.1)

    def test_on_rolling_ground_naismith_is_the_optimistic_one(self) -> None:
        distance = Distance.miles(10.0)
        gain = Distance.feet(1200)
        loss = Distance.feet(1200)
        naismith = naismith_langmuir_time(distance, gain, loss)
        munter = munter_time(distance, gain, loss)
        assert naismith.in_hours < munter.in_hours

    def test_none_of_them_returns_a_negative_duration(self) -> None:
        distance = Distance.miles(3.0)
        for gain_ft, loss_ft in [(0, 0), (1500, 0), (0, 1500), (900, 900)]:
            gain = Distance.feet(gain_ft)
            loss = Distance.feet(loss_ft)
            assert naismith_langmuir_time(distance, gain, loss) >= Duration.zero()
            assert munter_time(distance, gain, loss) >= Duration.zero()
