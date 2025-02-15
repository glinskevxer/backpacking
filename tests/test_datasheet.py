"""Datasheet parsing, corridor construction and the export round trip."""

from __future__ import annotations

import pytest

from backpacking.errors import DataSourceError
from backpacking.trail.corridor import Corridor
from backpacking.trail.datasheet import (
    DatasheetRow,
    corridor_from_rows,
    corridor_to_rows,
    load_corridor,
    load_datasheet,
    parse_datasheet,
    write_datasheet,
)
from backpacking.trail.models import Surface, WaypointKind

SHEET = """mile,id,name,elevation_ft,kind,tags,gain_ft,loss_ft,surface,notes
0,echo-trailhead,Echo Lake Trailhead,7420,trailhead,,340,80,tread,quota board here
2.4,tamarack-creek,Tamarack Creek,7680,water,reliable,410,80,tread,
5.1,haypress-camp,Haypress Camp,8010,campsite,designated|bearbox,620,180,talus,
8.7,lake-aloha-inlet,Lake Aloha Inlet,8180,water,reliable,,,,
11.9,mosquito-pass,Mosquito Pass,8620,pass,,,,,exposed above treeline
"""

SHEET_WITH_EXTRA = """mile,id,name,elevation_ft,kind,cell_signal
0,start,Start,5000,trailhead,none
4,middle,Middle,6200,campsite,verizon
9,finish,Finish,5400,trailhead,att
"""


class TestParsing:
    def test_every_row_is_read(self) -> None:
        assert len(parse_datasheet(SHEET)) == 5

    def test_scalar_columns_are_typed(self) -> None:
        first = parse_datasheet(SHEET)[0]
        assert first.mile == pytest.approx(0.0)
        assert first.elevation_ft == pytest.approx(7420)
        assert first.kind is WaypointKind.TRAILHEAD
        assert first.surface is Surface.TREAD
        assert first.notes == "quota board here"

    def test_tags_split_on_the_pipe(self) -> None:
        camp = parse_datasheet(SHEET)[2]
        assert camp.tags == frozenset({"designated", "bearbox"})

    def test_a_row_without_tags_gets_an_empty_set(self) -> None:
        assert parse_datasheet(SHEET)[0].tags == frozenset()

    def test_blank_gain_and_loss_stay_none(self) -> None:
        row = parse_datasheet(SHEET)[3]
        assert row.gain_ft is None
        assert row.loss_ft is None

    def test_measured_gain_is_kept(self) -> None:
        row = parse_datasheet(SHEET)[2]
        assert row.gain_ft == pytest.approx(620)
        assert row.surface is Surface.TALUS

    def test_a_row_defaults_its_name_to_the_id(self) -> None:
        rows = parse_datasheet("mile,id,name,elevation_ft\n1,lone-pine,,6000\n")
        assert rows[0].name == "lone-pine"

    def test_unknown_columns_are_preserved(self) -> None:
        rows = parse_datasheet(SHEET_WITH_EXTRA)
        assert rows[1].extra == {"cell_signal": "verizon"}

    def test_an_empty_extra_column_is_dropped(self) -> None:
        rows = parse_datasheet("mile,id,name,elevation_ft,scratch\n1,a,A,100,\n2,b,B,200,x\n")
        assert rows[0].extra == {}
        assert rows[1].extra == {"scratch": "x"}

    def test_to_waypoint_carries_the_fields_across(self) -> None:
        waypoint = parse_datasheet(SHEET)[2].to_waypoint()
        assert waypoint.id == "haypress-camp"
        assert waypoint.elevation.in_feet == pytest.approx(8010)
        assert waypoint.can_camp
        assert waypoint.has_tag("bearbox")


class TestParseFailures:
    def test_missing_required_columns(self) -> None:
        with pytest.raises(DataSourceError, match="missing required columns"):
            parse_datasheet("mile,id\n1,a\n")

    def test_no_header_at_all(self) -> None:
        with pytest.raises(DataSourceError, match="no header row"):
            parse_datasheet("")

    def test_no_rows_under_a_valid_header(self) -> None:
        with pytest.raises(DataSourceError, match="contains no rows"):
            parse_datasheet("mile,id,name,elevation_ft\n")

    def test_a_blank_required_cell(self) -> None:
        with pytest.raises(DataSourceError, match="required column is empty"):
            parse_datasheet("mile,id,name,elevation_ft\n,a,A,100\n")

    def test_a_non_numeric_mile(self) -> None:
        with pytest.raises(DataSourceError, match="not a number"):
            parse_datasheet("mile,id,name,elevation_ft\nfar,a,A,100\n")

    def test_a_non_numeric_optional_column(self) -> None:
        with pytest.raises(DataSourceError, match="not a number"):
            parse_datasheet("mile,id,name,elevation_ft,gain_ft\n1,a,A,100,steep\n")

    def test_a_row_with_no_id(self) -> None:
        with pytest.raises(DataSourceError, match="no id"):
            parse_datasheet("mile,id,name,elevation_ft\n1,,A,100\n")

    def test_an_unknown_kind(self) -> None:
        with pytest.raises(DataSourceError, match="unknown waypoint kind"):
            parse_datasheet("mile,id,name,elevation_ft,kind\n1,a,A,100,helipad\n")

    def test_an_unknown_surface(self) -> None:
        with pytest.raises(DataSourceError, match="unknown surface"):
            parse_datasheet("mile,id,name,elevation_ft,surface\n1,a,A,100,lava\n")

    def test_a_missing_file(self, tmp_path) -> None:
        with pytest.raises(DataSourceError, match="could not read"):
            load_datasheet(tmp_path / "absent.csv")


class TestCorridorConstruction:
    @pytest.fixture
    def built(self) -> Corridor:
        return corridor_from_rows("Crystal Range", parse_datasheet(SHEET))

    def test_the_corridor_spans_the_rows(self, built: Corridor) -> None:
        assert built.start_mile == pytest.approx(0.0)
        assert built.end_mile == pytest.approx(11.9)
        assert len(built) == 5

    def test_measured_gain_is_used_where_supplied(self, built: Corridor) -> None:
        assert built.segments[0].gain.in_feet == pytest.approx(340)
        assert built.segments[0].loss.in_feet == pytest.approx(80)

    def test_missing_gain_falls_back_to_the_elevation_difference(self, built: Corridor) -> None:
        leg = built.segments[3]
        assert leg.start.id == "lake-aloha-inlet"
        assert leg.gain.in_feet == pytest.approx(440)
        assert leg.loss.in_feet == pytest.approx(0)

    def test_surface_reaches_the_segment(self, built: Corridor) -> None:
        assert built.segments[2].surface is Surface.TALUS

    def test_rows_are_sorted_before_construction(self) -> None:
        shuffled = "mile,id,name,elevation_ft\n9,c,C,300\n0,a,A,100\n4,b,B,200\n"
        built = corridor_from_rows("Shuffled", parse_datasheet(shuffled))
        assert [w.id for w in built] == ["a", "b", "c"]

    def test_notes_reach_the_segment(self, built: Corridor) -> None:
        assert built.segments[0].notes == "quota board here"

    def test_loading_from_a_file_names_the_corridor_after_it(self, tmp_path) -> None:
        path = tmp_path / "crystal-range.csv"
        path.write_text(SHEET, encoding="utf-8")
        built = load_corridor(path)
        assert built.name == "Crystal Range"

    def test_an_explicit_name_wins(self, tmp_path) -> None:
        path = tmp_path / "crystal-range.csv"
        path.write_text(SHEET, encoding="utf-8")
        assert load_corridor(path, name="North Half").name == "North Half"


class TestWriting:
    def test_round_trip_preserves_every_field(self) -> None:
        rows = parse_datasheet(SHEET)
        again = parse_datasheet(write_datasheet(rows))
        assert again == rows

    def test_round_trip_preserves_unknown_columns(self) -> None:
        rows = parse_datasheet(SHEET_WITH_EXTRA)
        text = write_datasheet(rows)
        assert "cell_signal" in text.splitlines()[0]
        assert parse_datasheet(text)[1].extra == {"cell_signal": "verizon"}

    def test_tags_are_written_sorted(self) -> None:
        rows = parse_datasheet(SHEET)
        text = write_datasheet(rows)
        assert "bearbox|designated" in text

    def test_writing_nothing_is_refused(self) -> None:
        with pytest.raises(DataSourceError, match="no rows"):
            write_datasheet([])

    def test_corridor_exports_back_to_rows(self, corridor: Corridor) -> None:
        rows = corridor_to_rows(corridor)
        assert len(rows) == len(corridor)
        assert rows[0].id == "echo-trailhead"
        assert rows[0].gain_ft == pytest.approx(340)

    def test_the_last_exported_row_has_no_leg(self, corridor: Corridor) -> None:
        assert corridor_to_rows(corridor)[-1].gain_ft is None

    def test_a_corridor_survives_an_export_and_reimport(self, corridor: Corridor) -> None:
        text = write_datasheet(corridor_to_rows(corridor))
        rebuilt = corridor_from_rows(corridor.name, parse_datasheet(text))
        assert rebuilt.total_gain().in_feet == pytest.approx(corridor.total_gain().in_feet)
        assert [w.id for w in rebuilt] == [w.id for w in corridor]
        assert rebuilt.length.in_miles == pytest.approx(corridor.length.in_miles)

    def test_a_row_built_by_hand_writes_cleanly(self) -> None:
        row = DatasheetRow(mile=1.5, id="spur", name="Spur", elevation_ft=6100.0)
        assert "1.5,spur,Spur,6100" in write_datasheet([row])
