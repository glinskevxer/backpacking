"""Serialisation, calendar export and the trip sheet."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backpacking.errors import DataSourceError
from backpacking.pace.models import HikerProfile
from backpacking.permits.validate import validate_nights
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.solver import PlanRequest, solve
from backpacking.report.calendar import (
    count_events,
    escape,
    fold,
    format_date,
    to_ics,
)
from backpacking.report.serialize import (
    SCHEMA_VERSION,
    corridor_to_dict,
    from_json,
    hiker_to_dict,
    permit_report_to_dict,
    plan_to_dict,
    to_json,
)
from backpacking.report.tripsheet import render_trip_sheet
from backpacking.trail.corridor import Corridor

START = date(2025, 7, 20)
STAMP = datetime(2025, 7, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def plan(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    return solve(PlanRequest(corridor=corridor, profile=hiker, start_date=START))


class TestCorridorSerialisation:
    def test_the_headline_numbers_are_present(self, corridor: Corridor) -> None:
        body = corridor_to_dict(corridor, "crystal-range")
        assert body["slug"] == "crystal-range"
        assert body["length_miles"] == pytest.approx(78.0)
        assert body["schema_version"] == SCHEMA_VERSION

    def test_every_waypoint_and_segment_is_included(self, corridor: Corridor) -> None:
        body = corridor_to_dict(corridor, "crystal-range")
        assert len(body["waypoints"]) == 20
        assert len(body["segments"]) == 19

    def test_units_are_in_the_key_names(self, corridor: Corridor) -> None:
        body = corridor_to_dict(corridor, "crystal-range")
        assert "elevation_ft" in body["waypoints"][0]
        assert "length_miles" in body["segments"][0]

    def test_it_survives_a_json_round_trip(self, corridor: Corridor) -> None:
        body = corridor_to_dict(corridor, "crystal-range")
        assert from_json(to_json(body))["name"] == corridor.name


class TestPlanSerialisation:
    def test_the_schedule_has_a_row_per_day(self, plan: Itinerary) -> None:
        body = plan_to_dict(plan, "crystal-range", generated_at=STAMP)
        assert len(body["schedule"]) == len(plan)

    def test_the_generated_stamp_is_recorded(self, plan: Itinerary) -> None:
        body = plan_to_dict(plan, "crystal-range", generated_at=STAMP)
        assert body["generated_at"].startswith("2025-07-01T12:00")

    def test_the_hiker_is_included_when_given(self, plan: Itinerary, hiker: HikerProfile) -> None:
        body = plan_to_dict(plan, "crystal-range", profile=hiker, generated_at=STAMP)
        assert body["hiker"]["flat_pace_mph"] == pytest.approx(2.7)

    def test_the_hiker_is_left_out_when_not_given(self, plan: Itinerary) -> None:
        assert "hiker" not in plan_to_dict(plan, "crystal-range", generated_at=STAMP)

    def test_the_totals_match_the_itinerary(self, plan: Itinerary) -> None:
        body = plan_to_dict(plan, "crystal-range", generated_at=STAMP)
        assert body["total_miles"] == pytest.approx(plan.total_distance.in_miles, abs=0.01)
        assert body["days"] == len(plan)

    def test_a_zero_day_is_marked(self, plan: Itinerary) -> None:
        body = plan_to_dict(plan.with_zero_day_after(0), "crystal-range", generated_at=STAMP)
        assert any(day["is_zero"] for day in body["schedule"])

    def test_the_hiker_dict_carries_every_field(self, hiker: HikerProfile) -> None:
        body = hiker_to_dict(hiker)
        assert set(body) == {
            "name",
            "flat_pace_mph",
            "max_moving_hours",
            "max_daily_gain_ft",
            "break_fraction",
            "reference_load_lb",
            "night_hiking",
        }


class TestJsonHelpers:
    def test_a_date_is_encoded(self) -> None:
        assert '"2025-07-20"' in to_json({"schema_version": 1, "when": START})

    def test_something_unserialisable_is_refused(self) -> None:
        with pytest.raises(DataSourceError, match="not serialisable"):
            to_json({"schema_version": 1, "value": object()})

    def test_bad_json_is_refused(self) -> None:
        with pytest.raises(DataSourceError, match="not valid json"):
            from_json("{not json")

    def test_a_json_array_is_refused(self) -> None:
        with pytest.raises(DataSourceError, match="must be a json object"):
            from_json("[1, 2, 3]")

    def test_an_unknown_schema_version_is_refused(self) -> None:
        with pytest.raises(DataSourceError, match="schema version is not supported"):
            from_json('{"schema_version": 99}')


class TestPermitReportSerialisation:
    def test_findings_are_flattened(self, plan: Itinerary, zone_map) -> None:
        report = validate_nights(plan.camp_nights(), zone_map)
        body = permit_report_to_dict(report)
        assert body["permittable"] is False
        assert body["nights_checked"] == len(plan)
        assert all("rule" in finding for finding in body["findings"])

    def test_a_clean_report_serialises(self, plan: Itinerary, zone_map) -> None:
        report = validate_nights([], zone_map)
        body = permit_report_to_dict(report)
        assert body["permittable"] is True
        assert body["findings"] == []


class TestCalendarHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("plain", "plain"),
            ("a,b", "a\\,b"),
            ("a;b", "a\\;b"),
            ("a\nb", "a\\nb"),
            ("a\\b", "a\\\\b"),
        ],
    )
    def test_escaping(self, raw: str, expected: str) -> None:
        assert escape(raw) == expected

    def test_short_lines_are_not_folded(self) -> None:
        assert fold("short") == ["short"]

    def test_long_lines_fold_onto_continuations(self) -> None:
        folded = fold("x" * 200)
        assert len(folded) > 1
        assert all(len(line) <= 75 for line in folded)
        assert all(line.startswith(" ") for line in folded[1:])

    def test_dates_use_the_basic_format(self) -> None:
        assert format_date(date(2025, 7, 20)) == "20250720"


class TestIcsExport:
    def test_the_calendar_is_well_formed(self, plan: Itinerary) -> None:
        ics = to_ics(plan, generated_at=STAMP)
        assert ics.startswith("BEGIN:VCALENDAR")
        assert ics.rstrip().endswith("END:VCALENDAR")

    def test_one_event_per_day(self, plan: Itinerary) -> None:
        assert count_events(to_ics(plan, generated_at=STAMP)) == len(plan)

    def test_events_are_all_day(self, plan: Itinerary) -> None:
        ics = to_ics(plan, generated_at=STAMP)
        assert "DTSTART;VALUE=DATE:" in ics
        assert "DTEND;VALUE=DATE:" in ics

    def test_the_end_date_is_the_day_after(self, plan: Itinerary) -> None:
        ics = to_ics(plan, generated_at=STAMP)
        assert f"DTSTART;VALUE=DATE:{format_date(START)}" in ics
        assert f"DTEND;VALUE=DATE:{format_date(date(2025, 7, 21))}" in ics

    def test_uids_are_unique(self, plan: Itinerary) -> None:
        ics = to_ics(plan, generated_at=STAMP)
        uids = [line for line in ics.splitlines() if line.startswith("UID:")]
        assert len(uids) == len(set(uids)) == len(plan)

    def test_the_summary_names_the_corridor_and_the_mileage(self, plan: Itinerary) -> None:
        ics = to_ics(plan, generated_at=STAMP)
        assert "Crystal Range Traverse" in ics
        assert "mi to" in ics

    def test_a_zero_day_says_so(self, plan: Itinerary) -> None:
        assert "zero day" in to_ics(plan.with_zero_day_after(0), generated_at=STAMP)

    def test_lines_use_crlf(self, plan: Itinerary) -> None:
        assert "\r\n" in to_ics(plan, generated_at=STAMP)

    def test_no_rendered_line_exceeds_the_limit(self, plan: Itinerary) -> None:
        ics = to_ics(plan, generated_at=STAMP)
        assert all(len(line) <= 75 for line in ics.split("\r\n"))


class TestTripSheet:
    def test_it_names_the_hiker_and_the_contact(self, plan: Itinerary) -> None:
        text = render_trip_sheet(
            plan, hiker_name="Ada Boulton", emergency_contact="Ruth on 555 0134"
        )
        assert "Ada Boulton" in text
        assert "Ruth on 555 0134" in text

    def test_it_lists_every_date(self, plan: Itinerary) -> None:
        text = render_trip_sheet(plan, hiker_name="Ada", emergency_contact="Ruth")
        for day in plan:
            assert day.day.isoformat() in text

    def test_it_lists_the_exits(self, plan: Itinerary) -> None:
        text = render_trip_sheet(plan, hiker_name="Ada", emergency_contact="Ruth")
        assert "EXIT POINTS" in text
        assert "Barker Pass Road" in text

    def test_it_lists_water_on_the_corridor(self, plan: Itinerary) -> None:
        text = render_trip_sheet(plan, hiker_name="Ada", emergency_contact="Ruth")
        assert "WATER ON THE CORRIDOR" in text
        assert "Tamarack Creek" in text

    def test_resupply_is_included_when_towns_are_given(self, plan: Itinerary, towns) -> None:
        text = render_trip_sheet(plan, hiker_name="Ada", emergency_contact="Ruth", towns=towns)
        assert "RESUPPLY AND SERVICES" in text
        assert "Soda Springs" in text

    def test_resupply_is_left_out_without_towns(self, plan: Itinerary) -> None:
        text = render_trip_sheet(plan, hiker_name="Ada", emergency_contact="Ruth")
        assert "RESUPPLY AND SERVICES" not in text

    def test_it_fits_a_printed_page_width(self, plan: Itinerary, towns) -> None:
        text = render_trip_sheet(plan, hiker_name="Ada", emergency_contact="Ruth", towns=towns)
        assert all(len(line) <= 80 for line in text.splitlines())

    def test_a_missing_hiker_name_is_refused(self, plan: Itinerary) -> None:
        with pytest.raises(DataSourceError, match="needs a hiker name"):
            render_trip_sheet(plan, hiker_name="  ", emergency_contact="Ruth")

    def test_a_missing_contact_is_refused(self, plan: Itinerary) -> None:
        with pytest.raises(DataSourceError, match="needs an emergency contact"):
            render_trip_sheet(plan, hiker_name="Ada", emergency_contact="")
