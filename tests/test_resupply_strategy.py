"""Choosing stops, and why the greedy answer is the wrong one."""

from __future__ import annotations

import pytest

from backpacking.errors import ResupplyInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.resupply.strategy import (
    carry_between,
    carry_cost_hours,
    plan_resupply,
    stop_cost_hours,
    town_time,
)
from backpacking.resupply.towns import ResupplyPoint, ServiceLevel, TownIndex
from backpacking.units import Distance, Energy

BURN = Energy.kilocalories(2900.0)


class TestCarryBetween:
    def test_days_come_from_the_daily_mileage(self) -> None:
        carry = carry_between(0.0, 36.0, daily_miles=18.0, burned_per_day=BURN)
        assert carry.days == pytest.approx(2.0)
        assert carry.miles == pytest.approx(36.0)

    def test_a_short_hop_still_costs_half_a_day_of_food(self) -> None:
        carry = carry_between(0.0, 2.0, daily_miles=18.0, burned_per_day=BURN)
        assert carry.days == pytest.approx(0.5)

    def test_food_weight_scales_with_the_days(self) -> None:
        short = carry_between(0.0, 18.0, 18.0, BURN)
        long = carry_between(0.0, 90.0, 18.0, BURN)
        assert long.food_mass.in_pounds == pytest.approx(short.food_mass.in_pounds * 5.0)

    def test_a_denser_bag_weighs_less(self) -> None:
        poor = carry_between(0.0, 90.0, 18.0, BURN, density_kcal_per_oz=100.0)
        rich = carry_between(0.0, 90.0, 18.0, BURN, density_kcal_per_oz=150.0)
        assert rich.food_mass < poor.food_mass

    def test_a_backwards_carry_is_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="must advance"):
            carry_between(40.0, 10.0, 18.0, BURN)

    def test_a_zero_daily_mileage_is_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="must be positive"):
            carry_between(0.0, 40.0, 0.0, BURN)

    def test_repr(self) -> None:
        carry = carry_between(0.0, 36.0, 18.0, BURN)
        assert repr(carry).startswith("Carry(0.0-36.0 mi, 2.0 days,")


class TestCosts:
    def test_a_longer_carry_costs_more(self, hiker: HikerProfile) -> None:
        short = carry_cost_hours(carry_between(0.0, 36.0, 18.0, BURN), hiker)
        long = carry_cost_hours(carry_between(0.0, 126.0, 18.0, BURN), hiker)
        assert long > short

    def test_the_cost_is_quadratic_in_carry_length(self, hiker: HikerProfile) -> None:
        """Twice the days is more than twice the cost: heavier for longer."""
        single = carry_cost_hours(carry_between(0.0, 54.0, 18.0, BURN), hiker)
        double = carry_cost_hours(carry_between(0.0, 108.0, 18.0, BURN), hiker)
        assert double > single * 2.0

    def test_a_stop_costs_its_access_plus_the_overhead(self, towns: TownIndex) -> None:
        soda = towns.get("soda-springs")
        assert stop_cost_hours(soda) == pytest.approx(soda.access_cost().in_hours + 3.0)

    def test_a_stop_that_cannot_supply_is_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="cannot supply a whole carry"):
            stop_cost_hours(towns.get("alpine-store"))

    def test_the_overhead_can_be_tuned(self, towns: TownIndex) -> None:
        soda = towns.get("soda-springs")
        assert stop_cost_hours(soda, overhead_hours=12.0) > stop_cost_hours(soda)


class TestPlanResupply:
    def test_a_generous_carry_limit_skips_every_stop(
        self, towns: TownIndex, hiker: HikerProfile
    ) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=20.0)
        assert plan.stops == ()
        assert len(plan.carries) == 1

    def test_a_tight_carry_limit_forces_a_stop(self, towns: TownIndex, hiker: HikerProfile) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=3.0)
        assert len(plan.stops) >= 1
        assert plan.longest_carry.days <= 3.0

    def test_every_chosen_stop_can_actually_supply(
        self, towns: TownIndex, hiker: HikerProfile
    ) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=2.0)
        assert all(stop.supports_full_resupply for stop in plan.stops)

    def test_the_carries_tile_the_whole_route(self, towns: TownIndex, hiker: HikerProfile) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=2.5)
        assert plan.carries[0].start_mile == pytest.approx(0.0)
        assert plan.carries[-1].end_mile == pytest.approx(78.0)
        for first, second in zip(plan.carries, plan.carries[1:], strict=False):
            assert first.end_mile == pytest.approx(second.start_mile)

    def test_the_stop_count_matches_the_carry_count(
        self, towns: TownIndex, hiker: HikerProfile
    ) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=2.5)
        assert len(plan.carries) == len(plan.stops) + 1

    def test_an_expensive_town_is_avoided_when_a_cheaper_one_works(
        self, hiker: HikerProfile
    ) -> None:
        awkward = ResupplyPoint(
            id="awkward",
            name="Awkward",
            mile=38.0,
            groceries=ServiceLevel.FULL_GROCERY,
            hitch=Distance.miles(45.0),
        )
        easy = ResupplyPoint(id="easy", name="Easy", mile=40.0, groceries=ServiceLevel.FULL_GROCERY)
        index = TownIndex([awkward, easy])
        plan = plan_resupply(index, 0.0, 78.0, hiker, max_carry_days=3.0)
        assert [stop.id for stop in plan.stops] == ["easy"]

    def test_an_impossible_limit_is_reported(self, towns: TownIndex, hiker: HikerProfile) -> None:
        with pytest.raises(ResupplyInfeasible, match="no admissible set of stops") as caught:
            plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=0.6)
        assert caught.value.context["longest_unavoidable_gap"] > 0.0

    def test_a_backwards_route_is_refused(self, towns: TownIndex, hiker: HikerProfile) -> None:
        with pytest.raises(ResupplyInfeasible, match="must advance"):
            plan_resupply(towns, 60.0, 20.0, hiker)

    def test_explicit_candidates_override_the_index(
        self, towns: TownIndex, hiker: HikerProfile
    ) -> None:
        plan = plan_resupply(
            towns,
            0.0,
            78.0,
            hiker,
            max_carry_days=4.0,
            candidates=[towns.get("tahoma")],
        )
        assert {stop.id for stop in plan.stops} <= {"tahoma"}

    def test_the_heaviest_food_bag_is_reported(self, towns: TownIndex, hiker: HikerProfile) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=3.0)
        assert plan.heaviest_food_bag.in_pounds > 2.0

    def test_town_time_sums_the_stops(self, towns: TownIndex, hiker: HikerProfile) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=2.5)
        expected = sum(stop_cost_hours(stop) for stop in plan.stops)
        assert town_time(plan).in_hours == pytest.approx(expected)

    def test_a_faster_walker_needs_fewer_stops(self, towns: TownIndex) -> None:
        plodder = HikerProfile(name="plodder", flat_pace_mph=2.2)
        plan_slow = plan_resupply(towns, 0.0, 78.0, plodder, daily_miles=10.0, max_carry_days=4.0)
        plan_fast = plan_resupply(towns, 0.0, 78.0, plodder, daily_miles=26.0, max_carry_days=4.0)
        assert len(plan_fast.stops) <= len(plan_slow.stops)

    def test_repr(self, towns: TownIndex, hiker: HikerProfile) -> None:
        plan = plan_resupply(towns, 0.0, 78.0, hiker, max_carry_days=2.5)
        assert repr(plan).startswith("ResupplyStrategy(")
