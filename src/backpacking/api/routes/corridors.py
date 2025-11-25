"""Corridor resources."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from backpacking.api.deps import get_corridors
from backpacking.api.schemas import CorridorOut, CorridorSummaryOut, WaypointOut
from backpacking.errors import CorridorError
from backpacking.storage.repository import CorridorRepository
from backpacking.trail.models import WaypointKind

router = APIRouter(prefix="/corridors", tags=["corridors"])


@router.get("", response_model=list[CorridorSummaryOut])
def list_corridors(
    repository: CorridorRepository = Depends(get_corridors),
) -> list[CorridorSummaryOut]:
    """Every stored corridor, summarised."""
    return [
        CorridorSummaryOut.of(slug, repository.load(slug)) for slug in repository.list_slugs()
    ]


@router.get("/{slug}", response_model=CorridorOut)
def get_corridor(
    slug: str, repository: CorridorRepository = Depends(get_corridors)
) -> CorridorOut:
    """One corridor with its waypoints and segments."""
    return CorridorOut.full(slug, repository.load(slug))


@router.get("/{slug}/waypoints", response_model=list[WaypointOut])
def list_waypoints(
    slug: str,
    kind: str | None = Query(default=None, description="filter to one waypoint kind"),
    from_mile: float | None = Query(default=None, ge=0.0),
    to_mile: float | None = Query(default=None, ge=0.0),
    repository: CorridorRepository = Depends(get_corridors),
) -> list[WaypointOut]:
    """Waypoints, optionally filtered by kind and by mileage window."""
    corridor = repository.load(slug)
    low = corridor.start_mile if from_mile is None else from_mile
    high = corridor.end_mile if to_mile is None else to_mile
    if high < low:
        raise CorridorError("to_mile precedes from_mile", from_mile=low, to_mile=high)
    found = corridor.waypoints_between(low, high)
    if kind is not None:
        try:
            wanted = WaypointKind(kind)
        except ValueError as exc:
            raise CorridorError(
                "unknown waypoint kind", kind=kind, known=[k.value for k in WaypointKind]
            ) from exc
        found = tuple(w for w in found if w.kind is wanted)
    return [WaypointOut.of(w) for w in found]


@router.get("/{slug}/profile")
def corridor_profile(
    slug: str,
    step_miles: float = Query(default=1.0, gt=0.0, le=10.0),
    repository: CorridorRepository = Depends(get_corridors),
) -> dict[str, list[float]]:
    """Elevation sampled evenly, for drawing a profile."""
    corridor = repository.load(slug)
    miles: list[float] = []
    elevations: list[float] = []
    cursor = corridor.start_mile
    while cursor < corridor.end_mile:
        miles.append(round(cursor, 3))
        elevations.append(round(corridor.elevation_at(cursor).in_feet, 1))
        cursor += step_miles
    miles.append(round(corridor.end_mile, 3))
    elevations.append(round(corridor.elevation_at(corridor.end_mile).in_feet, 1))
    return {"miles": miles, "elevation_ft": elevations}


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_corridor(
    slug: str, repository: CorridorRepository = Depends(get_corridors)
) -> Response:
    """Remove a corridor and everything hanging off it."""
    repository.delete(slug)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
