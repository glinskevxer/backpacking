"""Quota windows, walk up hold backs and reserving against a calendar."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import PermitError
from backpacking.permits.quota import EntryPoint, QuotaCalendar, QuotaWindow


class TestQuotaWindow:
    def test_the_advance_limit_excludes_the_walk_up_hold_back(self) -> None:
        window = QuotaWindow(date(2025, 6, 15), date(2025, 9, 15), daily_limit=12, walk_up_reserved=4)
        assert window.advance_limit == 8

    def test_a_window_with_no_hold_back_gives_everything_in_advance(self) -> None:
        window = QuotaWindow(date(2025, 6, 1), date(2025, 6, 30), daily_limit=10)
        assert window.advance_limit == 10

    def test_covers_is_inclusive_of_both_ends(self) -> None:
        window = QuotaWindow(date(2025, 6, 15), date(2025, 9, 15), daily_limit=10)
        assert window.covers(date(2025, 6, 15))
        assert window.covers(date(2025, 9, 15))
        assert not window.covers(date(2025, 9, 16))

    def test_a_backwards_window_is_refused(self) -> None:
        with pytest.raises(PermitError, match="must not end before it starts"):
            QuotaWindow(date(2025, 9, 15), date(2025, 6, 15), daily_limit=10)

    def test_a_negative_limit_is_refused(self) -> None:
        with pytest.raises(PermitError, match="must not be negative"):
            QuotaWindow(date(2025, 6, 1), date(2025, 6, 30), daily_limit=-1)

    def test_a_hold_back_bigger_than_the_limit_is_refused(self) -> None:
        with pytest.raises(PermitError, match="cannot exceed the daily limit"):
            QuotaWindow(date(2025, 6, 1), date(2025, 6, 30), daily_limit=5, walk_up_reserved=9)

    def test_repr(self) -> None:
        window = QuotaWindow(date(2025, 6, 15), date(2025, 9, 15), daily_limit=12, walk_up_reserved=4)
        assert repr(window) == "QuotaWindow(2025-06-15..2025-09-15, 8/12)"


class TestEntryPoint:
    def test_a_date_inside_a_window_reports_its_capacity(self, quota: QuotaCalendar) -> None:
        echo = quota.entry("echo-trailhead")
        assert echo.advance_capacity(date(2025, 7, 20)) == 8

    def test_a_date_outside_every_window_is_unquotaed(self, quota: QuotaCalendar) -> None:
        echo = quota.entry("echo-trailhead")
        assert echo.advance_capacity(date(2025, 5, 1)) is None

    def test_a_closure_gives_no_capacity(self, quota: QuotaCalendar) -> None:
        echo = quota.entry("echo-trailhead")
        assert not echo.is_open(date(2025, 7, 4))
        assert echo.advance_capacity(date(2025, 7, 4)) == 0

    def test_an_entry_with_no_windows_is_never_quotaed(self, quota: QuotaCalendar) -> None:
        barker = quota.entry("barker-road")
        assert barker.advance_capacity(date(2025, 7, 20)) is None

    def test_overlapping_windows_are_refused(self) -> None:
        with pytest.raises(PermitError, match="quota windows overlap"):
            EntryPoint(
                id="e",
                name="E",
                mile=0.0,
                zone_id="z",
                windows=(
                    QuotaWindow(date(2025, 6, 1), date(2025, 7, 31), daily_limit=5),
                    QuotaWindow(date(2025, 7, 15), date(2025, 8, 31), daily_limit=5),
                ),
            )

    def test_abutting_windows_are_allowed(self) -> None:
        entry = EntryPoint(
            id="e",
            name="E",
            mile=0.0,
            zone_id="z",
            windows=(
                QuotaWindow(date(2025, 6, 1), date(2025, 6, 30), daily_limit=5),
                QuotaWindow(date(2025, 7, 1), date(2025, 7, 31), daily_limit=9),
            ),
        )
        assert entry.advance_capacity(date(2025, 6, 15)) == 5
        assert entry.advance_capacity(date(2025, 7, 15)) == 9

    def test_repr(self, quota: QuotaCalendar) -> None:
        assert repr(quota.entry("echo-trailhead")) == "EntryPoint('echo-trailhead' @ 0.0 mi, 1 windows)"


class TestQuotaCalendar:
    def test_lookup_by_id(self, quota: QuotaCalendar) -> None:
        assert quota.entry("barker-road").mile == pytest.approx(23.6)

    def test_an_unknown_entry_raises(self, quota: QuotaCalendar) -> None:
        with pytest.raises(PermitError, match="no such entry point"):
            quota.entry("nowhere")

    def test_duplicate_entry_ids_are_refused(self) -> None:
        with pytest.raises(PermitError, match="duplicate entry point id"):
            QuotaCalendar(
                [
                    EntryPoint(id="e", name="E", mile=0.0, zone_id="z"),
                    EntryPoint(id="e", name="E2", mile=4.0, zone_id="z"),
                ]
            )

    def test_a_fresh_calendar_has_everything_remaining(self, quota: QuotaCalendar) -> None:
        assert quota.remaining("echo-trailhead", date(2025, 7, 20)) == 8

    def test_an_unquotaed_entry_has_no_remaining_count(self, quota: QuotaCalendar) -> None:
        assert quota.remaining("barker-road", date(2025, 7, 20)) is None
        assert quota.is_available("barker-road", date(2025, 7, 20), party_size=40)

    def test_reserving_reduces_what_is_left(self, quota: QuotaCalendar) -> None:
        after = quota.reserve("echo-trailhead", date(2025, 7, 20), party_size=3)
        assert after.remaining("echo-trailhead", date(2025, 7, 20)) == 5

    def test_reserving_returns_a_new_calendar(self, quota: QuotaCalendar) -> None:
        quota.reserve("echo-trailhead", date(2025, 7, 20), party_size=3)
        assert quota.remaining("echo-trailhead", date(2025, 7, 20)) == 8

    def test_reservations_accumulate(self, quota: QuotaCalendar) -> None:
        after = (
            quota.reserve("echo-trailhead", date(2025, 7, 20), 3)
            .reserve("echo-trailhead", date(2025, 7, 20), 4)
        )
        assert after.remaining("echo-trailhead", date(2025, 7, 20)) == 1

    def test_oversubscribing_is_refused(self, quota: QuotaCalendar) -> None:
        with pytest.raises(PermitError, match="not enough permits left"):
            quota.reserve("echo-trailhead", date(2025, 7, 20), party_size=9)

    def test_a_closed_day_cannot_be_reserved(self, quota: QuotaCalendar) -> None:
        with pytest.raises(PermitError, match="not enough permits left"):
            quota.reserve("echo-trailhead", date(2025, 7, 4), party_size=1)

    def test_a_party_size_below_one_is_refused(self, quota: QuotaCalendar) -> None:
        with pytest.raises(PermitError, match="at least one"):
            quota.is_available("echo-trailhead", date(2025, 7, 20), party_size=0)

    def test_taken_on_reports_what_has_gone(self, quota: QuotaCalendar) -> None:
        after = quota.reserve("echo-trailhead", date(2025, 7, 20), 2)
        assert after.taken_on("echo-trailhead", date(2025, 7, 20)) == 2
        assert after.taken_on("echo-trailhead", date(2025, 7, 21)) == 0

    def test_repr(self, quota: QuotaCalendar) -> None:
        assert repr(quota) == "QuotaCalendar(2 entries, 0 reservations)"


class TestSearching:
    def test_first_available_returns_the_asked_for_date_when_it_is_free(
        self, quota: QuotaCalendar
    ) -> None:
        assert quota.first_available("echo-trailhead", date(2025, 7, 20)) == date(2025, 7, 20)

    def test_first_available_steps_past_a_full_day(self, quota: QuotaCalendar) -> None:
        full = quota.reserve("echo-trailhead", date(2025, 7, 20), 8)
        assert full.first_available("echo-trailhead", date(2025, 7, 20)) == date(2025, 7, 21)

    def test_first_available_steps_past_a_closure(self, quota: QuotaCalendar) -> None:
        assert quota.first_available("echo-trailhead", date(2025, 7, 4)) == date(2025, 7, 5)

    def test_first_available_gives_up_after_the_search_window(
        self, quota: QuotaCalendar
    ) -> None:
        blocked = quota
        for offset in range(5):
            blocked = blocked.reserve(
                "echo-trailhead", date(2025, 7, 20 + offset), 8
            )
        assert blocked.first_available("echo-trailhead", date(2025, 7, 20), search_days=3) is None

    def test_a_zero_search_window_is_refused(self, quota: QuotaCalendar) -> None:
        with pytest.raises(PermitError, match="at least one day"):
            quota.first_available("echo-trailhead", date(2025, 7, 20), search_days=0)

    def test_availability_reports_a_run_of_dates(self, quota: QuotaCalendar) -> None:
        table = quota.availability("echo-trailhead", date(2025, 7, 2), days=4)
        assert len(table) == 4
        assert table[date(2025, 7, 4)] == 0
        assert table[date(2025, 7, 3)] == 8

    def test_availability_before_the_season_reports_none(self, quota: QuotaCalendar) -> None:
        table = quota.availability("echo-trailhead", date(2025, 5, 1), days=2)
        assert set(table.values()) == {None}

    def test_a_zero_availability_window_is_refused(self, quota: QuotaCalendar) -> None:
        with pytest.raises(PermitError, match="at least one day"):
            quota.availability("echo-trailhead", date(2025, 7, 20), days=0)
