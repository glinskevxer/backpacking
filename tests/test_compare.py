"""Comparing plans and ranking candidates."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.analysis.compare import compare_plans, rank_plans, render_delta
from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.solver import PlanRequest, solve
from backpacking.trail.corridor import Corridor

START = date(2025, 7, 20)


def plan_for(corridor: Corridor, hiker: HikerProfile, **kwargs: object) -> Itinerary:
    defaults: dict[str, object] = {
        "corridor": corridor,
        "profile": hiker,
        "start_date": START,
    }
    defaults.update(kwargs)
    return solve(PlanRequest(**defaults))  # type: ignore[arg-type]


@pytest.fixture
def baseline(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    return plan_for(corridor, hiker)


@pytest.fixture
def gentle(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    return plan_for(
        corridor,
        hiker,
        constraints=PlanConstraints(max_daily_miles=13.0, min_daily_miles=4.0),
    )


class TestCompareIdentical:
    def test_a_plan_against_itself_is_identical(self, baseline: Itinerary) -> None:
        delta = compare_plans(baseline, baseline)
        assert delta.is_identical
        assert delta.day_count_delta == 0
        assert delta.distance_delta.in_miles == pytest.approx(0.0)

    def test_the_rendering_says_so(self, baseline: Itinerary) -> None:
        assert "is the same plan as" in render_delta(compare_plans(baseline, baseline))

    def test_a_rebuilt_plan_matches(self, corridor: Corridor, hiker: HikerProfile) -> None:
        first = plan_for(corridor, hiker)
        second = plan_for(corridor, hiker)
        assert compare_plans(first, second).is_identical


class TestCompareDifferent:
    def test_a_gentler_plan_takes_more_days(self, baseline: Itinerary, gentle: Itinerary) -> None:
        delta = compare_plans(baseline, gentle)
        assert delta.day_count_delta > 0
        assert not delta.is_shorter_trip

    def test_the_distance_is_unchanged_over_the_same_route(
        self, baseline: Itinerary, gentle: Itinerary
    ) -> None:
        delta = compare_plans(baseline, gentle)
        assert delta.distance_delta.in_miles == pytest.approx(0.0, abs=0.01)

    def test_the_average_day_falls(self, baseline: Itinerary, gentle: Itinerary) -> None:
        assert compare_plans(baseline, gentle).average_daily_delta < 0.0

    def test_the_added_days_are_reported(self, baseline: Itinerary, gentle: Itinerary) -> None:
        delta = compare_plans(baseline, gentle)
        added = [day for day in delta.days if day.is_added]
        assert len(added) == delta.day_count_delta

    def test_removed_days_are_reported_the_other_way(
        self, baseline: Itinerary, gentle: Itinerary
    ) -> None:
        delta = compare_plans(gentle, baseline)
        removed = [day for day in delta.days if day.is_removed]
        assert len(removed) == -delta.day_count_delta

    def test_a_camp_change_is_detected(self, baseline: Itinerary, gentle: Itinerary) -> None:
        delta = compare_plans(baseline, gentle)
        assert any(day.camp_changed for day in delta.changed_days)

    def test_rest_days_are_counted(self, baseline: Itinerary) -> None:
        rested = baseline.with_zero_day_after(0)
        assert compare_plans(baseline, rested).zero_day_delta == 1

    def test_a_zero_day_adds_time_but_no_distance(self, baseline: Itinerary) -> None:
        delta = compare_plans(baseline, baseline.with_zero_day_after(0))
        assert delta.distance_delta.in_miles == pytest.approx(0.0)
        assert delta.day_count_delta == 1

    def test_comparing_across_corridors_is_refused(
        self, baseline: Itinerary, short_corridor: Corridor, hiker: HikerProfile
    ) -> None:
        other = plan_for(short_corridor, hiker)
        with pytest.raises(PlanInfeasible, match="different corridors"):
            compare_plans(baseline, other)


class TestDayDelta:
    def test_the_repr_of_an_added_day(self, baseline: Itinerary, gentle: Itinerary) -> None:
        delta = compare_plans(baseline, gentle)
        added = next(day for day in delta.days if day.is_added)
        assert repr(added) == f"DayDelta({added.index}: added)"

    def test_the_repr_of_a_changed_day(self, baseline: Itinerary, gentle: Itinerary) -> None:
        delta = compare_plans(baseline, gentle)
        changed = next(
            day for day in delta.days if not day.is_added and abs(day.miles_delta) > 0.05
        )
        assert "mi)" in repr(changed)

    def test_an_unchanged_day_is_not_listed(self, baseline: Itinerary) -> None:
        assert compare_plans(baseline, baseline).changed_days == ()


class TestRenderDelta:
    def test_every_headline_is_present(self, baseline: Itinerary, gentle: Itinerary) -> None:
        text = render_delta(compare_plans(baseline, gentle))
        for label in ("days", "distance", "climb", "time on feet", "average day", "rest days"):
            assert label in text

    def test_signs_are_explicit(self, baseline: Itinerary, gentle: Itinerary) -> None:
        text = render_delta(compare_plans(baseline, gentle))
        assert "+" in text

    def test_changed_days_are_listed(self, baseline: Itinerary, gentle: Itinerary) -> None:
        text = render_delta(compare_plans(baseline, gentle))
        assert "day changed:" in text or "days changed:" in text

    def test_a_camp_change_is_called_out(self, baseline: Itinerary, gentle: Itinerary) -> None:
        text = render_delta(compare_plans(baseline, gentle))
        assert "camps elsewhere" in text

    def test_the_plan_repr(self, baseline: Itinerary, gentle: Itinerary) -> None:
        assert repr(compare_plans(baseline, gentle)).startswith("PlanDelta(")


class TestRankPlans:
    def test_fewer_days_wins_by_default(self, baseline: Itinerary, gentle: Itinerary) -> None:
        assert rank_plans([gentle, baseline])[0] is baseline

    def test_the_preference_can_be_flipped(self, baseline: Itinerary, gentle: Itinerary) -> None:
        assert rank_plans([baseline, gentle], prefer_fewer_days=False)[0] is gentle

    def test_a_tie_is_broken_by_the_longest_day(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        hard = plan_for(corridor, hiker, aggressiveness=1.0)
        soft = plan_for(corridor, hiker, aggressiveness=0.9)
        ranked = rank_plans([hard, soft])
        if len(hard) == len(soft):
            assert ranked[0].longest_day.miles <= ranked[1].longest_day.miles

    def test_ranking_nothing_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="empty list of plans"):
            rank_plans([])

    def test_a_single_plan_ranks_trivially(self, baseline: Itinerary) -> None:
        assert rank_plans([baseline]) == [baseline]
