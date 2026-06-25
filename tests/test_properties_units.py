"""Properties the quantities and the geometry have to hold for any input.

Example based tests check the cases somebody thought of. These check the ones
nobody did, which is where the conversion bugs live.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from backpacking.geo import (
    GeoPoint,
    bounding_box,
    haversine,
    initial_bearing,
    interpolate,
    path_length,
)
from backpacking.pace.functions import (
    MAX_MODELLED_GRADE,
    munter_time,
    naismith_langmuir_time,
    tobler_speed_kmh,
)
from backpacking.units import Distance, Duration, Energy, Mass, Volume

finite = st.floats(min_value=-1e7, max_value=1e7, allow_nan=False, allow_infinity=False)
positive = st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False)
latitudes = st.floats(min_value=-89.0, max_value=89.0, allow_nan=False)
longitudes = st.floats(min_value=-179.0, max_value=179.0, allow_nan=False)
grades = st.floats(min_value=-MAX_MODELLED_GRADE, max_value=MAX_MODELLED_GRADE, allow_nan=False)


class TestDistanceProperties:
    @given(finite)
    def test_metres_round_trip_through_miles(self, value: float) -> None:
        assert Distance.miles(value).in_miles == pytest.approx(value, rel=1e-9, abs=1e-9)

    @given(finite)
    def test_feet_and_metres_agree(self, value: float) -> None:
        distance = Distance.feet(value)
        assert Distance.meters(distance.in_meters).in_feet == pytest.approx(
            value, rel=1e-9, abs=1e-9
        )

    @given(finite, finite)
    def test_addition_is_commutative(self, first: float, second: float) -> None:
        left = Distance.miles(first) + Distance.miles(second)
        right = Distance.miles(second) + Distance.miles(first)
        assert left.in_meters == pytest.approx(right.in_meters)

    @given(finite, finite)
    def test_subtraction_undoes_addition(self, first: float, second: float) -> None:
        combined = Distance.miles(first) + Distance.miles(second)
        assert (combined - Distance.miles(second)).in_miles == pytest.approx(first, abs=1e-6)

    @given(finite)
    def test_negation_is_its_own_inverse(self, value: float) -> None:
        once = -Distance.miles(value)
        assert (-once).in_miles == pytest.approx(value)

    @given(finite)
    def test_absolute_value_is_never_negative(self, value: float) -> None:
        assert abs(Distance.miles(value)).in_miles >= 0.0

    @given(finite, finite)
    def test_ordering_is_consistent_with_the_underlying_value(
        self, first: float, second: float
    ) -> None:
        assert (Distance.miles(first) < Distance.miles(second)) == (first < second)


class TestOtherQuantityProperties:
    @given(finite)
    def test_mass_round_trips_through_pounds(self, value: float) -> None:
        assert Mass.pounds(value).in_pounds == pytest.approx(value, rel=1e-9, abs=1e-9)

    @given(finite)
    def test_volume_round_trips_through_cubic_inches(self, value: float) -> None:
        assert Volume.cubic_inches(value).in_cubic_inches == pytest.approx(
            value, rel=1e-9, abs=1e-9
        )

    @given(finite)
    def test_duration_round_trips_through_hours(self, value: float) -> None:
        assert Duration.hours(value).in_hours == pytest.approx(value, rel=1e-9, abs=1e-9)

    @given(st.floats(min_value=0.0, max_value=1e5, allow_nan=False))
    def test_the_clock_never_shows_negative_minutes(self, hours: float) -> None:
        rendered = Duration.hours(hours).as_clock()
        minutes = int(rendered.split(":")[1])
        assert 0 <= minutes < 60

    @given(finite)
    def test_energy_round_trips(self, value: float) -> None:
        assert Energy.kilocalories(value).in_kilocalories == pytest.approx(value)


class TestGeoProperties:
    @given(latitudes, longitudes)
    def test_a_point_is_zero_from_itself(self, lat: float, lon: float) -> None:
        point = GeoPoint(lat, lon)
        assert haversine(point, point).in_meters == pytest.approx(0.0, abs=1e-6)

    @given(latitudes, longitudes, latitudes, longitudes)
    def test_distance_is_symmetric(
        self, lat_a: float, lon_a: float, lat_b: float, lon_b: float
    ) -> None:
        first = GeoPoint(lat_a, lon_a)
        second = GeoPoint(lat_b, lon_b)
        assert haversine(first, second).in_meters == pytest.approx(
            haversine(second, first).in_meters, rel=1e-9
        )

    @given(latitudes, longitudes, latitudes, longitudes)
    def test_distance_is_never_negative(
        self, lat_a: float, lon_a: float, lat_b: float, lon_b: float
    ) -> None:
        assert haversine(GeoPoint(lat_a, lon_a), GeoPoint(lat_b, lon_b)).in_meters >= 0.0

    @given(latitudes, longitudes, latitudes, longitudes, latitudes, longitudes)
    @settings(max_examples=60)
    def test_the_triangle_inequality_holds(
        self,
        lat_a: float,
        lon_a: float,
        lat_b: float,
        lon_b: float,
        lat_c: float,
        lon_c: float,
    ) -> None:
        a = GeoPoint(lat_a, lon_a)
        b = GeoPoint(lat_b, lon_b)
        c = GeoPoint(lat_c, lon_c)
        direct = haversine(a, c).in_meters
        via = haversine(a, b).in_meters + haversine(b, c).in_meters
        assert via >= direct - 1.0

    @given(latitudes, longitudes, latitudes, longitudes)
    def test_bearing_is_normalised(
        self, lat_a: float, lon_a: float, lat_b: float, lon_b: float
    ) -> None:
        bearing = initial_bearing(GeoPoint(lat_a, lon_a), GeoPoint(lat_b, lon_b))
        assert 0.0 <= bearing < 360.0
        assert not math.isnan(bearing)

    @given(
        latitudes,
        longitudes,
        latitudes,
        longitudes,
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    def test_an_interpolated_point_stays_on_the_globe(
        self, lat_a: float, lon_a: float, lat_b: float, lon_b: float, fraction: float
    ) -> None:
        mid = interpolate(GeoPoint(lat_a, lon_a), GeoPoint(lat_b, lon_b), fraction)
        assert -90.0 <= mid.latitude <= 90.0
        assert -180.0 <= mid.longitude <= 180.0

    @given(st.lists(st.tuples(latitudes, longitudes), min_size=1, max_size=8))
    def test_a_bounding_box_contains_every_point(
        self, coordinates: list[tuple[float, float]]
    ) -> None:
        points = [GeoPoint(lat, lon) for lat, lon in coordinates]
        box = bounding_box(points)
        assert all(box.contains(point) for point in points)

    @given(st.lists(st.tuples(latitudes, longitudes), min_size=2, max_size=8))
    def test_path_length_is_at_least_the_direct_distance(
        self, coordinates: list[tuple[float, float]]
    ) -> None:
        points = [GeoPoint(lat, lon) for lat, lon in coordinates]
        direct = haversine(points[0], points[-1]).in_meters
        assert path_length(points).in_meters >= direct - 1.0


class TestPaceProperties:
    @given(grades)
    def test_tobler_never_returns_a_non_positive_speed(self, grade: float) -> None:
        assert tobler_speed_kmh(grade) > 0.0

    @given(grades)
    def test_tobler_never_exceeds_its_peak(self, grade: float) -> None:
        assert tobler_speed_kmh(grade) <= 6.0 + 1e-9

    @given(
        st.floats(min_value=0.1, max_value=60.0, allow_nan=False),
        st.floats(min_value=0.0, max_value=20000.0, allow_nan=False),
        st.floats(min_value=0.0, max_value=20000.0, allow_nan=False),
    )
    def test_naismith_never_goes_backwards_in_time(
        self, miles: float, gain: float, loss: float
    ) -> None:
        estimate = naismith_langmuir_time(
            Distance.miles(miles), Distance.feet(gain), Distance.feet(loss)
        )
        assert estimate.in_seconds >= 0.0

    @given(
        st.floats(min_value=0.1, max_value=60.0, allow_nan=False),
        st.floats(min_value=0.0, max_value=20000.0, allow_nan=False),
    )
    def test_a_longer_leg_never_takes_less_time(self, miles: float, gain: float) -> None:
        shorter = munter_time(Distance.miles(miles), Distance.feet(gain), Distance.zero())
        longer = munter_time(Distance.miles(miles * 2.0), Distance.feet(gain), Distance.zero())
        assert longer >= shorter

    @given(
        st.floats(min_value=0.1, max_value=60.0, allow_nan=False),
        st.floats(min_value=0.0, max_value=15000.0, allow_nan=False),
        st.floats(min_value=0.0, max_value=15000.0, allow_nan=False),
    )
    def test_more_climb_never_takes_less_time(
        self, miles: float, gain: float, extra: float
    ) -> None:
        assume(extra > 0.0)
        base = munter_time(Distance.miles(miles), Distance.feet(gain), Distance.zero())
        more = munter_time(Distance.miles(miles), Distance.feet(gain + extra), Distance.zero())
        assert more >= base
