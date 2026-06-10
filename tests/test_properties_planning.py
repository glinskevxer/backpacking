"""Properties the corridor, the index and the solver have to hold.

These generate whole corridors rather than single values, because the invariants
that matter are structural: a plan tiles the route, an index answers consistently,
a slice is still a corridor.
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.solver import PlanRequest, solve, stop_miles
from backpacking.trail.corridor import Corridor
from backpacking.trail.index import MileIndex
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance

SLOW = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@st.composite
def mile_lists(draw, min_size: int = 2, max_size: int = 25) -> list[float]:
    """Strictly ascending mile keys."""
    gaps = draw(
        st.lists(
            st.floats(min_value=0.2, max_value=12.0, allow_nan=False),
            min_size=min_size - 1,
            max_size=max_size - 1,
        )
    )
    miles = [0.0]
    for gap in gaps:
        miles.append(round(miles[-1] + gap, 3))
    return miles


@st.composite
def corridors(draw) -> Corridor:
    """A corridor of a few waypoints with plausible elevations."""
    miles = draw(mile_lists(min_size=4, max_size=14))
    elevations = draw(
        st.lists(
            st.floats(min_value=1000.0, max_value=13000.0, allow_nan=False),
            min_size=len(miles),
            max_size=len(miles),
        )
    )
    kinds = draw(
        st.lists(
            st.sampled_from(
                [
                    WaypointKind.CAMPSITE,
                    WaypointKind.WATER,
                    WaypointKind.LANDMARK,
                    WaypointKind.PASS,
                ]
            ),
            min_size=len(miles),
            max_size=len(miles),
        )
    )
    waypoints = [
        Waypoint(
            id=f"point-{index:03d}",
            name=f"Point {index}",
            mile=mile,
            elevation=Distance.feet(elevation),
            kind=kind,
        )
        for index, (mile, elevation, kind) in enumerate(
            zip(miles, elevations, kinds, strict=True)
        )
    ]
    return Corridor.from_waypoints("Generated", waypoints)


class TestMileIndexProperties:
    @given(mile_lists())
    def test_the_interval_always_brackets_the_mile(self, miles: list[float]) -> None:
        index = MileIndex(miles)
        for probe in miles:
            interval = index.interval_for(probe)
            assert 0 <= interval <= max(0, len(miles) - 2)

    @given(mile_lists())
    def test_nearest_returns_a_valid_position(self, miles: list[float]) -> None:
        index = MileIndex(miles)
        for probe in (miles[0] - 5.0, miles[-1] + 5.0, sum(miles) / len(miles)):
            assert 0 <= index.nearest(probe) < len(miles)

    @given(mile_lists())
    def test_an_exact_key_is_its_own_nearest(self, miles: list[float]) -> None:
        index = MileIndex(miles)
        for position, mile in enumerate(miles):
            assert index.nearest(mile) == position

    @given(mile_lists())
    def test_a_bracket_on_a_key_is_exact(self, miles: list[float]) -> None:
        index = MileIndex(miles)
        for mile in miles:
            assert index.bracket(mile).exact

    @given(mile_lists())
    def test_first_after_is_strictly_greater(self, miles: list[float]) -> None:
        index = MileIndex(miles)
        for mile in miles:
            position = index.first_after(mile)
            if position is not None:
                assert miles[position] > mile

    @given(mile_lists())
    def test_the_span_of_everything_is_everything(self, miles: list[float]) -> None:
        index = MileIndex(miles)
        left, right = index.span(miles[0], miles[-1])
        assert (left, right) == (0, len(miles))

    @given(mile_lists())
    def test_the_fraction_is_always_within_the_unit_interval(
        self, miles: list[float]
    ) -> None:
        index = MileIndex(miles)
        for probe in (miles[0], miles[-1], (miles[0] + miles[-1]) / 2.0):
            _, fraction = index.fraction_within(probe)
            assert 0.0 <= fraction <= 1.0


class TestCorridorProperties:
    @given(corridors())
    def test_a_corridor_is_always_in_mile_order(self, corridor: Corridor) -> None:
        miles = [w.mile for w in corridor]
        assert miles == sorted(miles)

    @given(corridors())
    def test_segments_trail_waypoints_by_one(self, corridor: Corridor) -> None:
        assert len(corridor.segments) == len(corridor) - 1

    @given(corridors())
    def test_gain_minus_loss_matches_the_terminus_difference(
        self, corridor: Corridor
    ) -> None:
        net = corridor.total_gain().in_feet - corridor.total_loss().in_feet
        expected = (
            corridor.waypoints[-1].elevation.in_feet - corridor.waypoints[0].elevation.in_feet
        )
        assert net == pytest.approx(expected, abs=0.5)

    @given(corridors())
    def test_elevation_at_a_waypoint_is_the_stored_one(self, corridor: Corridor) -> None:
        for waypoint in corridor:
            assert corridor.elevation_at(waypoint.mile).in_feet == pytest.approx(
                waypoint.elevation.in_feet
            )

    @given(corridors())
    def test_a_whole_span_gain_equals_the_total(self, corridor: Corridor) -> None:
        spanning = corridor.gain_between(corridor.start_mile, corridor.end_mile)
        assert spanning.in_feet == pytest.approx(corridor.total_gain().in_feet, abs=0.5)

    @given(corridors())
    def test_prorated_gain_is_never_more_than_the_total(self, corridor: Corridor) -> None:
        middle = (corridor.start_mile + corridor.end_mile) / 2.0
        part = corridor.gain_between(corridor.start_mile, middle)
        assert part.in_feet <= corridor.total_gain().in_feet + 0.5

    @given(corridors())
    def test_a_slice_is_still_a_valid_corridor(self, corridor: Corridor) -> None:
        piece = corridor.slice(corridor.start_mile, corridor.end_mile)
        assert len(piece.segments) == len(piece) - 1
        assert piece.start_mile == pytest.approx(corridor.start_mile)


class TestSolverProperties:
    @given(corridors())
    @SLOW
    def test_a_plan_tiles_the_route(self, corridor: Corridor) -> None:
        profile = HikerProfile(flat_pace_mph=3.0)
        try:
            plan = solve(
                PlanRequest(
                    corridor=corridor,
                    profile=profile,
                    start_date=date(2025, 7, 20),
                    constraints=PlanConstraints(min_daily_miles=0.5, max_daily_miles=60.0),
                )
            )
        except PlanInfeasible:
            return
        assert plan.days[0].start_mile == pytest.approx(corridor.start_mile)
        assert plan.days[-1].end_mile == pytest.approx(corridor.end_mile)
        for first, second in zip(plan.days, plan.days[1:], strict=False):
            assert first.end_mile == pytest.approx(second.start_mile)

    @given(corridors())
    @SLOW
    def test_every_day_respects_the_mileage_cap(self, corridor: Corridor) -> None:
        limits = PlanConstraints(min_daily_miles=0.5, max_daily_miles=9.0)
        try:
            plan = solve(
                PlanRequest(
                    corridor=corridor,
                    profile=HikerProfile(flat_pace_mph=3.0),
                    start_date=date(2025, 7, 20),
                    constraints=limits,
                )
            )
        except PlanInfeasible:
            return
        assert all(day.miles <= 9.0 + 1e-6 for day in plan)

    @given(corridors())
    @SLOW
    def test_the_stop_graph_starts_and_ends_on_the_route(self, corridor: Corridor) -> None:
        request = PlanRequest(
            corridor=corridor,
            profile=HikerProfile(),
            start_date=date(2025, 7, 20),
        )
        miles = stop_miles(request)
        assert miles[0] == pytest.approx(corridor.start_mile)
        assert miles[-1] == pytest.approx(corridor.end_mile)
        assert list(miles) == sorted(miles)

    @given(corridors())
    @SLOW
    def test_dates_always_advance(self, corridor: Corridor) -> None:
        try:
            plan = solve(
                PlanRequest(
                    corridor=corridor,
                    profile=HikerProfile(),
                    start_date=date(2025, 7, 20),
                    constraints=PlanConstraints(min_daily_miles=0.5, max_daily_miles=60.0),
                )
            )
        except PlanInfeasible:
            return
        dates = [day.day for day in plan]
        assert dates == sorted(dates)
        assert len(set(dates)) == len(dates)
