"""Resupply stops and strategy."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backpacking.api.deps import get_corridors, get_resupply
from backpacking.pace.models import HikerProfile
from backpacking.resupply.strategy import plan_resupply, town_time
from backpacking.storage.repository import CorridorRepository, ResupplyRepository
from backpacking.units import Energy

router = APIRouter(prefix="/resupply", tags=["resupply"])


@router.get("/{slug}", response_model=list[dict[str, object]])
def list_points(
    slug: str,
    full_only: bool = Query(default=False),
    corridors: CorridorRepository = Depends(get_corridors),
    resupply: ResupplyRepository = Depends(get_resupply),
) -> list[dict[str, object]]:
    """Resupply points on a corridor."""
    index = resupply.load(corridors.corridor_id(slug))
    points = index.full_resupplies() if full_only else index.points
    return [
        {
            "id": point.id,
            "name": point.name,
            "mile": point.mile,
            "groceries": point.groceries.label,
            "supports_full_resupply": point.supports_full_resupply,
            "access_hours": round(point.access_cost().in_hours, 2),
            "has_post_office": point.has_post_office,
        }
        for point in points
    ]


@router.get("/{slug}/strategy", response_model=dict[str, object])
def strategy(
    slug: str,
    daily_miles: float = Query(default=18.0, gt=0.0, le=60.0),
    max_carry_days: float = Query(default=7.0, gt=0.0, le=30.0),
    burn_kcal_per_day: float = Query(default=2900.0, gt=0.0, le=10000.0),
    flat_pace_mph: float = Query(default=3.0, gt=0.0, le=8.0),
    corridors: CorridorRepository = Depends(get_corridors),
    resupply: ResupplyRepository = Depends(get_resupply),
) -> dict[str, object]:
    """Cheapest admissible set of stops for the corridor."""
    corridor = corridors.load(slug)
    index = resupply.load(corridors.corridor_id(slug))
    profile = HikerProfile(flat_pace_mph=flat_pace_mph)
    plan = plan_resupply(
        index,
        corridor.start_mile,
        corridor.end_mile,
        profile,
        daily_miles=daily_miles,
        burned_per_day=Energy.kilocalories(burn_kcal_per_day),
        max_carry_days=max_carry_days,
    )
    return {
        "stops": [stop.id for stop in plan.stops],
        "town_hours": round(town_time(plan).in_hours, 2),
        "longest_carry_days": round(plan.longest_carry.days, 2),
        "heaviest_food_lb": round(plan.heaviest_food_bag.in_pounds, 2),
        "carries": [
            {
                "start_mile": round(carry.start_mile, 2),
                "end_mile": round(carry.end_mile, 2),
                "days": round(carry.days, 2),
                "food_lb": round(carry.food_mass.in_pounds, 2),
            }
            for carry in plan.carries
        ],
    }


@router.get("/{slug}/gap", response_model=dict[str, float])
def longest_gap(
    slug: str,
    full_only: bool = Query(default=True),
    corridors: CorridorRepository = Depends(get_corridors),
    resupply: ResupplyRepository = Depends(get_resupply),
) -> dict[str, float]:
    """Longest stretch between usable stops, which sizes the biggest carry."""
    index = resupply.load(corridors.corridor_id(slug))
    return {"longest_gap_miles": round(index.longest_gap(full_only=full_only), 2)}
