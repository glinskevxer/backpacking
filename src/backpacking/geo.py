"""Spherical geometry for corridor work.

Trail corridors are long and thin, so the operations that matter are along track
and cross track distance rather than area or projection. Everything here works
on a sphere of mean earth radius. Over a 20 mile segment the error against an
ellipsoid is a few metres, which is far below the noise in the elevation and
mileage data these numbers are compared against.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from backpacking.units import Distance

#: IUGG mean earth radius in metres.
EARTH_RADIUS_M = 6371008.8


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A position on the earth, optionally with an elevation."""

    latitude: float
    longitude: float
    elevation: Distance | None = None

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")

    @property
    def lat_rad(self) -> float:
        return math.radians(self.latitude)

    @property
    def lon_rad(self) -> float:
        return math.radians(self.longitude)

    def with_elevation(self, elevation: Distance | None) -> GeoPoint:
        return GeoPoint(self.latitude, self.longitude, elevation)

    def __repr__(self) -> str:
        if self.elevation is None:
            return f"GeoPoint({self.latitude:.5f}, {self.longitude:.5f})"
        return (
            f"GeoPoint({self.latitude:.5f}, {self.longitude:.5f}, "
            f"{self.elevation.in_feet:.0f} ft)"
        )


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis aligned latitude and longitude window."""

    south: float
    west: float
    north: float
    east: float

    def contains(self, point: GeoPoint) -> bool:
        return (
            self.south <= point.latitude <= self.north and self.west <= point.longitude <= self.east
        )

    def expanded(self, margin_degrees: float) -> BoundingBox:
        return BoundingBox(
            south=max(-90.0, self.south - margin_degrees),
            west=max(-180.0, self.west - margin_degrees),
            north=min(90.0, self.north + margin_degrees),
            east=min(180.0, self.east + margin_degrees),
        )


def haversine(a: GeoPoint, b: GeoPoint) -> Distance:
    """Great circle distance between two points."""
    d_lat = b.lat_rad - a.lat_rad
    d_lon = b.lon_rad - a.lon_rad
    h = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(a.lat_rad) * math.cos(b.lat_rad) * math.sin(d_lon / 2.0) ** 2
    )
    return Distance.meters(2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h))))


def initial_bearing(a: GeoPoint, b: GeoPoint) -> float:
    """Forward azimuth from ``a`` to ``b`` in degrees, normalised to [0, 360)."""
    d_lon = b.lon_rad - a.lon_rad
    y = math.sin(d_lon) * math.cos(b.lat_rad)
    x = math.cos(a.lat_rad) * math.sin(b.lat_rad) - math.sin(a.lat_rad) * math.cos(
        b.lat_rad
    ) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def cross_track_distance(point: GeoPoint, start: GeoPoint, end: GeoPoint) -> Distance:
    """Signed perpendicular distance from ``point`` to the great circle start-end.

    Positive means the point lies left of the path when walking start to end.
    Used to decide whether a reported waypoint really sits on the corridor.
    """
    angular = haversine(start, point).in_meters / EARTH_RADIUS_M
    theta_path = math.radians(initial_bearing(start, end))
    theta_point = math.radians(initial_bearing(start, point))
    return Distance.meters(
        math.asin(math.sin(angular) * math.sin(theta_point - theta_path)) * EARTH_RADIUS_M
    )


def along_track_distance(point: GeoPoint, start: GeoPoint, end: GeoPoint) -> Distance:
    """How far along start-end the projection of ``point`` falls."""
    angular = haversine(start, point).in_meters / EARTH_RADIUS_M
    cross = cross_track_distance(point, start, end).in_meters / EARTH_RADIUS_M
    cos_cross = math.cos(cross)
    if cos_cross == 0.0:
        return Distance.zero()
    ratio = math.cos(angular) / cos_cross
    return Distance.meters(math.acos(max(-1.0, min(1.0, ratio))) * EARTH_RADIUS_M)


def interpolate(a: GeoPoint, b: GeoPoint, fraction: float) -> GeoPoint:
    """Point a given fraction of the way along the great circle from a to b."""
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be within [0, 1], got {fraction}")
    total = haversine(a, b).in_meters / EARTH_RADIUS_M
    if total == 0.0:
        return a
    sin_total = math.sin(total)
    coef_a = math.sin((1.0 - fraction) * total) / sin_total
    coef_b = math.sin(fraction * total) / sin_total
    x = coef_a * math.cos(a.lat_rad) * math.cos(a.lon_rad) + coef_b * math.cos(
        b.lat_rad
    ) * math.cos(b.lon_rad)
    y = coef_a * math.cos(a.lat_rad) * math.sin(a.lon_rad) + coef_b * math.cos(
        b.lat_rad
    ) * math.sin(b.lon_rad)
    z = coef_a * math.sin(a.lat_rad) + coef_b * math.sin(b.lat_rad)
    lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
    lon = math.degrees(math.atan2(y, x))
    elevation = _interpolate_elevation(a.elevation, b.elevation, fraction)
    return GeoPoint(lat, lon, elevation)


def _interpolate_elevation(
    a: Distance | None, b: Distance | None, fraction: float
) -> Distance | None:
    if a is None or b is None:
        return None
    return Distance.meters(a.in_meters + (b.in_meters - a.in_meters) * fraction)


def path_length(points: list[GeoPoint]) -> Distance:
    """Summed great circle length of a polyline."""
    total = 0.0
    for first, second in itertools.pairwise(points):
        total += haversine(first, second).in_meters
    return Distance.meters(total)


def bounding_box(points: list[GeoPoint]) -> BoundingBox:
    """Smallest latitude and longitude window covering every point."""
    if not points:
        raise ValueError("cannot build a bounding box from an empty point list")
    lats = [p.latitude for p in points]
    lons = [p.longitude for p in points]
    return BoundingBox(south=min(lats), west=min(lons), north=max(lats), east=max(lons))
