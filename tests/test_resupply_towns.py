"""Resupply points, service levels and access cost."""

from __future__ import annotations

from datetime import date, time

import pytest

from backpacking.errors import ResupplyInfeasible
from backpacking.resupply.towns import ResupplyPoint, ServiceLevel, TownIndex
from backpacking.units import Distance, Duration


class TestServiceLevel:
    def test_levels_are_ordered(self) -> None:
        assert ServiceLevel.FULL_GROCERY > ServiceLevel.SMALL_GROCERY > ServiceLevel.CONVENIENCE

    def test_only_groceries_support_a_full_resupply(self) -> None:
        supporting = {level for level in ServiceLevel if level.supports_full_resupply}
        assert supporting == {ServiceLevel.SMALL_GROCERY, ServiceLevel.FULL_GROCERY}

    def test_labels_are_readable(self) -> None:
        assert ServiceLevel.GAS_STATION.label == "gas station"


class TestResupplyPoint:
    def test_a_hitch_costs_time_both_ways(self, towns: TownIndex) -> None:
        tahoma = towns.get("tahoma")
        assert tahoma.access_cost(hitch_speed_mph=30.0).in_hours == pytest.approx(14.0 / 30.0)

    def test_a_shuttle_wait_is_counted_twice(self, towns: TownIndex) -> None:
        soda = towns.get("soda-springs")
        driving = 8.0 / 30.0
        assert soda.access_cost(hitch_speed_mph=30.0).in_hours == pytest.approx(
            driving + 2.0 * (20.0 / 60.0)
        )

    def test_a_walk_in_uses_walking_speed(self, towns: TownIndex) -> None:
        chalet = towns.get("echo-chalet")
        assert chalet.access_cost(walk_mph=3.0).in_hours == pytest.approx(0.4 / 3.0)

    def test_an_on_trail_stop_is_detected(self) -> None:
        on_trail = ResupplyPoint(id="p", name="P", mile=4.0, groceries=ServiceLevel.FULL_GROCERY)
        assert on_trail.is_on_trail
        assert on_trail.access_cost().in_hours == pytest.approx(0.0)

    def test_a_hitching_stop_is_not_on_trail(self, towns: TownIndex) -> None:
        assert not towns.get("tahoma").is_on_trail

    def test_zero_speeds_are_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="must be positive"):
            towns.get("tahoma").access_cost(hitch_speed_mph=0.0)

    def test_open_days_are_respected(self, towns: TownIndex) -> None:
        chalet = towns.get("echo-chalet")
        assert chalet.is_open_on(date(2025, 7, 18))
        assert not chalet.is_open_on(date(2025, 7, 15))

    def test_next_open_day_steps_forward(self, towns: TownIndex) -> None:
        chalet = towns.get("echo-chalet")
        assert chalet.next_open_day(date(2025, 7, 15)) == date(2025, 7, 18)

    def test_next_open_day_returns_the_same_day_when_open(self, towns: TownIndex) -> None:
        chalet = towns.get("echo-chalet")
        assert chalet.next_open_day(date(2025, 7, 18)) == date(2025, 7, 18)

    def test_a_negative_mile_is_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="must not be negative"):
            ResupplyPoint(id="p", name="P", mile=-1.0)

    def test_a_negative_access_distance_is_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="must not be negative"):
            ResupplyPoint(id="p", name="P", mile=1.0, hitch=Distance.miles(-1.0))

    def test_an_invalid_weekday_is_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="Monday zero through Sunday six"):
            ResupplyPoint(id="p", name="P", mile=1.0, open_days=frozenset({9}))

    def test_backwards_hours_are_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="span forwards"):
            ResupplyPoint(id="p", name="P", mile=1.0, hours=(time(17, 0), time(9, 0)))

    def test_repr(self, towns: TownIndex) -> None:
        assert (
            repr(towns.get("soda-springs"))
            == "ResupplyPoint('soda-springs' @ 57.4 mi, full grocery)"
        )


class TestTownIndex:
    def test_points_are_held_in_mile_order(self, towns: TownIndex) -> None:
        miles = [point.mile for point in towns]
        assert miles == sorted(miles)
        assert len(towns) == 5

    def test_only_three_stops_can_supply_a_carry(self, towns: TownIndex) -> None:
        assert [p.id for p in towns.full_resupplies()] == [
            "tahoma",
            "soda-springs",
            "donner-summit",
        ]

    def test_post_offices_are_listed(self, towns: TownIndex) -> None:
        assert {p.id for p in towns.with_post_office()} == {"tahoma", "soda-springs"}

    def test_lookup_by_id(self, towns: TownIndex) -> None:
        assert towns.get("alpine-store").mile == pytest.approx(40.4)

    def test_an_unknown_id_raises(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="no such resupply point"):
            towns.get("nowhere")

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="duplicate resupply point id"):
            TownIndex(
                [
                    ResupplyPoint(id="p", name="P", mile=1.0),
                    ResupplyPoint(id="p", name="P2", mile=4.0),
                ]
            )

    def test_between_clips_to_the_range(self, towns: TownIndex) -> None:
        assert [p.id for p in towns.between(20.0, 60.0)] == [
            "tahoma",
            "alpine-store",
            "soda-springs",
        ]

    def test_next_after_looks_forward(self, towns: TownIndex) -> None:
        found = towns.next_after(24.0)
        assert found is not None
        assert found.id == "alpine-store"

    def test_next_after_can_skip_the_useless_stops(self, towns: TownIndex) -> None:
        found = towns.next_after(24.0, full_only=True)
        assert found is not None
        assert found.id == "soda-springs"

    def test_next_after_returns_none_past_the_end(self, towns: TownIndex) -> None:
        assert towns.next_after(99.0) is None

    def test_the_longest_gap_between_full_stops(self, towns: TownIndex) -> None:
        assert towns.longest_gap() == pytest.approx(33.8)

    def test_the_longest_gap_shrinks_when_every_stop_counts(self, towns: TownIndex) -> None:
        assert towns.longest_gap(full_only=False) == pytest.approx(23.3)

    def test_measuring_a_gap_needs_two_stops(self) -> None:
        thin = TownIndex(
            [ResupplyPoint(id="p", name="P", mile=4.0, groceries=ServiceLevel.FULL_GROCERY)]
        )
        with pytest.raises(ResupplyInfeasible, match="at least two stops"):
            thin.longest_gap()

    def test_repr(self, towns: TownIndex) -> None:
        assert repr(towns) == "TownIndex(5 points, 3 full)"

    def test_shuttle_wait_is_a_duration(self, towns: TownIndex) -> None:
        assert towns.get("soda-springs").shuttle_wait == Duration.minutes(20.0)
