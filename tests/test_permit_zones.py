"""Zone geometry, camping policy and the map that holds them."""

from __future__ import annotations

import pytest

from backpacking.errors import PermitError
from backpacking.permits.zones import CampingPolicy, PermitZone, ZoneMap
from backpacking.units import Distance


class TestCampingPolicy:
    def test_only_two_policies_need_a_named_site(self) -> None:
        needs = {p for p in CampingPolicy if p.requires_named_site}
        assert needs == {CampingPolicy.DESIGNATED_ONLY, CampingPolicy.PERMITTED_SITE}

    def test_policies_serialise_as_strings(self) -> None:
        assert CampingPolicy.NO_CAMPING == "no_camping"


class TestPermitZone:
    def test_length_comes_from_the_mile_span(self, zone_map: ZoneMap) -> None:
        assert zone_map.get("crystal-wilderness").length.in_miles == pytest.approx(27.8)

    def test_a_zone_is_half_open_at_the_far_end(self, zone_map: ZoneMap) -> None:
        wilderness = zone_map.get("crystal-wilderness")
        assert wilderness.contains(8.7)
        assert wilderness.contains(36.4)
        assert not wilderness.contains(36.5)

    def test_a_zero_length_zone_is_refused(self) -> None:
        with pytest.raises(PermitError, match="positive span"):
            PermitZone(id="z", name="Z", agency="A", start_mile=4.0, end_mile=4.0)

    def test_a_negative_night_cap_is_refused(self) -> None:
        with pytest.raises(PermitError, match="must not be negative"):
            PermitZone(
                id="z", name="Z", agency="A", start_mile=0.0, end_mile=4.0,
                max_consecutive_nights=-1,
            )

    def test_a_designated_zone_must_list_its_sites(self) -> None:
        with pytest.raises(PermitError, match="must list its sites"):
            PermitZone(
                id="z", name="Z", agency="A", start_mile=0.0, end_mile=4.0,
                camping=CampingPolicy.DESIGNATED_ONLY,
            )

    def test_dispersed_camping_allows_any_mile_in_the_zone(self, zone_map: ZoneMap) -> None:
        front = zone_map.get("echo-front")
        assert front.allows_camp_at(4.0, None)
        assert not front.allows_camp_at(40.0, None)

    def test_designated_camping_needs_a_listed_site(self, zone_map: ZoneMap) -> None:
        wilderness = zone_map.get("crystal-wilderness")
        assert wilderness.allows_camp_at(15.3, "clyde-basin")
        assert not wilderness.allows_camp_at(15.3, "somewhere-else")
        assert not wilderness.allows_camp_at(15.3, None)

    def test_a_no_camping_zone_refuses_everything(self) -> None:
        closed = PermitZone(
            id="z", name="Z", agency="A", start_mile=0.0, end_mile=4.0,
            camping=CampingPolicy.NO_CAMPING,
        )
        assert not closed.allows_camp_at(2.0, "anywhere")

    def test_fires_follow_the_elevation_limit(self, zone_map: ZoneMap) -> None:
        wilderness = zone_map.get("crystal-wilderness")
        assert wilderness.allows_fire_at(Distance.feet(7500))
        assert wilderness.allows_fire_at(Distance.feet(8000))
        assert not wilderness.allows_fire_at(Distance.feet(8600))

    def test_a_zone_with_no_fires_refuses_at_any_elevation(self, zone_map: ZoneMap) -> None:
        park = zone_map.get("granite-state-park")
        assert not park.allows_fire_at(Distance.feet(1000))

    def test_a_zone_with_no_limit_allows_fires_anywhere_in_it(self, zone_map: ZoneMap) -> None:
        assert zone_map.get("donner-north").allows_fire_at(Distance.feet(20000))

    def test_overlap_detection(self) -> None:
        first = PermitZone(id="a", name="A", agency="X", start_mile=0.0, end_mile=10.0)
        second = PermitZone(id="b", name="B", agency="X", start_mile=9.0, end_mile=20.0)
        third = PermitZone(id="c", name="C", agency="X", start_mile=10.0, end_mile=20.0)
        assert first.overlaps(second)
        assert not first.overlaps(third)

    def test_repr(self, zone_map: ZoneMap) -> None:
        assert repr(zone_map.get("echo-front")) == "PermitZone('echo-front', 0.0-8.7 mi, dispersed)"


class TestZoneMap:
    def test_the_reference_map_covers_the_whole_corridor(self, zone_map: ZoneMap) -> None:
        assert len(zone_map) == 4
        assert zone_map.gaps() == ()

    def test_zones_are_held_in_mile_order(self, zone_map: ZoneMap) -> None:
        starts = [zone.start_mile for zone in zone_map]
        assert starts == sorted(starts)

    def test_lookup_by_mile(self, zone_map: ZoneMap) -> None:
        assert zone_map.at(15.3).id == "crystal-wilderness"
        assert zone_map.at(0.0).id == "echo-front"
        assert zone_map.at(77.9).id == "donner-north"

    def test_a_boundary_belongs_to_the_zone_that_starts_there(self, zone_map: ZoneMap) -> None:
        assert zone_map.at(36.5).id == "granite-state-park"
        assert zone_map.at(57.4).id == "donner-north"

    def test_a_mile_past_the_end_is_unmapped(self, zone_map: ZoneMap) -> None:
        assert zone_map.at(78.0) is None

    def test_require_at_raises_where_at_returns_none(self, zone_map: ZoneMap) -> None:
        with pytest.raises(PermitError, match="no permit zone covers"):
            zone_map.require_at(120.0)

    def test_lookup_by_id(self, zone_map: ZoneMap) -> None:
        assert zone_map.get("donner-north").agency == "Tahoe National Forest"

    def test_an_unknown_id_raises(self, zone_map: ZoneMap) -> None:
        with pytest.raises(PermitError, match="no such permit zone"):
            zone_map.get("nowhere")

    def test_between_returns_every_overlapping_zone(self, zone_map: ZoneMap) -> None:
        found = zone_map.between(5.0, 40.0)
        assert [zone.id for zone in found] == [
            "echo-front",
            "crystal-wilderness",
            "granite-state-park",
        ]

    def test_agencies_are_listed_once_each_in_order(self, zone_map: ZoneMap) -> None:
        assert zone_map.agencies() == (
            "Eldorado National Forest",
            "California State Parks",
            "Tahoe National Forest",
        )

    def test_canister_requirement_is_detected_across_a_span(self, zone_map: ZoneMap) -> None:
        assert zone_map.canister_required_between(10.0, 20.0)
        assert not zone_map.canister_required_between(60.0, 70.0)

    def test_overlapping_zones_are_refused(self) -> None:
        with pytest.raises(PermitError, match="overlap"):
            ZoneMap(
                [
                    PermitZone(id="a", name="A", agency="X", start_mile=0.0, end_mile=10.0),
                    PermitZone(id="b", name="B", agency="X", start_mile=9.0, end_mile=20.0),
                ]
            )

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(PermitError, match="duplicate permit zone id"):
            ZoneMap(
                [
                    PermitZone(id="a", name="A", agency="X", start_mile=0.0, end_mile=10.0),
                    PermitZone(id="a", name="A2", agency="X", start_mile=10.0, end_mile=20.0),
                ]
            )

    def test_gaps_are_reported(self) -> None:
        gapped = ZoneMap(
            [
                PermitZone(id="a", name="A", agency="X", start_mile=0.0, end_mile=10.0),
                PermitZone(id="b", name="B", agency="X", start_mile=14.0, end_mile=20.0),
            ]
        )
        assert gapped.gaps() == ((10.0, 14.0),)
        assert gapped.at(12.0) is None

    def test_gaps_can_be_forbidden(self) -> None:
        with pytest.raises(PermitError, match="gap between permit zones"):
            ZoneMap(
                [
                    PermitZone(id="a", name="A", agency="X", start_mile=0.0, end_mile=10.0),
                    PermitZone(id="b", name="B", agency="X", start_mile=14.0, end_mile=20.0),
                ],
                allow_gaps=False,
            )

    def test_repr(self, zone_map: ZoneMap) -> None:
        assert repr(zone_map) == "ZoneMap(4 zones, 3 agencies)"
