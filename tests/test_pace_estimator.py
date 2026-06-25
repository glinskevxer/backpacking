"""Estimating real corridor legs for a real hiker."""

from __future__ import annotations

import pytest
from tests.conftest import wp

from backpacking.errors import PaceModelError
from backpacking.pace.estimator import PaceEstimator, PaceModel
from backpacking.pace.fatigue import FatigueState
from backpacking.pace.models import HikerProfile, LegEstimate
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Segment, Surface
from backpacking.units import Distance, Duration, Mass


class TestCalibration:
    def test_a_slower_hiker_calibrates_below_one(self, estimator: PaceEstimator) -> None:
        assert estimator.calibration() == pytest.approx(2.7 / 3.129, abs=0.005)
        assert estimator.calibration() < 1.0

    def test_a_faster_hiker_calibrates_above_one(self) -> None:
        quick = PaceEstimator(profile=HikerProfile(flat_pace_mph=3.6))
        assert quick.calibration() > 1.0

    def test_calibration_scales_the_estimate(self, corridor: Corridor) -> None:
        slow = PaceEstimator(profile=HikerProfile(flat_pace_mph=2.0))
        fast = PaceEstimator(profile=HikerProfile(flat_pace_mph=4.0))
        slow_time = slow.estimate_span(corridor, 0.0, 10.0).moving_time
        fast_time = fast.estimate_span(corridor, 0.0, 10.0).moving_time
        assert slow_time.in_hours == pytest.approx(fast_time.in_hours * 2.0, rel=0.01)


class TestBaseTime:
    def test_zero_distance_is_zero_time(self, estimator: PaceEstimator) -> None:
        assert (
            estimator.base_time(Distance.zero(), Distance.zero(), Distance.zero()).in_seconds == 0.0
        )

    def test_negative_distance_is_refused(self, estimator: PaceEstimator) -> None:
        with pytest.raises(PaceModelError, match="must not be negative"):
            estimator.base_time(Distance.miles(-1.0), Distance.zero(), Distance.zero())

    @pytest.mark.parametrize("model", list(PaceModel))
    def test_every_model_produces_a_positive_time(
        self, hiker: HikerProfile, model: PaceModel
    ) -> None:
        estimator = PaceEstimator(profile=hiker, model=model)
        estimate = estimator.base_time(Distance.miles(5.0), Distance.feet(1400), Distance.feet(600))
        assert estimate.in_hours > 0.0

    def test_the_models_give_different_answers(self, hiker: HikerProfile) -> None:
        args = (Distance.miles(8.0), Distance.feet(2400), Distance.feet(1800))
        times = {
            model: PaceEstimator(profile=hiker, model=model).base_time(*args).in_hours
            for model in PaceModel
        }
        assert len({round(t, 3) for t in times.values()}) == 3


class TestEstimateSegment:
    @pytest.fixture
    def climb(self) -> Segment:
        return Segment(
            start=wp("low", "Low", 10.0, 7000),
            end=wp("high", "High", 13.0, 8320),
            gain=Distance.feet(1500),
            loss=Distance.feet(180),
        )

    def test_the_estimate_reports_the_leg_geometry(
        self, estimator: PaceEstimator, climb: Segment
    ) -> None:
        estimate = estimator.estimate_segment(climb)
        assert estimate.distance.in_miles == pytest.approx(3.0)
        assert estimate.gain.in_feet == pytest.approx(1500)

    def test_elapsed_time_exceeds_moving_time_by_the_break_fraction(
        self, estimator: PaceEstimator, climb: Segment
    ) -> None:
        estimate = estimator.estimate_segment(climb)
        assert estimate.elapsed_time.in_seconds == pytest.approx(
            estimate.moving_time.in_seconds * 1.18
        )
        assert estimate.break_time.in_seconds > 0.0

    def test_a_climb_is_slower_than_the_flat_pace(
        self, estimator: PaceEstimator, climb: Segment
    ) -> None:
        assert estimate_mph(estimator.estimate_segment(climb)) < 2.7

    def test_talus_is_slower_than_tread(self, estimator: PaceEstimator, climb: Segment) -> None:
        on_tread = estimator.estimate_segment(climb)
        rough = Segment(
            start=climb.start,
            end=climb.end,
            gain=climb.gain,
            loss=climb.loss,
            surface=Surface.TALUS,
        )
        assert estimator.estimate_segment(rough).moving_time > on_tread.moving_time

    def test_a_heavier_pack_is_slower(self, estimator: PaceEstimator, climb: Segment) -> None:
        light = estimator.estimate_segment(climb, carried=Mass.pounds(20.0))
        heavy = estimator.estimate_segment(climb, carried=Mass.pounds(40.0))
        assert heavy.moving_time > light.moving_time

    def test_the_reference_load_is_the_default(
        self, estimator: PaceEstimator, climb: Segment
    ) -> None:
        default = estimator.estimate_segment(climb)
        explicit = estimator.estimate_segment(climb, carried=Mass.pounds(26.0))
        assert default.moving_time.in_seconds == pytest.approx(explicit.moving_time.in_seconds)

    def test_fatigue_slows_the_estimate(self, estimator: PaceEstimator, climb: Segment) -> None:
        fresh = estimator.estimate_segment(climb, state=FatigueState())
        tired = estimator.estimate_segment(
            climb, state=FatigueState(day=9, fatigue=0.20, conditioning=0.05)
        )
        assert tired.moving_time > fresh.moving_time

    def test_altitude_slows_the_estimate(self, estimator: PaceEstimator) -> None:
        low = Segment(
            start=wp("a", "A", 0.0, 3000),
            end=wp("b", "B", 3.0, 3000),
            gain=Distance.zero(),
            loss=Distance.zero(),
        )
        high = Segment(
            start=wp("c", "C", 0.0, 12000),
            end=wp("d", "D", 3.0, 12000),
            gain=Distance.zero(),
            loss=Distance.zero(),
        )
        assert (
            estimator.estimate_segment(high).moving_time
            > estimator.estimate_segment(low).moving_time
        )


class TestEstimateSpan:
    def test_a_whole_segment_span_matches_the_segment_estimate(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        segment = corridor.segments[4]
        span = estimator.estimate_span(corridor, segment.start.mile, segment.end.mile)
        assert span.distance.in_miles == pytest.approx(segment.length.in_miles)
        assert span.gain.in_feet == pytest.approx(segment.gain.in_feet)

    def test_a_partial_span_prorates_the_climb(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        half = estimator.estimate_span(corridor, 8.7, 10.3)
        assert half.gain.in_feet == pytest.approx(310, abs=1.0)

    def test_spans_compose(self, estimator: PaceEstimator, corridor: Corridor) -> None:
        whole = estimator.estimate_span(corridor, 0.0, 23.6)
        first = estimator.estimate_span(corridor, 0.0, 11.9)
        second = estimator.estimate_span(corridor, 11.9, 23.6)
        assert whole.moving_time.in_hours == pytest.approx(
            first.moving_time.in_hours + second.moving_time.in_hours, rel=1e-6
        )

    def test_an_empty_span_is_empty(self, estimator: PaceEstimator, corridor: Corridor) -> None:
        assert estimator.estimate_span(corridor, 12.0, 12.0) == LegEstimate.empty()

    def test_a_reversed_span_is_refused(self, estimator: PaceEstimator, corridor: Corridor) -> None:
        with pytest.raises(PaceModelError, match="must advance"):
            estimator.estimate_span(corridor, 20.0, 10.0)

    def test_a_full_corridor_day_lands_in_a_believable_range(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        day = estimator.estimate_span(corridor, 0.0, 15.3)
        assert 5.0 < day.elapsed_time.in_hours < 11.0
        assert 1.4 < day.average_mph < 2.8


class TestReachableMile:
    def test_no_budget_means_no_progress(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        assert estimator.reachable_mile(corridor, 5.0, Duration.zero()) == pytest.approx(5.0)

    def test_a_generous_budget_reaches_the_end(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        far = estimator.reachable_mile(corridor, 0.0, Duration.hours(200.0))
        assert far == pytest.approx(corridor.end_mile)

    def test_the_time_to_the_reached_mile_matches_the_budget(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        budget = Duration.hours(7.0)
        reached = estimator.reachable_mile(corridor, 0.0, budget)
        spent = estimator.estimate_span(corridor, 0.0, reached).moving_time
        assert spent.in_hours == pytest.approx(7.0, abs=0.15)

    def test_a_bigger_budget_reaches_further(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        short = estimator.reachable_mile(corridor, 0.0, Duration.hours(4.0))
        long = estimator.reachable_mile(corridor, 0.0, Duration.hours(8.0))
        assert long > short

    def test_a_tired_hiker_reaches_less_far(
        self, estimator: PaceEstimator, corridor: Corridor
    ) -> None:
        fresh = estimator.reachable_mile(corridor, 0.0, Duration.hours(8.0))
        tired = estimator.reachable_mile(
            corridor, 0.0, Duration.hours(8.0), state=FatigueState(day=14, fatigue=0.25)
        )
        assert tired < fresh


def estimate_mph(estimate: LegEstimate) -> float:
    return estimate.average_mph
