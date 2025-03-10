"""The corridor: an ordered, validated run of waypoints and the gaps between them.

A corridor is immutable. Every operation that would change it returns a new one,
which keeps a cached mile index honest and makes it safe to hand the same object
to the solver, the permit checker and the resupply planner at once.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from backpacking.errors import CorridorError, WaypointNotFound
from backpacking.trail.index import MileIndex
from backpacking.trail.models import Segment, Surface, Waypoint, WaypointKind
from backpacking.units import Distance


@dataclass(frozen=True, slots=True)
class Corridor:
    """An ordered set of waypoints with a segment between each consecutive pair."""

    name: str
    waypoints: tuple[Waypoint, ...]
    segments: tuple[Segment, ...]
    _index: MileIndex | None = field(default=None, repr=False, compare=False)
    _by_id: dict[str, Waypoint] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.waypoints) < 2:
            raise CorridorError(
                "a corridor needs at least two waypoints", name=self.name, count=len(self.waypoints)
            )
        if len(self.segments) != len(self.waypoints) - 1:
            raise CorridorError(
                "segment count must be one less than waypoint count",
                name=self.name,
                waypoints=len(self.waypoints),
                segments=len(self.segments),
            )
        seen: set[str] = set()
        previous = -1.0
        for waypoint in self.waypoints:
            if waypoint.id in seen:
                raise CorridorError(
                    "duplicate waypoint id in corridor", name=self.name, waypoint_id=waypoint.id
                )
            seen.add(waypoint.id)
            if waypoint.mile <= previous:
                raise CorridorError(
                    "waypoints must be strictly increasing in mile",
                    name=self.name,
                    waypoint_id=waypoint.id,
                    mile=waypoint.mile,
                    previous_mile=previous,
                )
            previous = waypoint.mile
        object.__setattr__(self, "_index", MileIndex([w.mile for w in self.waypoints]))
        object.__setattr__(self, "_by_id", {w.id: w for w in self.waypoints})

    @property
    def index(self) -> MileIndex:
        """The mile index behind every lookup on this corridor."""
        assert self._index is not None  # set in __post_init__
        return self._index

    # -- construction ----------------------------------------------------

    @classmethod
    def from_waypoints(
        cls,
        name: str,
        waypoints: Sequence[Waypoint],
        *,
        surfaces: dict[str, Surface] | None = None,
    ) -> Corridor:
        """Build a corridor deriving each segment's gain and loss from elevations.

        This is the honest reading when only spot elevations are known: the
        segment climbs the difference or descends it, never both. A corridor
        built from a GPX track gets real gain and loss instead, through
        :meth:`with_segments`.
        """
        ordered = tuple(sorted(waypoints, key=lambda w: w.mile))
        surfaces = surfaces or {}
        segments: list[Segment] = []
        for start, end in zip(ordered, ordered[1:], strict=False):
            delta_ft = end.elevation.in_feet - start.elevation.in_feet
            segments.append(
                Segment(
                    start=start,
                    end=end,
                    gain=Distance.feet(max(0.0, delta_ft)),
                    loss=Distance.feet(max(0.0, -delta_ft)),
                    surface=surfaces.get(start.id, Surface.TREAD),
                )
            )
        return cls(name=name, waypoints=ordered, segments=tuple(segments))

    def with_segments(self, segments: Sequence[Segment]) -> Corridor:
        """Return a copy carrying measured segment gain and loss."""
        return Corridor(name=self.name, waypoints=self.waypoints, segments=tuple(segments))

    # -- basic reads -----------------------------------------------------

    @property
    def start_mile(self) -> float:
        return self.waypoints[0].mile

    @property
    def end_mile(self) -> float:
        return self.waypoints[-1].mile

    @property
    def length(self) -> Distance:
        return Distance.miles(self.end_mile - self.start_mile)

    def __len__(self) -> int:
        return len(self.waypoints)

    def __iter__(self) -> Iterator[Waypoint]:
        return iter(self.waypoints)

    def waypoint(self, waypoint_id: str) -> Waypoint:
        try:
            return self._by_id[waypoint_id]
        except KeyError:
            raise WaypointNotFound(
                "no such waypoint on this corridor",
                corridor=self.name,
                waypoint_id=waypoint_id,
            ) from None

    def has_waypoint(self, waypoint_id: str) -> bool:
        return waypoint_id in self._by_id

    def of_kind(self, *kinds: WaypointKind) -> tuple[Waypoint, ...]:
        wanted = set(kinds)
        return tuple(w for w in self.waypoints if w.kind in wanted)

    def tagged(self, tag: str) -> tuple[Waypoint, ...]:
        return tuple(w for w in self.waypoints if w.has_tag(tag))

    # -- mile addressed lookups -----------------------------------------

    def _check_mile(self, mile: float) -> None:
        if not self.index.contains(mile):
            raise CorridorError(
                "mile falls outside the corridor",
                corridor=self.name,
                mile=mile,
                start_mile=self.start_mile,
                end_mile=self.end_mile,
            )

    def segment_at(self, mile: float) -> Segment:
        """The segment containing ``mile``. The boundary belongs to the later one."""
        self._check_mile(mile)
        return self.segments[self.index.interval_for(mile)]

    def nearest_waypoint(self, mile: float) -> Waypoint:
        self._check_mile(mile)
        return self.waypoints[self.index.nearest(mile)]

    def next_waypoint(self, mile: float, *, kind: WaypointKind | None = None) -> Waypoint | None:
        """First waypoint strictly ahead of ``mile``, optionally filtered by kind."""
        position = self.index.first_after(mile)
        if position is None:
            return None
        for waypoint in self.waypoints[position:]:
            if kind is None or waypoint.kind is kind:
                return waypoint
        return None

    def waypoints_between(self, start_mile: float, end_mile: float) -> tuple[Waypoint, ...]:
        if end_mile < start_mile:
            raise CorridorError(
                "end mile precedes start mile", start_mile=start_mile, end_mile=end_mile
            )
        left, right = self.index.span(start_mile, end_mile)
        return self.waypoints[left:right]

    def elevation_at(self, mile: float) -> Distance:
        """Elevation interpolated linearly between the bracketing waypoints."""
        self._check_mile(mile)
        bracket = self.index.bracket(mile)
        if bracket.exact:
            return self.waypoints[bracket.before].elevation
        before = self.waypoints[bracket.before]
        after = self.waypoints[bracket.after]
        _, fraction = self.index.fraction_within(mile)
        rise = after.elevation.in_feet - before.elevation.in_feet
        return Distance.feet(before.elevation.in_feet + rise * fraction)

    # -- derived aggregates ---------------------------------------------

    def segments_between(self, start_mile: float, end_mile: float) -> tuple[Segment, ...]:
        return tuple(
            s for s in self.segments if s.end.mile > start_mile and s.start.mile < end_mile
        )

    def gain_between(self, start_mile: float, end_mile: float) -> Distance:
        """Climb over a stretch, prorating the segments the ends fall inside."""
        return Distance.feet(self._prorated(start_mile, end_mile, uphill=True))

    def loss_between(self, start_mile: float, end_mile: float) -> Distance:
        return Distance.feet(self._prorated(start_mile, end_mile, uphill=False))

    def _prorated(self, start_mile: float, end_mile: float, *, uphill: bool) -> float:
        total = 0.0
        for segment in self.segments_between(start_mile, end_mile):
            overlap = min(end_mile, segment.end.mile) - max(start_mile, segment.start.mile)
            if overlap <= 0.0:
                continue
            share = overlap / segment.length.in_miles
            total += (segment.gain if uphill else segment.loss).in_feet * share
        return total

    def total_gain(self) -> Distance:
        return Distance.feet(sum(s.gain.in_feet for s in self.segments))

    def total_loss(self) -> Distance:
        return Distance.feet(sum(s.loss.in_feet for s in self.segments))

    def slice(self, start_mile: float, end_mile: float) -> Corridor:
        """A corridor covering only the given stretch, ends included if anchored."""
        kept = self.waypoints_between(start_mile, end_mile)
        if len(kept) < 2:
            raise CorridorError(
                "slice does not contain two anchored waypoints",
                corridor=self.name,
                start_mile=start_mile,
                end_mile=end_mile,
            )
        kept_ids = {w.id for w in kept}
        segments = tuple(
            s for s in self.segments if s.start.id in kept_ids and s.end.id in kept_ids
        )
        return Corridor(name=self.name, waypoints=kept, segments=segments)

    def renamed(self, name: str) -> Corridor:
        return Corridor(name=name, waypoints=self.waypoints, segments=self.segments)

    def __repr__(self) -> str:
        return (
            f"Corridor({self.name!r}, {len(self.waypoints)} waypoints, "
            f"{self.length.in_miles:.1f} mi)"
        )


def merge_corridors(name: str, parts: Iterable[Corridor]) -> Corridor:
    """Join corridors end to end, re-anchoring each one after the last."""
    ordered = list(parts)
    if not ordered:
        raise CorridorError("cannot merge an empty sequence of corridors", name=name)
    waypoints: list[Waypoint] = []
    segments: list[Segment] = []
    offset = 0.0
    for index, part in enumerate(ordered):
        shift = offset - part.start_mile
        moved = [w.with_mile(w.mile + shift) for w in part.waypoints]
        if index > 0:
            if moved[0].id == waypoints[-1].id:
                moved = moved[1:]
            else:
                raise CorridorError(
                    "corridors must meet at a shared waypoint to merge",
                    left=waypoints[-1].id,
                    right=moved[0].id,
                )
        waypoints.extend(moved)
        offset = waypoints[-1].mile
    for start, end in zip(waypoints, waypoints[1:], strict=False):
        delta = end.elevation.in_feet - start.elevation.in_feet
        segments.append(
            Segment(
                start=start,
                end=end,
                gain=Distance.feet(max(0.0, delta)),
                loss=Distance.feet(max(0.0, -delta)),
            )
        )
    return Corridor(name=name, waypoints=tuple(waypoints), segments=tuple(segments))
