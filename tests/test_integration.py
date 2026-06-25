"""End to end: a datasheet on disk becomes a permitted, exported trip.

Every other test file exercises one layer. This one walks the whole path a real
planner takes, in order, through the public surfaces only. It is the test that
catches the failures that live between two modules that each pass their own
tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from tests.conftest import build_inventory
from typer.testing import CliRunner

from backpacking.api.app import create_app
from backpacking.cli.main import app as cli_app
from backpacking.config import Settings
from backpacking.food.rations import plan_rations
from backpacking.gear.loadout import Loadout, fuel_for
from backpacking.pace.estimator import PaceEstimator
from backpacking.permits.validate import suggest_fixes, validate_nights
from backpacking.plan.rebalance import mark_resupply, rebalance_for_rest
from backpacking.plan.solver import PlanRequest, solve
from backpacking.report.calendar import count_events, to_ics
from backpacking.report.serialize import from_json, plan_to_dict, to_json
from backpacking.report.tripsheet import render_trip_sheet
from backpacking.resupply.strategy import plan_resupply
from backpacking.season.conditions import check_itinerary, earliest_walkable_start
from backpacking.season.snowpack import SnowYear
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database
from backpacking.trail.datasheet import corridor_to_rows, load_corridor, write_datasheet
from backpacking.units import Energy, Volume
from backpacking.water.carry import find_dry_stretches, plan_carry

START = date(2025, 7, 20)


@pytest.fixture
def workspace(tmp_path, corridor, water, zone_map, towns) -> Iterator[dict[str, object]]:
    """A datasheet on disk and a database with everything else loaded."""
    sheet = tmp_path / "crystal-range.csv"
    sheet.write_text(write_datasheet(corridor_to_rows(corridor)), encoding="utf-8")
    url = f"sqlite+pysqlite:///{tmp_path / 'trip.sqlite3'}"
    database = Database(Settings(database_url=url))
    database.create_all()
    with database.session() as session:
        corridor_id = CorridorRepository(session).save(
            load_corridor(sheet, name=corridor.name), "crystal-range"
        )
        WaterRepository(session).save(corridor_id, list(water))
        PermitRepository(session).save(corridor_id, list(zone_map))
        ResupplyRepository(session).save(corridor_id, list(towns))
    yield {"sheet": sheet, "url": url, "database": database, "tmp": tmp_path}
    database.dispose()


class TestFullPlanningRun:
    def test_a_datasheet_becomes_a_finished_trip(self, workspace, hiker) -> None:
        database = workspace["database"]

        with database.session() as session:
            corridors = CorridorRepository(session)
            corridor = corridors.load("crystal-range")
            corridor_id = corridors.corridor_id("crystal-range")
            zones = PermitRepository(session).load(corridor_id)
            sources = WaterRepository(session).load(corridor_id)
            towns = ResupplyRepository(session).load(corridor_id)

        # The corridor survived the datasheet round trip intact.
        assert corridor.length.in_miles == pytest.approx(78.0)
        assert corridor.total_gain().in_feet == pytest.approx(9490.0)

        # The season says when it is walkable at all.
        snow_year = SnowYear(year=2025, percent_of_median=115.0)
        earliest = earliest_walkable_start(corridor, snow_year)
        assert earliest.year == 2025

        # Resupply decides how long the carries are.
        strategy = plan_resupply(
            towns, corridor.start_mile, corridor.end_mile, hiker, max_carry_days=4.0
        )
        assert strategy.longest_carry.days <= 4.0

        # The pack is built from the longest carry.
        rations = plan_rations(strategy.longest_carry.days, Energy.kilocalories(3000.0))
        loadout = Loadout(
            inventory=build_inventory(),
            rations=rations,
            fuel_start=fuel_for(strategy.longest_carry.days),
            carried_water=Volume.liters(2.0),
        )
        assert loadout.start_weight > loadout.base_weight
        assert 15.0 < loadout.start_weight.in_pounds < 40.0

        # The plan is built for that pack weight.
        plan = solve(
            PlanRequest(
                corridor=corridor,
                profile=hiker,
                start_date=max(START, earliest),
                pack_weight=loadout.start_weight,
            )
        )
        assert plan.covers_whole_corridor()

        # It is reshaped for rest and annotated with the resupply stops.
        reshaped = mark_resupply(rebalance_for_rest(plan, hiker, threshold=0.02), strategy.stops)
        assert reshaped.total_distance.in_miles == pytest.approx(78.0)

        # Water is checked against the month it actually falls in.
        estimator = PaceEstimator(profile=hiker)
        gaps = find_dry_stretches(corridor, sources, reshaped.start_date.month)
        for gap in gaps:
            carry = plan_carry(corridor, estimator, gap, Volume.liters(6.0))
            assert carry.required.in_liters > 0.0

        # Permits are checked, and the fix is actionable.
        report = validate_nights(reshaped.camp_nights(has_canister=True), zones)
        if not report.is_permittable:
            assert suggest_fixes(report)

        # The season is checked against the finished plan.
        findings = check_itinerary(reshaped, snow_year)
        assert all(0.0 <= finding.severity <= 1.0 for finding in findings)

        # The plan is stored and comes back the same.
        with database.session() as session:
            plans = PlanRepository(session)
            plan_id = plans.save(
                reshaped, CorridorRepository(session).corridor_id("crystal-range"), hiker.name
            )
        with database.session() as session:
            restored = PlanRepository(session).load(plan_id, corridor)
        assert len(restored) == len(reshaped)
        assert restored.total_distance.in_miles == pytest.approx(reshaped.total_distance.in_miles)

        # And it exports to everything a hiker leaves with.
        ics = to_ics(restored)
        assert count_events(ics) == len(restored)
        sheet = render_trip_sheet(
            restored, hiker_name="Ada Boulton", emergency_contact="Ruth", towns=towns
        )
        assert "TRIP SHEET" in sheet
        archived = from_json(to_json(plan_to_dict(restored, "crystal-range", profile=hiker)))
        assert archived["days"] == len(restored)


class TestApiAndCliAgree:
    def test_the_same_plan_comes_out_of_both(self, workspace, hiker) -> None:
        settings = Settings(database_url=str(workspace["url"]))
        app = create_app(settings, database=workspace["database"])
        body = {
            "corridor": "crystal-range",
            "start_date": START.isoformat(),
            "hiker": {
                "name": hiker.name,
                "flat_pace_mph": hiker.flat_pace_mph,
                "max_moving_hours": hiker.max_moving_hours,
                "break_fraction": hiker.break_fraction,
                "pack_weight_lb": hiker.reference_load.in_pounds,
            },
        }
        with TestClient(app) as client:
            api_plan = client.post("/plans", json=body).json()

        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            [
                "--database",
                str(workspace["url"]),
                "plan",
                "build",
                "crystal-range",
                "--start",
                START.isoformat(),
                "--pace",
                str(hiker.flat_pace_mph),
                "--pack",
                str(round(hiker.reference_load.in_pounds, 2)),
                "--hours",
                str(hiker.max_moving_hours),
            ],
        )
        assert result.exit_code == 0
        assert f"{len(api_plan['days'])} days" in result.output

    def test_a_plan_saved_by_the_cli_is_readable_by_the_api(self, workspace) -> None:
        runner = CliRunner()
        runner.invoke(
            cli_app,
            [
                "--database",
                str(workspace["url"]),
                "plan",
                "build",
                "crystal-range",
                "--start",
                START.isoformat(),
                "--save",
            ],
        )
        settings = Settings(database_url=str(workspace["url"]))
        app = create_app(settings, database=workspace["database"])
        with TestClient(app) as client:
            listed = client.get("/plans?corridor=crystal-range").json()
            assert len(listed) == 1
            plan_id = listed[0]["plan_id"]
            loaded = client.get(f"/plans/{plan_id}?corridor=crystal-range").json()
        assert loaded["total_miles"] == pytest.approx(78.0)

    def test_the_calendar_from_the_api_matches_the_one_from_the_cli(
        self, workspace, tmp_path
    ) -> None:
        runner = CliRunner()
        runner.invoke(
            cli_app,
            [
                "--database",
                str(workspace["url"]),
                "plan",
                "build",
                "crystal-range",
                "--start",
                START.isoformat(),
                "--save",
            ],
        )
        out = tmp_path / "cli.ics"
        runner.invoke(
            cli_app,
            [
                "--database",
                str(workspace["url"]),
                "report",
                "calendar",
                "1",
                "-c",
                "crystal-range",
                "-o",
                str(out),
            ],
        )
        settings = Settings(database_url=str(workspace["url"]))
        app = create_app(settings, database=workspace["database"])
        with TestClient(app) as client:
            served = client.get("/reports/plan/1/calendar?corridor=crystal-range").text
        assert count_events(served) == count_events(out.read_text(encoding="utf-8"))


class TestRegressionsWeHaveHit:
    def test_a_plan_shifted_across_a_month_boundary_stays_valid(self, workspace, hiker) -> None:
        """Shifting dates must not disturb the mileage or the day ordering."""
        with workspace["database"].session() as session:
            corridor = CorridorRepository(session).load("crystal-range")
        plan = solve(PlanRequest(corridor=corridor, profile=hiker, start_date=date(2025, 7, 29)))
        shifted = plan.shifted_to(date(2025, 8, 30))
        assert shifted.total_distance.in_miles == pytest.approx(plan.total_distance.in_miles)
        assert [day.day for day in shifted] == sorted(day.day for day in shifted)

    def test_a_corridor_deleted_takes_its_plans_with_it(self, workspace, hiker) -> None:
        database = workspace["database"]
        with database.session() as session:
            corridors = CorridorRepository(session)
            corridor = corridors.load("crystal-range")
            plan = solve(PlanRequest(corridor=corridor, profile=hiker, start_date=START))
            plan_id = PlanRepository(session).save(
                plan, corridors.corridor_id("crystal-range"), hiker.name
            )
        with database.session() as session:
            CorridorRepository(session).delete("crystal-range")
        with database.session() as session:
            from backpacking.errors import DataSourceError

            with pytest.raises(DataSourceError):
                PlanRepository(session).load(plan_id, corridor)

    def test_rest_days_do_not_change_where_the_hiker_ends_up(self, workspace, hiker) -> None:
        with workspace["database"].session() as session:
            corridor = CorridorRepository(session).load("crystal-range")
        plan = solve(PlanRequest(corridor=corridor, profile=hiker, start_date=START))
        rested = plan.with_zero_day_after(1)
        assert rested.end_mile == pytest.approx(plan.end_mile)
        assert rested.finish_date == plan.finish_date + timedelta(days=1)
