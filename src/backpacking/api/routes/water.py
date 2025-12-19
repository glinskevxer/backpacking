"""Water sources and dry stretch reporting."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backpacking.api.deps import get_corridors, get_water
from backpacking.api.schemas import WaterGapOut
from backpacking.pace.estimator import PaceEstimator
from backpacking.pace.models import HikerProfile
from backpacking.storage.repository import CorridorRepository, WaterRepository
from backpacking.units import Volume
from backpacking.water.carry import find_dry_stretches, plan_carry, water_needed

router = APIRouter(prefix="/water", tags=["water"])


@router.get("/{slug}", response_model=list[dict[str, object]])
def list_sources(
    slug: str,
    month: int = Query(default=7, ge=1, le=12),
    threshold: float = Query(default=0.6, ge=0.0, le=1.0),
    usable_only: bool = Query(default=False),
    corridors: CorridorRepository = Depends(get_corridors),
    water: WaterRepository = Depends(get_water),
) -> list[dict[str, object]]:
    """Water on a corridor, with this month's confidence for each source."""
    table = water.load(corridors.corridor_id(slug))
    sources = table.usable(month, threshold) if usable_only else table.sources
    return [
        {
            "id": source.id,
            "name": source.name,
            "mile": source.mile,
            "reliability": source.reliability.value,
            "confidence": round(source.confidence(month), 3),
            "usable": source.is_usable(month, threshold),
            "off_trail_miles": source.off_trail.in_miles,
        }
        for source in sources
    ]


@router.get("/{slug}/gaps", response_model=list[WaterGapOut])
def dry_stretches(
    slug: str,
    month: int = Query(default=7, ge=1, le=12),
    threshold: float = Query(default=0.6, ge=0.0, le=1.0),
    min_length_miles: float = Query(default=8.0, gt=0.0),
    capacity_liters: float = Query(default=4.0, gt=0.0, le=20.0),
    temperature_c: float = Query(default=20.0, ge=-40.0, le=55.0),
    flat_pace_mph: float = Query(default=3.0, gt=0.0, le=8.0),
    corridors: CorridorRepository = Depends(get_corridors),
    water: WaterRepository = Depends(get_water),
) -> list[WaterGapOut]:
    """Dry stretches, sized against a stated bottle capacity."""
    corridor = corridors.load(slug)
    table = water.load(corridors.corridor_id(slug))
    estimator = PaceEstimator(profile=HikerProfile(flat_pace_mph=flat_pace_mph))
    capacity = Volume.liters(capacity_liters)
    out: list[WaterGapOut] = []
    for stretch in find_dry_stretches(
        corridor, table, month, threshold=threshold, min_length_miles=min_length_miles
    ):
        carry = plan_carry(
            corridor, estimator, stretch, capacity, temperature_c=temperature_c
        )
        out.append(
            WaterGapOut(
                start_mile=round(stretch.start_mile, 2),
                end_mile=round(stretch.end_mile, 2),
                length_miles=round(stretch.length.in_miles, 2),
                start_source=None if stretch.start_source is None else stretch.start_source.id,
                end_source=None if stretch.end_source is None else stretch.end_source.id,
                liters_required=round(carry.required.in_liters, 2),
                fits_capacity=carry.is_feasible,
            )
        )
    return out


@router.get("/{slug}/needed", response_model=dict[str, float])
def needed_for_stretch(
    slug: str,
    from_mile: float = Query(..., ge=0.0),
    to_mile: float = Query(..., ge=0.0),
    temperature_c: float = Query(default=20.0, ge=-40.0, le=55.0),
    flat_pace_mph: float = Query(default=3.0, gt=0.0, le=8.0),
    camping_en_route: bool = Query(default=False),
    corridors: CorridorRepository = Depends(get_corridors),
) -> dict[str, float]:
    """Litres to leave one mile with, to reach another."""
    corridor = corridors.load(slug)
    estimator = PaceEstimator(profile=HikerProfile(flat_pace_mph=flat_pace_mph))
    needed = water_needed(
        corridor,
        estimator,
        from_mile,
        to_mile,
        temperature_c=temperature_c,
        camping_en_route=camping_en_route,
    )
    return {"liters": round(needed.in_liters, 2), "miles": round(to_mile - from_mile, 2)}
