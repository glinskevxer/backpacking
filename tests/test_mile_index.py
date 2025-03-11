"""The boundary convention every mile keyed table depends on."""

from __future__ import annotations

import pytest

from backpacking.trail.index import Bracket, MileIndex

KEYS = [0.0, 2.4, 5.1, 8.7, 11.9, 18.0]


@pytest.fixture
def index() -> MileIndex:
    return MileIndex(KEYS)


class TestConstruction:
    def test_keys_are_kept_in_order(self, index: MileIndex) -> None:
        assert index.miles == tuple(KEYS)
        assert len(index) == 6

    def test_first_and_last(self, index: MileIndex) -> None:
        assert index.first == pytest.approx(0.0)
        assert index.last == pytest.approx(18.0)

    def test_an_empty_index_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one key"):
            MileIndex([])

    def test_descending_keys_are_refused(self) -> None:
        with pytest.raises(ValueError, match="must ascend"):
            MileIndex([0.0, 4.0, 2.0])

    def test_repeated_keys_are_refused(self) -> None:
        with pytest.raises(ValueError, match="must ascend"):
            MileIndex([0.0, 4.0, 4.0])

    def test_a_single_key_index_is_allowed(self) -> None:
        single = MileIndex([7.0])
        assert single.first == single.last == pytest.approx(7.0)
        assert single.interval_for(7.0) == 0

    def test_repr(self, index: MileIndex) -> None:
        assert repr(index) == "MileIndex(6 keys, 0.0-18.0)"


class TestContains:
    @pytest.mark.parametrize("mile", [0.0, 5.1, 9.0, 18.0])
    def test_inside(self, index: MileIndex, mile: float) -> None:
        assert index.contains(mile)

    @pytest.mark.parametrize("mile", [-0.1, 18.1, 100.0])
    def test_outside(self, index: MileIndex, mile: float) -> None:
        assert not index.contains(mile)


class TestIntervalFor:
    def test_a_mile_inside_an_interval(self, index: MileIndex) -> None:
        assert index.interval_for(3.0) == 1

    def test_a_boundary_belongs_to_the_interval_starting_there(self, index: MileIndex) -> None:
        assert index.interval_for(2.4) == 1
        assert index.interval_for(5.1) == 2

    def test_the_first_key(self, index: MileIndex) -> None:
        assert index.interval_for(0.0) == 0

    def test_the_last_key_stays_in_the_final_interval(self, index: MileIndex) -> None:
        assert index.interval_for(18.0) == 4

    def test_below_the_start_clamps_to_the_first(self, index: MileIndex) -> None:
        assert index.interval_for(-5.0) == 0

    def test_above_the_end_clamps_to_the_last(self, index: MileIndex) -> None:
        assert index.interval_for(99.0) == 4


class TestBracket:
    def test_an_exact_key_reports_itself_twice(self, index: MileIndex) -> None:
        assert index.bracket(5.1) == Bracket(before=2, after=2, exact=True)

    def test_a_mile_between_keys(self, index: MileIndex) -> None:
        assert index.bracket(7.0) == Bracket(before=2, after=3, exact=False)

    def test_below_the_first_key(self, index: MileIndex) -> None:
        assert index.bracket(-1.0) == Bracket(before=0, after=0, exact=False)

    def test_above_the_last_key(self, index: MileIndex) -> None:
        assert index.bracket(50.0) == Bracket(before=5, after=5, exact=False)


class TestNearest:
    def test_picks_the_closer_key(self, index: MileIndex) -> None:
        assert index.nearest(2.5) == 1
        assert index.nearest(5.0) == 2

    def test_a_tie_goes_to_the_earlier_key(self) -> None:
        even = MileIndex([0.0, 10.0, 20.0])
        assert even.nearest(5.0) == 0
        assert even.nearest(15.0) == 1

    def test_the_ends(self, index: MileIndex) -> None:
        assert index.nearest(-3.0) == 0
        assert index.nearest(40.0) == 5

    def test_an_exact_key_returns_itself(self, index: MileIndex) -> None:
        assert index.nearest(11.9) == 4


class TestFirstAfter:
    def test_strictly_greater(self, index: MileIndex) -> None:
        assert index.first_after(2.4) == 2
        assert index.first_after(2.5) == 2

    def test_from_before_the_start(self, index: MileIndex) -> None:
        assert index.first_after(-1.0) == 0

    def test_nothing_after_the_last_key(self, index: MileIndex) -> None:
        assert index.first_after(18.0) is None
        assert index.first_after(25.0) is None


class TestSpan:
    def test_an_inclusive_range(self, index: MileIndex) -> None:
        assert index.span(2.4, 8.7) == (1, 4)

    def test_a_range_between_keys(self, index: MileIndex) -> None:
        assert index.span(3.0, 7.0) == (2, 3)

    def test_a_range_covering_everything(self, index: MileIndex) -> None:
        assert index.span(-1.0, 100.0) == (0, 6)

    def test_an_empty_range(self, index: MileIndex) -> None:
        left, right = index.span(6.0, 7.0)
        assert left == right


class TestFractionWithin:
    def test_at_the_start_of_an_interval(self, index: MileIndex) -> None:
        interval, fraction = index.fraction_within(2.4)
        assert interval == 1
        assert fraction == pytest.approx(0.0)

    def test_halfway_through_an_interval(self) -> None:
        even = MileIndex([0.0, 10.0, 20.0])
        interval, fraction = even.fraction_within(5.0)
        assert interval == 0
        assert fraction == pytest.approx(0.5)

    def test_the_fraction_is_clamped(self, index: MileIndex) -> None:
        _, low = index.fraction_within(-4.0)
        _, high = index.fraction_within(99.0)
        assert low == pytest.approx(0.0)
        assert high == pytest.approx(1.0)

    def test_a_single_key_index_has_no_fraction(self) -> None:
        assert MileIndex([3.0]).fraction_within(3.0) == (0, 0.0)


class TestCorridorUsesTheIndex:
    def test_the_corridor_exposes_its_index(self, corridor) -> None:
        assert isinstance(corridor.index, MileIndex)
        assert len(corridor.index) == len(corridor)

    def test_the_index_keys_are_the_waypoint_miles(self, corridor) -> None:
        assert corridor.index.miles == tuple(w.mile for w in corridor)
