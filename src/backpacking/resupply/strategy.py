"""Choosing which resupply stops to make.

This is a shortest path problem, not a greedy one. A stop that looks cheap in
isolation can force an eight day carry on the leg after it, and a greedy walk
down the corridor will take it every time. So the corridor is turned into a
directed graph whose nodes are the possible stops and whose edges are the carries
between them, each edge weighted by what that carry actually costs, and the
answer is the cheapest path from the start to the finish.

The weights are deliberately not just miles. A carry costs the food weight it
forces, the stop at its far end costs time off trail, and both scale differently,
so the objective has to hold them in the same units. Everything is converted to
hours: pack weight becomes hours through the pace penalty, town time is already
hours.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from backpacking.errors import ResupplyInfeasible
from backpacking.food.rations import GOOD_DENSITY, plan_rations
from backpacking.pace.models import HikerProfile
from backpacking.resupply.towns import ResupplyPoint, TownIndex
from backpacking.units import Duration, Energy, Mass

#: Hours a hiker loses to a town stop beyond the travel time to reach it.
DEFAULT_TOWN_OVERHEAD_HOURS = 3.0

#: Carrying more than this many days of food is possible and miserable.
DEFAULT_MAX_CARRY_DAYS = 7.0


@dataclass(frozen=True, slots=True)
class Carry:
    """One leg between two resupplies."""

    start_mile: float
    end_mile: float
    start_point: ResupplyPoint | None
    end_point: ResupplyPoint | None
    days: float
    food_mass: Mass

    @property
    def miles(self) -> float:
        return self.end_mile - self.start_mile

    def __repr__(self) -> str:
        return (
            f"Carry({self.start_mile:.1f}-{self.end_mile:.1f} mi, "
            f"{self.days:.1f} days, {self.food_mass.in_pounds:.1f} lb)"
        )


@dataclass(frozen=True, slots=True)
class ResupplyStrategy:
    """The chosen stops, the carries between them, and what it cost."""

    stops: tuple[ResupplyPoint, ...]
    carries: tuple[Carry, ...]
    cost_hours: float

    @property
    def longest_carry(self) -> Carry:
        return max(self.carries, key=lambda carry: carry.days)

    @property
    def heaviest_food_bag(self) -> Mass:
        return max((carry.food_mass for carry in self.carries), key=lambda m: m.in_grams)

    def __repr__(self) -> str:
        return (
            f"ResupplyStrategy({len(self.stops)} stops, "
            f"longest {self.longest_carry.days:.1f} days)"
        )


def carry_between(
    start_mile: float,
    end_mile: float,
    daily_miles: float,
    burned_per_day: Energy,
    *,
    start_point: ResupplyPoint | None = None,
    end_point: ResupplyPoint | None = None,
    density_kcal_per_oz: float = GOOD_DENSITY,
) -> Carry:
    """Describe the carry between two miles at a given daily pace."""
    if daily_miles <= 0.0:
        raise ResupplyInfeasible("daily mileage must be positive", daily_miles=daily_miles)
    if end_mile < start_mile:
        raise ResupplyInfeasible("a carry must advance", start_mile=start_mile, end_mile=end_mile)
    days = max(0.5, (end_mile - start_mile) / daily_miles)
    rations = plan_rations(days, burned_per_day, density_kcal_per_oz=density_kcal_per_oz)
    return Carry(
        start_mile=start_mile,
        end_mile=end_mile,
        start_point=start_point,
        end_point=end_point,
        days=days,
        food_mass=rations.total_mass,
    )


def carry_cost_hours(carry: Carry, profile: HikerProfile) -> float:
    """What this carry costs, in hours, through the pack weight penalty.

    The penalty is applied to the mean food weight over the carry rather than the
    starting weight, because the bag empties as the days pass.
    """
    mean_food = carry.food_mass * 0.5
    excess_pounds = max(0.0, mean_food.in_pounds - 2.0)
    slowdown = profile.load_penalty_per_pound * excess_pounds
    walking_hours = carry.days * profile.max_moving_hours
    return walking_hours * slowdown


def stop_cost_hours(
    point: ResupplyPoint,
    *,
    overhead_hours: float = DEFAULT_TOWN_OVERHEAD_HOURS,
) -> float:
    """What stopping here costs, in hours off the trail."""
    if not point.supports_full_resupply:
        raise ResupplyInfeasible(
            "this stop cannot supply a whole carry", point=point.id, level=point.groceries.label
        )
    return point.access_cost().in_hours + overhead_hours


def plan_resupply(
    towns: TownIndex,
    start_mile: float,
    end_mile: float,
    profile: HikerProfile,
    *,
    daily_miles: float = 18.0,
    burned_per_day: Energy = Energy.kilocalories(2900.0),
    max_carry_days: float = DEFAULT_MAX_CARRY_DAYS,
    overhead_hours: float = DEFAULT_TOWN_OVERHEAD_HOURS,
    candidates: Sequence[ResupplyPoint] | None = None,
) -> ResupplyStrategy:
    """Cheapest admissible set of stops, by dynamic programming along the corridor."""
    if end_mile <= start_mile:
        raise ResupplyInfeasible("the route must advance", start_mile=start_mile, end_mile=end_mile)
    usable = [
        point
        for point in (candidates if candidates is not None else towns.full_resupplies())
        if start_mile < point.mile < end_mile and point.supports_full_resupply
    ]
    usable.sort(key=lambda point: point.mile)

    nodes: list[tuple[float, ResupplyPoint | None]] = [(start_mile, None)]
    nodes.extend((point.mile, point) for point in usable)
    nodes.append((end_mile, None))

    best: list[float] = [0.0] + [float("inf")] * (len(nodes) - 1)
    previous: list[int | None] = [None] * len(nodes)

    for target in range(1, len(nodes)):
        target_mile, target_point = nodes[target]
        for source in range(target):
            if best[source] == float("inf"):
                continue
            source_mile, source_point = nodes[source]
            carry = carry_between(
                source_mile,
                target_mile,
                daily_miles,
                burned_per_day,
                start_point=source_point,
                end_point=target_point,
            )
            if carry.days > max_carry_days:
                continue
            cost = best[source] + carry_cost_hours(carry, profile)
            if target_point is not None:
                cost += stop_cost_hours(target_point, overhead_hours=overhead_hours)
            if cost < best[target]:
                best[target] = cost
                previous[target] = source

    if best[-1] == float("inf"):
        raise ResupplyInfeasible(
            "no admissible set of stops covers this route",
            start_mile=start_mile,
            end_mile=end_mile,
            max_carry_days=max_carry_days,
            longest_unavoidable_gap=round(_longest_gap(nodes), 1),
        )

    path: list[int] = []
    cursor: int | None = len(nodes) - 1
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    path.reverse()

    carries: list[Carry] = []
    stops: list[ResupplyPoint] = []
    for source, target in itertools.pairwise(path):
        source_mile, source_point = nodes[source]
        target_mile, target_point = nodes[target]
        carries.append(
            carry_between(
                source_mile,
                target_mile,
                daily_miles,
                burned_per_day,
                start_point=source_point,
                end_point=target_point,
            )
        )
        if target_point is not None:
            stops.append(target_point)

    return ResupplyStrategy(stops=tuple(stops), carries=tuple(carries), cost_hours=best[-1])


def _longest_gap(nodes: Sequence[tuple[float, ResupplyPoint | None]]) -> float:
    return max(second[0] - first[0] for first, second in itertools.pairwise(nodes))


def town_time(strategy: ResupplyStrategy) -> Duration:
    """Total time the chosen stops take off the trail."""
    return Duration.hours(sum(stop_cost_hours(stop) for stop in strategy.stops))
