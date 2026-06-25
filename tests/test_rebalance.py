"""Adding rest days, marking resupply and compressing to a deadline."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.rebalance import (
    REST_THRESHOLD,
    add_town_day,
    compress_to_deadline,
    fatigue_curve,
    insert_rest_days,
    mark_resupply,
    rebalance_for_rest,
    suggest_rest_days,
    worst_fatigue,
)
from backpacking.plan.solver import PlanRequest, solve
from backpacking.resupply.towns import TownIndex
from backpacking.trail.corridor import Corridor

START = date(2025, 7, 20)


@pytest.fixture
def plan(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    return solve(PlanRequest(corridor=corridor, profile=hiker, start_date=START))


@pytest.fixture
def hard_plan(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    """A plan pushed hard enough that fatigue actually accumulates."""
    return solve(
        PlanRequest(
            corridor=corridor,
            profile=hiker,
            start_date=START,
            aggressiveness=1.0,
            constraints=PlanConstraints(max_daily_miles=40.0),
        )
    )


class TestFatigueCurve:
    def test_one_state_per_day(self, plan: Itinerary, hiker: HikerProfile) -> None:
        assert len(fatigue_curve(plan, hiker)) == len(plan)

    def test_the_days_are_numbered_forward(self, plan: Itinerary, hiker: HikerProfile) -> None:
        curve = fatigue_curve(plan, hiker)
        assert [state.day for state in curve] == list(range(1, len(plan) + 1))

    def test_a_zero_day_sheds_fatigue(self, hard_plan: Itinerary, hiker: HikerProfile) -> None:
        before = fatigue_curve(hard_plan, hiker)
        rested = fatigue_curve(hard_plan.with_zero_day_after(0), hiker)
        assert rested[-1].fatigue <= before[-1].fatigue

    def test_worst_fatigue_is_the_peak(self, plan: Itinerary, hiker: HikerProfile) -> None:
        curve = fatigue_curve(plan, hiker)
        assert worst_fatigue(plan, hiker) == pytest.approx(max(state.fatigue for state in curve))


class TestSuggestRestDays:
    def test_an_easy_plan_needs_no_rest(self, corridor: Corridor, hiker: HikerProfile) -> None:
        easy = solve(
            PlanRequest(corridor=corridor, profile=hiker, start_date=START, aggressiveness=0.55)
        )
        assert suggest_rest_days(easy, hiker) == ()

    def test_a_hard_plan_suggests_something(
        self, hard_plan: Itinerary, hiker: HikerProfile
    ) -> None:
        assert suggest_rest_days(hard_plan, hiker, threshold=0.02)

    def test_suggestions_are_day_indices(self, hard_plan: Itinerary, hiker: HikerProfile) -> None:
        for index in suggest_rest_days(hard_plan, hiker, threshold=0.02):
            assert 0 <= index < len(hard_plan)

    def test_nothing_is_suggested_near_the_finish(
        self, hard_plan: Itinerary, hiker: HikerProfile
    ) -> None:
        for index in suggest_rest_days(hard_plan, hiker, threshold=0.01):
            assert index <= len(hard_plan) - 3

    def test_a_lower_threshold_suggests_more(
        self, hard_plan: Itinerary, hiker: HikerProfile
    ) -> None:
        strict = suggest_rest_days(hard_plan, hiker, threshold=0.25)
        loose = suggest_rest_days(hard_plan, hiker, threshold=0.02)
        assert len(loose) >= len(strict)

    def test_an_impossible_threshold_is_refused(self, plan: Itinerary, hiker: HikerProfile) -> None:
        with pytest.raises(PlanInfeasible, match=r"\(0, 1\)"):
            suggest_rest_days(plan, hiker, threshold=1.5)


class TestInsertRestDays:
    def test_one_insertion_lengthens_the_trip(self, plan: Itinerary) -> None:
        rested = insert_rest_days(plan, [1])
        assert len(rested) == len(plan) + 1
        assert rested[2].is_zero

    def test_several_insertions_all_land(self, plan: Itinerary) -> None:
        rested = insert_rest_days(plan, [0, 2])
        assert len(rested.zero_days) == 2

    def test_the_mileage_is_unchanged(self, plan: Itinerary) -> None:
        rested = insert_rest_days(plan, [0, 2])
        assert rested.total_distance.in_miles == pytest.approx(plan.total_distance.in_miles)

    def test_duplicate_indices_insert_once(self, plan: Itinerary) -> None:
        assert len(insert_rest_days(plan, [1, 1, 1])) == len(plan) + 1

    def test_an_empty_list_changes_nothing(self, plan: Itinerary) -> None:
        assert len(insert_rest_days(plan, [])) == len(plan)


class TestRebalanceForRest:
    def test_an_easy_plan_is_left_alone(self, corridor: Corridor, hiker: HikerProfile) -> None:
        easy = solve(
            PlanRequest(corridor=corridor, profile=hiker, start_date=START, aggressiveness=0.55)
        )
        assert len(rebalance_for_rest(easy, hiker)) == len(easy)

    def test_a_hard_plan_gains_rest_days(self, hard_plan: Itinerary, hiker: HikerProfile) -> None:
        rested = rebalance_for_rest(hard_plan, hiker, threshold=0.02)
        assert len(rested) > len(hard_plan)

    def test_the_cap_is_respected(self, hard_plan: Itinerary, hiker: HikerProfile) -> None:
        rested = rebalance_for_rest(hard_plan, hiker, threshold=0.01, max_rest_days=1)
        assert len(rested.zero_days) <= 1

    def test_a_zero_cap_changes_nothing(self, hard_plan: Itinerary, hiker: HikerProfile) -> None:
        assert len(rebalance_for_rest(hard_plan, hiker, max_rest_days=0)) == len(hard_plan)

    def test_a_negative_cap_is_refused(self, plan: Itinerary, hiker: HikerProfile) -> None:
        with pytest.raises(PlanInfeasible, match="must not be negative"):
            rebalance_for_rest(plan, hiker, max_rest_days=-1)

    def test_the_route_is_still_covered(self, hard_plan: Itinerary, hiker: HikerProfile) -> None:
        rested = rebalance_for_rest(hard_plan, hiker, threshold=0.02)
        assert rested.covers_whole_corridor()


class TestMarkResupply:
    def test_the_day_passing_a_stop_is_annotated(self, plan: Itinerary, towns: TownIndex) -> None:
        marked = mark_resupply(plan, towns.full_resupplies())
        assert marked.resupply_days

    def test_each_stop_lands_on_one_day(self, plan: Itinerary, towns: TownIndex) -> None:
        marked = mark_resupply(plan, towns.full_resupplies())
        annotated = [day.resupply_at for day in marked if day.resupply_at]
        assert len(annotated) == len(set(annotated))

    def test_the_annotated_day_covers_the_stop(self, plan: Itinerary, towns: TownIndex) -> None:
        marked = mark_resupply(plan, towns.full_resupplies(), tolerance_miles=0.0)
        for day in marked.resupply_days:
            stop = towns.get(day.resupply_at or "")
            assert day.start_mile <= stop.mile <= day.end_mile

    def test_nothing_changes_when_no_stop_matches(self, plan: Itinerary) -> None:
        assert mark_resupply(plan, []) is plan

    def test_the_mileage_is_untouched(self, plan: Itinerary, towns: TownIndex) -> None:
        marked = mark_resupply(plan, towns.full_resupplies())
        assert [day.end_mile for day in marked] == [day.end_mile for day in plan]

    def test_a_negative_tolerance_is_refused(self, plan: Itinerary, towns: TownIndex) -> None:
        with pytest.raises(PlanInfeasible, match="must not be negative"):
            mark_resupply(plan, towns.points, tolerance_miles=-1.0)


class TestTownDay:
    def test_a_town_day_is_a_zero_with_a_note(self, plan: Itinerary) -> None:
        with_town = add_town_day(plan, 1)
        assert with_town[2].is_zero
        assert with_town[2].notes == "town day"

    def test_a_custom_note(self, plan: Itinerary) -> None:
        with_town = add_town_day(plan, 0, note="waiting for the post office")
        assert with_town[1].notes == "waiting for the post office"

    def test_it_lengthens_the_trip(self, plan: Itinerary) -> None:
        assert add_town_day(plan, 1).finish_date == plan.finish_date + timedelta(days=1)


class TestCompressToDeadline:
    def test_a_plan_already_inside_the_deadline_is_untouched(self, plan: Itinerary) -> None:
        late = plan.finish_date + timedelta(days=5)
        assert len(compress_to_deadline(plan, late)) == len(plan)

    def test_rest_days_are_dropped_to_meet_a_deadline(self, plan: Itinerary) -> None:
        rested = insert_rest_days(plan, [0, 2])
        compressed = compress_to_deadline(rested, plan.finish_date)
        assert compressed.finish_date <= plan.finish_date
        assert len(compressed.zero_days) < len(rested.zero_days)

    def test_the_route_survives_compression(self, plan: Itinerary) -> None:
        rested = insert_rest_days(plan, [0, 2])
        compressed = compress_to_deadline(rested, plan.finish_date)
        assert compressed.total_distance.in_miles == pytest.approx(plan.total_distance.in_miles)

    def test_an_impossible_deadline_is_refused(self, plan: Itinerary) -> None:
        with pytest.raises(PlanInfeasible, match="without walking further"):
            compress_to_deadline(plan, START)

    def test_a_non_date_deadline_is_refused(self, plan: Itinerary) -> None:
        with pytest.raises(PlanInfeasible, match="must be a date"):
            compress_to_deadline(plan, "2025-07-25")

    def test_the_default_rest_threshold_is_sensible(self) -> None:
        assert 0.0 < REST_THRESHOLD < 0.3
