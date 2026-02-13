"""The command line, driven through the runner rather than a subprocess."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from backpacking.cli.formatting import keyed, miles, plural, table
from backpacking.cli.main import app
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database
from backpacking.config import Settings
from backpacking.trail.datasheet import corridor_to_rows, write_datasheet


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_db(tmp_path, corridor, water, zone_map, towns) -> Iterator[str]:
    """A populated database, returned as the URL to pass with --database."""
    url = f"sqlite+pysqlite:///{tmp_path / 'cli.sqlite3'}"
    database = Database(Settings(database_url=url))
    database.create_all()
    with database.session() as session:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        WaterRepository(session).save(corridor_id, list(water))
        PermitRepository(session).save(corridor_id, list(zone_map))
        ResupplyRepository(session).save(corridor_id, list(towns))
    database.dispose()
    yield url


def run(runner: CliRunner, url: str, *args: str):
    return runner.invoke(app, ["--database", url, *args])


class TestFormatting:
    def test_a_table_pads_to_the_widest_cell(self) -> None:
        text = table(["id", "mile"], [["a", 1.0], ["longer", 12.5]])
        lines = text.splitlines()
        assert len(lines) == 4
        assert lines[0].startswith("id    ")

    def test_a_table_needs_columns(self) -> None:
        with pytest.raises(ValueError, match="at least one column"):
            table([], [])

    def test_a_ragged_row_is_refused(self) -> None:
        with pytest.raises(ValueError, match="3 cells but there are 2 columns"):
            table(["a", "b"], [["x", "y", "z"]])

    def test_keyed_aligns_the_keys(self) -> None:
        text = keyed({"a": 1, "longer": 2})
        assert text.splitlines()[0].startswith("a      ")

    def test_keyed_of_nothing_is_empty(self) -> None:
        assert keyed({}) == ""

    def test_miles_are_one_decimal(self) -> None:
        assert miles(12.345) == "12.3"

    def test_plural_switches_on_the_count(self) -> None:
        assert plural(1, "day") == "1 day"
        assert plural(3, "day") == "3 days"
        assert plural(2, "mile", "miles") == "2 miles"


class TestRootCommands:
    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "backpacking 0.1.0" in result.output

    def test_help_lists_every_group(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for group in ("corridor", "plan", "water", "permit", "resupply"):
            assert group in result.output

    def test_init_creates_the_tables(self, runner: CliRunner, tmp_path) -> None:
        url = f"sqlite+pysqlite:///{tmp_path / 'fresh.sqlite3'}"
        result = run(runner, url, "init")
        assert result.exit_code == 0
        assert "initialised" in result.output
        assert (tmp_path / "fresh.sqlite3").exists()


class TestCorridorCommands:
    def test_list_shows_the_stored_corridor(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "list")
        assert result.exit_code == 0
        assert "crystal-range" in result.output
        assert "78.0" in result.output

    def test_list_on_an_empty_database(self, runner: CliRunner, tmp_path) -> None:
        url = f"sqlite+pysqlite:///{tmp_path / 'empty.sqlite3'}"
        run(runner, url, "init")
        result = run(runner, url, "corridor", "list")
        assert "no corridors stored" in result.output

    def test_show_prints_the_waypoints(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "show", "crystal-range")
        assert result.exit_code == 0
        assert "mosquito-pass" in result.output
        assert "Crystal Range Traverse" in result.output

    def test_show_can_filter_by_kind(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "show", "crystal-range", "--kind", "water")
        assert "tamarack-creek" in result.output
        assert "mosquito-pass" not in result.output

    def test_show_of_an_unknown_corridor_fails(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "show", "nowhere")
        assert result.exit_code != 0

    def test_profile_prints_grade_bands(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "profile", "crystal-range")
        assert result.exit_code == 0
        assert "grade band" in result.output

    def test_import_reads_a_datasheet(
        self, runner: CliRunner, tmp_path, corridor
    ) -> None:
        url = f"sqlite+pysqlite:///{tmp_path / 'import.sqlite3'}"
        run(runner, url, "init")
        sheet = tmp_path / "sheet.csv"
        sheet.write_text(write_datasheet(corridor_to_rows(corridor)), encoding="utf-8")
        result = run(runner, url, "corridor", "import", str(sheet), "--slug", "imported")
        assert result.exit_code == 0
        assert "stored imported: 20 waypoints" in result.output

    def test_export_writes_a_datasheet(
        self, runner: CliRunner, cli_db: str, tmp_path
    ) -> None:
        out = tmp_path / "out.csv"
        result = run(runner, cli_db, "corridor", "export", "crystal-range", "-o", str(out))
        assert result.exit_code == 0
        assert out.exists()
        assert "mosquito-pass" in out.read_text(encoding="utf-8")

    def test_delete_needs_confirmation(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "delete", "crystal-range")
        assert result.exit_code != 0

    def test_delete_with_yes_removes_it(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "corridor", "delete", "crystal-range", "--yes")
        assert result.exit_code == 0
        assert "no corridors stored" in run(runner, cli_db, "corridor", "list").output


class TestPlanCommands:
    def test_build_prints_a_schedule(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20")
        assert result.exit_code == 0
        assert "Crystal Range Traverse - " in result.output
        assert "2025-07-20" in result.output

    def test_build_can_show_the_costs(self, runner: CliRunner, cli_db: str) -> None:
        result = run(
            runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20", "--costs"
        )
        assert "effort" in result.output
        assert "per_day" in result.output

    def test_build_rejects_a_bad_date(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "plan", "build", "crystal-range", "--start", "not-a-date")
        assert result.exit_code != 0

    def test_a_tighter_pace_makes_more_days(self, runner: CliRunner, cli_db: str) -> None:
        slow = run(
            runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20",
            "--pace", "2.0",
        )
        fast = run(
            runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20",
            "--pace", "3.8",
        )
        assert len(slow.output.splitlines()) >= len(fast.output.splitlines())

    def test_save_then_list_then_show(self, runner: CliRunner, cli_db: str) -> None:
        built = run(
            runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20", "--save"
        )
        assert "saved as plan 1" in built.output
        listed = run(runner, cli_db, "plan", "list", "crystal-range")
        assert "2025-07-20" in listed.output
        shown = run(runner, cli_db, "plan", "show", "1", "--corridor", "crystal-range")
        assert "Crystal Range Traverse - " in shown.output

    def test_list_with_no_plans(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "plan", "list", "crystal-range")
        assert "no plans stored" in result.output

    def test_stats_reports_the_headline_numbers(self, runner: CliRunner, cli_db: str) -> None:
        run(runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20", "--save")
        result = run(runner, cli_db, "plan", "stats", "1", "--corridor", "crystal-range")
        assert "longest day" in result.output
        assert "biggest climb" in result.output

    def test_check_reports_permit_violations(self, runner: CliRunner, cli_db: str) -> None:
        run(runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20", "--save")
        result = run(runner, cli_db, "plan", "check", "1", "--corridor", "crystal-range")
        assert result.exit_code == 1
        assert "blocking:" in result.output
        assert "try:" in result.output

    def test_check_with_a_canister_clears_that_rule(
        self, runner: CliRunner, cli_db: str
    ) -> None:
        run(runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20", "--save")
        result = run(
            runner, cli_db, "plan", "check", "1", "--corridor", "crystal-range", "--canister"
        )
        assert "canister" not in result.output

    def test_delete_removes_the_plan(self, runner: CliRunner, cli_db: str) -> None:
        run(runner, cli_db, "plan", "build", "crystal-range", "--start", "2025-07-20", "--save")
        result = run(runner, cli_db, "plan", "delete", "1")
        assert result.exit_code == 0
        assert "no plans stored" in run(runner, cli_db, "plan", "list", "crystal-range").output


class TestTrailCommands:
    def test_water_list(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "water", "list", "crystal-range", "--month", "8")
        assert result.exit_code == 0
        assert "rubicon-spring" in result.output
        assert "confidence" in result.output

    def test_water_gaps(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "water", "gaps", "crystal-range", "--month", "6")
        assert result.exit_code == 0
        assert "litres" in result.output

    def test_water_gaps_with_a_huge_minimum_finds_nothing(
        self, runner: CliRunner, cli_db: str
    ) -> None:
        result = run(
            runner, cli_db, "water", "gaps", "crystal-range", "--min-miles", "200"
        )
        assert "no dry stretches" in result.output

    def test_permit_list(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "permit", "list", "crystal-range")
        assert "crystal-wilderness" in result.output
        assert "designated_only" in result.output

    def test_permit_at_a_mile(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "permit", "at", "crystal-range", "15.3")
        assert result.exit_code == 0
        assert "crystal-wilderness" in result.output

    def test_permit_at_an_unmanaged_mile(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "permit", "at", "crystal-range", "78")
        assert result.exit_code == 1
        assert "not inside any mapped zone" in result.output

    def test_resupply_list(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "resupply", "list", "crystal-range")
        assert "soda-springs" in result.output
        assert "full grocery" in result.output

    def test_resupply_list_full_only(self, runner: CliRunner, cli_db: str) -> None:
        result = run(runner, cli_db, "resupply", "list", "crystal-range", "--full-only")
        assert "alpine-store" not in result.output

    def test_resupply_strategy(self, runner: CliRunner, cli_db: str) -> None:
        result = run(
            runner, cli_db, "resupply", "strategy", "crystal-range", "--max-carry", "3"
        )
        assert result.exit_code == 0
        assert "longest carry" in result.output

    def test_resupply_export(self, runner: CliRunner, cli_db: str, tmp_path) -> None:
        out = tmp_path / "carries.csv"
        result = run(
            runner, cli_db, "resupply", "export", "crystal-range", "-o", str(out),
            "--max-carry", "3",
        )
        assert result.exit_code == 0
        assert out.read_text(encoding="utf-8").startswith("start_mile,end_mile")
