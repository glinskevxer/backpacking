"""Request and response bodies.

These are a separate set of types from the domain objects on purpose. The domain
objects carry typed quantities, which are exactly what a planner wants and
exactly what an HTTP client does not: a client wants a number and a documented
unit. So every field here is a plain number named for its unit, and the mapping
happens in one direction only, at the edge.

The other reason is versioning. A field can be renamed in the domain without
breaking a client, and a response field can be kept alive after the domain has
moved on.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backpacking.plan.itinerary import Itinerary
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Waypoint


class WaypointOut(BaseModel):
    """A waypoint as the API returns it."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    mile: float
    elevation_ft: float
    kind: str
    latitude: float | None = None
    longitude: float | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @classmethod
    def of(cls, waypoint: Waypoint) -> WaypointOut:
        return cls(
            id=waypoint.id,
            name=waypoint.name,
            mile=round(waypoint.mile, 3),
            elevation_ft=round(waypoint.elevation.in_feet, 1),
            kind=waypoint.kind.value,
            latitude=None if waypoint.position is None else waypoint.position.latitude,
            longitude=None if waypoint.position is None else waypoint.position.longitude,
            tags=sorted(waypoint.tags),
            notes=waypoint.notes,
        )


class SegmentOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_id: str
    end_id: str
    length_miles: float
    gain_ft: float
    loss_ft: float
    surface: str


class CorridorSummaryOut(BaseModel):
    """A corridor without its waypoints, for listing."""

    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    length_miles: float
    waypoint_count: int
    total_gain_ft: float
    total_loss_ft: float

    @classmethod
    def of(cls, slug: str, corridor: Corridor) -> CorridorSummaryOut:
        return cls(
            slug=slug,
            name=corridor.name,
            length_miles=round(corridor.length.in_miles, 2),
            waypoint_count=len(corridor),
            total_gain_ft=round(corridor.total_gain().in_feet, 0),
            total_loss_ft=round(corridor.total_loss().in_feet, 0),
        )


class CorridorOut(CorridorSummaryOut):
    """A corridor with everything on it."""

    waypoints: list[WaypointOut] = Field(default_factory=list)
    segments: list[SegmentOut] = Field(default_factory=list)

    @classmethod
    def full(cls, slug: str, corridor: Corridor) -> CorridorOut:
        summary = CorridorSummaryOut.of(slug, corridor)
        return cls(
            **summary.model_dump(),
            waypoints=[WaypointOut.of(w) for w in corridor],
            segments=[
                SegmentOut(
                    start_id=s.start.id,
                    end_id=s.end.id,
                    length_miles=round(s.length.in_miles, 3),
                    gain_ft=round(s.gain.in_feet, 1),
                    loss_ft=round(s.loss.in_feet, 1),
                    surface=s.surface.value,
                )
                for s in corridor.segments
            ],
        )


class HikerIn(BaseModel):
    """The hiker a plan is built for."""

    name: str = "default"
    flat_pace_mph: float = Field(default=3.0, gt=0.0, le=8.0)
    max_moving_hours: float = Field(default=9.0, gt=0.0, le=20.0)
    max_daily_gain_ft: float = Field(default=6000.0, gt=0.0, le=25000.0)
    break_fraction: float = Field(default=0.18, ge=0.0, lt=1.0)
    pack_weight_lb: float = Field(default=26.0, gt=0.0, le=120.0)
    night_hiking: bool = False


class ConstraintsIn(BaseModel):
    """Hard limits the plan has to satisfy."""

    max_daily_miles: float = Field(default=32.0, gt=0.0, le=80.0)
    min_daily_miles: float = Field(default=4.0, ge=0.0, le=40.0)
    max_daily_gain_ft: float = Field(default=6000.0, gt=0.0)
    max_daily_hours: float = Field(default=12.0, gt=0.0, le=24.0)
    camps_must_be_named: bool = False
    max_total_days: int | None = Field(default=None, ge=1, le=400)
    forbidden_camps: list[str] = Field(default_factory=list)

    @field_validator("min_daily_miles")
    @classmethod
    def _min_below_max(cls, value: float, info: object) -> float:
        return value


class PlanRequestIn(BaseModel):
    """Everything needed to build a plan over a stored corridor."""

    corridor: str
    start_date: date
    start_mile: float | None = Field(default=None, ge=0.0)
    end_mile: float | None = Field(default=None, ge=0.0)
    hiker: HikerIn = Field(default_factory=HikerIn)
    constraints: ConstraintsIn = Field(default_factory=ConstraintsIn)
    aggressiveness: float = Field(default=0.8, gt=0.0, le=1.0)


class DayOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    date: date
    start_mile: float
    end_mile: float
    miles: float
    gain_ft: float
    loss_ft: float
    moving_hours: float
    elapsed_hours: float
    camp_id: str | None
    is_zero: bool
    resupply_at: str | None


class PlanOut(BaseModel):
    """A finished plan."""

    model_config = ConfigDict(frozen=True)

    corridor: str
    label: str
    start_date: date
    finish_date: date
    days: list[DayOut]
    total_miles: float
    total_gain_ft: float
    average_daily_miles: float

    @classmethod
    def of(cls, slug: str, itinerary: Itinerary) -> PlanOut:
        return cls(
            corridor=slug,
            label=itinerary.label,
            start_date=itinerary.start_date,
            finish_date=itinerary.finish_date,
            total_miles=round(itinerary.total_distance.in_miles, 2),
            total_gain_ft=round(itinerary.total_gain.in_feet, 0),
            average_daily_miles=round(itinerary.average_daily_miles, 2),
            days=[
                DayOut(
                    index=day.index,
                    date=day.day,
                    start_mile=round(day.start_mile, 2),
                    end_mile=round(day.end_mile, 2),
                    miles=round(day.miles, 2),
                    gain_ft=round(day.estimate.gain.in_feet, 0),
                    loss_ft=round(day.estimate.loss.in_feet, 0),
                    moving_hours=round(day.estimate.moving_time.in_hours, 2),
                    elapsed_hours=round(day.elapsed.in_hours, 2),
                    camp_id=day.camp_id,
                    is_zero=day.is_zero,
                    resupply_at=day.resupply_at,
                )
                for day in itinerary
            ],
        )


class FindingOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: str
    severity: str
    message: str
    night: date | None = None
    zone_id: str | None = None


class PermitReportOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    permittable: bool
    nights_checked: int
    zones_visited: list[str]
    violations: list[FindingOut]
    advisories: list[FindingOut]
    suggestions: list[str]


class WaterGapOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_mile: float
    end_mile: float
    length_miles: float
    start_source: str | None
    end_source: str | None
    liters_required: float
    fits_capacity: bool


class ErrorOut(BaseModel):
    """The body every failure returns."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    context: dict[str, object] = Field(default_factory=dict)


class HealthOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    version: str
    database: str
