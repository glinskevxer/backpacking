"""Hard constraints and the soft objective, separately."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile, LegEstimate
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.scoring import (
    DEFAULT_WEIGHTS,
    ScoringWeights,
    camp_cost,
    day_cost,
    describe_cost,
    effort_cost,
    elapsed_budget,
    late_finish_cost,
    steep_finish_cost,
    target_hours_for,
    total_plan_cost,
)
from backpacking.trail.models import WaypointKind
from backpacking.units import Distance, Duration
from tests.conftest import wp


def leg(miles: float, hours: float, gain_ft: float = 0.0) -> LegEstimate:
    return LegEstimate(
        distance=Distance.miles(miles),
        gain=Distance.feet(gain_ft),
        loss=Distance.zero(),
        moving_time=Duration.hours(hours),
        elapsed_time=Duration.hours(hours * 1.18),
    )


class TestPlanConstraints:
    def test_a_reasonable_day_is_admissible(self) -> None:
        limits = PlanConstraints()
        assert limits.day_is_admissible(18.0, Distance.feet(3200), Duration.hours(9.0))

    def test_too_far_is_refused(self) -> None:
        limits = PlanConstraints()
        assert not limits.day_is_admissible(40.0, Distance.feet(1000), Duration.hours(9.0))

    def test_too_short_is_refused(self) -> None:
        limits = PlanConstraints()
        assert not limits.day_is_admissible(2.0, Distance.feet(200), Duration.hours(1.0))

    def test_the_final_day_is_exempt_from_the_minimum(self) -> None:
        limits = PlanConstraints()
        assert limits.day_is_admissible(
            2.0, Distance.feet(200), Duration.hours(1.0), is_final=True
        )

    def test_too_much_climb_is_refused(self) -> None:
        limits = PlanConstraints()
        assert not limits.day_is_admissible(14.0, Distance.feet(9000), Duration.hours(9.0))

    def test_too_long_a_day_is_refused(self) -> None:
        limits = PlanConstraints()
        assert not limits.day_is_admissible(20.0, Distance.feet(1000), Duration.hours(15.0))

    def test_constraints_from_a_profile_follow_the_hiker(self, hiker: HikerProfile) -> None:
        limits = PlanConstraints.for_profile(hiker)
        assert limits.max_daily_gain.in_feet == pytest.approx(6000.0)
        assert limits.max_daily_elapsed.in_hours == pytest.approx(9.0 * 1.18)

    def test_a_night_owl_gets_a_longer_day(self) -> None:
        owl = PlanConstraints.for_profile(HikerProfile(night_hiking=True))
        day = PlanConstraints.for_profile(HikerProfile(night_hiking=False))
        assert owl.max_daily_elapsed > day.max_daily_elapsed

    def test_an_inverted_mileage_range_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="must exceed the minimum"):
            PlanConstraints(min_daily_miles=20.0, max_daily_miles=10.0)

    def test_a_zero_gain_cap_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="gain must be positive"):
            PlanConstraints(max_daily_gain=Distance.zero())

    def test_a_camp_cannot_be_required_and_forbidden(self) -> None:
        with pytest.raises(PlanInfeasible, match="both required and forbidden"):
            PlanConstraints(
                required_camps=frozenset({"clyde-basin"}),
                forbidden_camps=frozenset({"clyde-basin"}),
            )

    def test_a_zero_day_trip_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="at least one day"):
            PlanConstraints(max_total_days=0)

    def test_forbidden_camps_are_rejected(self) -> None:
        limits = PlanConstraints(forbidden_camps=frozenset({"dry-bench"}))
        assert not limits.camp_is_allowed("dry-bench")
        assert limits.camp_is_allowed("clyde-basin")

    def test_an_unnamed_camp_can_be_required_to_be_named(self) -> None:
        loose = PlanConstraints()
        strict = PlanConstraints(camps_must_be_named=True)
        assert loose.camp_is_allowed(None)
        assert not strict.camp_is_allowed(None)

    def test_trip_length_is_capped(self) -> None:
        limits = PlanConstraints(max_total_days=5)
        assert limits.trip_is_admissible(5, date(2025, 7, 25))
        assert not limits.trip_is_admissible(6, date(2025, 7, 26))

    def test_a_finish_deadline_is_enforced(self) -> None:
        limits = PlanConstraints(must_finish_by=date(2025, 7, 25))
        assert limits.trip_is_admissible(4, date(2025, 7, 24))
        assert not limits.trip_is_admissible(4, date(2025, 7, 26))

    def test_relaxing_returns_a_looser_copy(self) -> None:
        limits = PlanConstraints(max_daily_miles=24.0)
        looser = limits.relaxed(max_daily_miles=30.0)
        assert looser.max_daily_miles == pytest.approx(30.0)
        assert limits.max_daily_miles == pytest.approx(24.0)

    def test_repr(self) -> None:
        assert repr(PlanConstraints()) == "PlanConstraints(4-32 mi, <=6000 ft)"


class TestScoring:
    def test_hitting_the_target_costs_nothing_for_effort(self, hiker: HikerProfile) -> None:
        assert effort_cost(leg(18.0, 7.2), hiker, target_hours=7.2) == pytest.approx(0.0)

    def test_deviation_is_squared(self, hiker: HikerProfile) -> None:
        small = effort_cost(leg(18.0, 8.2), hiker, target_hours=7.2)
        large = effort_cost(leg(18.0, 9.2), hiker, target_hours=7.2)
        assert large == pytest.approx(small * 4.0)

    def test_short_and_long_are_penalised_alike(self, hiker: HikerProfile) -> None:
        short = effort_cost(leg(10.0, 6.2), hiker, target_hours=7.2)
        long = effort_cost(leg(24.0, 8.2), hiker, target_hours=7.2)
        assert short == pytest.approx(long)

    def test_a_zero_target_is_refused(self, hiker: HikerProfile) -> None:
        with pytest.raises(PlanInfeasible, match="must be positive"):
            effort_cost(leg(18.0, 7.0), hiker, target_hours=0.0)

    def test_a_real_campsite_is_cheaper_than_nowhere(self) -> None:
        camp = wp("clyde-basin", "Clyde Basin", 15.3, 8040, WaypointKind.CAMPSITE)
        assert camp_cost(camp) < camp_cost(None)

    def test_a_non_camp_waypoint_costs_the_unnamed_penalty(self) -> None:
        junction = wp("twin-peaks", "Twin Peaks", 27.2, 8100, WaypointKind.JUNCTION)
        assert camp_cost(junction) == pytest.approx(DEFAULT_WEIGHTS.unnamed_camp)

    def test_an_exposed_camp_costs_more(self) -> None:
        sheltered = wp("a", "A", 4.0, 7000, WaypointKind.CAMPSITE)
        exposed = wp("b", "B", 4.0, 7000, WaypointKind.CAMPSITE, tags={"exposed"})
        assert camp_cost(exposed) > camp_cost(sheltered)

    def test_a_resupply_waypoint_earns_a_bonus(self) -> None:
        town = wp("soda", "Soda Springs", 57.4, 6870, WaypointKind.RESUPPLY)
        junction = wp("junction", "Junction", 57.4, 6870, WaypointKind.JUNCTION)
        assert camp_cost(town) < camp_cost(junction)

    def test_a_day_inside_the_budget_has_no_late_finish_cost(
        self, hiker: HikerProfile
    ) -> None:
        assert late_finish_cost(leg(18.0, 7.0), hiker) == pytest.approx(0.0)

    def test_a_day_past_the_budget_is_penalised(self, hiker: HikerProfile) -> None:
        assert late_finish_cost(leg(28.0, 12.0), hiker) > 0.0

    def test_the_elapsed_budget_includes_breaks(self, hiker: HikerProfile) -> None:
        assert elapsed_budget(hiker).in_hours == pytest.approx(9.0 * 1.18)

    def test_a_climb_at_the_end_of_the_day_costs(self) -> None:
        assert steep_finish_cost(Distance.feet(2000)) == pytest.approx(
            DEFAULT_WEIGHTS.steep_finish * 2.0
        )

    def test_a_flat_finish_costs_nothing(self) -> None:
        assert steep_finish_cost(Distance.zero()) == pytest.approx(0.0)

    def test_the_day_cost_adds_every_term(self, hiker: HikerProfile) -> None:
        camp = wp("clyde-basin", "Clyde Basin", 15.3, 8040, WaypointKind.CAMPSITE)
        estimate = leg(18.0, 8.0, gain_ft=2600)
        parts = describe_cost(
            estimate, camp, hiker, target_hours=7.2, gain_in_last_third=Distance.feet(900)
        )
        whole = day_cost(
            estimate, camp, hiker, target_hours=7.2, gain_in_last_third=Distance.feet(900)
        )
        assert whole == pytest.approx(sum(parts.values()), abs=0.01)

    def test_the_per_day_cost_stops_endless_plans(self, hiker: HikerProfile) -> None:
        camp = wp("clyde-basin", "Clyde Basin", 15.3, 8040, WaypointKind.CAMPSITE)
        cheap = ScoringWeights(per_day=0.0)
        assert day_cost(leg(18.0, 7.2), camp, hiker, target_hours=7.2, weights=cheap) < day_cost(
            leg(18.0, 7.2), camp, hiker, target_hours=7.2
        )

    def test_target_hours_scale_with_aggressiveness(self, hiker: HikerProfile) -> None:
        easy = target_hours_for(hiker, aggressiveness=0.6)
        hard = target_hours_for(hiker, aggressiveness=1.0)
        assert hard > easy
        assert hard == pytest.approx(9.0)

    def test_an_aggressiveness_above_one_is_refused(self, hiker: HikerProfile) -> None:
        with pytest.raises(PlanInfeasible, match=r"\(0, 1\]"):
            target_hours_for(hiker, aggressiveness=1.4)

    def test_a_negative_per_day_weight_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="must not be negative"):
            ScoringWeights(per_day=-1.0)

    def test_the_plan_cost_sums_the_days(self) -> None:
        assert total_plan_cost([1.0, 2.5, 3.0]) == pytest.approx(6.5)

    def test_an_empty_plan_cannot_be_scored(self) -> None:
        with pytest.raises(PlanInfeasible, match="empty plan"):
            total_plan_cost([])
