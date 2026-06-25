"""Dry stretch detection and sizing the carry across one."""

from __future__ import annotations

import pytest

from backpacking.errors import WaterCarryError
from backpacking.pace.estimator import PaceEstimator
from backpacking.trail.corridor import Corridor
from backpacking.units import Volume
from backpacking.water.carry import (
    CAMP_WATER_LITERS,
    DryStretch,
    consumption_rate,
    find_dry_stretches,
    furthest_reachable,
    infeasible_carries,
    plan_carry,
    water_needed,
)
from backpacking.water.sources import WaterTable


class TestFindDryStretches:
    def test_june_leaves_the_mid_trail_gap_and_the_run_out(
        self, corridor: Corridor, water: WaterTable
    ) -> None:
        stretches = find_dry_stretches(corridor, water, month=6)
        assert [round(s.length.in_miles, 1) for s in stretches] == [22.1, 9.0]

    def test_the_long_gap_is_bounded_by_real_sources(
        self, corridor: Corridor, water: WaterTable
    ) -> None:
        gap = find_dry_stretches(corridor, water, month=6)[0]
        assert gap.start_source is not None
        assert gap.start_source.id == "rubicon-spring"
        assert gap.end_source is not None
        assert gap.end_source.id == "five-lakes-creek"
        assert not gap.is_open_ended

    def test_august_opens_more_gaps(self, corridor: Corridor, water: WaterTable) -> None:
        june = find_dry_stretches(corridor, water, month=6)
        august = find_dry_stretches(corridor, water, month=8)
        assert len(august) > len(june)

    def test_the_worst_august_gap_is_long_enough_to_matter(
        self, corridor: Corridor, water: WaterTable
    ) -> None:
        worst = max(find_dry_stretches(corridor, water, month=8), key=lambda s: s.length.in_miles)
        assert worst.length.in_miles > 25.0

    def test_a_lower_minimum_finds_more(self, corridor: Corridor, water: WaterTable) -> None:
        coarse = find_dry_stretches(corridor, water, month=6, min_length_miles=8.0)
        fine = find_dry_stretches(corridor, water, month=6, min_length_miles=4.0)
        assert len(fine) > len(coarse)

    def test_a_gap_running_off_the_end_is_open_ended(
        self, corridor: Corridor, water: WaterTable
    ) -> None:
        stretches = find_dry_stretches(corridor, water, month=6, min_length_miles=2.0)
        assert stretches[0].start_source is None
        assert stretches[0].is_open_ended
        assert stretches[-1].end_source is None

    def test_a_non_positive_minimum_is_refused(self, corridor: Corridor, water: WaterTable) -> None:
        with pytest.raises(WaterCarryError, match="must be positive"):
            find_dry_stretches(corridor, water, month=6, min_length_miles=0.0)

    def test_repr(self) -> None:
        stretch = DryStretch(23.8, 40.1, None, None)
        assert repr(stretch) == "DryStretch(23.8-40.1 mi, 16.3 mi)"


class TestConsumptionRate:
    def test_a_mild_flat_hour(self) -> None:
        assert consumption_rate(15.0) == pytest.approx(0.45)

    def test_cool_weather_does_not_go_below_the_base(self) -> None:
        assert consumption_rate(2.0) == pytest.approx(0.45)

    def test_heat_raises_it(self) -> None:
        assert consumption_rate(35.0) == pytest.approx(0.45 * 1.7)

    def test_climbing_raises_it(self) -> None:
        assert consumption_rate(15.0, gain_per_hour_ft=1000.0) == pytest.approx(0.65)

    def test_descending_adds_nothing(self) -> None:
        assert consumption_rate(15.0, gain_per_hour_ft=-1000.0) == pytest.approx(0.45)

    def test_an_implausible_temperature_is_refused(self) -> None:
        with pytest.raises(WaterCarryError, match="outside any plausible range"):
            consumption_rate(120.0)


class TestWaterNeeded:
    def test_a_short_cool_stretch_needs_little(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        needed = water_needed(corridor, estimator, 0.0, 5.1, temperature_c=12.0)
        assert 1.0 < needed.in_liters < 2.5

    def test_heat_raises_the_requirement(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        cool = water_needed(corridor, estimator, 23.8, 40.1, temperature_c=14.0)
        hot = water_needed(corridor, estimator, 23.8, 40.1, temperature_c=34.0)
        assert hot > cool

    def test_a_longer_stretch_needs_more(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        short = water_needed(corridor, estimator, 23.8, 30.0)
        long = water_needed(corridor, estimator, 23.8, 40.1)
        assert long > short

    def test_camping_en_route_adds_the_camp_allowance(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        dry = water_needed(corridor, estimator, 23.8, 40.1)
        with_camp = water_needed(corridor, estimator, 23.8, 40.1, camping_en_route=True)
        assert with_camp.in_liters == pytest.approx(dry.in_liters + CAMP_WATER_LITERS)

    def test_the_reserve_is_included(self, corridor: Corridor, estimator: PaceEstimator) -> None:
        none = water_needed(corridor, estimator, 10.0, 15.0, reserve_liters=0.0)
        held = water_needed(corridor, estimator, 10.0, 15.0, reserve_liters=1.0)
        assert held.in_liters == pytest.approx(none.in_liters + 1.0)

    def test_a_zero_length_stretch_needs_only_the_reserve(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        needed = water_needed(corridor, estimator, 10.0, 10.0, reserve_liters=0.4)
        assert needed.in_liters == pytest.approx(0.4)

    def test_a_reversed_stretch_is_refused(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        with pytest.raises(WaterCarryError, match="must advance"):
            water_needed(corridor, estimator, 20.0, 10.0)

    def test_a_negative_reserve_is_refused(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        with pytest.raises(WaterCarryError, match="must not be negative"):
            water_needed(corridor, estimator, 10.0, 15.0, reserve_liters=-1.0)


class TestPlanCarry:
    def test_a_big_bladder_covers_the_june_gap_in_mild_weather(
        self, corridor: Corridor, estimator: PaceEstimator, water: WaterTable
    ) -> None:
        gap = find_dry_stretches(corridor, water, month=6)[0]
        plan = plan_carry(corridor, estimator, gap, Volume.liters(8.0), temperature_c=16.0)
        assert plan.is_feasible
        assert plan.headroom.in_liters > 0.0

    def test_the_same_gap_in_heat_overruns_the_bottles(
        self, corridor: Corridor, estimator: PaceEstimator, water: WaterTable
    ) -> None:
        gap = find_dry_stretches(corridor, water, month=6)[0]
        plan = plan_carry(corridor, estimator, gap, Volume.liters(2.0), temperature_c=36.0)
        assert not plan.is_feasible
        assert plan.headroom.in_liters < 0.0

    def test_the_plan_reports_the_moving_time(
        self, corridor: Corridor, estimator: PaceEstimator, water: WaterTable
    ) -> None:
        gap = find_dry_stretches(corridor, water, month=6)[0]
        plan = plan_carry(corridor, estimator, gap, Volume.liters(4.0))
        assert plan.moving_time.in_hours > 4.0

    def test_repr_says_whether_it_fits(
        self, corridor: Corridor, estimator: PaceEstimator, water: WaterTable
    ) -> None:
        gap = find_dry_stretches(corridor, water, month=6)[0]
        assert repr(plan_carry(corridor, estimator, gap, Volume.liters(10.0))).endswith("ok)")
        assert repr(plan_carry(corridor, estimator, gap, Volume.liters(0.5))).endswith("short)")

    def test_infeasible_carries_come_back_worst_first(
        self, corridor: Corridor, estimator: PaceEstimator, water: WaterTable
    ) -> None:
        gaps = find_dry_stretches(corridor, water, month=8)
        plans = [
            plan_carry(corridor, estimator, gap, Volume.liters(2.0), temperature_c=32.0)
            for gap in gaps
        ]
        short = infeasible_carries(plans)
        assert short
        assert short[0].headroom <= short[-1].headroom

    def test_a_generous_capacity_leaves_nothing_infeasible(
        self, corridor: Corridor, estimator: PaceEstimator, water: WaterTable
    ) -> None:
        gaps = find_dry_stretches(corridor, water, month=6)
        plans = [plan_carry(corridor, estimator, gap, Volume.liters(20.0)) for gap in gaps]
        assert infeasible_carries(plans) == []


class TestFurthestReachable:
    def test_a_bigger_capacity_reaches_further(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        small = furthest_reachable(corridor, estimator, 0.0, Volume.liters(1.5))
        large = furthest_reachable(corridor, estimator, 0.0, Volume.liters(4.0))
        assert large > small

    def test_the_water_needed_at_the_reached_mile_matches_the_capacity(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        capacity = Volume.liters(3.0)
        reached = furthest_reachable(corridor, estimator, 0.0, capacity)
        needed = water_needed(corridor, estimator, 0.0, reached)
        assert needed.in_liters == pytest.approx(3.0, abs=0.1)

    def test_a_huge_capacity_reaches_the_terminus(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        reached = furthest_reachable(corridor, estimator, 0.0, Volume.liters(200.0))
        assert reached == pytest.approx(corridor.end_mile)

    def test_heat_pulls_the_reach_in(self, corridor: Corridor, estimator: PaceEstimator) -> None:
        mild = furthest_reachable(corridor, estimator, 0.0, Volume.liters(3.0), temperature_c=14.0)
        hot = furthest_reachable(corridor, estimator, 0.0, Volume.liters(3.0), temperature_c=36.0)
        assert hot < mild
