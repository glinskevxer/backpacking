"""Pack weight penalties and the metabolic cost of carrying them."""

from __future__ import annotations

import pytest

from backpacking.errors import PaceModelError
from backpacking.pace.load import (
    TERRAIN_COEFFICIENT,
    altitude_factor,
    combined_factor,
    energy_cost,
    load_factor,
    pandolf_watts,
    surface_factor,
)
from backpacking.pace.models import HikerProfile
from backpacking.trail.models import Surface
from backpacking.units import Mass


class TestLoadFactor:
    def test_the_reference_load_is_neutral(self, hiker: HikerProfile) -> None:
        assert load_factor(hiker, Mass.pounds(26.0)) == pytest.approx(1.0)

    def test_a_heavier_pack_slows(self, hiker: HikerProfile) -> None:
        assert load_factor(hiker, Mass.pounds(36.0)) == pytest.approx(1.0 - 0.11)

    def test_a_lighter_pack_speeds_up(self, hiker: HikerProfile) -> None:
        assert load_factor(hiker, Mass.pounds(18.0)) > 1.0

    def test_an_absurd_load_is_floored(self, hiker: HikerProfile) -> None:
        assert load_factor(hiker, Mass.pounds(300.0)) == pytest.approx(0.25)

    def test_the_penalty_is_a_hiker_preference(self) -> None:
        stoic = HikerProfile(reference_load=Mass.pounds(25.0), load_penalty_per_pound=0.004)
        fussy = HikerProfile(reference_load=Mass.pounds(25.0), load_penalty_per_pound=0.02)
        assert load_factor(stoic, Mass.pounds(40.0)) > load_factor(fussy, Mass.pounds(40.0))


class TestAltitudeFactor:
    def test_below_the_threshold_is_neutral(self, hiker: HikerProfile) -> None:
        assert altitude_factor(hiker, 5000.0) == pytest.approx(1.0)
        assert altitude_factor(hiker, 8000.0) == pytest.approx(1.0)

    def test_a_thousand_feet_above_costs_the_stated_penalty(self, hiker: HikerProfile) -> None:
        assert altitude_factor(hiker, 9000.0) == pytest.approx(0.94)

    def test_the_penalty_accumulates(self, hiker: HikerProfile) -> None:
        assert altitude_factor(hiker, 12000.0) == pytest.approx(1.0 - 0.24)

    def test_it_is_floored(self, hiker: HikerProfile) -> None:
        assert altitude_factor(hiker, 29000.0) == pytest.approx(0.4)


class TestSurfaceFactor:
    def test_matches_the_surface_enum(self) -> None:
        for surface in Surface:
            assert surface_factor(surface) == surface.pace_factor

    def test_every_surface_has_a_terrain_coefficient(self) -> None:
        assert set(TERRAIN_COEFFICIENT) == set(Surface)

    def test_road_is_the_reference_terrain(self) -> None:
        assert TERRAIN_COEFFICIENT[Surface.ROAD] == pytest.approx(1.0)

    def test_sand_is_the_most_expensive(self) -> None:
        assert max(TERRAIN_COEFFICIENT.values()) == TERRAIN_COEFFICIENT[Surface.SAND]


class TestCombinedFactor:
    def test_it_is_the_product_of_the_three(self, hiker: HikerProfile) -> None:
        carried = Mass.pounds(32.0)
        expected = (
            load_factor(hiker, carried)
            * surface_factor(Surface.TALUS)
            * altitude_factor(hiker, 10500.0)
        )
        assert combined_factor(hiker, carried, Surface.TALUS, 10500.0) == pytest.approx(expected)

    def test_neutral_conditions_give_one(self, hiker: HikerProfile) -> None:
        assert combined_factor(hiker, Mass.pounds(26.0), Surface.TREAD, 6000.0) == pytest.approx(1.0)


class TestPandolf:
    BODY = Mass.kilograms(70.0)

    def test_standing_load_free_walking_is_plausible(self) -> None:
        watts = pandolf_watts(self.BODY, Mass.zero(), 1.34, 0.0)
        assert 250.0 < watts < 400.0

    def test_carrying_a_pack_costs_more(self) -> None:
        bare = pandolf_watts(self.BODY, Mass.zero(), 1.2, 0.0)
        loaded = pandolf_watts(self.BODY, Mass.kilograms(15.0), 1.2, 0.0)
        assert loaded > bare

    def test_climbing_costs_more_than_the_flat(self) -> None:
        flat = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.0, 0.0)
        uphill = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.0, 10.0)
        assert uphill > flat

    def test_walking_faster_costs_more(self) -> None:
        slow = pandolf_watts(self.BODY, Mass.kilograms(12.0), 0.8, 2.0)
        quick = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.6, 2.0)
        assert quick > slow

    def test_rough_terrain_costs_more(self) -> None:
        tread = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.0, 3.0, Surface.TREAD)
        sand = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.0, 3.0, Surface.SAND)
        assert sand > tread

    def test_the_descent_correction_pulls_the_cost_down(self) -> None:
        level = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.2, 0.0)
        downhill = pandolf_watts(self.BODY, Mass.kilograms(12.0), 1.2, -12.0)
        assert downhill < level

    def test_the_result_never_falls_below_resting(self) -> None:
        floor = 1.5 * self.BODY.in_kilograms
        assert pandolf_watts(self.BODY, Mass.zero(), 0.5, -40.0) >= floor

    def test_a_zero_body_mass_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="body mass must be positive"):
            pandolf_watts(Mass.zero(), Mass.kilograms(10.0), 1.2, 0.0)

    def test_a_negative_load_is_refused(self) -> None:
        with pytest.raises(PaceModelError, match="must not be negative"):
            pandolf_watts(self.BODY, Mass.kilograms(-1.0), 1.2, 0.0)

    def test_standing_still_is_outside_the_model(self) -> None:
        with pytest.raises(PaceModelError, match="below what the metabolic model"):
            pandolf_watts(self.BODY, Mass.kilograms(10.0), 0.0, 0.0)


class TestEnergyCost:
    BODY = Mass.kilograms(70.0)

    def test_a_full_day_burns_a_believable_number_of_calories(self) -> None:
        burned = energy_cost(self.BODY, Mass.kilograms(13.0), 1.1, 3.0, hours=8.0)
        assert 2200.0 < burned.in_kilocalories < 4500.0

    def test_cost_scales_with_hours(self) -> None:
        short = energy_cost(self.BODY, Mass.kilograms(13.0), 1.1, 3.0, hours=2.0)
        long = energy_cost(self.BODY, Mass.kilograms(13.0), 1.1, 3.0, hours=6.0)
        assert long.in_kilocalories == pytest.approx(short.in_kilocalories * 3.0)

    def test_zero_hours_costs_nothing(self) -> None:
        assert energy_cost(self.BODY, Mass.kilograms(13.0), 1.1, 3.0, hours=0.0).in_kilocalories == 0.0

    def test_negative_hours_are_refused(self) -> None:
        with pytest.raises(PaceModelError, match="hours must not be negative"):
            energy_cost(self.BODY, Mass.kilograms(13.0), 1.1, 3.0, hours=-1.0)
