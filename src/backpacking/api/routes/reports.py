"""Report and season endpoints.

These return files rather than JSON documents in two cases, and it is
deliberate: the calendar and the trip sheet exist to be downloaded, so they come
back with a filename and the right content type rather than as a string inside a
JSON envelope that a client then has to unwrap and write out itself.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from backpacking.api.deps import get_corridors, get_permits, get_plans, get_resupply
from backpacking.errors import PlanInfeasible
from backpacking.report.calendar import to_ics
from backpacking.report.serialize import (
    corridor_to_dict,
    permit_report_to_dict,
    plan_to_dict,
)
from backpacking.report.tripsheet import render_trip_sheet
from backpacking.season.conditions import (
    check_itinerary,
    corridor_melt_out,
    earliest_walkable_start,
    serious_findings,
    summarise,
)
from backpacking.season.snowpack import SnowYear
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
    ResupplyRepository,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/corridor/{slug}", response_model=dict)
def corridor_report(
    slug: str, corridors: CorridorRepository = Depends(get_corridors)
) -> dict[str, object]:
    """The archival JSON view of a corridor."""
    return corridor_to_dict(corridors.load(slug), slug)


@router.get("/plan/{plan_id}", response_model=dict)
def plan_report(
    plan_id: int,
    corridor: str = Query(...),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> dict[str, object]:
    """The archival JSON view of a stored plan."""
    itinerary = plans.load(plan_id, corridors.load(corridor))
    return plan_to_dict(itinerary, corridor)


@router.get("/plan/{plan_id}/permits", response_model=dict)
def plan_permit_report(
    plan_id: int,
    corridor: str = Query(...),
    has_canister: bool = Query(default=False),
    corridors: CorridorRepository = Depends(get_corridors),
    permits: PermitRepository = Depends(get_permits),
    plans: PlanRepository = Depends(get_plans),
) -> dict[str, object]:
    """The archival JSON view of a permit check."""
    from backpacking.permits.validate import validate_nights

    loaded = corridors.load(corridor)
    itinerary = plans.load(plan_id, loaded)
    zones = permits.load(corridors.corridor_id(corridor))
    report = validate_nights(itinerary.camp_nights(has_canister=has_canister), zones)
    return permit_report_to_dict(report)


@router.get("/plan/{plan_id}/calendar", response_class=Response)
def plan_calendar(
    plan_id: int,
    corridor: str = Query(...),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> Response:
    """The plan as an ICS file."""
    itinerary = plans.load(plan_id, corridors.load(corridor))
    return Response(
        content=to_ics(itinerary),
        media_type="text/calendar",
        headers={"content-disposition": f'attachment; filename="plan-{plan_id}.ics"'},
    )


@router.get("/plan/{plan_id}/tripsheet", response_class=Response)
def plan_trip_sheet(
    plan_id: int,
    corridor: str = Query(...),
    hiker_name: str = Query(..., min_length=1),
    emergency_contact: str = Query(..., min_length=1),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
    resupply: ResupplyRepository = Depends(get_resupply),
) -> Response:
    """The one page sheet a hiker leaves with somebody."""
    loaded = corridors.load(corridor)
    itinerary = plans.load(plan_id, loaded)
    towns = resupply.load(corridors.corridor_id(corridor))
    text = render_trip_sheet(
        itinerary,
        hiker_name=hiker_name,
        emergency_contact=emergency_contact,
        towns=towns,
    )
    return Response(
        content=text,
        media_type="text/plain",
        headers={"content-disposition": f'attachment; filename="tripsheet-{plan_id}.txt"'},
    )


@router.get("/season/{slug}", response_model=dict)
def season_outlook(
    slug: str,
    year: int = Query(..., ge=1900, le=2200),
    percent_of_median: float = Query(..., ge=20.0, le=260.0),
    corridors: CorridorRepository = Depends(get_corridors),
) -> dict[str, object]:
    """When a corridor's high points melt out in a given snow year."""
    corridor = corridors.load(slug)
    snow_year = SnowYear(year=year, percent_of_median=percent_of_median)
    melt = corridor_melt_out(corridor, snow_year)
    return {
        "corridor": slug,
        "year": year,
        "percent_of_median": percent_of_median,
        "descriptor": snow_year.descriptor,
        "melt_out": {key: value.isoformat() for key, value in melt.items()},
        "earliest_start": earliest_walkable_start(corridor, snow_year).isoformat(),
    }


@router.get("/season/{slug}/plan/{plan_id}", response_model=dict)
def season_check(
    slug: str,
    plan_id: int,
    year: int = Query(..., ge=1900, le=2200),
    percent_of_median: float = Query(..., ge=20.0, le=260.0),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> dict[str, object]:
    """What the snow year says about a stored plan."""
    corridor = corridors.load(slug)
    itinerary = plans.load(plan_id, corridor)
    snow_year = SnowYear(year=year, percent_of_median=percent_of_median)
    if itinerary.start_date.year != year:
        raise PlanInfeasible(
            "the plan does not start in the snow year given",
            plan_start=itinerary.start_date.isoformat(),
            snow_year=year,
        )
    findings = check_itinerary(itinerary, snow_year)
    return {
        "corridor": slug,
        "plan_id": plan_id,
        "summary": summarise(findings),
        "serious": [
            {
                "waypoint": finding.waypoint.id,
                "date": finding.when.isoformat(),
                "kind": finding.kind,
                "severity": round(finding.severity, 3),
                "message": finding.message,
            }
            for finding in serious_findings(findings)
        ],
        "total_findings": len(findings),
    }


@router.get("/season/{slug}/earliest", response_model=dict)
def earliest_start(
    slug: str,
    year: int = Query(..., ge=1900, le=2200),
    percent_of_median: float = Query(..., ge=20.0, le=260.0),
    margin_days: int = Query(default=0, ge=0, le=60),
    corridors: CorridorRepository = Depends(get_corridors),
) -> dict[str, str | date]:
    """Earliest date every high point is melted out, with an optional margin."""
    corridor = corridors.load(slug)
    snow_year = SnowYear(year=year, percent_of_median=percent_of_median)
    return {
        "corridor": slug,
        "earliest_start": earliest_walkable_start(
            corridor, snow_year, margin_days=margin_days
        ).isoformat(),
        "descriptor": snow_year.descriptor,
    }
