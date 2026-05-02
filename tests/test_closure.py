"""Closures, the detours that span them and the skips that do not."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import RouteResolutionError
from backpacking.trail.alternates import Alternate, resolve_route
from backpacking.trail.closure import (
    Closure,
    ClosureKind,
    ClosureSet,
    alternates_covering,
    choose_detour,
    skip_for,
)
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import WaypointKind
from tests.conftest import wp

JULY = date(2025, 7, 20)

FIRE = Closure(
    id="whiskey-fire",
    start_mile=41.0,
    end_mile=48.0,
    kind=ClosureKind.FIRE,
    effective_from=date(2025, 7, 10),
    effective_to=date(2025, 9, 30),
    agency="Tahoe National Forest",
)
SEASONAL = Closure(
    id="grebe-nesting",
    start_mile=8.0,
    end_mile=9.5,
    kind=ClosureKind.WILDLIFE,
    effective_from=date(2025, 4, 1),
    effective_to=date(2025, 6, 30),
)
PERMANENT = Closure(id="ranch", start_mile=60.0, end_mile=61.0, kind=ClosureKind.PRIVATE_LAND)

SHORT_DETOUR = Alternate(
    id="fire-road-detour",
    name="Fire Road Detour",
    departs_at="five-lakes-creek",
    rejoins_at="mule-ear-pass",
    length_miles=7.0,
    official=True,
)
LONG_DETOUR = Alternate(
    id="valley-detour",
    name="Valley Detour",
    departs_at="granite-chief",
    rejoins_at="squaw-ford",
    length_miles=19.0,
    waypoints=(wp("valley-road", "Valley Road", 8.0, 6200, WaypointKind.ROAD),),
)
TOO_SHORT = Alternate(
    id="spur",
    name="Spur",
    departs_at="whiskey-flat",
    rejoins_at="mule-ear-pass",
    length_miles=4.0,
)


class TestClosureKind:
    def test_the_hard_kinds(self) -> None:
        hard = {kind for kind in ClosureKind if kind.is_hard}
        assert hard == {ClosureKind.FIRE, ClosureKind.PRIVATE_LAND, ClosureKind.WILDLIFE}

    def test_construction_is_soft(self) -> None:
        assert not ClosureKind.CONSTRUCTION.is_hard


class TestClosure:
    def test_length_comes_from_the_span(self) -> None:
        assert FIRE.length.in_miles == pytest.approx(7.0)

    def test_it_is_half_open_at_the_far_end(self) -> None:
        assert FIRE.covers(41.0)
        assert FIRE.covers(47.9)
        assert not FIRE.covers(48.0)

    def test_dates_bound_it(self) -> None:
        assert FIRE.applies_on(JULY)
        assert not FIRE.applies_on(date(2025, 7, 1))
        assert not FIRE.applies_on(date(2025, 10, 5))

    def test_an_open_ended_closure_always_applies(self) -> None:
        assert PERMANENT.applies_on(date(2020, 1, 1))
        assert PERMANENT.applies_on(date(2030, 1, 1))

    def test_span_overlap(self) -> None:
        assert FIRE.overlaps_span(45.0, 60.0)
        assert FIRE.overlaps_span(30.0, 42.0)
        assert not FIRE.overlaps_span(48.0, 60.0)

    def test_a_zero_length_closure_is_refused(self) -> None:
        with pytest.raises(RouteResolutionError, match="positive span"):
            Closure(id="c", start_mile=4.0, end_mile=4.0)

    def test_backwards_dates_are_refused(self) -> None:
        with pytest.raises(RouteResolutionError, match="end before it starts"):
            Closure(
                id="c",
                start_mile=1.0,
                end_mile=2.0,
                effective_from=date(2025, 9, 1),
                effective_to=date(2025, 8, 1),
            )

    def test_repr(self) -> None:
        assert repr(FIRE) == "Closure('whiskey-fire', 41.0-48.0 mi, fire)"


class TestClosureSet:
    @pytest.fixture
    def closures(self) -> ClosureSet:
        return ClosureSet([FIRE, SEASONAL, PERMANENT])

    def test_closures_are_held_in_mile_order(self, closures: ClosureSet) -> None:
        assert [c.id for c in closures] == ["grebe-nesting", "whiskey-fire", "ranch"]

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(RouteResolutionError, match="duplicate closure id"):
            ClosureSet([FIRE, FIRE])

    def test_lookup_by_id(self, closures: ClosureSet) -> None:
        assert closures.get("whiskey-fire").start_mile == pytest.approx(41.0)

    def test_an_unknown_id_raises(self, closures: ClosureSet) -> None:
        with pytest.raises(RouteResolutionError, match="no such closure"):
            closures.get("nowhere")

    def test_only_the_ones_in_force_are_active(self, closures: ClosureSet) -> None:
        active = {c.id for c in closures.active_on(JULY)}
        assert active == {"whiskey-fire", "ranch"}

    def test_soft_closures_can_be_filtered_out(self) -> None:
        mixed = ClosureSet(
            [FIRE, Closure(id="work", start_mile=2.0, end_mile=3.0, kind=ClosureKind.CONSTRUCTION)]
        )
        assert {c.id for c in mixed.active_on(JULY, hard_only=True)} == {"whiskey-fire"}

    def test_blocking_finds_the_overlap(self, closures: ClosureSet) -> None:
        assert [c.id for c in closures.blocking(40.0, 50.0, JULY)] == ["whiskey-fire"]

    def test_nothing_blocks_a_clear_stretch(self, closures: ClosureSet) -> None:
        assert closures.blocking(20.0, 35.0, JULY) == ()

    def test_closed_miles_sums_the_active_ones(self, closures: ClosureSet) -> None:
        assert closures.closed_miles(JULY) == pytest.approx(8.0)

    def test_overlapping_closures_are_not_double_counted(self) -> None:
        overlapping = ClosureSet(
            [
                Closure(id="a", start_mile=10.0, end_mile=20.0),
                Closure(id="b", start_mile=15.0, end_mile=25.0),
            ]
        )
        assert overlapping.closed_miles(JULY) == pytest.approx(15.0)

    def test_an_empty_set_closes_nothing(self) -> None:
        assert ClosureSet().closed_miles(JULY) == pytest.approx(0.0)
        assert repr(ClosureSet()) == "ClosureSet(0 closures)"


class TestDetours:
    def test_a_spanning_alternate_is_found(self, corridor: Corridor) -> None:
        covering = alternates_covering(corridor, FIRE, [SHORT_DETOUR, LONG_DETOUR, TOO_SHORT])
        assert {a.id for a in covering} == {"fire-road-detour", "valley-detour"}

    def test_an_alternate_that_does_not_span_is_excluded(self, corridor: Corridor) -> None:
        covering = alternates_covering(corridor, FIRE, [TOO_SHORT])
        assert covering == ()

    def test_an_alternate_naming_an_absent_waypoint_is_skipped(
        self, corridor: Corridor
    ) -> None:
        broken = Alternate(
            id="broken", name="Broken", departs_at="nowhere", rejoins_at="also-nowhere",
            length_miles=5.0,
        )
        assert alternates_covering(corridor, FIRE, [broken]) == ()

    def test_the_official_short_detour_wins(self, corridor: Corridor) -> None:
        chosen = choose_detour(corridor, FIRE, [LONG_DETOUR, SHORT_DETOUR])
        assert chosen.id == "fire-road-detour"

    def test_an_unofficial_detour_is_used_when_it_is_the_only_one(
        self, corridor: Corridor
    ) -> None:
        assert choose_detour(corridor, FIRE, [LONG_DETOUR]).id == "valley-detour"

    def test_no_detour_is_reported(self, corridor: Corridor) -> None:
        with pytest.raises(RouteResolutionError, match="no alternate spans"):
            choose_detour(corridor, FIRE, [TOO_SHORT])

    def test_the_chosen_detour_actually_resolves(self, corridor: Corridor) -> None:
        chosen = choose_detour(corridor, FIRE, [SHORT_DETOUR, LONG_DETOUR])
        route = resolve_route(corridor, [chosen], [chosen.id]).corridor
        assert not route.has_waypoint("whiskey-flat")
        assert route.has_waypoint("mule-ear-pass")


class TestSkip:
    def test_the_skip_reports_the_lost_mileage(self, corridor: Corridor) -> None:
        report = skip_for(corridor, FIRE)
        assert report.skipped.in_miles == pytest.approx(7.0)
        assert report.resume_at == pytest.approx(48.0)

    def test_a_closure_past_the_end_is_refused(self, corridor: Corridor) -> None:
        beyond = Closure(id="beyond", start_mile=70.0, end_mile=120.0)
        with pytest.raises(RouteResolutionError, match="past the end of the corridor"):
            skip_for(corridor, beyond)

    def test_repr(self, corridor: Corridor) -> None:
        assert repr(skip_for(corridor, FIRE)) == (
            "SkipReport(whiskey-fire, skip 7.0 mi, resume at 48.0)"
        )
