"""Corridor construction, lookups and slicing."""

from __future__ import annotations

import pytest

from backpacking.errors import CorridorError, WaypointNotFound
from backpacking.trail.corridor import Corridor, merge_corridors
from backpacking.trail.models import Segment, Surface, WaypointKind
from backpacking.units import Distance
from tests.conftest import wp


class TestConstruction:
    def test_the_reference_corridor_is_seventy_eight_miles(self, corridor: Corridor) -> None:
        assert corridor.start_mile == pytest.approx(0.0)
        assert corridor.end_mile == pytest.approx(78.0)
        assert corridor.length.in_miles == pytest.approx(78.0)

    def test_segment_count_trails_waypoint_count_by_one(self, corridor: Corridor) -> None:
        assert len(corridor.segments) == len(corridor.waypoints) - 1
        assert len(corridor) == 20

    def test_iteration_yields_waypoints_in_mile_order(self, corridor: Corridor) -> None:
        miles = [w.mile for w in corridor]
        assert miles == sorted(miles)

    def test_from_waypoints_sorts_and_derives_the_profile(self) -> None:
        built = Corridor.from_waypoints(
            "Unsorted",
            [
                wp("c", "C", 8.0, 6000),
                wp("a", "A", 0.0, 5000),
                wp("b", "B", 3.0, 7000),
            ],
        )
        assert [w.id for w in built] == ["a", "b", "c"]
        assert built.segments[0].gain.in_feet == pytest.approx(2000)
        assert built.segments[0].loss.in_feet == pytest.approx(0)
        assert built.segments[1].gain.in_feet == pytest.approx(0)
        assert built.segments[1].loss.in_feet == pytest.approx(1000)

    def test_from_waypoints_accepts_a_surface_override(self) -> None:
        built = Corridor.from_waypoints(
            "Surfaced",
            [wp("a", "A", 0.0, 100), wp("b", "B", 2.0, 200)],
            surfaces={"a": Surface.SNOWFIELD},
        )
        assert built.segments[0].surface is Surface.SNOWFIELD

    def test_two_waypoints_are_the_minimum(self) -> None:
        with pytest.raises(CorridorError, match="at least two waypoints"):
            Corridor.from_waypoints("Lonely", [wp("a", "A", 0.0, 100)])

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(CorridorError, match="duplicate waypoint id"):
            Corridor.from_waypoints("Dup", [wp("a", "A", 0.0, 100), wp("a", "A2", 4.0, 200)])

    def test_repeated_miles_are_refused_by_the_segment_check(self) -> None:
        with pytest.raises(CorridorError, match="must advance"):
            Corridor.from_waypoints("Same", [wp("a", "A", 4.0, 100), wp("b", "B", 4.0, 200)])

    def test_the_corridor_also_refuses_waypoints_that_do_not_advance(self) -> None:
        legal = Segment(
            start=wp("a", "A", 3.0, 100),
            end=wp("b", "B", 4.0, 200),
            gain=Distance.feet(100),
            loss=Distance.zero(),
        )
        with pytest.raises(CorridorError, match="strictly increasing"):
            Corridor(
                name="Same",
                waypoints=(wp("a", "A", 4.0, 100), wp("b", "B", 4.0, 200)),
                segments=(legal,),
            )

    def test_segment_count_mismatch_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(CorridorError, match="one less than waypoint count"):
            Corridor(
                name=corridor.name,
                waypoints=corridor.waypoints,
                segments=corridor.segments[:-1],
            )


class TestLookups:
    def test_waypoint_by_id(self, corridor: Corridor) -> None:
        assert corridor.waypoint("mosquito-pass").mile == pytest.approx(11.9)

    def test_unknown_id_raises(self, corridor: Corridor) -> None:
        with pytest.raises(WaypointNotFound, match="no such waypoint"):
            corridor.waypoint("nonexistent")

    def test_has_waypoint(self, corridor: Corridor) -> None:
        assert corridor.has_waypoint("donner-pass")
        assert not corridor.has_waypoint("donner-lake")

    def test_of_kind_filters(self, corridor: Corridor) -> None:
        water = corridor.of_kind(WaypointKind.WATER)
        assert [w.id for w in water] == [
            "tamarack-creek",
            "lake-aloha-inlet",
            "rubicon-spring",
            "five-lakes-creek",
            "basin-outlet",
        ]

    def test_of_kind_accepts_several_kinds(self, corridor: Corridor) -> None:
        camps = corridor.of_kind(WaypointKind.CAMPSITE, WaypointKind.SHELTER)
        assert len(camps) == 6
        assert all(w.can_camp for w in camps)

    def test_tagged_filters(self, corridor: Corridor) -> None:
        assert [w.id for w in corridor.tagged("hitch")] == ["barker-road", "soda-springs"]

    def test_segment_at_finds_the_containing_leg(self, corridor: Corridor) -> None:
        segment = corridor.segment_at(13.0)
        assert segment.start.id == "mosquito-pass"
        assert segment.end.id == "clyde-basin"

    def test_segment_at_a_boundary_takes_the_later_leg(self, corridor: Corridor) -> None:
        assert corridor.segment_at(11.9).start.id == "mosquito-pass"

    def test_segment_at_the_far_end_stays_in_range(self, corridor: Corridor) -> None:
        assert corridor.segment_at(78.0).end.id == "donner-pass"

    def test_a_mile_off_the_corridor_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(CorridorError, match="outside the corridor"):
            corridor.segment_at(120.0)

    def test_nearest_waypoint_picks_the_closer_side(self, corridor: Corridor) -> None:
        assert corridor.nearest_waypoint(12.1).id == "mosquito-pass"
        assert corridor.nearest_waypoint(15.0).id == "clyde-basin"

    def test_nearest_waypoint_at_the_ends(self, corridor: Corridor) -> None:
        assert corridor.nearest_waypoint(0.0).id == "echo-trailhead"
        assert corridor.nearest_waypoint(78.0).id == "donner-pass"

    def test_next_waypoint_is_strictly_ahead(self, corridor: Corridor) -> None:
        following = corridor.next_waypoint(11.9)
        assert following is not None
        assert following.id == "clyde-basin"

    def test_next_waypoint_can_filter_by_kind(self, corridor: Corridor) -> None:
        water = corridor.next_waypoint(19.0, kind=WaypointKind.WATER)
        assert water is not None
        assert water.id == "five-lakes-creek"

    def test_next_waypoint_returns_none_past_the_end(self, corridor: Corridor) -> None:
        assert corridor.next_waypoint(78.0) is None

    def test_waypoints_between_is_inclusive(self, corridor: Corridor) -> None:
        span = corridor.waypoints_between(11.9, 18.0)
        assert [w.id for w in span] == ["mosquito-pass", "clyde-basin", "rubicon-spring"]

    def test_waypoints_between_refuses_a_reversed_range(self, corridor: Corridor) -> None:
        with pytest.raises(CorridorError, match="precedes start mile"):
            corridor.waypoints_between(20.0, 10.0)


class TestElevation:
    def test_at_an_anchor_the_stored_elevation_is_returned(self, corridor: Corridor) -> None:
        assert corridor.elevation_at(11.9).in_feet == pytest.approx(8620)

    def test_between_anchors_it_interpolates(self, short_corridor: Corridor) -> None:
        assert short_corridor.elevation_at(2.0).in_feet == pytest.approx(5600)

    def test_at_the_terminus(self, corridor: Corridor) -> None:
        assert corridor.elevation_at(78.0).in_feet == pytest.approx(7090)

    def test_outside_the_corridor_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(CorridorError, match="outside the corridor"):
            corridor.elevation_at(-1.0)


class TestAggregates:
    def test_total_gain_and_loss_sum_the_segments(self, corridor: Corridor) -> None:
        assert corridor.total_gain().in_feet == pytest.approx(9490)
        assert corridor.total_loss().in_feet == pytest.approx(9820)

    def test_the_net_matches_the_terminus_difference(self, corridor: Corridor) -> None:
        net = corridor.total_gain().in_feet - corridor.total_loss().in_feet
        assert net == pytest.approx(7090 - 7420, abs=1.0)

    def test_gain_over_a_whole_segment_is_the_segment_gain(self, corridor: Corridor) -> None:
        assert corridor.gain_between(8.7, 11.9).in_feet == pytest.approx(620)

    def test_gain_is_prorated_across_a_partial_segment(self, corridor: Corridor) -> None:
        half = corridor.gain_between(8.7, 10.3)
        assert half.in_feet == pytest.approx(310, abs=1.0)

    def test_loss_over_a_descent(self, corridor: Corridor) -> None:
        assert corridor.loss_between(11.9, 15.3).in_feet == pytest.approx(820)

    def test_an_empty_range_contributes_nothing(self, corridor: Corridor) -> None:
        assert corridor.gain_between(12.0, 12.0).in_feet == pytest.approx(0.0)

    def test_segments_between_clips_to_the_overlap(self, corridor: Corridor) -> None:
        segments = corridor.segments_between(9.0, 12.5)
        assert [s.start.id for s in segments] == ["lake-aloha-inlet", "mosquito-pass"]

    def test_whole_corridor_gain_matches_the_total(self, corridor: Corridor) -> None:
        spanning = corridor.gain_between(corridor.start_mile, corridor.end_mile)
        assert spanning.in_feet == pytest.approx(corridor.total_gain().in_feet)


class TestSlicing:
    def test_slice_keeps_the_anchored_waypoints(self, corridor: Corridor) -> None:
        piece = corridor.slice(23.6, 44.7)
        assert piece.waypoints[0].id == "barker-road"
        assert piece.waypoints[-1].id == "whiskey-flat"
        assert len(piece.segments) == len(piece.waypoints) - 1

    def test_slice_preserves_absolute_mileage(self, corridor: Corridor) -> None:
        piece = corridor.slice(23.6, 44.7)
        assert piece.start_mile == pytest.approx(23.6)
        assert piece.length.in_miles == pytest.approx(21.1)

    def test_a_slice_with_one_anchor_is_refused(self, corridor: Corridor) -> None:
        with pytest.raises(CorridorError, match="two anchored waypoints"):
            corridor.slice(12.0, 13.0)

    def test_renaming_leaves_the_geometry_alone(self, corridor: Corridor) -> None:
        renamed = corridor.renamed("Crystal Range Traverse North")
        assert renamed.name == "Crystal Range Traverse North"
        assert renamed.waypoints == corridor.waypoints

    def test_repr_summarises(self, corridor: Corridor) -> None:
        assert repr(corridor) == "Corridor('Crystal Range Traverse', 20 waypoints, 78.0 mi)"


class TestMerge:
    def test_merging_reanchors_the_second_part(self) -> None:
        first = Corridor.from_waypoints(
            "First", [wp("a", "A", 0.0, 100), wp("b", "B", 5.0, 400)]
        )
        second = Corridor.from_waypoints(
            "Second", [wp("b", "B", 0.0, 400), wp("c", "C", 7.0, 900)]
        )
        joined = merge_corridors("Joined", [first, second])
        assert [w.id for w in joined] == ["a", "b", "c"]
        assert joined.waypoint("c").mile == pytest.approx(12.0)
        assert joined.length.in_miles == pytest.approx(12.0)

    def test_parts_must_meet_at_a_shared_waypoint(self) -> None:
        first = Corridor.from_waypoints("First", [wp("a", "A", 0.0, 100), wp("b", "B", 5.0, 400)])
        second = Corridor.from_waypoints("Second", [wp("x", "X", 0.0, 400), wp("y", "Y", 7.0, 900)])
        with pytest.raises(CorridorError, match="shared waypoint"):
            merge_corridors("Joined", [first, second])

    def test_merging_nothing_is_refused(self) -> None:
        with pytest.raises(CorridorError, match="empty sequence"):
            merge_corridors("Joined", [])

    def test_with_segments_swaps_the_measured_profile(self, short_corridor: Corridor) -> None:
        replacement = [
            Segment(
                start=short_corridor.waypoints[i],
                end=short_corridor.waypoints[i + 1],
                gain=Distance.feet(999),
                loss=Distance.feet(111),
            )
            for i in range(len(short_corridor.waypoints) - 1)
        ]
        swapped = short_corridor.with_segments(replacement)
        assert swapped.total_gain().in_feet == pytest.approx(1998)
        assert short_corridor.total_gain().in_feet != pytest.approx(1998)
