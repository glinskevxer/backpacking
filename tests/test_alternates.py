"""Alternate validation and route splicing."""

from __future__ import annotations

import pytest

from backpacking.errors import RouteResolutionError
from backpacking.trail.alternates import (
    Alternate,
    bypassed_span,
    mileage_delta,
    resolve_route,
)
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import WaypointKind
from tests.conftest import wp

# Replaces the 11.9 to 18.0 stretch with a 9.4 mile high route: 3.3 miles longer.
HIGH_ROUTE = Alternate(
    id="crystal-high-route",
    name="Crystal High Route",
    departs_at="mosquito-pass",
    rejoins_at="rubicon-spring",
    length_miles=9.4,
    waypoints=(
        wp("pyramid-saddle", "Pyramid Saddle", 3.1, 9240, WaypointKind.PASS),
        wp("crystal-tarn", "Crystal Tarn", 6.0, 8850, WaypointKind.WATER, tags={"seasonal"}),
    ),
    official=False,
    tags=frozenset({"exposed", "class2"}),
)

# Replaces the 40.1 to 49.3 stretch with a 6.0 mile road walk: 3.2 miles shorter.
FIRE_DETOUR = Alternate(
    id="whiskey-fire-detour",
    name="Whiskey Fire Detour",
    departs_at="five-lakes-creek",
    rejoins_at="mule-ear-pass",
    length_miles=6.0,
    waypoints=(wp("forest-road-16", "Forest Road 16", 2.5, 7000, WaypointKind.ROAD),),
    official=True,
)


class TestAlternateValidation:
    def test_a_valid_alternate_keeps_its_fields(self) -> None:
        assert HIGH_ROUTE.length.in_miles == pytest.approx(9.4)
        assert HIGH_ROUTE.has_tag("exposed")
        assert not HIGH_ROUTE.official
        assert FIRE_DETOUR.official

    def test_length_must_be_positive(self) -> None:
        with pytest.raises(RouteResolutionError, match="length must be positive"):
            Alternate(id="a", name="A", departs_at="x", rejoins_at="y", length_miles=0.0)

    def test_it_must_rejoin_somewhere_else(self) -> None:
        with pytest.raises(RouteResolutionError, match="different waypoint"):
            Alternate(id="a", name="A", departs_at="x", rejoins_at="x", length_miles=2.0)

    def test_interior_offsets_must_fall_inside(self) -> None:
        with pytest.raises(RouteResolutionError, match="inside the alternate"):
            Alternate(
                id="a",
                name="A",
                departs_at="x",
                rejoins_at="y",
                length_miles=4.0,
                waypoints=(wp("far", "Far", 9.0, 7000),),
            )

    def test_an_offset_at_zero_is_outside(self) -> None:
        with pytest.raises(RouteResolutionError, match="inside the alternate"):
            Alternate(
                id="a",
                name="A",
                departs_at="x",
                rejoins_at="y",
                length_miles=4.0,
                waypoints=(wp("start", "Start", 0.0, 7000),),
            )

    def test_interior_offsets_must_ascend(self) -> None:
        with pytest.raises(RouteResolutionError, match="must ascend"):
            Alternate(
                id="a",
                name="A",
                departs_at="x",
                rejoins_at="y",
                length_miles=8.0,
                waypoints=(wp("b", "B", 5.0, 7000), wp("c", "C", 2.0, 7000)),
            )

    def test_repr_reads_as_a_branch(self) -> None:
        assert repr(FIRE_DETOUR) == (
            "Alternate('whiskey-fire-detour', five-lakes-creek -> mule-ear-pass, 6.0 mi)"
        )


class TestSpanAndDelta:
    def test_the_bypassed_span_comes_from_the_corridor(self, corridor: Corridor) -> None:
        assert bypassed_span(corridor, HIGH_ROUTE) == (pytest.approx(11.9), pytest.approx(18.0))

    def test_a_longer_alternate_reports_a_positive_delta(self, corridor: Corridor) -> None:
        assert mileage_delta(corridor, HIGH_ROUTE).in_miles == pytest.approx(3.3)

    def test_a_shorter_alternate_reports_a_negative_delta(self, corridor: Corridor) -> None:
        assert mileage_delta(corridor, FIRE_DETOUR).in_miles == pytest.approx(-3.2)

    def test_a_backwards_alternate_is_refused(self, corridor: Corridor) -> None:
        backwards = Alternate(
            id="backwards",
            name="Backwards",
            departs_at="rubicon-spring",
            rejoins_at="mosquito-pass",
            length_miles=5.0,
        )
        with pytest.raises(RouteResolutionError, match="rejoins before it departs"):
            bypassed_span(corridor, backwards)


class TestResolveRoute:
    def test_choosing_nothing_leaves_the_corridor_alone(self, corridor: Corridor) -> None:
        result = resolve_route(corridor, [HIGH_ROUTE], [])
        assert result.corridor.waypoints == corridor.waypoints
        assert result.delta.in_miles == pytest.approx(0.0)
        assert result.chosen == ()

    def test_a_longer_alternate_lengthens_the_route(self, corridor: Corridor) -> None:
        result = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"])
        assert result.delta.in_miles == pytest.approx(3.3)
        assert result.corridor.length.in_miles == pytest.approx(81.3)
        assert not result.is_shorter

    def test_interior_waypoints_are_anchored_after_the_departure(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        assert route.waypoint("pyramid-saddle").mile == pytest.approx(15.0)
        assert route.waypoint("crystal-tarn").mile == pytest.approx(17.9)

    def test_the_bypassed_waypoints_are_gone(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        assert not route.has_waypoint("clyde-basin")
        assert route.has_waypoint("mosquito-pass")
        assert route.has_waypoint("rubicon-spring")

    def test_everything_after_the_rejoin_shifts(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        assert route.waypoint("rubicon-spring").mile == pytest.approx(21.3)
        assert route.waypoint("barker-road").mile == pytest.approx(26.9)
        assert route.waypoint("donner-pass").mile == pytest.approx(81.3)

    def test_everything_before_the_departure_is_untouched(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        assert route.waypoint("haypress-camp").mile == pytest.approx(5.1)
        assert route.waypoint("mosquito-pass").mile == pytest.approx(11.9)

    def test_a_shorter_alternate_pulls_the_route_in(self, corridor: Corridor) -> None:
        result = resolve_route(corridor, [FIRE_DETOUR], ["whiskey-fire-detour"])
        assert result.is_shorter
        assert result.corridor.length.in_miles == pytest.approx(74.8)
        assert result.corridor.waypoint("donner-pass").mile == pytest.approx(74.8)

    def test_two_disjoint_alternates_compose(self, corridor: Corridor) -> None:
        result = resolve_route(
            corridor,
            [HIGH_ROUTE, FIRE_DETOUR],
            ["whiskey-fire-detour", "crystal-high-route"],
        )
        assert result.delta.in_miles == pytest.approx(0.1)
        assert result.corridor.length.in_miles == pytest.approx(78.1)
        assert result.chosen == ("crystal-high-route", "whiskey-fire-detour")

    def test_composition_keeps_both_sets_of_interior_points(self, corridor: Corridor) -> None:
        route = resolve_route(
            corridor, [HIGH_ROUTE, FIRE_DETOUR], ["crystal-high-route", "whiskey-fire-detour"]
        ).corridor
        assert route.has_waypoint("pyramid-saddle")
        assert route.has_waypoint("forest-road-16")
        assert not route.has_waypoint("whiskey-flat")

    def test_the_route_stays_a_valid_corridor(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        miles = [w.mile for w in route]
        assert miles == sorted(miles)
        assert len(route.segments) == len(route.waypoints) - 1

    def test_surviving_segments_keep_their_measured_profile(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        original = next(s for s in corridor.segments if s.start.id == "haypress-camp")
        spliced = next(s for s in route.segments if s.start.id == "haypress-camp")
        assert spliced.gain.in_feet == pytest.approx(original.gain.in_feet)
        assert spliced.surface is original.surface

    def test_new_segments_are_derived_from_the_spot_elevations(self, corridor: Corridor) -> None:
        route = resolve_route(corridor, [HIGH_ROUTE], ["crystal-high-route"]).corridor
        leg = next(s for s in route.segments if s.start.id == "mosquito-pass")
        assert leg.end.id == "pyramid-saddle"
        assert leg.gain.in_feet == pytest.approx(620)
        assert leg.loss.in_feet == pytest.approx(0)

    def test_an_unknown_alternate_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(RouteResolutionError, match="no such alternate"):
            resolve_route(corridor, [HIGH_ROUTE], ["nonexistent"])

    def test_overlapping_alternates_are_refused(self, corridor: Corridor) -> None:
        overlapping = Alternate(
            id="overlap",
            name="Overlap",
            departs_at="clyde-basin",
            rejoins_at="barker-road",
            length_miles=7.0,
        )
        with pytest.raises(RouteResolutionError, match="overlap on the corridor"):
            resolve_route(
                corridor, [HIGH_ROUTE, overlapping], ["crystal-high-route", "overlap"]
            )

    def test_abutting_alternates_are_allowed(self, corridor: Corridor) -> None:
        second = Alternate(
            id="rubicon-bypass",
            name="Rubicon Bypass",
            departs_at="rubicon-spring",
            rejoins_at="barker-road",
            length_miles=4.0,
        )
        result = resolve_route(
            corridor, [HIGH_ROUTE, second], ["crystal-high-route", "rubicon-bypass"]
        )
        assert result.delta.in_miles == pytest.approx(3.3 - 1.6)
        assert [w.id for w in result.corridor].count("rubicon-spring") == 1
