"""The two value objects every other module is written against.

A corridor is modelled as an ordered list of :class:`Waypoint` anchored by
cumulative mileage from the southern or western terminus, with a :class:`Segment`
between each consecutive pair. Mileage is the primary key rather than position,
because that is how trail datasheets, permits and resupply guides all address
the trail, and because it survives a GPX track being resampled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from backpacking.errors import CorridorError
from backpacking.geo import GeoPoint
from backpacking.units import Distance

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class WaypointKind(StrEnum):
    """What a waypoint is for. Several kinds carry planning meaning."""

    TRAILHEAD = "trailhead"
    JUNCTION = "junction"
    WATER = "water"
    CAMPSITE = "campsite"
    SHELTER = "shelter"
    ROAD = "road"
    PASS = "pass"
    SUMMIT = "summit"
    FORD = "ford"
    RESUPPLY = "resupply"
    ZONE_BOUNDARY = "zone_boundary"
    LANDMARK = "landmark"

    @property
    def can_camp(self) -> bool:
        """Whether an itinerary may end a day here without further permission."""
        return self in {WaypointKind.CAMPSITE, WaypointKind.SHELTER}

    @property
    def is_exit(self) -> bool:
        """Whether a hiker can leave the corridor here."""
        return self in {WaypointKind.TRAILHEAD, WaypointKind.ROAD, WaypointKind.RESUPPLY}


class Surface(StrEnum):
    """Tread quality, which drives the pace penalty for a segment."""

    TREAD = "tread"
    ROAD = "road"
    TALUS = "talus"
    SCREE = "scree"
    SAND = "sand"
    SNOWFIELD = "snowfield"
    BLOWDOWN = "blowdown"
    BUSHWHACK = "bushwhack"

    @property
    def pace_factor(self) -> float:
        """Multiplier applied to walking speed on this surface."""
        return _SURFACE_PACE[self]


_SURFACE_PACE: dict[Surface, float] = {
    Surface.ROAD: 1.10,
    Surface.TREAD: 1.00,
    Surface.SAND: 0.80,
    Surface.TALUS: 0.62,
    Surface.SCREE: 0.55,
    Surface.SNOWFIELD: 0.58,
    Surface.BLOWDOWN: 0.70,
    Surface.BUSHWHACK: 0.40,
}


@dataclass(frozen=True, slots=True)
class Waypoint:
    """A named point on the corridor, addressed by cumulative mile."""

    id: str
    name: str
    mile: float
    elevation: Distance
    kind: WaypointKind = WaypointKind.LANDMARK
    position: GeoPoint | None = None
    notes: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not _SLUG.match(self.id):
            raise CorridorError(
                "waypoint id must be a lowercase hyphenated slug",
                waypoint_id=self.id,
            )
        if not self.name.strip():
            raise CorridorError("waypoint name must not be blank", waypoint_id=self.id)
        if self.mile < 0.0:
            raise CorridorError(
                "waypoint mile must not be negative", waypoint_id=self.id, mile=self.mile
            )

    @property
    def can_camp(self) -> bool:
        return self.kind.can_camp

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def with_mile(self, mile: float) -> Waypoint:
        """Return a copy re-anchored to a new cumulative mile."""
        return Waypoint(
            id=self.id,
            name=self.name,
            mile=mile,
            elevation=self.elevation,
            kind=self.kind,
            position=self.position,
            notes=self.notes,
            tags=self.tags,
        )

    def __repr__(self) -> str:
        return f"Waypoint({self.id!r} @ {self.mile:.1f} mi, {self.kind.value})"


@dataclass(frozen=True, slots=True)
class Segment:
    """The stretch of trail between two consecutive waypoints."""

    start: Waypoint
    end: Waypoint
    gain: Distance
    loss: Distance
    surface: Surface = Surface.TREAD
    notes: str = ""

    def __post_init__(self) -> None:
        if self.end.mile <= self.start.mile:
            raise CorridorError(
                "segment must advance along the corridor",
                start=self.start.id,
                end=self.end.id,
                start_mile=self.start.mile,
                end_mile=self.end.mile,
            )
        if self.gain.in_feet < 0.0 or self.loss.in_feet < 0.0:
            raise CorridorError(
                "segment gain and loss are magnitudes and must not be negative",
                start=self.start.id,
                end=self.end.id,
            )

    @property
    def length(self) -> Distance:
        return Distance.miles(self.end.mile - self.start.mile)

    @property
    def net_elevation_change(self) -> Distance:
        return Distance.feet(self.end.elevation.in_feet - self.start.elevation.in_feet)

    @property
    def average_grade(self) -> float:
        """Net rise over run as a fraction, positive uphill."""
        run = self.length.in_meters
        if run == 0.0:
            return 0.0
        return self.net_elevation_change.in_meters / run

    @property
    def roughness(self) -> float:
        """Gain plus loss per mile, a blunt proxy for how broken the tread is."""
        miles = self.length.in_miles
        if miles == 0.0:
            return 0.0
        return (self.gain.in_feet + self.loss.in_feet) / miles

    def contains_mile(self, mile: float) -> bool:
        return self.start.mile <= mile <= self.end.mile

    def __repr__(self) -> str:
        return (
            f"Segment({self.start.id!r} -> {self.end.id!r}, "
            f"{self.length.in_miles:.1f} mi, +{self.gain.in_feet:.0f}/-{self.loss.in_feet:.0f} ft)"
        )
