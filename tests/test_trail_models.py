"""Waypoint and segment invariants."""

from __future__ import annotations

import pytest
from tests.conftest import wp

from backpacking.errors import CorridorError
from backpacking.geo import GeoPoint
from backpacking.trail.models import Segment, Surface, Waypoint, WaypointKind
from backpacking.units import Distance


class TestWaypointKind:
    def test_only_campsites_and_shelters_allow_camping(self) -> None:
        camps = {k for k in WaypointKind if k.can_camp}
        assert camps == {WaypointKind.CAMPSITE, WaypointKind.SHELTER}

    def test_exits_are_the_places_a_hiker_can_leave(self) -> None:
        exits = {k for k in WaypointKind if k.is_exit}
        assert exits == {WaypointKind.TRAILHEAD, WaypointKind.ROAD, WaypointKind.RESUPPLY}

    def test_kinds_serialise_as_their_string_value(self) -> None:
        assert WaypointKind.WATER == "water"
        assert f"{WaypointKind.PASS}" == "pass"


class TestSurface:
    def test_road_is_faster_than_tread_and_talus_is_slower(self) -> None:
        assert Surface.ROAD.pace_factor > Surface.TREAD.pace_factor
        assert Surface.TALUS.pace_factor < Surface.TREAD.pace_factor

    def test_every_surface_has_a_positive_factor(self) -> None:
        for surface in Surface:
            assert 0.0 < surface.pace_factor <= 1.2

    def test_bushwhack_is_the_slowest(self) -> None:
        slowest = min(Surface, key=lambda s: s.pace_factor)
        assert slowest is Surface.BUSHWHACK


class TestWaypointValidation:
    @pytest.mark.parametrize("bad_id", ["Echo", "echo_lake", "echo lake", "-echo", "echo-", ""])
    def test_id_must_be_a_slug(self, bad_id: str) -> None:
        with pytest.raises(CorridorError, match="hyphenated slug"):
            wp(bad_id, "Echo", 1.0, 7000)

    def test_name_must_not_be_blank(self) -> None:
        with pytest.raises(CorridorError, match="must not be blank"):
            wp("echo", "   ", 1.0, 7000)

    def test_mile_must_not_be_negative(self) -> None:
        with pytest.raises(CorridorError, match="must not be negative"):
            wp("echo", "Echo", -0.1, 7000)

    def test_a_valid_waypoint_keeps_its_fields(self) -> None:
        point = Waypoint(
            id="mosquito-pass",
            name="Mosquito Pass",
            mile=11.9,
            elevation=Distance.feet(8620),
            kind=WaypointKind.PASS,
            position=GeoPoint(38.86, -120.13),
            notes="wind exposed",
            tags=frozenset({"exposed"}),
        )
        assert point.elevation.in_feet == pytest.approx(8620)
        assert point.has_tag("exposed")
        assert not point.has_tag("water")
        assert not point.can_camp

    def test_with_mile_reanchors_and_keeps_everything_else(self) -> None:
        original = wp("clyde-basin", "Clyde Basin", 15.3, 8040, WaypointKind.CAMPSITE, tags={"a"})
        moved = original.with_mile(115.3)
        assert moved.mile == pytest.approx(115.3)
        assert moved.id == original.id
        assert moved.kind is original.kind
        assert moved.tags == original.tags
        assert original.mile == pytest.approx(15.3)

    def test_waypoints_are_hashable_and_comparable(self) -> None:
        first = wp("a", "A", 1.0, 100)
        again = wp("a", "A", 1.0, 100)
        assert first == again
        assert len({first, again}) == 1

    def test_repr_names_the_mile_and_kind(self) -> None:
        assert repr(wp("a", "A", 1.25, 100, WaypointKind.WATER)) == "Waypoint('a' @ 1.2 mi, water)"


class TestSegment:
    @pytest.fixture
    def leg(self) -> Segment:
        return Segment(
            start=wp("low", "Low", 10.0, 7000),
            end=wp("high", "High", 13.0, 8320),
            gain=Distance.feet(1500),
            loss=Distance.feet(180),
            surface=Surface.TALUS,
        )

    def test_length_comes_from_the_mile_delta(self, leg: Segment) -> None:
        assert leg.length.in_miles == pytest.approx(3.0)

    def test_net_change_is_the_elevation_difference(self, leg: Segment) -> None:
        assert leg.net_elevation_change.in_feet == pytest.approx(1320)

    def test_average_grade_is_rise_over_run(self, leg: Segment) -> None:
        expected = Distance.feet(1320).in_meters / Distance.miles(3.0).in_meters
        assert leg.average_grade == pytest.approx(expected)

    def test_roughness_is_gain_plus_loss_per_mile(self, leg: Segment) -> None:
        assert leg.roughness == pytest.approx((1500 + 180) / 3.0)

    def test_contains_mile_covers_both_ends(self, leg: Segment) -> None:
        assert leg.contains_mile(10.0)
        assert leg.contains_mile(11.5)
        assert leg.contains_mile(13.0)
        assert not leg.contains_mile(13.01)

    def test_a_segment_must_advance(self) -> None:
        with pytest.raises(CorridorError, match="must advance"):
            Segment(
                start=wp("b", "B", 5.0, 100),
                end=wp("a", "A", 3.0, 100),
                gain=Distance.zero(),
                loss=Distance.zero(),
            )

    def test_gain_and_loss_are_magnitudes(self) -> None:
        with pytest.raises(CorridorError, match="must not be negative"):
            Segment(
                start=wp("a", "A", 1.0, 100),
                end=wp("b", "B", 2.0, 100),
                gain=Distance.feet(-10),
                loss=Distance.zero(),
            )

    def test_repr_shows_the_profile(self, leg: Segment) -> None:
        assert repr(leg) == "Segment('low' -> 'high', 3.0 mi, +1500/-180 ft)"
