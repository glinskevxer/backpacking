"""GPX parsing, round tripping and the failures a bad export produces."""

from __future__ import annotations

import pytest

from backpacking.errors import DataSourceError
from backpacking.trail.gpx import (
    GpxTrack,
    load_gpx,
    parse_gpx,
    slugify,
    write_gpx,
)
from backpacking.trail.models import WaypointKind
from backpacking.units import Distance

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="38.83990" lon="-120.04180">
    <ele>2261.0</ele>
    <name>Echo Lake Trailhead</name>
    <type>trailhead</type>
    <desc>parking fills by seven</desc>
  </wpt>
  <wpt lat="38.86500" lon="-120.11000">
    <ele>2444.0</ele>
    <name>Mosquito Pass</name>
    <type>pass</type>
  </wpt>
  <wpt lat="38.88000" lon="-120.13000">
    <ele>2500.0</ele>
    <name>Unlabelled Spot</name>
    <type>something-else</type>
  </wpt>
  <trk>
    <name>Crystal Range Traverse</name>
    <trkseg>
      <trkpt lat="38.83990" lon="-120.04180"><ele>2261.0</ele></trkpt>
      <trkpt lat="38.85000" lon="-120.07000"><ele>2340.0</ele></trkpt>
      <trkpt lat="38.86500" lon="-120.11000"><ele>2444.0</ele></trkpt>
    </trkseg>
    <trkseg>
      <trkpt lat="38.88000" lon="-120.13000"><ele>2500.0</ele></trkpt>
      <trkpt lat="38.90000" lon="-120.16000"><ele>2380.0</ele></trkpt>
    </trkseg>
  </trk>
  <trk>
    <name>Side Trip</name>
    <trkseg>
      <trkpt lat="38.83990" lon="-120.04180"><ele>2261.0</ele></trkpt>
      <trkpt lat="38.84200" lon="-120.04500"><ele>2280.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


@pytest.fixture
def document():
    return parse_gpx(SAMPLE)


class TestParsing:
    def test_both_tracks_are_found(self, document) -> None:
        assert [t.name for t in document.tracks] == ["Crystal Range Traverse", "Side Trip"]

    def test_segments_are_flattened_into_one_point_run(self, document) -> None:
        assert len(document.track("Crystal Range Traverse").points) == 5

    def test_coordinates_and_elevation_are_read(self, document) -> None:
        first = document.track("Crystal Range Traverse").points[0]
        assert first.latitude == pytest.approx(38.8399)
        assert first.longitude == pytest.approx(-120.0418)
        assert first.elevation is not None
        assert first.elevation.in_meters == pytest.approx(2261.0)

    def test_the_primary_track_is_the_longest(self, document) -> None:
        assert document.primary.name == "Crystal Range Traverse"

    def test_an_unknown_track_name_raises(self, document) -> None:
        with pytest.raises(DataSourceError, match="no such track"):
            document.track("Nonexistent")

    def test_waypoints_are_read_with_their_kinds(self, document) -> None:
        kinds = {w.id: w.kind for w in document.waypoints}
        assert kinds["echo-lake-trailhead"] is WaypointKind.TRAILHEAD
        assert kinds["mosquito-pass"] is WaypointKind.PASS

    def test_an_unmapped_type_falls_back_to_landmark(self, document) -> None:
        spot = next(w for w in document.waypoints if w.id == "unlabelled-spot")
        assert spot.kind is WaypointKind.LANDMARK

    def test_waypoint_description_is_kept(self, document) -> None:
        head = next(w for w in document.waypoints if w.id == "echo-lake-trailhead")
        assert head.notes == "parking fills by seven"
        assert head.position is not None

    def test_waypoints_come_back_unanchored(self, document) -> None:
        assert all(w.mile == 0.0 for w in document.waypoints)


class TestTrackGeometry:
    def test_cumulative_miles_start_at_zero_and_ascend(self, document) -> None:
        miles = document.primary.cumulative_miles()
        assert miles[0] == pytest.approx(0.0)
        assert miles == sorted(miles)
        assert len(miles) == len(document.primary.points)

    def test_track_length_matches_the_last_cumulative_mile(self, document) -> None:
        track = document.primary
        assert track.length.in_miles == pytest.approx(track.cumulative_miles()[-1])

    def test_the_sample_track_is_about_seven_miles(self, document) -> None:
        assert document.primary.length.in_miles == pytest.approx(7.4, abs=0.4)

    def test_elevation_profile_is_keyed_by_mile(self, document) -> None:
        profile = document.primary.elevation_profile()
        assert len(profile) == 5
        assert profile.start_mile == pytest.approx(0.0)
        assert profile.elevation_at(0.0).in_meters == pytest.approx(2261.0)

    def test_a_track_needs_two_points(self) -> None:
        one_point = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>Stub</name><trkseg>
            <trkpt lat="1.0" lon="2.0"><ele>10.0</ele></trkpt>
          </trkseg></trk></gpx>"""
        with pytest.raises(DataSourceError, match="at least two points"):
            parse_gpx(one_point)

    def test_a_track_without_elevation_cannot_make_a_profile(self) -> None:
        bare = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>Bare</name><trkseg>
            <trkpt lat="1.0" lon="2.0"/><trkpt lat="1.1" lon="2.1"/>
          </trkseg></trk></gpx>"""
        track = parse_gpx(bare).primary
        with pytest.raises(DataSourceError, match="enough elevation data"):
            track.elevation_profile()


class TestParseFailures:
    def test_malformed_xml(self) -> None:
        with pytest.raises(DataSourceError, match="not well formed"):
            parse_gpx("<gpx><trk>")

    def test_wrong_root_element(self) -> None:
        with pytest.raises(DataSourceError, match="not <gpx>"):
            parse_gpx("<kml></kml>")

    def test_a_point_without_coordinates(self) -> None:
        broken = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>Broken</name><trkseg>
            <trkpt lat="1.0"/><trkpt lat="1.1" lon="2.1"/>
          </trkseg></trk></gpx>"""
        with pytest.raises(DataSourceError, match="missing coordinates"):
            parse_gpx(broken)

    def test_a_point_with_non_numeric_coordinates(self) -> None:
        broken = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>Broken</name><trkseg>
            <trkpt lat="north" lon="2.1"/><trkpt lat="1.1" lon="2.1"/>
          </trkseg></trk></gpx>"""
        with pytest.raises(DataSourceError, match="not numbers"):
            parse_gpx(broken)

    def test_a_point_with_a_bad_elevation(self) -> None:
        broken = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>Broken</name><trkseg>
            <trkpt lat="1.0" lon="2.0"><ele>high</ele></trkpt>
            <trkpt lat="1.1" lon="2.1"/>
          </trkseg></trk></gpx>"""
        with pytest.raises(DataSourceError, match="elevation is not a number"):
            parse_gpx(broken)

    def test_coordinates_outside_the_globe(self) -> None:
        broken = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>Broken</name><trkseg>
            <trkpt lat="200.0" lon="2.0"/><trkpt lat="1.1" lon="2.1"/>
          </trkseg></trk></gpx>"""
        with pytest.raises(DataSourceError, match="out of range"):
            parse_gpx(broken)

    def test_a_document_with_no_tracks_has_no_primary(self) -> None:
        empty = '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>'
        document = parse_gpx(empty)
        with pytest.raises(DataSourceError, match="contains no tracks"):
            _ = document.primary

    def test_missing_file(self, tmp_path) -> None:
        with pytest.raises(DataSourceError, match="could not read"):
            load_gpx(tmp_path / "absent.gpx")


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Echo Lake Trailhead", "echo-lake-trailhead"),
            ("Mosquito Pass", "mosquito-pass"),
            ("  Squaw Creek Ford  ", "squaw-creek-ford"),
            ("Highway 50 / Echo Summit", "highway-50-echo-summit"),
            ("Lake Aloha (inlet)", "lake-aloha-inlet"),
            ("Camp #3", "camp-3"),
        ],
    )
    def test_names_reduce_to_slugs(self, name: str, expected: str) -> None:
        assert slugify(name) == expected

    def test_a_name_with_nothing_usable_is_refused(self) -> None:
        with pytest.raises(DataSourceError, match="usable slug"):
            slugify("///")


class TestRoundTrip:
    def test_writing_and_reparsing_preserves_the_track(self, document) -> None:
        text = write_gpx(document.tracks, document.waypoints)
        again = parse_gpx(text)
        assert [t.name for t in again.tracks] == [t.name for t in document.tracks]
        assert again.primary.length.in_miles == pytest.approx(
            document.primary.length.in_miles, abs=0.01
        )

    def test_writing_preserves_waypoint_kinds(self, document) -> None:
        again = parse_gpx(write_gpx(document.tracks, document.waypoints))
        assert {w.id: w.kind for w in again.waypoints} == {w.id: w.kind for w in document.waypoints}

    def test_a_waypoint_without_a_position_is_skipped(self, document) -> None:
        stripped = list(document.waypoints)
        text = write_gpx(document.tracks, [stripped[0].with_mile(4.0)])
        assert "Echo Lake Trailhead" in text

    def test_written_gpx_declares_the_namespace(self, document) -> None:
        text = write_gpx(document.tracks)
        assert 'xmlns="http://www.topografix.com/GPX/1/1"' in text
        assert 'version="1.1"' in text

    def test_a_track_can_be_built_by_hand_and_written(self) -> None:
        from backpacking.geo import GeoPoint

        track = GpxTrack(
            name="Hand Built",
            points=(
                GeoPoint(38.0, -120.0, Distance.meters(2000)),
                GeoPoint(38.1, -120.1, Distance.meters(2100)),
            ),
        )
        again = parse_gpx(write_gpx([track]))
        assert again.primary.name == "Hand Built"
        assert len(again.primary.points) == 2

    def test_round_trip_through_a_file(self, tmp_path, document) -> None:
        path = tmp_path / "corridor.gpx"
        path.write_text(write_gpx(document.tracks, document.waypoints), encoding="utf-8")
        loaded = load_gpx(path)
        assert loaded.primary.name == "Crystal Range Traverse"
