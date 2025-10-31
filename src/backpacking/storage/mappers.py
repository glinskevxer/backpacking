"""Translating between the domain objects and the rows.

This is the only place that knows both shapes. Keeping it in one file means the
unit conversions live together and can be read against each other, which is the
whole reason a corridor imported through GPX and one imported through a
datasheet now agree.

Every function here is total and pure. A row that cannot be turned into a domain
object raises rather than returning a half built one.
"""

from __future__ import annotations

from collections.abc import Sequence

from backpacking.errors import DataSourceError
from backpacking.geo import GeoPoint
from backpacking.permits.zones import CampingPolicy, PermitZone, ZoneMap
from backpacking.plan.itinerary import Itinerary
from backpacking.resupply.towns import ResupplyPoint, ServiceLevel, TownIndex
from backpacking.storage.schema import (
    CorridorRow,
    PermitZoneRow,
    PlanDayRow,
    PlanRow,
    ResupplyPointRow,
    SegmentRow,
    WaterSourceRow,
    WaypointRow,
)
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Segment, Surface, Waypoint, WaypointKind
from backpacking.units import Distance, Duration, Mass
from backpacking.water.sources import Reliability, WaterSource, WaterTable

TAG_SEPARATOR = "|"


def waypoint_to_row(waypoint: Waypoint, corridor_id: int) -> WaypointRow:
    return WaypointRow(
        corridor_id=corridor_id,
        slug=waypoint.id,
        name=waypoint.name,
        mile=waypoint.mile,
        elevation_ft=waypoint.elevation.in_feet,
        kind=waypoint.kind.value,
        latitude=None if waypoint.position is None else waypoint.position.latitude,
        longitude=None if waypoint.position is None else waypoint.position.longitude,
        tags=TAG_SEPARATOR.join(sorted(waypoint.tags)),
        notes=waypoint.notes,
    )


def row_to_waypoint(row: WaypointRow) -> Waypoint:
    position = None
    if row.latitude is not None and row.longitude is not None:
        position = GeoPoint(row.latitude, row.longitude, Distance.feet(row.elevation_ft))
    try:
        kind = WaypointKind(row.kind)
    except ValueError as exc:
        raise DataSourceError(
            "stored waypoint kind is not recognised", slug=row.slug, kind=row.kind
        ) from exc
    return Waypoint(
        id=row.slug,
        name=row.name,
        mile=row.mile,
        elevation=Distance.feet(row.elevation_ft),
        kind=kind,
        position=position,
        notes=row.notes,
        tags=frozenset(t for t in row.tags.split(TAG_SEPARATOR) if t),
    )


def segment_to_row(segment: Segment, corridor_id: int) -> SegmentRow:
    return SegmentRow(
        corridor_id=corridor_id,
        start_slug=segment.start.id,
        end_slug=segment.end.id,
        start_mile=segment.start.mile,
        end_mile=segment.end.mile,
        gain_ft=segment.gain.in_feet,
        loss_ft=segment.loss.in_feet,
        surface=segment.surface.value,
        notes=segment.notes,
    )


def corridor_to_rows(corridor: Corridor, slug: str) -> CorridorRow:
    """One corridor row with its waypoints and segments attached."""
    row = CorridorRow(slug=slug, name=corridor.name)
    row.waypoints = [waypoint_to_row(w, 0) for w in corridor.waypoints]
    row.segments = [segment_to_row(s, 0) for s in corridor.segments]
    return row


def rows_to_corridor(row: CorridorRow) -> Corridor:
    """Rebuild a corridor, matching segments back onto waypoints by slug."""
    waypoints = [row_to_waypoint(w) for w in row.waypoints]
    by_slug = {w.id: w for w in waypoints}
    segments: list[Segment] = []
    for segment_row in row.segments:
        start = by_slug.get(segment_row.start_slug)
        end = by_slug.get(segment_row.end_slug)
        if start is None or end is None:
            raise DataSourceError(
                "stored segment references a waypoint that is not there",
                corridor=row.slug,
                start=segment_row.start_slug,
                end=segment_row.end_slug,
            )
        try:
            surface = Surface(segment_row.surface)
        except ValueError as exc:
            raise DataSourceError(
                "stored surface is not recognised", surface=segment_row.surface
            ) from exc
        segments.append(
            Segment(
                start=start,
                end=end,
                gain=Distance.feet(segment_row.gain_ft),
                loss=Distance.feet(segment_row.loss_ft),
                surface=surface,
                notes=segment_row.notes,
            )
        )
    return Corridor(name=row.name, waypoints=tuple(waypoints), segments=tuple(segments))


def water_source_to_row(source: WaterSource, corridor_id: int) -> WaterSourceRow:
    return WaterSourceRow(
        corridor_id=corridor_id,
        slug=source.id,
        name=source.name,
        mile=source.mile,
        reliability=source.reliability.value,
        off_trail_miles=source.off_trail.in_miles,
        needs_treatment=source.needs_treatment,
        notes=source.notes,
    )


def rows_to_water_table(rows: Sequence[WaterSourceRow]) -> WaterTable:
    sources = []
    for row in rows:
        try:
            reliability = Reliability(row.reliability)
        except ValueError as exc:
            raise DataSourceError(
                "stored reliability is not recognised", slug=row.slug, value=row.reliability
            ) from exc
        sources.append(
            WaterSource(
                id=row.slug,
                name=row.name,
                mile=row.mile,
                reliability=reliability,
                off_trail=Distance.miles(row.off_trail_miles),
                needs_treatment=row.needs_treatment,
                notes=row.notes,
            )
        )
    return WaterTable(sources)


def permit_zone_to_row(zone: PermitZone, corridor_id: int) -> PermitZoneRow:
    return PermitZoneRow(
        corridor_id=corridor_id,
        slug=zone.id,
        name=zone.name,
        agency=zone.agency,
        start_mile=zone.start_mile,
        end_mile=zone.end_mile,
        camping=zone.camping.value,
        max_consecutive_nights=zone.max_consecutive_nights,
        min_water_setback_ft=zone.min_distance_from_water.in_feet,
        campfires_allowed=zone.campfires_allowed,
        campfire_limit_ft=(
            None if zone.campfire_elevation_limit is None else zone.campfire_elevation_limit.in_feet
        ),
        canister_required=zone.canister_required,
        designated_sites=TAG_SEPARATOR.join(sorted(zone.designated_sites)),
    )


def rows_to_zone_map(rows: Sequence[PermitZoneRow]) -> ZoneMap:
    zones = []
    for row in rows:
        try:
            camping = CampingPolicy(row.camping)
        except ValueError as exc:
            raise DataSourceError(
                "stored camping policy is not recognised", slug=row.slug, value=row.camping
            ) from exc
        zones.append(
            PermitZone(
                id=row.slug,
                name=row.name,
                agency=row.agency,
                start_mile=row.start_mile,
                end_mile=row.end_mile,
                camping=camping,
                max_consecutive_nights=row.max_consecutive_nights,
                min_distance_from_water=Distance.feet(row.min_water_setback_ft),
                campfires_allowed=row.campfires_allowed,
                campfire_elevation_limit=(
                    None if row.campfire_limit_ft is None else Distance.feet(row.campfire_limit_ft)
                ),
                canister_required=row.canister_required,
                designated_sites=frozenset(
                    site for site in row.designated_sites.split(TAG_SEPARATOR) if site
                ),
            )
        )
    return ZoneMap(zones)


def resupply_to_row(point: ResupplyPoint, corridor_id: int) -> ResupplyPointRow:
    return ResupplyPointRow(
        corridor_id=corridor_id,
        slug=point.id,
        name=point.name,
        mile=point.mile,
        groceries=int(point.groceries),
        hitch_miles=point.hitch.in_miles,
        walk_in_miles=point.walk_in.in_miles,
        shuttle_wait_minutes=point.shuttle_wait.in_minutes,
        has_post_office=point.has_post_office,
        has_lodging=point.has_lodging,
        has_shower=point.has_shower,
        open_days="".join(str(day) for day in sorted(point.open_days)),
        notes=point.notes,
    )


def rows_to_town_index(rows: Sequence[ResupplyPointRow]) -> TownIndex:
    points = []
    for row in rows:
        try:
            groceries = ServiceLevel(row.groceries)
        except ValueError as exc:
            raise DataSourceError(
                "stored service level is not recognised", slug=row.slug, value=row.groceries
            ) from exc
        points.append(
            ResupplyPoint(
                id=row.slug,
                name=row.name,
                mile=row.mile,
                groceries=groceries,
                hitch=Distance.miles(row.hitch_miles),
                walk_in=Distance.miles(row.walk_in_miles),
                shuttle_wait=Duration.minutes(row.shuttle_wait_minutes),
                has_post_office=row.has_post_office,
                has_lodging=row.has_lodging,
                has_shower=row.has_shower,
                open_days=frozenset(int(day) for day in row.open_days),
                notes=row.notes,
            )
        )
    return TownIndex(points)


def itinerary_to_rows(itinerary: Itinerary, corridor_id: int, hiker_name: str) -> PlanRow:
    plan = PlanRow(
        corridor_id=corridor_id,
        label=itinerary.label,
        hiker_name=hiker_name,
        start_date=itinerary.start_date,
        finish_date=itinerary.finish_date,
        total_miles=itinerary.total_distance.in_miles,
        total_gain_ft=itinerary.total_gain.in_feet,
    )
    plan.days = [
        PlanDayRow(
            day_index=day.index,
            day=day.day,
            start_mile=day.start_mile,
            end_mile=day.end_mile,
            gain_ft=day.estimate.gain.in_feet,
            loss_ft=day.estimate.loss.in_feet,
            moving_seconds=day.estimate.moving_time.in_seconds,
            elapsed_seconds=day.estimate.elapsed_time.in_seconds,
            camp_slug=day.camp_id,
            pack_weight_g=day.pack_weight.in_grams,
            is_zero=day.is_zero,
            resupply_at=day.resupply_at,
            notes=day.notes,
        )
        for day in itinerary
    ]
    return plan


def rows_to_itinerary(plan: PlanRow, corridor: Corridor) -> Itinerary:
    from backpacking.pace.models import LegEstimate
    from backpacking.plan.itinerary import DayPlan

    days = []
    for row in plan.days:
        camp = corridor.waypoint(row.camp_slug) if row.camp_slug else None
        days.append(
            DayPlan(
                index=row.day_index,
                day=row.day,
                start_mile=row.start_mile,
                end_mile=row.end_mile,
                estimate=LegEstimate(
                    distance=Distance.miles(row.end_mile - row.start_mile),
                    gain=Distance.feet(row.gain_ft),
                    loss=Distance.feet(row.loss_ft),
                    moving_time=Duration.seconds(row.moving_seconds),
                    elapsed_time=Duration.seconds(row.elapsed_seconds),
                ),
                camp=camp,
                pack_weight=Mass.grams(row.pack_weight_g),
                is_zero=row.is_zero,
                resupply_at=row.resupply_at,
                notes=row.notes,
            )
        )
    return Itinerary(corridor=corridor, days=tuple(days), label=plan.label)
