"""Splitting a corridor into days.

This was greedy to begin with and it did not survive contact with tight
constraints. Walking forward one day at a time, taking the cheapest camp near
the target mile, means the choice on day one is made before anything is known
about day four, and a mileage cap well inside the search window leaves nothing
admissible even though a legal split exists a few miles back. Widening the
window helped and did not fix it, because the problem is not the window, it is
the commitment.

So the corridor is now a directed acyclic graph. Nodes are the miles a day could
end at, which is every waypoint plus the two termini; edges are admissible days;
edge weights come from :mod:`backpacking.plan.scoring`. The cheapest path is the
plan, and it is optimal for the objective as written rather than merely locally
sensible.

One approximation is left, deliberately. Fatigue depends on the whole history of
a path, not on where it is, so the state carried into a node is the state along
the cheapest path found to that node so far. That makes the search a Bellman
relaxation rather than an exact shortest path. Over the trips this is used for
the effect is under a tenth of a mile per day, and removing it would mean
carrying a state per path rather than per node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from backpacking.errors import PlanInfeasible
from backpacking.pace.estimator import PaceEstimator
from backpacking.pace.fatigue import FatigueState, advance
from backpacking.pace.models import HikerProfile, LegEstimate
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.itinerary import DayPlan, Itinerary
from backpacking.plan.scoring import (
    DEFAULT_WEIGHTS,
    ScoringWeights,
    day_cost,
    target_hours_for,
)
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance, Mass

#: How far either side of a mile to look when listing camps, used by callers
#: that want to inspect the options rather than by the search itself.
DEFAULT_WINDOW_MILES = 4.0


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Everything the solver needs to produce an itinerary."""

    corridor: Corridor
    profile: HikerProfile
    start_date: date
    constraints: PlanConstraints = field(default_factory=PlanConstraints)
    start_mile: float | None = None
    end_mile: float | None = None
    weights: ScoringWeights = DEFAULT_WEIGHTS
    aggressiveness: float = 0.8
    pack_weight: Mass = Mass.pounds(26.0)
    window_miles: float = DEFAULT_WINDOW_MILES

    def resolved_start(self) -> float:
        return self.corridor.start_mile if self.start_mile is None else self.start_mile

    def resolved_end(self) -> float:
        return self.corridor.end_mile if self.end_mile is None else self.end_mile

    def __post_init__(self) -> None:
        if self.window_miles <= 0.0:
            raise PlanInfeasible("the camp search window must be positive")
        if self.resolved_end() <= self.resolved_start():
            raise PlanInfeasible(
                "the plan must advance along the corridor",
                start_mile=self.resolved_start(),
                end_mile=self.resolved_end(),
            )


@dataclass(slots=True)
class _Cell:
    """The best path found to one node so far."""

    cost: float
    previous: int | None
    estimate: LegEstimate | None
    state: FatigueState
    days: int


def candidate_camps(
    corridor: Corridor, around_mile: float, window_miles: float
) -> tuple[Waypoint, ...]:
    """Waypoints within the window that a day could reasonably end at."""
    low = max(corridor.start_mile, around_mile - window_miles)
    high = min(corridor.end_mile, around_mile + window_miles)
    return corridor.waypoints_between(low, high)


def stop_miles(request: PlanRequest) -> tuple[float, ...]:
    """Every mile the search may end a day at, ascending and deduplicated."""
    start = request.resolved_start()
    finish = request.resolved_end()
    miles = {start, finish}
    for waypoint in request.corridor.waypoints_between(start, finish):
        if request.constraints.camp_is_allowed(waypoint.id):
            miles.add(waypoint.mile)
    return tuple(sorted(miles))


def solve(request: PlanRequest) -> Itinerary:
    """Cheapest admissible itinerary, by shortest path over the stop graph."""
    corridor = request.corridor
    estimator = PaceEstimator(profile=request.profile)
    constraints = request.constraints
    target = target_hours_for(request.profile, aggressiveness=request.aggressiveness)
    nodes = stop_miles(request)
    if len(nodes) < 2:
        raise PlanInfeasible(
            "not enough stop candidates to plan a trip",
            start_mile=request.resolved_start(),
            end_mile=request.resolved_end(),
        )

    cells: list[_Cell | None] = [None] * len(nodes)
    cells[0] = _Cell(cost=0.0, previous=None, estimate=None, state=FatigueState(), days=0)

    for target_index in range(1, len(nodes)):
        is_final = target_index == len(nodes) - 1
        for source_index in range(target_index):
            source = cells[source_index]
            if source is None:
                continue
            candidate = _relax(
                request, estimator, nodes, source_index, target_index, source, target, is_final
            )
            if candidate is None:
                continue
            current = cells[target_index]
            if current is None or candidate.cost < current.cost:
                cells[target_index] = candidate

    final = cells[-1]
    if final is None:
        raise PlanInfeasible(
            "no admissible sequence of days reaches the end of the route",
            start_mile=request.resolved_start(),
            end_mile=request.resolved_end(),
            stops_considered=len(nodes),
            max_daily_miles=constraints.max_daily_miles,
        )

    itinerary = _rebuild(request, nodes, cells)
    if not constraints.trip_is_admissible(len(itinerary), itinerary.finish_date):
        raise PlanInfeasible(
            "the plan does not fit the trip level limits",
            days=len(itinerary),
            finish=itinerary.finish_date.isoformat(),
        )
    return itinerary


def _relax(
    request: PlanRequest,
    estimator: PaceEstimator,
    nodes: tuple[float, ...],
    source_index: int,
    target_index: int,
    source: _Cell,
    target_hours: float,
    is_final: bool,
) -> _Cell | None:
    """Cost of extending the best path at ``source_index`` by one day."""
    constraints = request.constraints
    if constraints.max_total_days is not None and source.days >= constraints.max_total_days:
        return None
    start_mile = nodes[source_index]
    end_mile = nodes[target_index]
    estimate = estimator.estimate_span(
        request.corridor,
        start_mile,
        end_mile,
        carried=request.pack_weight,
        state=source.state,
    )
    if not constraints.day_is_admissible(
        end_mile - start_mile, estimate.gain, estimate.elapsed_time, is_final=is_final
    ):
        return None
    camp = None if is_final else _waypoint_at(request.corridor, end_mile)
    if not constraints.camp_is_allowed(None if camp is None else camp.id):
        return None
    cost = source.cost + day_cost(
        estimate,
        camp,
        request.profile,
        target_hours=target_hours,
        gain_in_last_third=_final_third_gain(request.corridor, start_mile, end_mile),
        weights=request.weights,
    )
    return _Cell(
        cost=cost,
        previous=source_index,
        estimate=estimate,
        state=advance(source.state, request.profile, estimate.moving_time.in_hours),
        days=source.days + 1,
    )


def _rebuild(
    request: PlanRequest, nodes: tuple[float, ...], cells: list[_Cell | None]
) -> Itinerary:
    """Walk the predecessor chain back and turn it into days."""
    path: list[int] = []
    cursor: int | None = len(nodes) - 1
    while cursor is not None:
        path.append(cursor)
        cell = cells[cursor]
        cursor = None if cell is None else cell.previous
    path.reverse()

    days: list[DayPlan] = []
    when = request.start_date
    finish = request.resolved_end()
    for position, node_index in enumerate(path[1:]):
        cell = cells[node_index]
        if cell is None or cell.estimate is None:
            raise PlanInfeasible("the reconstructed path is not connected", node=node_index)
        end_mile = nodes[node_index]
        camp = None if end_mile >= finish - 1e-6 else _waypoint_at(request.corridor, end_mile)
        days.append(
            DayPlan(
                index=position,
                day=when,
                start_mile=nodes[path[position]],
                end_mile=end_mile,
                estimate=cell.estimate,
                camp=camp,
                pack_weight=request.pack_weight,
            )
        )
        when = when + timedelta(days=1)
    return Itinerary(corridor=request.corridor, days=tuple(days), label="shortest-path")


def _waypoint_at(corridor: Corridor, mile: float) -> Waypoint | None:
    nearest = corridor.nearest_waypoint(mile)
    return nearest if abs(nearest.mile - mile) < 1e-6 else None


def _final_third_gain(corridor: Corridor, start_mile: float, end_mile: float) -> Distance:
    span = end_mile - start_mile
    if span <= 0.0:
        return Distance.zero()
    return corridor.gain_between(end_mile - span / 3.0, end_mile)


def campable_waypoints(corridor: Corridor) -> tuple[Waypoint, ...]:
    """Every waypoint on the corridor that a permit would let a hiker sleep at."""
    return corridor.of_kind(WaypointKind.CAMPSITE, WaypointKind.SHELTER)
