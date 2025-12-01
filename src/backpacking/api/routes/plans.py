"""Plan resources.

Building a plan is a POST rather than a GET even though it changes nothing,
because the request body is large and structured and does not belong in a query
string. Saving one is a separate call, so a client can iterate on a plan without
filling the database with attempts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from backpacking.api.deps import get_corridors, get_plans
from backpacking.api.schemas import PlanOut, PlanRequestIn
from backpacking.pace.models import HikerProfile
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.explain import explain_plan, render_schedule
from backpacking.plan.scoring import target_hours_for
from backpacking.plan.solver import PlanRequest, solve
from backpacking.storage.repository import CorridorRepository, PlanRepository
from backpacking.units import Distance, Duration, Mass

router = APIRouter(prefix="/plans", tags=["plans"])


def profile_from(body: PlanRequestIn) -> HikerProfile:
    return HikerProfile(
        name=body.hiker.name,
        flat_pace_mph=body.hiker.flat_pace_mph,
        max_moving_hours=body.hiker.max_moving_hours,
        max_daily_gain_ft=body.hiker.max_daily_gain_ft,
        break_fraction=body.hiker.break_fraction,
        reference_load=Mass.pounds(body.hiker.pack_weight_lb),
        night_hiking=body.hiker.night_hiking,
    )


def constraints_from(body: PlanRequestIn) -> PlanConstraints:
    return PlanConstraints(
        max_daily_miles=body.constraints.max_daily_miles,
        min_daily_miles=body.constraints.min_daily_miles,
        max_daily_gain=Distance.feet(body.constraints.max_daily_gain_ft),
        max_daily_elapsed=Duration.hours(body.constraints.max_daily_hours),
        camps_must_be_named=body.constraints.camps_must_be_named,
        max_total_days=body.constraints.max_total_days,
        forbidden_camps=frozenset(body.constraints.forbidden_camps),
    )


def request_from(body: PlanRequestIn, repository: CorridorRepository) -> PlanRequest:
    return PlanRequest(
        corridor=repository.load(body.corridor),
        profile=profile_from(body),
        start_date=body.start_date,
        constraints=constraints_from(body),
        start_mile=body.start_mile,
        end_mile=body.end_mile,
        aggressiveness=body.aggressiveness,
        pack_weight=Mass.pounds(body.hiker.pack_weight_lb),
    )


@router.post("", response_model=PlanOut)
def build_plan(
    body: PlanRequestIn,
    corridors: CorridorRepository = Depends(get_corridors),
) -> PlanOut:
    """Build a plan without storing it."""
    return PlanOut.of(body.corridor, solve(request_from(body, corridors)))


@router.post("/save", response_model=dict[str, int], status_code=status.HTTP_201_CREATED)
def build_and_save(
    body: PlanRequestIn,
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> dict[str, int]:
    """Build a plan and keep it, returning its id."""
    itinerary = solve(request_from(body, corridors))
    plan_id = plans.save(itinerary, corridors.corridor_id(body.corridor), body.hiker.name)
    return {"plan_id": plan_id}


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(
    plan_id: int,
    corridor: str = Query(..., description="the corridor the plan was built over"),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> PlanOut:
    """A stored plan."""
    return PlanOut.of(corridor, plans.load(plan_id, corridors.load(corridor)))


@router.get("/{plan_id}/schedule", response_class=Response)
def get_schedule(
    plan_id: int,
    corridor: str = Query(...),
    corridors: CorridorRepository = Depends(get_corridors),
    plans: PlanRepository = Depends(get_plans),
) -> Response:
    """The plan as the plain text table a hiker would print."""
    itinerary = plans.load(plan_id, corridors.load(corridor))
    return Response(content=render_schedule(itinerary), media_type="text/plain")


@router.post("/explain", response_model=list[dict[str, float]])
def explain(
    body: PlanRequestIn,
    corridors: CorridorRepository = Depends(get_corridors),
) -> list[dict[str, float]]:
    """The objective, term by term, for each day of a freshly built plan."""
    request = request_from(body, corridors)
    itinerary = solve(request)
    target = target_hours_for(request.profile, aggressiveness=body.aggressiveness)
    return [
        explanation.terms
        for explanation in explain_plan(itinerary, request.profile, target_hours=target)
    ]


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
