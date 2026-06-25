"""Plan resources.

Building a plan is a POST rather than a GET even though it changes nothing,
because the request body is large and structured and does not belong in a query
string. Saving one is a separate call, so a client can iterate on a plan without
filling the database with attempts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from backpacking.api.deps import get_corridors, get_plans, get_service
from backpacking.api.schemas import PlanOut, PlanRequestIn
from backpacking.plan.explain import render_schedule
from backpacking.plan.solver import PlanRequest
from backpacking.services.planning import ConstraintSpec, HikerSpec, PlanningService
from backpacking.storage.repository import CorridorRepository, PlanRepository

router = APIRouter(prefix="/plans", tags=["plans"])


def hiker_spec(body: PlanRequestIn) -> HikerSpec:
    return HikerSpec(
        name=body.hiker.name,
        flat_pace_mph=body.hiker.flat_pace_mph,
        max_moving_hours=body.hiker.max_moving_hours,
        max_daily_gain_ft=body.hiker.max_daily_gain_ft,
        break_fraction=body.hiker.break_fraction,
        pack_weight_lb=body.hiker.pack_weight_lb,
        night_hiking=body.hiker.night_hiking,
    )


def constraint_spec(body: PlanRequestIn) -> ConstraintSpec:
    return ConstraintSpec(
        max_daily_miles=body.constraints.max_daily_miles,
        min_daily_miles=body.constraints.min_daily_miles,
        max_daily_gain_ft=body.constraints.max_daily_gain_ft,
        max_daily_hours=body.constraints.max_daily_hours,
        camps_must_be_named=body.constraints.camps_must_be_named,
        max_total_days=body.constraints.max_total_days,
        forbidden_camps=tuple(body.constraints.forbidden_camps),
    )


def request_from(body: PlanRequestIn, service: PlanningService) -> PlanRequest:
    return service.build_request(
        body.corridor,
        body.start_date,
        hiker=hiker_spec(body),
        constraints=constraint_spec(body),
        start_mile=body.start_mile,
        end_mile=body.end_mile,
        aggressiveness=body.aggressiveness,
    )


@router.post("", response_model=PlanOut)
def build_plan(
    body: PlanRequestIn,
    service: PlanningService = Depends(get_service),
) -> PlanOut:
    """Build a plan without storing it."""
    return PlanOut.of(body.corridor, service.build_plan(request_from(body, service)))


@router.post("/save", response_model=dict[str, int], status_code=status.HTTP_201_CREATED)
def build_and_save(
    body: PlanRequestIn,
    service: PlanningService = Depends(get_service),
) -> dict[str, int]:
    """Build a plan and keep it, returning its id."""
    itinerary = service.build_plan(request_from(body, service))
    return {"plan_id": service.save_plan(itinerary, body.corridor, body.hiker.name)}


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(
    plan_id: int,
    corridor: str = Query(..., description="the corridor the plan was built over"),
    service: PlanningService = Depends(get_service),
) -> PlanOut:
    """A stored plan."""
    return PlanOut.of(corridor, service.load_plan(plan_id, corridor))


@router.get("/{plan_id}/schedule", response_class=Response)
def get_schedule(
    plan_id: int,
    corridor: str = Query(...),
    service: PlanningService = Depends(get_service),
) -> Response:
    """The plan as the plain text table a hiker would print."""
    itinerary = service.load_plan(plan_id, corridor)
    return Response(content=render_schedule(itinerary), media_type="text/plain")


@router.post("/explain", response_model=list[dict[str, float]])
def explain(
    body: PlanRequestIn,
    service: PlanningService = Depends(get_service),
) -> list[dict[str, float]]:
    """The objective, term by term, for each day of a freshly built plan."""
    request = request_from(body, service)
    itinerary = service.build_plan(request)
    return service.explain(itinerary, request.profile, aggressiveness=body.aggressiveness)


@router.get("", response_model=list[dict[str, object]])
def list_plans(
    corridor: str = Query(...),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> list[dict[str, object]]:
    """Stored plans for one corridor."""
    corridor_id = corridors.corridor_id(corridor)
    return [
        {"plan_id": plan_id, "label": label, "start_date": start.isoformat()}
        for plan_id, label, start in plans.list_for_corridor(corridor_id)
    ]


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, plans: PlanRepository = Depends(get_plans)) -> Response:
    plans.delete(plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
