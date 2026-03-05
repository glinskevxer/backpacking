"""JSON shaped dictionaries for corridors, plans and permit reports.

The API has its own response models and this is not a duplicate of them. These
are archival: they are what gets written to a file, mailed to whoever is holding
the emergency contact sheet, and read back in a year. So they carry units in
every key, they carry the inputs as well as the outputs, and they are stable in
a way an API response is not allowed to constrain itself to be.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from backpacking.errors import DataSourceError
from backpacking.pace.models import HikerProfile
from backpacking.permits.validate import PermitReport
from backpacking.plan.itinerary import Itinerary
from backpacking.trail.corridor import Corridor

SCHEMA_VERSION = 1


def corridor_to_dict(corridor: Corridor, slug: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "name": corridor.name,
        "length_miles": round(corridor.length.in_miles, 3),
        "total_gain_ft": round(corridor.total_gain().in_feet, 1),
        "total_loss_ft": round(corridor.total_loss().in_feet, 1),
        "waypoints": [
            {
                "id": waypoint.id,
                "name": waypoint.name,
                "mile": round(waypoint.mile, 3),
                "elevation_ft": round(waypoint.elevation.in_feet, 1),
                "kind": waypoint.kind.value,
                "tags": sorted(waypoint.tags),
                "latitude": None if waypoint.position is None else waypoint.position.latitude,
                "longitude": None if waypoint.position is None else waypoint.position.longitude,
            }
            for waypoint in corridor
        ],
        "segments": [
            {
                "start_id": segment.start.id,
                "end_id": segment.end.id,
                "length_miles": round(segment.length.in_miles, 3),
                "gain_ft": round(segment.gain.in_feet, 1),
                "loss_ft": round(segment.loss.in_feet, 1),
                "surface": segment.surface.value,
            }
            for segment in corridor.segments
        ],
    }


def hiker_to_dict(profile: HikerProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "flat_pace_mph": profile.flat_pace_mph,
        "max_moving_hours": profile.max_moving_hours,
        "max_daily_gain_ft": profile.max_daily_gain_ft,
        "break_fraction": profile.break_fraction,
        "reference_load_lb": round(profile.reference_load.in_pounds, 2),
        "night_hiking": profile.night_hiking,
    }


def plan_to_dict(
    itinerary: Itinerary,
    slug: str,
    *,
    profile: HikerProfile | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Everything about a plan, including what it was built from."""
    stamp = generated_at or datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": stamp.isoformat(),
        "corridor": slug,
        "corridor_name": itinerary.corridor.name,
        "label": itinerary.label,
        "start_date": itinerary.start_date.isoformat(),
        "finish_date": itinerary.finish_date.isoformat(),
        "days": len(itinerary),
        "total_miles": round(itinerary.total_distance.in_miles, 2),
        "total_gain_ft": round(itinerary.total_gain.in_feet, 1),
        "average_daily_miles": round(itinerary.average_daily_miles, 2),
        "schedule": [
            {
                "index": day.index,
                "date": day.day.isoformat(),
                "start_mile": round(day.start_mile, 2),
                "end_mile": round(day.end_mile, 2),
                "miles": round(day.miles, 2),
                "gain_ft": round(day.estimate.gain.in_feet, 1),
                "loss_ft": round(day.estimate.loss.in_feet, 1),
                "moving_hours": round(day.estimate.moving_time.in_hours, 2),
                "elapsed_hours": round(day.elapsed.in_hours, 2),
                "camp_id": day.camp_id,
                "camp_elevation_ft": (
                    None if day.camp is None else round(day.camp.elevation.in_feet, 1)
                ),
                "pack_weight_lb": round(day.pack_weight.in_pounds, 2),
                "is_zero": day.is_zero,
                "resupply_at": day.resupply_at,
                "notes": day.notes,
            }
            for day in itinerary
        ],
    }
    if profile is not None:
        body["hiker"] = hiker_to_dict(profile)
    return body


def permit_report_to_dict(report: PermitReport) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "permittable": report.is_permittable,
        "nights_checked": report.nights_checked,
        "zones_visited": list(report.zones_visited),
        "findings": [
            {
                "rule": finding.rule,
                "severity": str(finding.severity),
                "message": finding.message,
                "night": None if finding.night is None else finding.night.isoformat(),
                "zone_id": finding.zone_id,
            }
            for finding in report.findings
        ],
    }


def to_json(body: dict[str, Any], *, indent: int = 2) -> str:
    """Serialise, refusing anything that will not round trip."""
    try:
        return json.dumps(body, indent=indent, sort_keys=False, default=_encode)
    except (TypeError, ValueError) as exc:
        raise DataSourceError("report body is not serialisable", detail=str(exc)) from exc


def _encode(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value).__name__}")


def from_json(text: str) -> dict[str, Any]:
    """Read a report back, checking the schema version is one we understand."""
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataSourceError("report is not valid json", detail=str(exc)) from exc
    if not isinstance(body, dict):
        raise DataSourceError("report must be a json object")
    version = body.get("schema_version")
    if version != SCHEMA_VERSION:
        raise DataSourceError(
            "report schema version is not supported",
            found=version,
            supported=SCHEMA_VERSION,
        )
    return body
