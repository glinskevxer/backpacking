"""The snow model and what it says about a corridor and a plan."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backpacking.pace.models import HikerProfile
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.solver import PlanRequest, solve
from backpacking.season.conditions import (
    check_itinerary,
    corridor_melt_out,
    earliest_walkable_start,
    serious_findings,
    snowbound_waypoints,
    suggested_delay,
    summarise,
)
from backpacking.season.snowpack import (
    Aspect,
    SeasonError,
    SnowYear,
    describe_hazard,
    ford_hazard,
    is_snowbound,
    melt_out_date,
    melt_peak_date,
    snow_line,
)
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance

MEDIAN = SnowYear(year=2025, percent_of_median=100.0)
HEAVY = SnowYear(year=2025, percent_of_median=180.0)
LIGHT = SnowYear(year=2025, percent_of_median=55.0)


class TestSnowYear:
    def test_the_descriptors(self) -> None:
        assert MEDIAN.descriptor == "near median"
        assert HEAVY.descriptor == "exceptional"
        assert LIGHT.descriptor == "light"
        assert SnowYear(2025, 130.0).descriptor == "heavy"

    def test_the_flags(self) -> None:
        assert HEAVY.is_heavy and not HEAVY.is_light
        assert LIGHT.is_light and not LIGHT.is_heavy
        assert not MEDIAN.is_heavy and not MEDIAN.is_light

    def test_an_absurd_snowpack_is_refused(self) -> None:
        with pytest.raises(SeasonError, match="outside what the model describes"):
            SnowYear(2025, 900.0)

    def test_a_nonsense_year_is_refused(self) -> None:
        with pytest.raises(SeasonError, match="snow year is out of range"):
            SnowYear(1200, 100.0)

    def test_repr(self) -> None:
        assert repr(HEAVY) == "SnowYear(2025, 180% of median)"


class TestAspect:
    def test_south_melts_first_and_north_last(self) -> None:
        assert Aspect.SOUTH.melt_offset_days < Aspect.FLAT.melt_offset_days
        assert Aspect.NORTH.melt_offset_days > Aspect.EAST.melt_offset_days

    def test_flat_is_the_reference(self) -> None:
        assert Aspect.FLAT.melt_offset_days == 0


class TestSnowLine:
    def test_the_reference_date_in_a_median_year(self) -> None:
        assert snow_line(MEDIAN, date(2025, 6, 1)).in_feet == pytest.approx(7000.0)

    def test_it_rises_through_the_season(self) -> None:
        june = snow_line(MEDIAN, date(2025, 6, 1)).in_feet
        july = snow_line(MEDIAN, date(2025, 7, 1)).in_feet
        assert july > june

    def test_a_heavy_year_holds_it_down(self) -> None:
        assert snow_line(HEAVY, date(2025, 7, 1)) < snow_line(MEDIAN, date(2025, 7, 1))

    def test_a_light_year_pushes_it_up(self) -> None:
        assert snow_line(LIGHT, date(2025, 7, 1)) > snow_line(MEDIAN, date(2025, 7, 1))

    def test_a_north_aspect_lags(self) -> None:
        north = snow_line(MEDIAN, date(2025, 7, 1), Aspect.NORTH)
        south = snow_line(MEDIAN, date(2025, 7, 1), Aspect.SOUTH)
        assert north < south

    def test_a_date_from_another_year_is_refused(self) -> None:
        with pytest.raises(SeasonError, match="not in this snow year"):
            snow_line(MEDIAN, date(2024, 7, 1))

    def test_snowbound_compares_against_the_line(self) -> None:
        assert is_snowbound(MEDIAN, date(2025, 6, 1), Distance.feet(9000))
        assert not is_snowbound(MEDIAN, date(2025, 6, 1), Distance.feet(5000))


class TestMeltOut:
    def test_it_inverts_the_snow_line(self) -> None:
        when = melt_out_date(MEDIAN, Distance.feet(8620), Aspect.NORTH)
        line = snow_line(MEDIAN, when, Aspect.NORTH)
        assert line.in_feet == pytest.approx(8620.0, abs=70.0)

    def test_higher_ground_melts_later(self) -> None:
        low = melt_out_date(MEDIAN, Distance.feet(7500))
        high = melt_out_date(MEDIAN, Distance.feet(9500))
        assert high > low

    def test_a_heavy_year_melts_later(self) -> None:
        assert melt_out_date(HEAVY, Distance.feet(8600)) > melt_out_date(
            MEDIAN, Distance.feet(8600)
        )

    def test_the_result_stays_inside_the_year(self) -> None:
        assert melt_out_date(HEAVY, Distance.feet(14000)).year == 2025

    def test_the_melt_peak_is_later_in_a_heavy_year(self) -> None:
        assert melt_peak_date(HEAVY) > melt_peak_date(MEDIAN)


class TestFordHazard:
    def test_the_hazard_peaks_near_the_melt_peak(self) -> None:
        peak = melt_peak_date(MEDIAN)
        at_peak = ford_hazard(MEDIAN, peak, Distance.feet(8000))
        later = ford_hazard(MEDIAN, peak + timedelta(days=45), Distance.feet(8000))
        assert at_peak > later

    def test_a_heavy_year_is_more_dangerous_at_its_peak(self) -> None:
        assert ford_hazard(HEAVY, melt_peak_date(HEAVY), Distance.feet(8000)) > ford_hazard(
            LIGHT, melt_peak_date(LIGHT), Distance.feet(8000)
        )

    def test_the_hazard_stays_within_zero_and_one(self) -> None:
        for offset in range(-60, 120, 5):
            value = ford_hazard(
                HEAVY, melt_peak_date(HEAVY) + timedelta(days=offset), Distance.feet(9000)
            )
            assert 0.0 <= value <= 1.0

    def test_a_low_drainage_is_less_hazardous(self) -> None:
        peak = melt_peak_date(MEDIAN)
        assert ford_hazard(MEDIAN, peak, Distance.feet(3000)) < ford_hazard(
            MEDIAN, peak, Distance.feet(9000)
        )

    def test_a_date_from_another_year_is_refused(self) -> None:
        with pytest.raises(SeasonError, match="not in this snow year"):
            ford_hazard(MEDIAN, date(2024, 7, 1), Distance.feet(8000))

    @pytest.mark.parametrize(
        ("value", "word"),
        [
            (0.9, "dangerous"),
            (0.6, "serious"),
            (0.3, "wet but manageable"),
            (0.1, "straightforward"),
        ],
    )
    def test_the_descriptions(self, value: float, word: str) -> None:
        assert describe_hazard(value) == word


class TestCorridorConditions:
    def test_high_points_are_snowbound_early_in_a_heavy_year(self, corridor: Corridor) -> None:
        bound = snowbound_waypoints(corridor, HEAVY, date(2025, 6, 15))
        assert {w.id for w in bound} >= {"granite-chief", "mosquito-pass"}

    def test_nothing_is_snowbound_late_in_a_light_year(self, corridor: Corridor) -> None:
        assert snowbound_waypoints(corridor, LIGHT, date(2025, 8, 15)) == ()

    def test_melt_out_covers_every_pass_and_summit(self, corridor: Corridor) -> None:
        melt = corridor_melt_out(corridor, MEDIAN)
        assert set(melt) == {"mosquito-pass", "granite-chief", "mule-ear-pass"}

    def test_the_earliest_start_is_after_the_last_melt(self, corridor: Corridor) -> None:
        melt = corridor_melt_out(corridor, MEDIAN)
        assert earliest_walkable_start(corridor, MEDIAN) == max(melt.values())

    def test_a_margin_pushes_the_start_back(self, corridor: Corridor) -> None:
        plain = earliest_walkable_start(corridor, MEDIAN)
        padded = earliest_walkable_start(corridor, MEDIAN, margin_days=7)
        assert (padded - plain).days == 7

    def test_a_heavy_year_needs_a_later_start(self, corridor: Corridor) -> None:
        assert earliest_walkable_start(corridor, HEAVY) > earliest_walkable_start(corridor, MEDIAN)

    def test_a_corridor_with_no_high_points_is_refused(self, short_corridor: Corridor) -> None:
        with pytest.raises(SeasonError, match="no passes or summits"):
            earliest_walkable_start(short_corridor, MEDIAN)


class TestItineraryConditions:
    @pytest.fixture
    def plan(self, corridor: Corridor, hiker: HikerProfile) -> Itinerary:
        return solve(PlanRequest(corridor=corridor, profile=hiker, start_date=date(2025, 7, 20)))

    def test_a_july_plan_in_a_heavy_year_has_findings(self, plan: Itinerary) -> None:
        findings = check_itinerary(plan, HEAVY)
        assert findings
        assert any(finding.kind == "snowbound" for finding in findings)

    def test_the_ford_is_always_reported(self, plan: Itinerary) -> None:
        findings = check_itinerary(plan, MEDIAN)
        assert any(finding.waypoint.id == "squaw-ford" for finding in findings)

    def test_serious_findings_come_back_worst_first(self, plan: Itinerary) -> None:
        serious = serious_findings(check_itinerary(plan, HEAVY))
        assert [f.severity for f in serious] == sorted([f.severity for f in serious], reverse=True)

    def test_a_light_year_in_september_is_clean(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        late = solve(PlanRequest(corridor=corridor, profile=hiker, start_date=date(2025, 9, 10)))
        assert serious_findings(check_itinerary(late, LIGHT)) == ()

    def test_a_delay_is_suggested_for_a_heavy_year(self, plan: Itinerary) -> None:
        delay = suggested_delay(plan, HEAVY)
        assert delay > 0
        shifted = plan.shifted_to(plan.start_date + timedelta(days=delay))
        assert serious_findings(check_itinerary(shifted, HEAVY)) == ()

    def test_no_delay_is_needed_when_there_is_nothing_serious(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        late = solve(PlanRequest(corridor=corridor, profile=hiker, start_date=date(2025, 9, 10)))
        assert suggested_delay(late, LIGHT) == 0

    def test_the_summary_says_so_when_there_is_nothing_at_all(self) -> None:
        assert summarise([]).startswith("nothing of concern")

    def test_a_quiet_season_only_leaves_notes(
        self, corridor: Corridor, hiker: HikerProfile
    ) -> None:
        late = solve(PlanRequest(corridor=corridor, profile=hiker, start_date=date(2025, 9, 10)))
        findings = check_itinerary(late, LIGHT)
        assert serious_findings(findings) == ()
        assert summarise(findings) == "1 further note"

    def test_the_summary_counts_the_minor_notes(self, plan: Itinerary) -> None:
        text = summarise(check_itinerary(plan, HEAVY))
        assert "further note" in text or "\n" in text

    def test_a_finding_reprs_readably(self, plan: Itinerary) -> None:
        finding = check_itinerary(plan, HEAVY)[0]
        assert repr(finding).startswith("SnowFinding(")
