"""Splitting a corridor into days.

The approach is greedy and local: from the current mile, work out how far the
hiker gets in a target day, then look at the campsites within a window either
side of that point and take the cheapest one. Repeat until the terminus.

This is fast and it is usually reasonable, but it has the failure mode every
greedy scheduler has. A camp that looks cheap now can leave a 26 mile day and a
5 mile day to divide the remaining stretch, and by the time that shows up the
choice has already been made. The window is a partial mitigation, not a fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from backpacking.errors import PlanInfeasible
from backpacking.pace.estimator import PaceEstimator
from backpacking.pace.fatigue import FatigueState, advance
from backpacking.pace.models import HikerProfile
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
from backpacking.units import Distance, Duration, Mass

#: How far either side of the target mile to look for a camp.
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


def candidate_camps(
    corridor: Corridor, around_mile: float, window_miles: float
) -> tuple[Waypoint, ...]:
    """Waypoints within the window that a day could reasonably end at."""
    low = max(corridor.start_mile, around_mile - window_miles)
    high = min(corridor.end_mile, around_mile + window_miles)
    return corridor.waypoints_between(low, high)


def solve(request: PlanRequest) -> Itinerary:
    """Build an itinerary greedily, one day at a time."""
    corridor = request.corridor
    estimator = PaceEstimator(profile=request.profile)
    constraints = request.constraints
    target = target_hours_for(request.profile, aggressiveness=request.aggressiveness)

    start = request.resolved_start()
    finish = request.resolved_end()
    cursor = start
    when = request.start_date
    state = FatigueState()
    days: list[DayPlan] = []

    while cursor < finish - 1e-6:
        if len(days) >= constraints.max_total_days if constraints.max_total_days else False:
            raise PlanInfeasible(
                "ran out of allowed days before reaching the end",
                days_used=len(days),
                mile_reached=cursor,
            )
        reach = estimator.reachable_mile(
            corridor, cursor, Duration.hours(target), carried=request.pack_weight, state=state
        )
        chosen, estimate = _pick_camp(
            request, estimator, cursor, reach, finish, state, target
        )
        if chosen is None:
            raise PlanInfeasible(
                "no admissible camp within the search window",
                mile=cursor,
                target_mile=reach,
                window_miles=request.window_miles,
            )
        camp_waypoint = (
            None if chosen >= finish - 1e-6 else _waypoint_at(corridor, chosen)
        )
        days.append(
            DayPlan(
                index=len(days),
                day=when,
                start_mile=cursor,
                end_mile=chosen,
                estimate=estimate,
                camp=camp_waypoint,
                pack_weight=request.pack_weight,
            )
        )
        state = advance(state, request.profile, estimate.moving_time.in_hours)
        cursor = chosen
        when = when + timedelta(days=1)

    if not days:
        raise PlanInfeasible("the plan produced no days", start_mile=start, end_mile=finish)
    itinerary = Itinerary(corridor=corridor, days=tuple(days), label="greedy")
    if not constraints.trip_is_admissible(len(days), itinerary.finish_date):
        raise PlanInfeasible(
            "the plan does not fit the trip level limits",
            days=len(days),
            finish=itinerary.finish_date.isoformat(),
        )
    return itinerary


def _pick_camp(
    request: PlanRequest,
    estimator: PaceEstimator,
    cursor: float,
    reach: float,
    finish: float,
    state: FatigueState,
    target: float,
):
    """Cheapest admissible camp near ``reach``, and the estimate to get there."""
    corridor = request.corridor
    constraints = request.constraints
    options: list[float] = [
        waypoint.mile
        for waypoint in candidate_camps(corridor, reach, request.window_miles)
        if cursor < waypoint.mile <= finish
    ]
    if finish - reach <= request.window_miles:
        options.append(finish)
    if not options:
        options = [min(reach, finish)]

    best_mile: float | None = None
    best_estimate = None
    best_cost = float("inf")
    for mile in sorted(set(options)):
        estimate = estimator.estimate_span(
            corridor, cursor, mile, carried=request.pack_weight, state=state
        )
        is_final = mile >= finish - 1e-6
        if not constraints.day_is_admissible(
            mile - cursor, estimate.gain, estimate.elapsed_time, is_final=is_final
        ):
            continue
        camp = None if is_final else _waypoint_at(corridor, mile)
        if not constraints.camp_is_allowed(None if camp is None else camp.id):
            continue
        cost = day_cost(
            estimate,
            camp,
            request.profile,
            target_hours=target,
            gain_in_last_third=_final_third_gain(corridor, cursor, mile),
            weights=request.weights,
        )
        if cost < best_cost:
            best_cost = cost
            best_mile = mile
            best_estimate = estimate
    return best_mile, best_estimate


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
