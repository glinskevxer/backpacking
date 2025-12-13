"""Permit checking over HTTP."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from backpacking.api.deps import get_corridors, get_permits, get_plans
from backpacking.api.schemas import FindingOut, PermitReportOut
from backpacking.permits.validate import PermitReport, suggest_fixes, validate_nights
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
)

router = APIRouter(prefix="/permits", tags=["permits"])


def report_to_schema(report: PermitReport) -> PermitReportOut:
    return PermitReportOut(
        permittable=report.is_permittable,
        nights_checked=report.nights_checked,
        zones_visited=list(report.zones_visited),
        violations=[_finding(f) for f in report.violations],
        advisories=[_finding(f) for f in report.advisories],
        suggestions=list(suggest_fixes(report)),
    )


def _finding(finding: object) -> FindingOut:
    return FindingOut(
        rule=finding.rule,  # type: ignore[attr-defined]
        severity=str(finding.severity),  # type: ignore[attr-defined]
        message=finding.message,  # type: ignore[attr-defined]
        night=finding.night,  # type: ignore[attr-defined]
        zone_id=finding.zone_id,  # type: ignore[attr-defined]
    )


@router.get("/zones/{slug}", response_model=list[dict[str, object]])
def list_zones(
    slug: str,
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
) -> list[dict[str, object]]:
    """Every permit zone on a corridor."""
    zones = permits.load(corridors.corridor_id(slug))
    return [
        {
            "id": zone.id,
            "name": zone.name,
            "agency": zone.agency,
            "start_mile": zone.start_mile,
            "end_mile": zone.end_mile,
            "camping": zone.camping.value,
            "canister_required": zone.canister_required,
            "max_consecutive_nights": zone.max_consecutive_nights,
        }
        for zone in zones
    ]


@router.get("/zones/{slug}/at", response_model=dict[str, object])
def zone_at_mile(
    slug: str,
    mile: float = Query(..., ge=0.0),
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
) -> dict[str, object]:
    """Which zone a mile falls in, or nothing where the corridor is unmanaged."""
    zone = permits.load(corridors.corridor_id(slug)).at(mile)
    if zone is None:
        return {"zone": None, "mile": mile}
    return {"zone": zone.id, "name": zone.name, "agency": zone.agency, "mile": mile}


@router.get("/check/{plan_id}", response_model=PermitReportOut)
def check_plan(
    plan_id: int,
    corridor: str = Query(...),
    has_canister: bool = Query(default=False),
    wants_fire: bool = Query(default=False),
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
    plans: PlanRepository = Depends(get_plans),
) -> PermitReportOut:
    """Grade a stored plan against the corridor's permit rules."""
    loaded = corridors.load(corridor)
    itinerary = plans.load(plan_id, loaded)
    zones = permits.load(corridors.corridor_id(corridor))
    nights = itinerary.camp_nights(has_canister=has_canister, wants_fire=wants_fire)
    return report_to_schema(validate_nights(nights, zones))


@router.get("/canister/{slug}", response_model=dict[str, object])
def canister_required(
    slug: str,
    from_mile: float = Query(..., ge=0.0),
    to_mile: float = Query(..., ge=0.0),
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
) -> dict[str, object]:
    """Whether a canister is required anywhere in a mileage window."""
    zones = permits.load(corridors.corridor_id(slug))
    required = zones.canister_required_between(from_mile, to_mile)
    naming = [zone.id for zone in zones.between(from_mile, to_mile) if zone.canister_required]
    return {"required": required, "zones": naming}


@router.get("/gaps/{slug}", response_model=list[dict[str, float]])
def unmanaged_gaps(
    slug: str,
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
) -> list[dict[str, float]]:
    """Stretches of corridor no mapped zone covers."""
    zones = permits.load(corridors.corridor_id(slug))
    return [{"start_mile": start, "end_mile": end} for start, end in zones.gaps()]


@router.get("/season/{slug}", response_model=dict[str, object])
def season_summary(
    slug: str,
    on: date = Query(..., description="date the summary applies to"),
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
) -> dict[str, object]:
    """Agencies and headline restrictions in force on a given date."""
    zones = permits.load(corridors.corridor_id(slug))
    return {
        "date": on.isoformat(),
        "agencies": list(zones.agencies()),
        "zones": len(zones),
        "canister_zones": [zone.id for zone in zones if zone.canister_required],
        "no_fire_zones": [zone.id for zone in zones if not zone.campfires_allowed],
    }
