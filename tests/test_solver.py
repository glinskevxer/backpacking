"""Building itineraries end to end."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.solver import PlanRequest, campable_waypoints, candidate_camps, solve
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance, Mass

START = date(2025, 7, 20)


def request_for(corridor: Corridor, hiker: HikerProfile, **kwargs: object) -> PlanRequest:
    defaults: dict[str, object] = {
        "corridor": corridor,
        "profile": hiker,
        "start_date": START,
        "pack_weight": Mass.pounds(26.0),
    }
    defaults.update(kwargs)
    return PlanRequest(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def plan(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    return solve(request_for(corridor, hiker))


class TestPlanRequest:
    def test_unset_miles_default_to_the_corridor(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        request = request_for(corridor, hiker)
        assert request.resolved_start() == pytest.approx(0.0)
        assert request.resolved_end() == pytest.approx(78.0)

    def test_explicit_miles_win(self, corridor: Corridor, hiker: HikerProfile) -> None:
        request = request_for(corridor, hiker, start_mile=10.0, end_mile=50.0)
        assert request.resolved_start() == pytest.approx(10.0)
        assert request.resolved_end() == pytest.approx(50.0)

    def test_a_backwards_request_is_refused(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        with pytest.raises(PlanInfeasible, match="must advance"):
            request_for(corridor, hiker, start_mile=50.0, end_mile=10.0)

    def test_a_zero_window_is_refused(self, corridor: Corridor, hiker: HikerProfile) -> None:
        with pytest.raises(PlanInfeasible, match="window must be positive"):
            request_for(corridor, hiker, window_miles=0.0)


class TestCandidateCamps:
    def test_the_window_is_symmetric(self, corridor: Corridor) -> None:
        found = candidate_camps(corridor, 15.3, 4.0)
        assert all(11.3 <= waypoint.mile <= 19.3 for waypoint in found)
        assert "clyde-basin" in {w.id for w in found}

    def test_the_window_is_clipped_at_the_terminus(self, corridor: Corridor) -> None:
        found = candidate_camps(corridor, 77.0, 6.0)
        assert all(waypoint.mile <= 78.0 for waypoint in found)

    def test_campable_waypoints_are_only_camps_and_shelters(self, corridor: Corridor) -> None:
        assert all(waypoint.can_camp for waypoint in campable_waypoints(corridor))
        assert len(campable_waypoints(corridor)) == 6


class TestSolve:
    def test_the_plan_covers_the_whole_corridor(self, plan: Itinerary) -> None:
        assert plan.covers_whole_corridor()
        assert plan.total_distance.in_miles == pytest.approx(78.0)

    def test_the_plan_starts_on_the_requested_date(self, plan: Itinerary) -> None:
        assert plan.start_date == START

    def test_the_days_join_end_to_end(self, plan: Itinerary) -> None:
        for first, second in zip(plan.days, plan.days[1:], strict=False):
            assert first.end_mile == pytest.approx(second.start_mile)

    def test_a_seventy_eight_mile_corridor_takes_a_believable_number_of_days(
        self, plan: Itinerary
    ) -> None:
        assert 4 <= len(plan) <= 8

    def test_every_day_respects_the_constraints(
        self, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        limits = PlanConstraints()
        for day in plan.days[:-1]:
            assert limits.day_is_admissible(day.miles, day.gain, day.elapsed)

    def test_most_nights_land_on_a_real_campsite(self, plan: Itinerary) -> None:
        named = [day for day in plan.days[:-1] if day.camp is not None]
        assert len(named) >= len(plan.days) - 2

    def test_the_final_day_ends_at_the_terminus_with_no_camp(self, plan: Itinerary) -> None:
        assert plan.days[-1].end_mile == pytest.approx(78.0)
        assert plan.days[-1].camp is None

    def test_a_partial_section_can_be_planned(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        section = solve(request_for(corridor, hiker, start_mile=23.6, end_mile=57.4))
        assert section.start_mile == pytest.approx(23.6)
        assert section.end_mile == pytest.approx(57.4)

    def test_a_faster_hiker_finishes_sooner(self, corridor: Corridor) -> None:
        plodder = solve(request_for(corridor, HikerProfile(name="slow", flat_pace_mph=2.1)))
        runner = solve(request_for(corridor, HikerProfile(name="quick", flat_pace_mph=3.6)))
        assert len(runner) <= len(plodder)

    def test_a_night_hiker_covers_more_per_day(self, corridor: Corridor) -> None:
        day_only = solve(request_for(corridor, HikerProfile(flat_pace_mph=2.7)))
        owl = solve(request_for(corridor, HikerProfile(flat_pace_mph=2.7, night_hiking=True)))
        assert owl.average_daily_miles >= day_only.average_daily_miles

    def test_a_lower_aggressiveness_makes_shorter_days(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        easy = solve(request_for(corridor, hiker, aggressiveness=0.55))
        hard = solve(request_for(corridor, hiker, aggressiveness=1.0))
        assert easy.average_daily_miles < hard.average_daily_miles

    def test_a_heavier_pack_shortens_the_days(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        light = solve(request_for(corridor, hiker, pack_weight=Mass.pounds(18.0)))
        heavy = solve(request_for(corridor, hiker, pack_weight=Mass.pounds(45.0)))
        assert heavy.average_daily_miles < light.average_daily_miles

    def test_a_forbidden_camp_is_avoided(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        limits = PlanConstraints(forbidden_camps=frozenset({"clyde-basin", "dry-bench"}))
        plan = solve(request_for(corridor, hiker, constraints=limits))
        assert "clyde-basin" not in {day.camp_id for day in plan}
        assert "dry-bench" not in {day.camp_id for day in plan}

    def test_a_moderate_mileage_cap_forces_more_days(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        loose = solve(request_for(corridor, hiker))
        tight = solve(
            request_for(
                corridor,
                hiker,
                constraints=PlanConstraints(max_daily_miles=16.0, min_daily_miles=4.0),
                window_miles=12.0,
            )
        )
        assert len(tight) > len(loose)

    def test_a_tight_mileage_cap_defeats_the_greedy_window(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        """Known limitation. The window is centred on the target day, so a cap
        well inside it leaves nothing admissible even though a legal split
        exists further back."""
        limits = PlanConstraints(max_daily_miles=12.0, min_daily_miles=4.0)
        with pytest.raises(PlanInfeasible, match="no admissible camp"):
            solve(request_for(corridor, hiker, constraints=limits))

    def test_a_tight_gain_cap_also_defeats_it(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        limits = PlanConstraints(max_daily_gain=Distance.feet(1600))
        with pytest.raises(PlanInfeasible, match="no admissible camp"):
            solve(request_for(corridor, hiker, constraints=limits))

    def test_widening_the_window_recovers_the_tight_cap(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        limits = PlanConstraints(max_daily_miles=12.0, min_daily_miles=4.0)
        plan = solve(request_for(corridor, hiker, constraints=limits, window_miles=12.0))
        assert all(day.miles <= 12.0 for day in plan.days)

    def test_an_impossible_day_cap_is_reported(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        limits = PlanConstraints(max_total_days=2)
        with pytest.raises(PlanInfeasible):
            solve(request_for(corridor, hiker, constraints=limits))

    def test_an_impossible_deadline_is_reported(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        limits = PlanConstraints(must_finish_by=date(2025, 7, 21))
        with pytest.raises(PlanInfeasible, match="trip level limits"):
            solve(request_for(corridor, hiker, constraints=limits))

    def test_the_plan_is_labelled(self, plan: Itinerary) -> None:
        assert plan.label == "greedy"

    def test_pack_weight_is_carried_onto_every_day(self, plan: Itinerary) -> None:
        assert all(day.pack_weight.in_pounds == pytest.approx(26.0) for day in plan)

    def test_the_plan_validates_as_an_itinerary(self, plan: Itinerary) -> None:
        rebuilt = Itinerary(corridor=plan.corridor, days=plan.days, label=plan.label)
        assert rebuilt.total_distance == plan.total_distance
