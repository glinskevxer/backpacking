"""Itinerary invariants and the editing operations on one."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backpacking.errors import PlanInfeasible
from backpacking.pace.estimator import PaceEstimator
from backpacking.pace.models import LegEstimate
from backpacking.plan.itinerary import DayPlan, Itinerary, build_itinerary
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance, Mass

START = date(2025, 7, 20)

SPLITS = [0.0, 15.3, 31.8, 44.7, 62.9, 78.0]


def make_itinerary(corridor: Corridor, estimator: PaceEstimator) -> Itinerary:
    days = []
    for index, (low, high) in enumerate(zip(SPLITS, SPLITS[1:], strict=False)):
        estimate = estimator.estimate_span(corridor, low, high)
        camp = corridor.nearest_waypoint(high) if high < 78.0 else None
        days.append(
            DayPlan(
                index=index,
                day=START + timedelta(days=index),
                start_mile=low,
                end_mile=high,
                estimate=estimate,
                camp=camp,
                pack_weight=Mass.pounds(24.0),
            )
        )
    return Itinerary(corridor=corridor, days=tuple(days), label="reference")


@pytest.fixture
def itinerary(corridor: Corridor, estimator: PaceEstimator) -> Itinerary:
    return make_itinerary(corridor, estimator)


class TestDayPlan:
    def test_miles_come_from_the_endpoints(self, itinerary: Itinerary) -> None:
        assert itinerary[0].miles == pytest.approx(15.3)
        assert itinerary[0].distance.in_miles == pytest.approx(15.3)

    def test_a_backwards_day_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="must not walk backwards"):
            DayPlan(
                index=0,
                day=START,
                start_mile=20.0,
                end_mile=10.0,
                estimate=LegEstimate.empty(),
            )

    def test_a_negative_index_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="must not be negative"):
            DayPlan(index=-1, day=START, start_mile=0.0, end_mile=4.0, estimate=LegEstimate.empty())

    def test_a_zero_day_that_moves_is_refused(self) -> None:
        with pytest.raises(PlanInfeasible, match="covers no ground"):
            DayPlan(
                index=0,
                day=START,
                start_mile=0.0,
                end_mile=4.0,
                estimate=LegEstimate.empty(),
                is_zero=True,
            )

    def test_camp_id_is_none_without_a_camp(self) -> None:
        day = DayPlan(index=0, day=START, start_mile=0.0, end_mile=4.0, estimate=LegEstimate.empty())
        assert day.camp_id is None

    def test_to_camp_night_carries_the_mile_and_site(self, itinerary: Itinerary) -> None:
        camp = itinerary[0].to_camp_night(has_canister=True)
        assert camp.mile == pytest.approx(15.3)
        assert camp.site_id == "clyde-basin"
        assert camp.has_canister

    def test_repr_of_a_walking_day_and_a_zero(self, itinerary: Itinerary) -> None:
        assert repr(itinerary[0]) == "DayPlan(0, 2025-07-20, 15.3 mi to clyde-basin)"
        rested = itinerary.with_zero_day_after(0)
        assert repr(rested[1]) == "DayPlan(1, 2025-07-21, zero)"


class TestItineraryInvariants:
    def test_the_reference_itinerary_covers_the_corridor(self, itinerary: Itinerary) -> None:
        assert itinerary.covers_whole_corridor()
        assert itinerary.total_distance.in_miles == pytest.approx(78.0)
        assert len(itinerary) == 5

    def test_dates_run_forward(self, itinerary: Itinerary) -> None:
        assert itinerary.start_date == START
        assert itinerary.finish_date == START + timedelta(days=4)

    def test_days_must_join_end_to_end(self, corridor: Corridor) -> None:
        with pytest.raises(PlanInfeasible, match="join end to end"):
            Itinerary(
                corridor=corridor,
                days=(
                    DayPlan(index=0, day=START, start_mile=0.0, end_mile=10.0, estimate=LegEstimate.empty()),
                    DayPlan(
                        index=1,
                        day=START + timedelta(days=1),
                        start_mile=12.0,
                        end_mile=20.0,
                        estimate=LegEstimate.empty(),
                    ),
                ),
            )

    def test_dates_must_advance(self, corridor: Corridor) -> None:
        with pytest.raises(PlanInfeasible, match="dates must advance"):
            Itinerary(
                corridor=corridor,
                days=(
                    DayPlan(index=0, day=START, start_mile=0.0, end_mile=10.0, estimate=LegEstimate.empty()),
                    DayPlan(index=1, day=START, start_mile=10.0, end_mile=20.0, estimate=LegEstimate.empty()),
                ),
            )

    def test_indices_must_run_from_zero(self, corridor: Corridor) -> None:
        with pytest.raises(PlanInfeasible, match="from zero without gaps"):
            Itinerary(
                corridor=corridor,
                days=(
                    DayPlan(index=1, day=START, start_mile=0.0, end_mile=10.0, estimate=LegEstimate.empty()),
                ),
            )

    def test_an_empty_itinerary_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(PlanInfeasible, match="at least one day"):
            Itinerary(corridor=corridor, days=())

    def test_build_itinerary_renumbers(self, corridor: Corridor) -> None:
        days = [
            DayPlan(index=7, day=START, start_mile=0.0, end_mile=10.0, estimate=LegEstimate.empty()),
            DayPlan(
                index=9,
                day=START + timedelta(days=1),
                start_mile=10.0,
                end_mile=20.0,
                estimate=LegEstimate.empty(),
            ),
        ]
        built = build_itinerary(corridor, days, label="renumbered")
        assert [day.index for day in built] == [0, 1]
        assert built.label == "renumbered"


class TestItineraryAggregates:
    def test_total_gain_sums_the_days(self, itinerary: Itinerary) -> None:
        expected = sum(day.estimate.gain.in_feet for day in itinerary)
        assert itinerary.total_gain.in_feet == pytest.approx(expected)

    def test_total_elapsed_sums_the_days(self, itinerary: Itinerary) -> None:
        expected = sum(day.elapsed.in_seconds for day in itinerary)
        assert itinerary.total_elapsed.in_seconds == pytest.approx(expected)

    def test_the_average_daily_mileage(self, itinerary: Itinerary) -> None:
        assert itinerary.average_daily_miles == pytest.approx(78.0 / 5.0)

    def test_the_longest_day_is_found(self, itinerary: Itinerary) -> None:
        assert itinerary.longest_day.miles == pytest.approx(18.2)

    def test_the_biggest_climb_is_found(self, itinerary: Itinerary) -> None:
        biggest = itinerary.biggest_climb
        assert all(day.estimate.gain <= biggest.estimate.gain for day in itinerary)

    def test_indexing_and_iteration_agree(self, itinerary: Itinerary) -> None:
        assert list(itinerary) == [itinerary[index] for index in range(len(itinerary))]

    def test_day_on_a_date(self, itinerary: Itinerary) -> None:
        found = itinerary.day_on(START + timedelta(days=2))
        assert found is not None
        assert found.index == 2

    def test_day_on_an_absent_date(self, itinerary: Itinerary) -> None:
        assert itinerary.day_on(date(2030, 1, 1)) is None

    def test_mile_on_day(self, itinerary: Itinerary) -> None:
        assert itinerary.mile_on_day(1) == pytest.approx(31.8)

    def test_mile_on_a_day_that_does_not_exist(self, itinerary: Itinerary) -> None:
        with pytest.raises(PlanInfeasible, match="no such day"):
            itinerary.mile_on_day(50)

    def test_camp_nights_covers_every_day(self, itinerary: Itinerary) -> None:
        nights = itinerary.camp_nights(has_canister=True)
        assert len(nights) == len(itinerary)
        assert all(night.has_canister for night in nights)

    def test_repr(self, itinerary: Itinerary) -> None:
        assert repr(itinerary) == "Itinerary('Crystal Range Traverse', 5 days, 78.0 mi)"


class TestEditing:
    def test_a_zero_day_lengthens_the_trip_by_a_day(self, itinerary: Itinerary) -> None:
        rested = itinerary.with_zero_day_after(1)
        assert len(rested) == len(itinerary) + 1
        assert rested.finish_date == itinerary.finish_date + timedelta(days=1)

    def test_a_zero_day_covers_no_ground(self, itinerary: Itinerary) -> None:
        rested = itinerary.with_zero_day_after(1)
        assert rested[2].is_zero
        assert rested[2].miles == pytest.approx(0.0)
        assert rested.total_distance.in_miles == pytest.approx(78.0)

    def test_zero_and_walking_days_are_separable(self, itinerary: Itinerary) -> None:
        rested = itinerary.with_zero_day_after(1)
        assert len(rested.zero_days) == 1
        assert len(rested.walking_days) == 5

    def test_the_average_ignores_zero_days(self, itinerary: Itinerary) -> None:
        rested = itinerary.with_zero_day_after(1)
        assert rested.average_daily_miles == pytest.approx(itinerary.average_daily_miles)

    def test_resting_after_a_day_that_does_not_exist(self, itinerary: Itinerary) -> None:
        with pytest.raises(PlanInfeasible, match="no such day to rest after"):
            itinerary.with_zero_day_after(99)

    def test_shifting_moves_every_date(self, itinerary: Itinerary) -> None:
        moved = itinerary.shifted_to(date(2025, 8, 1))
        assert moved.start_date == date(2025, 8, 1)
        assert moved.finish_date == date(2025, 8, 5)
        assert moved.total_distance == itinerary.total_distance

    def test_shifting_leaves_the_original_alone(self, itinerary: Itinerary) -> None:
        itinerary.shifted_to(date(2025, 8, 1))
        assert itinerary.start_date == START

    def test_a_resupply_day_is_listed(self, corridor: Corridor) -> None:
        day = DayPlan(
            index=0,
            day=START,
            start_mile=0.0,
            end_mile=23.6,
            estimate=LegEstimate.empty(),
            resupply_at="tahoma",
        )
        second = DayPlan(
            index=1,
            day=START + timedelta(days=1),
            start_mile=23.6,
            end_mile=78.0,
            estimate=LegEstimate.empty(),
        )
        trip = Itinerary(corridor=corridor, days=(day, second))
        assert [d.resupply_at for d in trip.resupply_days] == ["tahoma"]

    def test_a_partial_itinerary_does_not_cover_the_corridor(
        self, corridor: Corridor, estimator: PaceEstimator
    ) -> None:
        partial = Itinerary(
            corridor=corridor,
            days=(
                DayPlan(
                    index=0,
                    day=START,
                    start_mile=0.0,
                    end_mile=23.6,
                    estimate=estimator.estimate_span(corridor, 0.0, 23.6),
                ),
            ),
        )
        assert not partial.covers_whole_corridor()
        assert partial.total_distance.in_miles == pytest.approx(23.6)
        assert partial.longest_day.miles == pytest.approx(23.6)
        assert partial.total_gain.in_feet > 0.0
        assert Distance.miles(partial.average_daily_miles).in_miles == pytest.approx(23.6)
