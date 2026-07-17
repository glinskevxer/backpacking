"""Cost regressions.

These do not assert that the code is fast. They assert that it has not become
quadratic in something it used to be linear in, which is the failure that
actually happens: a corridor grows from twenty waypoints to two thousand and a
lookup that was a bisect turns into a scan.

The thresholds are deliberately loose. A slow CI runner should not fail them; a
change in complexity should.
"""

from __future__ import annotations

import sys
import time
from datetime import date

import pytest

from backpacking.pace.estimator import PaceEstimator
from backpacking.pace.models import HikerProfile
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.solver import PlanRequest, solve
from backpacking.trail.corridor import Corridor
from backpacking.trail.index import MileIndex
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance

pytestmark = [
    pytest.mark.benchmark,
    # A tracer multiplies every call by an order of magnitude and does not do it
    # evenly, so a timing ratio measured under coverage says nothing about the
    # code. Skipping is honest; loosening the thresholds until they pass under a
    # tracer would leave them unable to catch anything.
    pytest.mark.skipif(
        sys.gettrace() is not None,
        reason="timing comparisons are meaningless under a tracer",
    ),
]

START = date(2025, 7, 20)


def synthetic_corridor(points: int, *, spacing: float = 0.5) -> Corridor:
    """A long corridor with a gentle saw tooth profile."""
    waypoints = [
        Waypoint(
            id=f"p{index:05d}",
            name=f"Point {index}",
            mile=round(index * spacing, 3),
            elevation=Distance.feet(6000 + 400 * ((index % 8) - 4)),
            kind=WaypointKind.CAMPSITE if index % 6 == 0 else WaypointKind.LANDMARK,
        )
        for index in range(points)
    ]
    return Corridor.from_waypoints("Synthetic", waypoints)


def elapsed(callable_, repeats: int = 1) -> float:
    started = time.perf_counter()
    for _ in range(repeats):
        callable_()
    return time.perf_counter() - started


class TestIndexScaling:
    def test_lookup_does_not_scale_with_the_index(self) -> None:
        small = MileIndex([i * 0.5 for i in range(200)])
        large = MileIndex([i * 0.5 for i in range(20000)])
        probe_small = elapsed(lambda: [small.interval_for(37.4) for _ in range(2000)])
        probe_large = elapsed(lambda: [large.interval_for(37.4) for _ in range(2000)])
        # A hundredfold more keys must not cost more than fourfold the time.
        assert probe_large < probe_small * 4.0 + 0.05

    def test_nearest_stays_logarithmic(self) -> None:
        small = MileIndex([i * 0.5 for i in range(200)])
        large = MileIndex([i * 0.5 for i in range(20000)])
        probe_small = elapsed(lambda: [small.nearest(37.4) for _ in range(2000)])
        probe_large = elapsed(lambda: [large.nearest(37.4) for _ in range(2000)])
        assert probe_large < probe_small * 4.0 + 0.05


class TestCorridorScaling:
    def test_building_a_large_corridor_is_linear_enough(self) -> None:
        small = elapsed(lambda: synthetic_corridor(500))
        large = elapsed(lambda: synthetic_corridor(4000))
        # Eight times the points, well under sixty four times the work.
        assert large < small * 20.0 + 0.5

    def test_waypoint_lookup_is_constant_time(self) -> None:
        corridor = synthetic_corridor(4000)
        first = elapsed(lambda: [corridor.waypoint("p00001") for _ in range(2000)])
        last = elapsed(lambda: [corridor.waypoint("p03999") for _ in range(2000)])
        assert last < first * 3.0 + 0.05

    def test_elevation_lookup_does_not_scan(self) -> None:
        corridor = synthetic_corridor(4000)
        near = elapsed(lambda: [corridor.elevation_at(1.0) for _ in range(1000)])
        far = elapsed(lambda: [corridor.elevation_at(1900.0) for _ in range(1000)])
        assert far < near * 4.0 + 0.05


class TestEstimatorScaling:
    def test_span_estimation_scales_with_the_span_not_the_corridor(self) -> None:
        short_corridor = synthetic_corridor(400)
        long_corridor = synthetic_corridor(4000)
        estimator = PaceEstimator(profile=HikerProfile())
        on_short = elapsed(lambda: estimator.estimate_span(short_corridor, 0.0, 20.0), repeats=20)
        on_long = elapsed(lambda: estimator.estimate_span(long_corridor, 0.0, 20.0), repeats=20)
        assert on_long < on_short * 4.0 + 0.2


class TestSolverBudget:
    @pytest.mark.slow
    def test_a_long_corridor_solves_in_reasonable_time(self) -> None:
        corridor = synthetic_corridor(240, spacing=0.5)
        started = time.perf_counter()
        plan = solve(
            PlanRequest(
                corridor=corridor,
                profile=HikerProfile(),
                start_date=START,
                constraints=PlanConstraints(min_daily_miles=4.0, max_daily_miles=30.0),
            )
        )
        taken = time.perf_counter() - started
        assert plan.covers_whole_corridor()
        assert taken < 30.0

    def test_the_search_is_quadratic_in_stops_not_worse(self) -> None:
        estimator_profile = HikerProfile()
        limits = PlanConstraints(min_daily_miles=4.0, max_daily_miles=30.0)

        def run(points: int) -> float:
            corridor = synthetic_corridor(points, spacing=0.5)
            started = time.perf_counter()
            solve(
                PlanRequest(
                    corridor=corridor,
                    profile=estimator_profile,
                    start_date=START,
                    constraints=limits,
                )
            )
            return time.perf_counter() - started

        small = run(50)
        large = run(100)
        # Doubling the stops squares the edge count. Anything past a factor of
        # twelve means the per edge cost has grown too.
        assert large < small * 12.0 + 0.5
