"""Report and season endpoints, plus the report commands."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from backpacking.cli.main import app as cli_app
from backpacking.config import Settings
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database

BODY = {
    "corridor": "crystal-range",
    "start_date": "2025-07-20",
    "hiker": {"name": "reference", "flat_pace_mph": 2.7},
}


@pytest.fixture
def plan_id(api: TestClient) -> int:
    return int(api.post("/plans/save", json=BODY).json()["plan_id"])


class TestCorridorReport:
    def test_the_archival_view_is_returned(self, api: TestClient) -> None:
        body = api.get("/reports/corridor/crystal-range").json()
        assert body["schema_version"] == 1
        assert len(body["waypoints"]) == 20

    def test_an_unknown_corridor_is_a_404(self, api: TestClient) -> None:
        assert api.get("/reports/corridor/nowhere").status_code == 404


class TestPlanReport:
    def test_the_schedule_is_included(self, api: TestClient, plan_id: int) -> None:
        body = api.get(f"/reports/plan/{plan_id}?corridor=crystal-range").json()
        assert body["days"] == len(body["schedule"])
        assert body["corridor"] == "crystal-range"

    def test_the_permit_report_is_available(self, api: TestClient, plan_id: int) -> None:
        body = api.get(f"/reports/plan/{plan_id}/permits?corridor=crystal-range").json()
        assert body["permittable"] is False
        assert body["findings"]

    def test_a_canister_changes_the_findings(self, api: TestClient, plan_id: int) -> None:
        without = api.get(f"/reports/plan/{plan_id}/permits?corridor=crystal-range").json()
        with_one = api.get(
            f"/reports/plan/{plan_id}/permits?corridor=crystal-range&has_canister=true"
        ).json()
        assert len(with_one["findings"]) < len(without["findings"])

    def test_an_unknown_plan_is_a_404(self, api: TestClient) -> None:
        assert api.get("/reports/plan/9999?corridor=crystal-range").status_code == 404


class TestCalendarEndpoint:
    def test_it_serves_a_calendar(self, api: TestClient, plan_id: int) -> None:
        response = api.get(f"/reports/plan/{plan_id}/calendar?corridor=crystal-range")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/calendar")
        assert response.text.startswith("BEGIN:VCALENDAR")

    def test_it_offers_a_filename(self, api: TestClient, plan_id: int) -> None:
        response = api.get(f"/reports/plan/{plan_id}/calendar?corridor=crystal-range")
        assert f"plan-{plan_id}.ics" in response.headers["content-disposition"]


class TestTripSheetEndpoint:
    def test_it_serves_the_sheet(self, api: TestClient, plan_id: int) -> None:
        response = api.get(
            f"/reports/plan/{plan_id}/tripsheet?corridor=crystal-range"
            "&hiker_name=Ada&emergency_contact=Ruth"
        )
        assert response.status_code == 200
        assert "TRIP SHEET" in response.text
        assert "Ada" in response.text

    def test_resupply_is_included(self, api: TestClient, plan_id: int) -> None:
        response = api.get(
            f"/reports/plan/{plan_id}/tripsheet?corridor=crystal-range"
            "&hiker_name=Ada&emergency_contact=Ruth"
        )
        assert "RESUPPLY AND SERVICES" in response.text

    def test_a_blank_hiker_name_is_rejected(self, api: TestClient, plan_id: int) -> None:
        response = api.get(
            f"/reports/plan/{plan_id}/tripsheet?corridor=crystal-range"
            "&hiker_name=&emergency_contact=Ruth"
        )
        assert response.status_code == 422


class TestSeasonEndpoints:
    def test_the_outlook_lists_melt_out_dates(self, api: TestClient) -> None:
        body = api.get(
            "/reports/season/crystal-range?year=2025&percent_of_median=100"
        ).json()
        assert set(body["melt_out"]) == {"mosquito-pass", "granite-chief", "mule-ear-pass"}
        assert body["descriptor"] == "near median"

    def test_a_heavy_year_starts_later(self, api: TestClient) -> None:
        median = api.get(
            "/reports/season/crystal-range?year=2025&percent_of_median=100"
        ).json()
        heavy = api.get(
            "/reports/season/crystal-range?year=2025&percent_of_median=180"
        ).json()
        assert heavy["earliest_start"] > median["earliest_start"]

    def test_an_absurd_snowpack_is_rejected(self, api: TestClient) -> None:
        assert (
            api.get("/reports/season/crystal-range?year=2025&percent_of_median=900").status_code
            == 422
        )

    def test_the_plan_check_reports_findings(self, api: TestClient, plan_id: int) -> None:
        body = api.get(
            f"/reports/season/crystal-range/plan/{plan_id}?year=2025&percent_of_median=180"
        ).json()
        assert body["total_findings"] > 0
        assert body["summary"]

    def test_a_plan_from_another_year_is_a_409(self, api: TestClient, plan_id: int) -> None:
        response = api.get(
            f"/reports/season/crystal-range/plan/{plan_id}?year=2024&percent_of_median=100"
        )
        assert response.status_code == 409

    def test_the_earliest_endpoint_honours_a_margin(self, api: TestClient) -> None:
        plain = api.get(
            "/reports/season/crystal-range/earliest?year=2025&percent_of_median=100"
        ).json()
        padded = api.get(
            "/reports/season/crystal-range/earliest?year=2025&percent_of_median=100&margin_days=10"
        ).json()
        assert padded["earliest_start"] > plain["earliest_start"]


class TestReportCommands:
    @pytest.fixture
    def cli_db(self, tmp_path, corridor, water, zone_map, towns) -> str:
        url = f"sqlite+pysqlite:///{tmp_path / 'report.sqlite3'}"
        database = Database(Settings(database_url=url))
        database.create_all()
        with database.session() as session:
            corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
            WaterRepository(session).save(corridor_id, list(water))
            PermitRepository(session).save(corridor_id, list(zone_map))
            ResupplyRepository(session).save(corridor_id, list(towns))
        database.dispose()
        return url

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def run(self, runner: CliRunner, url: str, *args: str):
        return runner.invoke(cli_app, ["--database", url, *args])

    def saved(self, runner: CliRunner, url: str) -> None:
        self.run(
            runner, url, "plan", "build", "crystal-range", "--start", "2025-07-20", "--save"
        )

    def test_json_export_to_stdout(self, runner: CliRunner, cli_db: str) -> None:
        self.saved(runner, cli_db)
        result = self.run(runner, cli_db, "report", "json", "1", "-c", "crystal-range")
        assert result.exit_code == 0
        assert '"schema_version": 1' in result.output

    def test_json_export_to_a_file(self, runner: CliRunner, cli_db: str, tmp_path) -> None:
        self.saved(runner, cli_db)
        out = tmp_path / "plan.json"
        result = self.run(
            runner, cli_db, "report", "json", "1", "-c", "crystal-range", "-o", str(out)
        )
        assert result.exit_code == 0
        assert '"corridor": "crystal-range"' in out.read_text(encoding="utf-8")

    def test_calendar_export(self, runner: CliRunner, cli_db: str, tmp_path) -> None:
        self.saved(runner, cli_db)
        out = tmp_path / "plan.ics"
        result = self.run(
            runner, cli_db, "report", "calendar", "1", "-c", "crystal-range", "-o", str(out)
        )
        assert result.exit_code == 0
        assert out.read_text(encoding="utf-8").startswith("BEGIN:VCALENDAR")

    def test_trip_sheet_to_stdout(self, runner: CliRunner, cli_db: str) -> None:
        self.saved(runner, cli_db)
        result = self.run(
            runner, cli_db, "report", "tripsheet", "1", "-c", "crystal-range",
            "--hiker", "Ada", "--contact", "Ruth",
        )
        assert result.exit_code == 0
        assert "TRIP SHEET" in result.output

    def test_season_lists_melt_out(self, runner: CliRunner, cli_db: str) -> None:
        result = self.run(
            runner, cli_db, "report", "season", "crystal-range", "--year", "2025",
            "--percent", "160",
        )
        assert result.exit_code == 0
        assert "heavy year" in result.output or "exceptional year" in result.output
        assert "granite-chief" in result.output

    def test_season_can_check_a_plan(self, runner: CliRunner, cli_db: str) -> None:
        self.saved(runner, cli_db)
        result = self.run(
            runner, cli_db, "report", "season", "crystal-range", "--year", "2025",
            "--percent", "180", "--plan", "1",
        )
        assert result.exit_code == 0
        assert "snow line" in result.output or "further note" in result.output

    def test_melt_prints_one_date(self, runner: CliRunner, cli_db: str) -> None:
        result = self.run(
            runner, cli_db, "report", "melt", "crystal-range", "--year", "2025"
        )
        assert result.exit_code == 0
        assert result.output.strip().startswith("2025-")

    def test_compare_two_plans(self, runner: CliRunner, cli_db: str) -> None:
        self.saved(runner, cli_db)
        self.run(
            runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20",
            "--max-miles", "13", "--save",
        )
        result = self.run(runner, cli_db, "report", "compare", "1", "2", "-c", "crystal-range")
        assert result.exit_code == 0
        assert "days" in result.output
