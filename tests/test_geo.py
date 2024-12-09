"""Spherical geometry checks against distances that can be looked up."""

from __future__ import annotations

import math

import pytest

from backpacking.geo import (
    BoundingBox,
    GeoPoint,
    along_track_distance,
    bounding_box,
    cross_track_distance,
    haversine,
    initial_bearing,
    interpolate,
    path_length,
)
from backpacking.units import Distance

# Three real anchors on the Pacific Crest Trail, used because their separation
# is published and easy to sanity check.
CAMPO = GeoPoint(32.58940, -116.46680, Distance.feet(2915))
KENNEDY_MEADOWS = GeoPoint(36.03390, -118.13340, Distance.feet(6120))
MANNING_PARK = GeoPoint(49.06390, -120.78330, Distance.feet(3800))


class TestHaversine:
    def test_a_point_is_zero_from_itself(self) -> None:
        assert haversine(CAMPO, CAMPO).in_meters == pytest.approx(0.0)

    def test_is_symmetric(self) -> None:
        there = haversine(CAMPO, KENNEDY_MEADOWS).in_meters
        back = haversine(KENNEDY_MEADOWS, CAMPO).in_meters
        assert there == pytest.approx(back)

    def test_southern_terminus_to_kennedy_meadows(self) -> None:
        straight_line = haversine(CAMPO, KENNEDY_MEADOWS)
        assert straight_line.in_miles == pytest.approx(255.0, abs=3.0)

    def test_a_degree_of_latitude_is_about_sixty_nautical_miles(self) -> None:
        a = GeoPoint(40.0, -120.0)
        b = GeoPoint(41.0, -120.0)
        assert haversine(a, b).in_kilometers == pytest.approx(111.19, abs=0.05)

    def test_longitude_shrinks_towards_the_pole(self) -> None:
        equator = haversine(GeoPoint(0.0, 0.0), GeoPoint(0.0, 1.0))
        high = haversine(GeoPoint(60.0, 0.0), GeoPoint(60.0, 1.0))
        assert high.in_meters == pytest.approx(equator.in_meters * 0.5, rel=0.001)


class TestBearing:
    def test_due_north(self) -> None:
        assert initial_bearing(GeoPoint(10.0, 20.0), GeoPoint(11.0, 20.0)) == pytest.approx(0.0)

    def test_due_east_on_the_equator(self) -> None:
        assert initial_bearing(GeoPoint(0.0, 20.0), GeoPoint(0.0, 21.0)) == pytest.approx(90.0)

    def test_due_south(self) -> None:
        assert initial_bearing(GeoPoint(10.0, 20.0), GeoPoint(9.0, 20.0)) == pytest.approx(180.0)

    def test_result_is_normalised_into_zero_to_three_sixty(self) -> None:
        bearing = initial_bearing(GeoPoint(0.0, 20.0), GeoPoint(0.0, 19.0))
        assert 0.0 <= bearing < 360.0
        assert bearing == pytest.approx(270.0)

    def test_the_trail_runs_broadly_north(self) -> None:
        assert initial_bearing(CAMPO, MANNING_PARK) == pytest.approx(350.2, abs=1.0)


class TestCrossTrack:
    def test_a_point_on_the_path_has_no_offset(self) -> None:
        mid = interpolate(CAMPO, KENNEDY_MEADOWS, 0.5)
        offset = cross_track_distance(mid, CAMPO, KENNEDY_MEADOWS)
        assert abs(offset.in_meters) < 1.0

    def test_sign_flips_either_side_of_the_path(self) -> None:
        start = GeoPoint(0.0, 0.0)
        end = GeoPoint(0.0, 1.0)
        north = cross_track_distance(GeoPoint(0.01, 0.5), start, end)
        south = cross_track_distance(GeoPoint(-0.01, 0.5), start, end)
        assert north.in_meters * south.in_meters < 0.0
        assert abs(north.in_meters) == pytest.approx(abs(south.in_meters), rel=1e-3)

    def test_offset_magnitude_matches_the_perpendicular_gap(self) -> None:
        start = GeoPoint(0.0, 0.0)
        end = GeoPoint(0.0, 1.0)
        offset = cross_track_distance(GeoPoint(0.02, 0.5), start, end)
        assert abs(offset.in_meters) == pytest.approx(2223.9, rel=1e-3)


class TestAlongTrack:
    def test_start_projects_to_zero(self) -> None:
        along = along_track_distance(CAMPO, CAMPO, KENNEDY_MEADOWS)
        assert along.in_meters == pytest.approx(0.0, abs=1.0)

    def test_midpoint_projects_to_half_the_leg(self) -> None:
        mid = interpolate(CAMPO, KENNEDY_MEADOWS, 0.5)
        along = along_track_distance(mid, CAMPO, KENNEDY_MEADOWS)
        whole = haversine(CAMPO, KENNEDY_MEADOWS)
        assert along.in_meters == pytest.approx(whole.in_meters / 2.0, rel=1e-4)

    def test_an_offset_point_still_projects_onto_the_leg(self) -> None:
        start = GeoPoint(0.0, 0.0)
        end = GeoPoint(0.0, 1.0)
        along = along_track_distance(GeoPoint(0.01, 0.25), start, end)
        whole = haversine(start, end)
        assert along.in_meters == pytest.approx(whole.in_meters * 0.25, rel=1e-3)


class TestInterpolate:
    def test_fraction_zero_and_one_return_the_ends(self) -> None:
        assert interpolate(CAMPO, KENNEDY_MEADOWS, 0.0).latitude == pytest.approx(CAMPO.latitude)
        end = interpolate(CAMPO, KENNEDY_MEADOWS, 1.0)
        assert end.latitude == pytest.approx(KENNEDY_MEADOWS.latitude)
        assert end.longitude == pytest.approx(KENNEDY_MEADOWS.longitude)

    def test_elevation_is_carried_across_linearly(self) -> None:
        mid = interpolate(CAMPO, KENNEDY_MEADOWS, 0.5)
        assert mid.elevation is not None
        assert mid.elevation.in_feet == pytest.approx((2915 + 6120) / 2.0, abs=1.0)

    def test_elevation_is_dropped_when_either_end_lacks_one(self) -> None:
        plain = GeoPoint(36.0, -118.0)
        assert interpolate(CAMPO, plain, 0.5).elevation is None

    def test_a_degenerate_leg_returns_the_start(self) -> None:
        assert interpolate(CAMPO, CAMPO, 0.4) == CAMPO

    def test_fraction_outside_the_unit_interval_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"within \[0, 1\]"):
            interpolate(CAMPO, KENNEDY_MEADOWS, 1.5)


class TestPolylineHelpers:
    def test_path_length_sums_the_legs(self) -> None:
        points = [CAMPO, KENNEDY_MEADOWS, MANNING_PARK]
        expected = haversine(CAMPO, KENNEDY_MEADOWS) + haversine(KENNEDY_MEADOWS, MANNING_PARK)
        assert path_length(points).in_meters == pytest.approx(expected.in_meters)

    def test_path_length_of_a_single_point_is_zero(self) -> None:
        assert path_length([CAMPO]).in_meters == pytest.approx(0.0)

    def test_bounding_box_covers_every_point(self) -> None:
        box = bounding_box([CAMPO, KENNEDY_MEADOWS, MANNING_PARK])
        assert box.south == pytest.approx(CAMPO.latitude)
        assert box.north == pytest.approx(MANNING_PARK.latitude)
        for point in (CAMPO, KENNEDY_MEADOWS, MANNING_PARK):
            assert box.contains(point)

    def test_bounding_box_needs_points(self) -> None:
        with pytest.raises(ValueError, match="empty point list"):
            bounding_box([])

    def test_expanding_a_box_keeps_it_valid_at_the_poles(self) -> None:
        box = BoundingBox(south=-89.5, west=-179.5, north=89.5, east=179.5).expanded(2.0)
        assert box.south == pytest.approx(-90.0)
        assert box.north == pytest.approx(90.0)
        assert box.west == pytest.approx(-180.0)
        assert box.east == pytest.approx(180.0)


class TestGeoPointValidation:
    @pytest.mark.parametrize("latitude", [90.1, -90.1, 1000.0])
    def test_latitude_is_bounded(self, latitude: float) -> None:
        with pytest.raises(ValueError, match="latitude out of range"):
            GeoPoint(latitude, 0.0)

    @pytest.mark.parametrize("longitude", [180.1, -180.1])
    def test_longitude_is_bounded(self, longitude: float) -> None:
        with pytest.raises(ValueError, match="longitude out of range"):
            GeoPoint(0.0, longitude)

    def test_repr_includes_elevation_when_present(self) -> None:
        assert "2915 ft" in repr(CAMPO)
        assert repr(GeoPoint(1.0, 2.0)) == "GeoPoint(1.00000, 2.00000)"

    def test_radians_properties(self) -> None:
        point = GeoPoint(45.0, -90.0)
        assert point.lat_rad == pytest.approx(math.pi / 4)
        assert point.lon_rad == pytest.approx(-math.pi / 2)
