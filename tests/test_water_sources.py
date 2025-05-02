"""Reliability curves and the table that indexes them."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import WaterCarryError
from backpacking.units import Distance
from backpacking.water.sources import Reliability, WaterSource, WaterTable


class TestReliability:
    def test_perennial_is_the_most_confident(self) -> None:
        assert Reliability.PERENNIAL.confidence == pytest.approx(0.98)

    def test_dry_is_zero(self) -> None:
        assert Reliability.DRY.confidence == pytest.approx(0.0)

    def test_the_ordering_matches_the_vocabulary(self) -> None:
        assert (
            Reliability.PERENNIAL.confidence
            > Reliability.SEASONAL.confidence
            > Reliability.CACHE.confidence
            > Reliability.UNRELIABLE.confidence
            > Reliability.DRY.confidence
        )


class TestConfidence:
    def test_a_perennial_source_ignores_the_month(self) -> None:
        creek = WaterSource(id="c", name="Creek", mile=4.0, reliability=Reliability.PERENNIAL)
        assert creek.confidence(7) == pytest.approx(creek.confidence(1))

    def test_a_seasonal_source_fades_through_the_summer(self) -> None:
        spring = WaterSource(id="s", name="Spring", mile=4.0, reliability=Reliability.SEASONAL)
        assert spring.confidence(6) > spring.confidence(7) > spring.confidence(8)
        assert spring.confidence(9) < spring.confidence(6)

    def test_a_seasonal_source_recovers_in_autumn(self) -> None:
        spring = WaterSource(id="s", name="Spring", mile=4.0, reliability=Reliability.SEASONAL)
        assert spring.confidence(10) > spring.confidence(9)

    def test_a_monthly_override_wins(self) -> None:
        reported = WaterSource(
            id="s",
            name="Spring",
            mile=4.0,
            reliability=Reliability.SEASONAL,
            monthly_override={8: 0.95},
        )
        assert reported.confidence(8) == pytest.approx(0.95)
        assert reported.confidence(7) < 0.95

    def test_an_invalid_month_is_refused(self) -> None:
        creek = WaterSource(id="c", name="Creek", mile=4.0)
        with pytest.raises(WaterCarryError, match="month must be 1 through 12"):
            creek.confidence(13)

    def test_is_usable_applies_the_threshold(self) -> None:
        spring = WaterSource(id="s", name="Spring", mile=4.0, reliability=Reliability.SEASONAL)
        assert spring.is_usable(6, threshold=0.6)
        assert not spring.is_usable(8, threshold=0.6)
        assert spring.is_usable(8, threshold=0.3)


class TestSourceValidation:
    def test_a_negative_mile_is_refused(self) -> None:
        with pytest.raises(WaterCarryError, match="must not be negative"):
            WaterSource(id="s", name="S", mile=-1.0)

    def test_a_negative_detour_is_refused(self) -> None:
        with pytest.raises(WaterCarryError, match="must not be negative"):
            WaterSource(id="s", name="S", mile=1.0, off_trail=Distance.miles(-0.1))

    def test_an_override_month_must_be_valid(self) -> None:
        with pytest.raises(WaterCarryError, match="invalid month"):
            WaterSource(id="s", name="S", mile=1.0, monthly_override={13: 0.5})

    def test_an_override_value_must_be_a_probability(self) -> None:
        with pytest.raises(WaterCarryError, match=r"\[0, 1\]"):
            WaterSource(id="s", name="S", mile=1.0, monthly_override={7: 1.4})

    def test_the_detour_cost_is_a_round_trip(self) -> None:
        source = WaterSource(id="s", name="S", mile=1.0, off_trail=Distance.miles(0.3))
        assert source.detour_cost_miles == pytest.approx(0.6)

    def test_repr(self) -> None:
        source = WaterSource(id="rubicon", name="Rubicon", mile=18.0)
        assert repr(source) == "WaterSource('rubicon' @ 18.0 mi, seasonal)"


class TestWaterTable:
    def test_sources_are_held_in_mile_order(self, water: WaterTable) -> None:
        miles = [s.mile for s in water.sources]
        assert miles == sorted(miles)
        assert len(water) == 11

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(WaterCarryError, match="duplicate water source id"):
            WaterTable(
                [
                    WaterSource(id="s", name="A", mile=1.0),
                    WaterSource(id="s", name="B", mile=4.0),
                ]
            )

    def test_lookup_by_id(self, water: WaterTable) -> None:
        assert water.get("squaw-ford").mile == pytest.approx(52.0)

    def test_an_unknown_id_raises(self, water: WaterTable) -> None:
        with pytest.raises(WaterCarryError, match="no such water source"):
            water.get("nonexistent")

    def test_usable_thins_out_in_august(self, water: WaterTable) -> None:
        june = water.usable(6)
        august = water.usable(8)
        assert len(august) < len(june)
        assert all(s.reliability is Reliability.PERENNIAL for s in august)

    def test_lowering_the_threshold_brings_sources_back(self, water: WaterTable) -> None:
        strict = water.usable(8, threshold=0.6)
        loose = water.usable(8, threshold=0.2)
        assert len(loose) > len(strict)

    def test_between_clips_to_the_range(self, water: WaterTable) -> None:
        found = water.between(20.0, 60.0, month=6)
        assert [s.id for s in found] == [
            "five-lakes-creek",
            "whiskey-seep",
            "squaw-ford",
            "soda-tap",
        ]

    def test_an_unreliable_source_stays_out_even_in_june(self, water: WaterTable) -> None:
        assert "barker-tank" not in {s.id for s in water.usable(6)}
        assert "barker-tank" in {s.id for s in water.usable(6, threshold=0.3)}

    def test_next_usable_looks_forward(self, water: WaterTable) -> None:
        found = water.next_usable(24.0, month=8)
        assert found is not None
        assert found.id == "five-lakes-creek"

    def test_next_usable_returns_none_past_the_last(self, water: WaterTable) -> None:
        assert water.next_usable(99.0, month=6) is None

    def test_previous_usable_looks_back(self, water: WaterTable) -> None:
        found = water.previous_usable(30.0, month=8)
        assert found is not None
        assert found.id == "lake-aloha-inlet"

    def test_previous_usable_returns_none_before_the_first(self, water: WaterTable) -> None:
        assert water.previous_usable(1.0, month=6) is None

    def test_adding_a_source_returns_a_new_table(self, water: WaterTable) -> None:
        cache = WaterSource(id="cache-32", name="Mile 32 Cache", mile=32.0, reliability=Reliability.CACHE)
        bigger = water.with_source(cache)
        assert len(bigger) == len(water) + 1
        assert len(water) == 11

    def test_removing_a_source_returns_a_new_table(self, water: WaterTable) -> None:
        smaller = water.without("barker-tank")
        assert len(smaller) == len(water) - 1
        with pytest.raises(WaterCarryError):
            smaller.get("barker-tank")

    def test_for_month_takes_a_date(self, water: WaterTable) -> None:
        assert water.for_month(date(2025, 8, 14)) == water.usable(8)

    def test_two_sources_can_share_a_mile(self) -> None:
        table = WaterTable(
            [
                WaterSource(id="a", name="A", mile=4.0),
                WaterSource(id="b", name="B", mile=4.0),
            ]
        )
        assert len(table) == 2

    def test_repr_reports_the_span(self, water: WaterTable) -> None:
        assert repr(water) == "WaterTable(11 sources, 2.4-70.9 mi)"

    def test_an_empty_table_reprs_cleanly(self) -> None:
        assert repr(WaterTable([])) == "WaterTable(empty)"
