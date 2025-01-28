"""Reading and writing GPX 1.1.

Only the parts a corridor needs are handled: track points for geometry and
waypoints for named anchors. Routes, extensions and any of the vendor specific
namespaces are ignored rather than half understood.

The parser is deliberately strict about structure and lenient about content. A
missing elevation is fine, because plenty of exports drop it. A track point
without coordinates is not, because silently skipping it would shorten the
corridor and every mileage downstream would be wrong.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element

from backpacking.errors import DataSourceError
from backpacking.geo import GeoPoint, haversine
from backpacking.trail.elevation import ElevationProfile, ElevationSample
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance

GPX_NS = "http://www.topografix.com/GPX/1/1"
_NS = {"gpx": GPX_NS}

#: GPX type strings this project maps onto waypoint kinds. Anything else lands
#: on ``LANDMARK`` rather than being guessed at.
TYPE_TO_KIND: dict[str, WaypointKind] = {
    "trailhead": WaypointKind.TRAILHEAD,
    "water": WaypointKind.WATER,
    "spring": WaypointKind.WATER,
    "creek": WaypointKind.WATER,
    "camp": WaypointKind.CAMPSITE,
    "campsite": WaypointKind.CAMPSITE,
    "shelter": WaypointKind.SHELTER,
    "road": WaypointKind.ROAD,
    "pass": WaypointKind.PASS,
    "summit": WaypointKind.SUMMIT,
    "peak": WaypointKind.SUMMIT,
    "ford": WaypointKind.FORD,
    "junction": WaypointKind.JUNCTION,
    "resupply": WaypointKind.RESUPPLY,
}


@dataclass(frozen=True, slots=True)
class GpxTrack:
    """One track from a GPX file, already flattened across its segments."""

    name: str
    points: tuple[GeoPoint, ...]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise DataSourceError(
                "a gpx track needs at least two points", track=self.name, count=len(self.points)
            )

    @property
    def length(self) -> Distance:
        return Distance.meters(sum(m for m in self.leg_lengths_m()))

    def leg_lengths_m(self) -> list[float]:
        return [
            haversine(a, b).in_meters
            for a, b in zip(self.points, self.points[1:], strict=False)
        ]

    def cumulative_miles(self) -> list[float]:
        """Mile of each point, measured along the track from its first point."""
        miles = [0.0]
        running = 0.0
        for leg in self.leg_lengths_m():
            running += leg
            miles.append(Distance.meters(running).in_miles)
        return miles

    def elevation_profile(self) -> ElevationProfile:
        """Profile keyed by cumulative mile. Points without elevation are dropped."""
        samples = [
            ElevationSample(mile, point.elevation)
            for mile, point in zip(self.cumulative_miles(), self.points, strict=False)
            if point.elevation is not None
        ]
        if len(samples) < 2:
            raise DataSourceError(
                "track does not carry enough elevation data for a profile",
                track=self.name,
                with_elevation=len(samples),
            )
        return ElevationProfile(samples)


@dataclass(frozen=True, slots=True)
class GpxDocument:
    """Everything this package reads out of one GPX file."""

    tracks: tuple[GpxTrack, ...]
    waypoints: tuple[Waypoint, ...]

    def track(self, name: str) -> GpxTrack:
        for candidate in self.tracks:
            if candidate.name == name:
                return candidate
        raise DataSourceError(
            "no such track in document",
            track=name,
            available=[t.name for t in self.tracks],
        )

    @property
    def primary(self) -> GpxTrack:
        """The longest track, which is the corridor in every export seen so far."""
        if not self.tracks:
            raise DataSourceError("gpx document contains no tracks")
        return max(self.tracks, key=lambda t: t.length.in_meters)


def parse_gpx(text: str) -> GpxDocument:
    """Parse GPX 1.1 from a string."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise DataSourceError("gpx is not well formed xml", detail=str(exc)) from exc
    if not root.tag.endswith("}gpx") and root.tag != "gpx":
        raise DataSourceError("root element is not <gpx>", tag=root.tag)
    tracks = tuple(_parse_track(node) for node in root.findall("gpx:trk", _NS))
    waypoints = tuple(
        _parse_waypoint(node, index) for index, node in enumerate(root.findall("gpx:wpt", _NS))
    )
    return GpxDocument(tracks=tracks, waypoints=waypoints)


def load_gpx(path: Path) -> GpxDocument:
    """Parse GPX from a file on disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataSourceError("could not read gpx file", path=str(path)) from exc
    return parse_gpx(text)


def _parse_track(node: Element) -> GpxTrack:
    name = _child_text(node, "name") or "unnamed"
    points: list[GeoPoint] = []
    for segment in node.findall("gpx:trkseg", _NS):
        for index, point in enumerate(segment.findall("gpx:trkpt", _NS)):
            points.append(_parse_point(point, f"{name}[{index}]"))
    return GpxTrack(name=name, points=tuple(points))


def _parse_point(node: Element, where: str) -> GeoPoint:
    latitude = node.get("lat")
    longitude = node.get("lon")
    if latitude is None or longitude is None:
        raise DataSourceError("track point is missing coordinates", where=where)
    try:
        parsed_lat = float(latitude)
        parsed_lon = float(longitude)
    except ValueError as exc:
        raise DataSourceError(
            "track point coordinates are not numbers",
            where=where,
            lat=latitude,
            lon=longitude,
        ) from exc
    elevation_text = _child_text(node, "ele")
    elevation = None
    if elevation_text is not None:
        try:
            elevation = Distance.meters(float(elevation_text))
        except ValueError as exc:
            raise DataSourceError(
                "elevation is not a number", where=where, value=elevation_text
            ) from exc
    try:
        return GeoPoint(parsed_lat, parsed_lon, elevation)
    except ValueError as exc:
        raise DataSourceError("coordinates are out of range", where=where) from exc


def _parse_waypoint(node: Element, index: int) -> Waypoint:
    point = _parse_point(node, f"wpt[{index}]")
    name = _child_text(node, "name") or f"waypoint-{index}"
    type_text = (_child_text(node, "type") or "").strip().lower()
    kind = TYPE_TO_KIND.get(type_text, WaypointKind.LANDMARK)
    elevation = point.elevation or Distance.zero()
    return Waypoint(
        id=slugify(name),
        name=name,
        mile=0.0,
        elevation=elevation,
        kind=kind,
        position=point,
        notes=_child_text(node, "desc") or "",
    )


def _child_text(node: Element, tag: str) -> str | None:
    child = node.find(f"gpx:{tag}", _NS)
    if child is None or child.text is None:
        return None
    stripped = child.text.strip()
    return stripped or None


def slugify(name: str) -> str:
    """Reduce a display name to the slug form waypoint ids require."""
    out: list[str] = []
    for character in name.lower():
        if character.isalnum() and character.isascii():
            out.append(character)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")
    if not slug:
        raise DataSourceError("name does not reduce to a usable slug", name=name)
    return slug


def write_gpx(tracks: Sequence[GpxTrack], waypoints: Iterable[Waypoint] = ()) -> str:
    """Serialise tracks and waypoints back to GPX 1.1."""
    root = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "backpacking",
            "xmlns": GPX_NS,
        },
    )
    for waypoint in waypoints:
        if waypoint.position is None:
            continue
        node = ET.SubElement(
            root,
            "wpt",
            {"lat": f"{waypoint.position.latitude:.6f}", "lon": f"{waypoint.position.longitude:.6f}"},
        )
        ET.SubElement(node, "ele").text = f"{waypoint.elevation.in_meters:.1f}"
        ET.SubElement(node, "name").text = waypoint.name
        ET.SubElement(node, "type").text = waypoint.kind.value
        if waypoint.notes:
            ET.SubElement(node, "desc").text = waypoint.notes
    for track in tracks:
        track_node = ET.SubElement(root, "trk")
        ET.SubElement(track_node, "name").text = track.name
        segment_node = ET.SubElement(track_node, "trkseg")
        for point in track.points:
            attributes = {"lat": f"{point.latitude:.6f}", "lon": f"{point.longitude:.6f}"}
            point_node = ET.SubElement(segment_node, "trkpt", attributes)
            if point.elevation is not None:
                ET.SubElement(point_node, "ele").text = f"{point.elevation.in_meters:.1f}"
    return ET.tostring(root, encoding="unicode")
