"""Alternates, and splicing a chosen set of them into a single linear route.

Every long trail has them: an official high route over a pass, a low route for
when the pass is still under snow, a fire closure detour, a road walk that skips
a burn. They all share one shape. An alternate leaves the main corridor at one
waypoint, runs its own sequence of waypoints, and rejoins at another waypoint
further along.

Splicing has to re-index everything after the rejoin, because an alternate is
almost never the same length as the stretch it replaces. Getting that wrong is
the single most damaging bug in this package: mileage is the primary key, so a
one mile error moves every permit boundary, water source and resupply for the
rest of the trail.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from backpacking.errors import RouteResolutionError
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Segment, Waypoint
from backpacking.units import Distance


@dataclass(frozen=True, slots=True)
class Alternate:
    """A branch that leaves the corridor at one waypoint and rejoins at another.

    ``waypoints`` are the interior points only, addressed by offset in miles
    from the departure waypoint. The departure and rejoin waypoints themselves
    stay owned by the main corridor, so choosing an alternate never renames them.
    """

    id: str
    name: str
    departs_at: str
    rejoins_at: str
    length_miles: float
    waypoints: tuple[Waypoint, ...] = ()
    official: bool = False
    notes: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.length_miles <= 0.0:
            raise RouteResolutionError(
                "alternate length must be positive",
                alternate=self.id,
                length_miles=self.length_miles,
            )
        if self.departs_at == self.rejoins_at:
            raise RouteResolutionError(
                "alternate must rejoin at a different waypoint", alternate=self.id
            )
        previous = 0.0
        for waypoint in self.waypoints:
            if not 0.0 < waypoint.mile < self.length_miles:
                raise RouteResolutionError(
                    "alternate waypoint offset must fall inside the alternate",
                    alternate=self.id,
                    waypoint_id=waypoint.id,
                    offset=waypoint.mile,
                    length_miles=self.length_miles,
                )
            if waypoint.mile <= previous:
                raise RouteResolutionError(
                    "alternate waypoints must ascend by offset",
                    alternate=self.id,
                    waypoint_id=waypoint.id,
                )
            previous = waypoint.mile

    @property
    def length(self) -> Distance:
        return Distance.miles(self.length_miles)

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def __repr__(self) -> str:
        return f"Alternate({self.id!r}, {self.departs_at} -> {self.rejoins_at}, {self.length_miles:.1f} mi)"


@dataclass(frozen=True, slots=True)
class RouteChoice:
    """The result of splicing: the route itself and what it cost or saved."""

    corridor: Corridor
    chosen: tuple[str, ...]
    delta: Distance

    @property
    def is_shorter(self) -> bool:
        return self.delta.in_miles < 0.0


def bypassed_span(corridor: Corridor, alternate: Alternate) -> tuple[float, float]:
    """Mileage of the main corridor stretch an alternate replaces."""
    departure = corridor.waypoint(alternate.departs_at)
    rejoin = corridor.waypoint(alternate.rejoins_at)
    if rejoin.mile <= departure.mile:
        raise RouteResolutionError(
            "alternate rejoins before it departs",
            alternate=alternate.id,
            departs_mile=departure.mile,
            rejoins_mile=rejoin.mile,
        )
    return departure.mile, rejoin.mile


def mileage_delta(corridor: Corridor, alternate: Alternate) -> Distance:
    """How much longer, or shorter, the alternate is than what it replaces."""
    start, end = bypassed_span(corridor, alternate)
    return Distance.miles(alternate.length_miles - (end - start))


def resolve_route(
    corridor: Corridor,
    alternates: Sequence[Alternate],
    chosen: Iterable[str],
) -> RouteChoice:
    """Splice the chosen alternates into the corridor and re-index the mileage."""
    by_id = {alternate.id: alternate for alternate in alternates}
    wanted: list[Alternate] = []
    for identifier in chosen:
        if identifier not in by_id:
            raise RouteResolutionError(
                "no such alternate", alternate=identifier, available=sorted(by_id)
            )
        wanted.append(by_id[identifier])
    spans = [(*bypassed_span(corridor, alternate), alternate) for alternate in wanted]
    spans.sort(key=lambda item: item[0])
    for (_, first_end, first), (second_start, _, second) in zip(spans, spans[1:], strict=False):
        if second_start < first_end:
            raise RouteResolutionError(
                "chosen alternates overlap on the corridor",
                first=first.id,
                second=second.id,
            )

    waypoints: list[Waypoint] = []
    shift = 0.0
    cursor = corridor.start_mile
    total_delta = 0.0
    for start, end, alternate in spans:
        for waypoint in corridor.waypoints_between(cursor, start):
            waypoints.append(waypoint.with_mile(waypoint.mile + shift))
        departure_mile = start + shift
        for interior in alternate.waypoints:
            waypoints.append(interior.with_mile(departure_mile + interior.mile))
        replaced = end - start
        total_delta += alternate.length_miles - replaced
        shift += alternate.length_miles - replaced
        cursor = end
    for waypoint in corridor.waypoints_between(cursor, corridor.end_mile):
        waypoints.append(waypoint.with_mile(waypoint.mile + shift))

    deduped = _drop_repeated_ids(waypoints)
    return RouteChoice(
        corridor=_rebuild(corridor, deduped),
        chosen=tuple(alternate.id for _, _, alternate in spans),
        delta=Distance.miles(total_delta),
    )


def _drop_repeated_ids(waypoints: list[Waypoint]) -> list[Waypoint]:
    """A departure waypoint can be emitted twice when spans abut. Keep the first."""
    seen: set[str] = set()
    out: list[Waypoint] = []
    for waypoint in waypoints:
        if waypoint.id in seen:
            continue
        seen.add(waypoint.id)
        out.append(waypoint)
    return out


def _rebuild(corridor: Corridor, waypoints: list[Waypoint]) -> Corridor:
    """Rebuild a corridor over spliced waypoints, keeping original segment data.

    A segment whose endpoints both survived the splice keeps its measured gain
    and loss. Anything else is derived from the spot elevations, which is the
    best available reading for a leg nobody has surveyed.
    """
    original = {(s.start.id, s.end.id): s for s in corridor.segments}
    segments: list[Segment] = []
    for start, end in zip(waypoints, waypoints[1:], strict=False):
        known = original.get((start.id, end.id))
        if known is not None:
            segments.append(
                Segment(
                    start=start,
                    end=end,
                    gain=known.gain,
                    loss=known.loss,
                    surface=known.surface,
                    notes=known.notes,
                )
            )
            continue
        delta = end.elevation.in_feet - start.elevation.in_feet
        segments.append(
            Segment(
                start=start,
                end=end,
                gain=Distance.feet(max(0.0, delta)),
                loss=Distance.feet(max(0.0, -delta)),
            )
        )
    return Corridor(name=corridor.name, waypoints=tuple(waypoints), segments=tuple(segments))
