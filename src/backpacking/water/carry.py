"""Dry stretches, and how much water has to leave the last source.

The planning question is never "how much water do I drink a day". It is "how
much do I have to be carrying when I walk away from this creek, given what is
ahead of me and how hot it is". Those are different numbers, and the second one
is what fills a pack.

Consumption is driven by the metabolic rate rather than by distance, because two
hours of climbing in the sun costs far more water than two hours of flat walking
in the shade, and a plan that averages them will run a hiker dry on the climb.
"""

from __future__ import annotations

from dataclasses import dataclass

from backpacking.errors import WaterCarryError
from backpacking.pace.estimator import PaceEstimator
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance, Duration, Volume
from backpacking.water.sources import WaterSource, WaterTable

#: Litres per hour of moving time at a moderate effort in mild conditions.
BASE_CONSUMPTION_LPH = 0.45

#: Multiplier on consumption per degree Celsius above a mild day.
TEMPERATURE_SENSITIVITY = 0.035
MILD_TEMPERATURE_C = 15.0

#: Climbing costs more water than the same time on the flat.
CLIMB_SURCHARGE_PER_1000FT = 0.20

#: Water left in the bottles on arrival. Running a plan to exactly zero is not
#: planning, it is arriving thirsty and hoping.
DEFAULT_RESERVE_LITERS = 0.4

#: Litres needed to cook and rehydrate an evening meal plus breakfast.
CAMP_WATER_LITERS = 1.5


@dataclass(frozen=True, slots=True)
class DryStretch:
    """A run of corridor with no usable water in it."""

    start_mile: float
    end_mile: float
    start_source: WaterSource | None
    end_source: WaterSource | None

    @property
    def length(self) -> Distance:
        return Distance.miles(self.end_mile - self.start_mile)

    @property
    def is_open_ended(self) -> bool:
        """True when the stretch runs off one end of the corridor."""
        return self.start_source is None or self.end_source is None

    def __repr__(self) -> str:
        return f"DryStretch({self.start_mile:.1f}-{self.end_mile:.1f} mi, {self.length.in_miles:.1f} mi)"


@dataclass(frozen=True, slots=True)
class CarryPlan:
    """What to leave a source carrying, and whether that is even possible."""

    stretch: DryStretch
    required: Volume
    capacity: Volume
    moving_time: Duration
    includes_camp: bool

    @property
    def is_feasible(self) -> bool:
        return self.required <= self.capacity

    @property
    def headroom(self) -> Volume:
        return self.capacity - self.required

    def __repr__(self) -> str:
        verdict = "ok" if self.is_feasible else "short"
        return (
            f"CarryPlan({self.stretch.length.in_miles:.1f} mi, "
            f"{self.required.in_liters:.1f} L, {verdict})"
        )


def find_dry_stretches(
    corridor: Corridor,
    table: WaterTable,
    month: int,
    *,
    threshold: float = 0.6,
    min_length_miles: float = 8.0,
) -> tuple[DryStretch, ...]:
    """Every gap between usable sources longer than ``min_length_miles``."""
    if min_length_miles <= 0.0:
        raise WaterCarryError(
            "minimum dry stretch length must be positive", min_length_miles=min_length_miles
        )
    usable = table.between(corridor.start_mile, corridor.end_mile, month, threshold)
    boundaries: list[tuple[float, WaterSource | None]] = [(corridor.start_mile, None)]
    boundaries.extend((source.mile, source) for source in usable)
    boundaries.append((corridor.end_mile, None))
    found: list[DryStretch] = []
    for (start_mile, start_source), (end_mile, end_source) in zip(
        boundaries, boundaries[1:], strict=False
    ):
        if end_mile - start_mile >= min_length_miles:
            found.append(
                DryStretch(
                    start_mile=start_mile,
                    end_mile=end_mile,
                    start_source=start_source,
                    end_source=end_source,
                )
            )
    return tuple(found)


def consumption_rate(temperature_c: float, gain_per_hour_ft: float = 0.0) -> float:
    """Litres per hour of moving time under these conditions."""
    if temperature_c < -60.0 or temperature_c > 60.0:
        raise WaterCarryError("temperature is outside any plausible range", temperature_c=temperature_c)
    heat = 1.0 + TEMPERATURE_SENSITIVITY * max(0.0, temperature_c - MILD_TEMPERATURE_C)
    climb = CLIMB_SURCHARGE_PER_1000FT * max(0.0, gain_per_hour_ft) / 1000.0
    return BASE_CONSUMPTION_LPH * heat + climb


def water_needed(
    corridor: Corridor,
    estimator: PaceEstimator,
    start_mile: float,
    end_mile: float,
    *,
    temperature_c: float = 20.0,
    reserve_liters: float = DEFAULT_RESERVE_LITERS,
    camping_en_route: bool = False,
) -> Volume:
    """Water to leave ``start_mile`` with, to reach ``end_mile`` with a reserve."""
    if end_mile < start_mile:
        raise WaterCarryError(
            "stretch must advance", start_mile=start_mile, end_mile=end_mile
        )
    if reserve_liters < 0.0:
        raise WaterCarryError("reserve must not be negative", reserve_liters=reserve_liters)
    leg = estimator.estimate_span(corridor, start_mile, end_mile)
    hours = leg.moving_time.in_hours
    gain_per_hour = 0.0 if hours <= 0.0 else leg.gain.in_feet / hours
    litres = consumption_rate(temperature_c, gain_per_hour) * hours + reserve_liters
    if camping_en_route:
        litres += CAMP_WATER_LITERS
    return Volume.liters(litres)


def plan_carry(
    corridor: Corridor,
    estimator: PaceEstimator,
    stretch: DryStretch,
    capacity: Volume,
    *,
    temperature_c: float = 20.0,
    reserve_liters: float = DEFAULT_RESERVE_LITERS,
    camping_en_route: bool = False,
) -> CarryPlan:
    """Work out what one dry stretch demands and whether the bottles cover it."""
    required = water_needed(
        corridor,
        estimator,
        stretch.start_mile,
        stretch.end_mile,
        temperature_c=temperature_c,
        reserve_liters=reserve_liters,
        camping_en_route=camping_en_route,
    )
    leg = estimator.estimate_span(corridor, stretch.start_mile, stretch.end_mile)
    return CarryPlan(
        stretch=stretch,
        required=required,
        capacity=capacity,
        moving_time=leg.moving_time,
        includes_camp=camping_en_route,
    )


def infeasible_carries(plans: list[CarryPlan]) -> list[CarryPlan]:
    """The carries that do not fit in the bottles, worst first."""
    short = [plan for plan in plans if not plan.is_feasible]
    short.sort(key=lambda plan: plan.headroom.in_liters)
    return short


def furthest_reachable(
    corridor: Corridor,
    estimator: PaceEstimator,
    start_mile: float,
    capacity: Volume,
    *,
    temperature_c: float = 20.0,
    reserve_liters: float = DEFAULT_RESERVE_LITERS,
    tolerance_miles: float = 0.05,
) -> float:
    """Furthest mile reachable on one fill, by bisection on the requirement."""
    low = start_mile
    high = corridor.end_mile
    whole = water_needed(
        corridor,
        estimator,
        start_mile,
        high,
        temperature_c=temperature_c,
        reserve_liters=reserve_liters,
    )
    if whole <= capacity:
        return high
    while high - low > tolerance_miles:
        middle = (low + high) / 2.0
        needed = water_needed(
            corridor,
            estimator,
            start_mile,
            middle,
            temperature_c=temperature_c,
            reserve_liters=reserve_liters,
        )
        if needed > capacity:
            high = middle
        else:
            low = middle
    return low
