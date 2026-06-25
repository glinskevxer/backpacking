"""Rendering plans and permit reports."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.permits.rules import CampNight
from backpacking.permits.validate import validate_nights
from backpacking.permits.zones import ZoneMap
from backpacking.plan.explain import (
    explain_day,
    explain_plan,
    render_costs,
    render_full_report,
    render_permit_report,
    render_schedule,
    render_summary,
)
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.scoring import target_hours_for
from backpacking.plan.solver import PlanRequest, solve
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance

START = date(2025, 7, 20)


@pytest.fixture
def plan(corridor: Corridor, hiker: HikerProfile) -> Itinerary:
    return solve(PlanRequest(corridor=corridor, profile=hiker, start_date=START))


class TestExplainDay:
    def test_the_terms_are_named(self, plan: Itinerary, hiker: HikerProfile) -> None:
        explanation = explain_day(plan[0], hiker, target_hours=7.2)
        assert set(explanation.terms) == {
            "effort",
            "camp",
            "late_finish",
            "steep_finish",
            "per_day",
        }

    def test_the_total_sums_the_terms(self, plan: Itinerary, hiker: HikerProfile) -> None:
        explanation = explain_day(plan[0], hiker, target_hours=7.2)
        assert explanation.total == pytest.approx(sum(explanation.terms.values()))

    def test_the_dominant_term_is_the_biggest(self, plan: Itinerary, hiker: HikerProfile) -> None:
        explanation = explain_day(plan[0], hiker, target_hours=7.2)
        biggest = max(explanation.terms.values())
        assert explanation.terms[explanation.dominant_term] == pytest.approx(biggest)

    def test_a_day_far_from_target_is_dominated_by_effort(
        self, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        explanation = explain_day(plan[0], hiker, target_hours=1.0)
        assert explanation.dominant_term == "effort"

    def test_a_climb_at_the_end_shows_up(self, plan: Itinerary, hiker: HikerProfile) -> None:
        flat = explain_day(plan[0], hiker, target_hours=7.2)
        steep = explain_day(
            plan[0], hiker, target_hours=7.2, gain_in_last_third=Distance.feet(2400)
        )
        assert steep.terms["steep_finish"] > flat.terms["steep_finish"]

    def test_repr(self, plan: Itinerary, hiker: HikerProfile) -> None:
        explanation = explain_day(plan[0], hiker, target_hours=7.2)
        assert repr(explanation).startswith("DayExplanation(day 0,")

    def test_explaining_a_plan_covers_every_day(self, plan: Itinerary, hiker: HikerProfile) -> None:
        assert len(explain_plan(plan, hiker, target_hours=7.2)) == len(plan)


class TestRenderSchedule:
    def test_the_header_names_the_corridor(self, plan: Itinerary) -> None:
        text = render_schedule(plan)
        assert text.splitlines()[0].startswith("Crystal Range Traverse - ")

    def test_there_is_a_line_per_day(self, plan: Itinerary) -> None:
        text = render_schedule(plan)
        body = text.splitlines()[4:]
        assert len(body) == len(plan)

    def test_days_are_numbered_from_one(self, plan: Itinerary) -> None:
        body = render_schedule(plan).splitlines()[4:]
        assert body[0].strip().startswith("1 ")

    def test_every_date_appears(self, plan: Itinerary) -> None:
        text = render_schedule(plan)
        for day in plan:
            assert day.day.isoformat() in text

    def test_a_zero_day_is_marked(self, plan: Itinerary) -> None:
        text = render_schedule(plan.with_zero_day_after(0))
        assert "zero" in text

    def test_an_unnamed_camp_says_so(self, plan: Itinerary) -> None:
        assert "wherever you get to" in render_schedule(plan)

    def test_no_line_runs_away(self, plan: Itinerary) -> None:
        assert all(len(line) < 90 for line in render_schedule(plan).splitlines())


class TestRenderCosts:
    def test_every_day_gets_a_row(self, plan: Itinerary, hiker: HikerProfile) -> None:
        explanations = explain_plan(plan, hiker, target_hours=7.2)
        rows = render_costs(explanations).splitlines()
        assert len(rows) == len(plan) + 3

    def test_the_header_names_every_term(self, plan: Itinerary, hiker: HikerProfile) -> None:
        header = render_costs(explain_plan(plan, hiker, target_hours=7.2)).splitlines()[0]
        for term in ("effort", "camp", "late_finish", "steep_finish", "per_day"):
            assert term in header

    def test_the_last_row_is_the_grand_total(self, plan: Itinerary, hiker: HikerProfile) -> None:
        explanations = explain_plan(plan, hiker, target_hours=7.2)
        expected = sum(explanation.total for explanation in explanations)
        assert f"{expected:.2f}" in render_costs(explanations).splitlines()[-1]

    def test_an_empty_plan_cannot_be_rendered(self) -> None:
        with pytest.raises(PlanInfeasible, match="empty plan"):
            render_costs([])


class TestRenderPermitReport:
    def test_a_clean_report_is_one_line(self, zone_map: ZoneMap) -> None:
        nights = [
            CampNight(
                night=START,
                mile=5.1,
                site_id="haypress-camp",
                distance_from_water=Distance.feet(300),
            )
        ]
        text = render_permit_report(validate_nights(nights, zone_map))
        assert text == "1 nights, no findings"

    def test_violations_are_listed_under_blocking(self, zone_map: ZoneMap) -> None:
        report = validate_nights([CampNight(night=START, mile=20.0)], zone_map)
        text = render_permit_report(report)
        assert "blocking:" in text
        assert "designated site" in text

    def test_advisories_are_listed_separately(self, zone_map: ZoneMap) -> None:
        nights = [
            CampNight(
                night=START,
                mile=15.3,
                site_id="clyde-basin",
                has_canister=True,
                distance_from_water=Distance.feet(20),
            )
        ]
        text = render_permit_report(validate_nights(nights, zone_map))
        assert "worth knowing:" in text
        assert "blocking:" not in text

    def test_dates_appear_beside_the_findings(self, zone_map: ZoneMap) -> None:
        report = validate_nights([CampNight(night=START, mile=20.0)], zone_map)
        assert START.isoformat() in render_permit_report(report)


class TestRenderSummary:
    def test_it_names_the_dates_and_the_hiker(self, plan: Itinerary, hiker: HikerProfile) -> None:
        text = render_summary(plan, hiker)
        assert plan.start_date.isoformat() in text
        assert plan.finish_date.isoformat() in text
        assert "reference" in text

    def test_it_reports_the_longest_day_and_biggest_climb(
        self, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        text = render_summary(plan, hiker)
        assert f"{plan.longest_day.miles:.1f} miles" in text
        assert f"{plan.biggest_climb.gain.in_feet:.0f} feet" in text

    def test_it_is_three_sentences(self, plan: Itinerary, hiker: HikerProfile) -> None:
        assert len(render_summary(plan, hiker).splitlines()) == 3


class TestRenderFullReport:
    def test_it_stacks_the_sections(self, plan: Itinerary, hiker: HikerProfile) -> None:
        text = render_full_report(plan, hiker, target_hours=target_hours_for(hiker))
        assert "Crystal Range Traverse - " in text
        assert "effort" in text
        assert plan.start_date.isoformat() in text

    def test_the_permit_report_is_appended_when_given(
        self, plan: Itinerary, hiker: HikerProfile, zone_map: ZoneMap
    ) -> None:
        report = validate_nights(plan.camp_nights(has_canister=True), zone_map)
        text = render_full_report(
            plan, hiker, target_hours=target_hours_for(hiker), permit_report=report
        )
        assert report.summary() in text

    def test_it_is_left_out_when_not_given(self, plan: Itinerary, hiker: HikerProfile) -> None:
        text = render_full_report(plan, hiker, target_hours=target_hours_for(hiker))
        assert "blocking:" not in text
