"""The planning use cases, in one place.

The HTTP route and the CLI command were doing the same six things in the same
order: load the corridor, build a profile, build the constraints, assemble a
request, solve, and then load whatever else the answer needed. They had drifted
apart twice, and the second time the CLI was applying a constraint the API was
not.

So the sequence lives here. The route and the command are now transport: they
translate their own input into these arguments and their own output out of the
result, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.permits.validate import PermitReport, validate_nights
from backpacking.permits.zones import ZoneMap
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.explain import explain_plan
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.scoring import DEFAULT_WEIGHTS, ScoringWeights, target_hours_for
from backpacking.plan.solver import PlanRequest, solve
from backpacking.resupply.towns import TownIndex
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance, Duration, Mass
from backpacking.water.sources import WaterTable


@dataclass(frozen=True, slots=True)
class TrailBundle:
    """Everything stored about one corridor, loaded together."""

    slug: str
    corridor_id: int
    corridor: Corridor
    water: WaterTable
    zones: ZoneMap
    towns: TownIndex

    def __repr__(self) -> str:
        return (
            f"TrailBundle({self.slug!r}, {len(self.corridor)} waypoints, "
            f"{len(self.water)} sources, {len(self.zones)} zones)"
        )


@dataclass(frozen=True, slots=True)
class HikerSpec:
    """A hiker as the outside world describes one, in plain numbers."""

    name: str = "default"
    flat_pace_mph: float = 3.0
    max_moving_hours: float = 9.0
    max_daily_gain_ft: float = 6000.0
    break_fraction: float = 0.18
    pack_weight_lb: float = 26.0
    night_hiking: bool = False

    def to_profile(self) -> HikerProfile:
        return HikerProfile(
            name=self.name,
            flat_pace_mph=self.flat_pace_mph,
            max_moving_hours=self.max_moving_hours,
            max_daily_gain_ft=self.max_daily_gain_ft,
            break_fraction=self.break_fraction,
            reference_load=Mass.pounds(self.pack_weight_lb),
            night_hiking=self.night_hiking,
        )


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    """Hard limits as the outside world describes them."""

    max_daily_miles: float = 32.0
    min_daily_miles: float = 4.0
    max_daily_gain_ft: float = 6000.0
    max_daily_hours: float = 12.0
    camps_must_be_named: bool = False
    max_total_days: int | None = None
    forbidden_camps: tuple[str, ...] = ()

    def to_constraints(self) -> PlanConstraints:
        return PlanConstraints(
            max_daily_miles=self.max_daily_miles,
            min_daily_miles=self.min_daily_miles,
            max_daily_gain=Distance.feet(self.max_daily_gain_ft),
            max_daily_elapsed=Duration.hours(self.max_daily_hours),
            camps_must_be_named=self.camps_must_be_named,
            max_total_days=self.max_total_days,
            forbidden_camps=frozenset(self.forbidden_camps),
        )


class PlanningService:
    """Loading, solving and checking, over one database session."""

    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def load_bundle(self, slug: str) -> TrailBundle:
        """Everything stored about a corridor, in one round trip each."""
        corridors = CorridorRepository(self.session)
        corridor_id = corridors.corridor_id(slug)
        return TrailBundle(
            slug=slug,
            corridor_id=corridor_id,
            corridor=corridors.load(slug),
            water=WaterRepository(self.session).load(corridor_id),
            zones=PermitRepository(self.session).load(corridor_id),
            towns=ResupplyRepository(self.session).load(corridor_id),
        )

    def build_request(
        self,
        slug: str,
        start_date: date,
        *,
        hiker: HikerSpec | None = None,
        constraints: ConstraintSpec | None = None,
        start_mile: float | None = None,
        end_mile: float | None = None,
        aggressiveness: float = 0.8,
        weights: ScoringWeights = DEFAULT_WEIGHTS,
    ) -> PlanRequest:
        """Assemble a solver request from the stored corridor and plain inputs."""
        spec = hiker or HikerSpec()
        limits = constraints or ConstraintSpec()
        return PlanRequest(
            corridor=CorridorRepository(self.session).load(slug),
            profile=spec.to_profile(),
            start_date=start_date,
            constraints=limits.to_constraints(),
            start_mile=start_mile,
            end_mile=end_mile,
            weights=weights,
            aggressiveness=aggressiveness,
            pack_weight=Mass.pounds(spec.pack_weight_lb),
        )

    def build_plan(self, request: PlanRequest) -> Itinerary:
        return solve(request)

    def plan(
        self,
        slug: str,
        start_date: date,
        *,
        hiker: HikerSpec | None = None,
        constraints: ConstraintSpec | None = None,
        start_mile: float | None = None,
        end_mile: float | None = None,
        aggressiveness: float = 0.8,
    ) -> Itinerary:
        """Load, assemble and solve in one call."""
        return self.build_plan(
            self.build_request(
                slug,
                start_date,
                hiker=hiker,
                constraints=constraints,
                start_mile=start_mile,
                end_mile=end_mile,
                aggressiveness=aggressiveness,
            )
        )

    def save_plan(self, itinerary: Itinerary, slug: str, hiker_name: str) -> int:
        corridor_id = CorridorRepository(self.session).corridor_id(slug)
        return PlanRepository(self.session).save(itinerary, corridor_id, hiker_name)

    def load_plan(self, plan_id: int, slug: str) -> Itinerary:
        corridor = CorridorRepository(self.session).load(slug)
        return PlanRepository(self.session).load(plan_id, corridor)

    def check_permits(
        self,
        itinerary: Itinerary,
        slug: str,
        *,
        has_canister: bool = False,
        wants_fire: bool = False,
    ) -> PermitReport:
        corridor_id = CorridorRepository(self.session).corridor_id(slug)
        zones = PermitRepository(self.session).load(corridor_id)
        nights = itinerary.camp_nights(has_canister=has_canister, wants_fire=wants_fire)
        return validate_nights(nights, zones)

    def explain(
        self, itinerary: Itinerary, profile: HikerProfile, *, aggressiveness: float = 0.8
    ) -> list[dict[str, float]]:
        target = target_hours_for(profile, aggressiveness=aggressiveness)
        return [
            explanation.terms
            for explanation in explain_plan(itinerary, profile, target_hours=target)
        ]

    def plan_and_save(
        self,
        slug: str,
        start_date: date,
        *,
        hiker: HikerSpec | None = None,
        constraints: ConstraintSpec | None = None,
        aggressiveness: float = 0.8,
    ) -> tuple[int, Itinerary]:
        """Solve and store, returning both so a caller does not reload."""
        spec = hiker or HikerSpec()
        itinerary = self.plan(
            slug,
            start_date,
            hiker=spec,
            constraints=constraints,
            aggressiveness=aggressiveness,
        )
        if not itinerary.covers_whole_corridor() and itinerary.total_distance.in_miles <= 0.0:
            raise PlanInfeasible("the solved plan covers no ground", corridor=slug)
        return self.save_plan(itinerary, slug, spec.name), itinerary
