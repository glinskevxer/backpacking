"""The objective the day splitter minimises.

Every term is in the same unit, an abstract cost, and every term is documented
with what it is trading against. That matters more than the exact weights: a
reader has to be able to see why a plan came out the way it did, and tell whether
a surprising choice is a bug or the objective working as written.

The terms, and what each one is for:

* **effort deviation** keeps days near the hiker's target rather than alternating
  a 26 and a 9
* **camp quality** prefers a real campsite over stopping wherever the arithmetic
  lands
* **late finish** penalises days that run past the hiker's hour budget
* **climb front loading** prefers doing a pass in the morning
* **day count** is a small flat cost per day, which is what stops the solver
  producing a comfortable but endless plan
"""

from __future__ import annotations

from dataclasses import dataclass

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile, LegEstimate
from backpacking.trail.models import Waypoint
from backpacking.units import Distance, Duration


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """How much each term counts. Tuning these changes the plan's character."""

    effort_deviation: float = 1.0
    unnamed_camp: float = 2.5
    exposed_camp: float = 1.5
    late_finish: float = 3.0
    steep_finish: float = 1.2
    per_day: float = 4.0
    resupply_bonus: float = -1.0

    def __post_init__(self) -> None:
        if self.per_day < 0.0:
            raise PlanInfeasible("the per day cost must not be negative")


DEFAULT_WEIGHTS = ScoringWeights()


def effort_cost(estimate: LegEstimate, profile: HikerProfile, target_hours: float) -> float:
    """Squared deviation from the target day, in hours.

    Squared rather than absolute so that one very long day costs more than two
    slightly long ones, which is how it feels.
    """
    if target_hours <= 0.0:
        raise PlanInfeasible("target hours must be positive", target_hours=target_hours)
    deviation = estimate.moving_time.in_hours - target_hours
    return deviation * deviation


def camp_cost(camp: Waypoint | None, weights: ScoringWeights = DEFAULT_WEIGHTS) -> float:
    """What ending the day here costs beyond the walking."""
    if camp is None:
        return weights.unnamed_camp
    cost = 0.0
    if not camp.can_camp:
        cost += weights.unnamed_camp
    if camp.has_tag("exposed"):
        cost += weights.exposed_camp
    if camp.kind.is_exit:
        cost += weights.resupply_bonus
    return cost


def late_finish_cost(
    estimate: LegEstimate, profile: HikerProfile, weights: ScoringWeights = DEFAULT_WEIGHTS
) -> float:
    """Cost of a day that runs past the hour budget, zero if it does not."""
    budget = profile.elapsed_from_moving(profile.daily_hour_budget)
    over = estimate.elapsed_time.in_hours - budget.in_hours
    return 0.0 if over <= 0.0 else weights.late_finish * over


def steep_finish_cost(
    gain_in_last_third: Distance, weights: ScoringWeights = DEFAULT_WEIGHTS
) -> float:
    """Cost of leaving a big climb for the end of the day."""
    thousands = max(0.0, gain_in_last_third.in_feet) / 1000.0
    return weights.steep_finish * thousands


def day_cost(
    estimate: LegEstimate,
    camp: Waypoint | None,
    profile: HikerProfile,
    *,
    target_hours: float,
    gain_in_last_third: Distance = Distance.zero(),
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> float:
    """Total cost of one candidate day."""
    return (
        weights.effort_deviation * effort_cost(estimate, profile, target_hours)
        + camp_cost(camp, weights)
        + late_finish_cost(estimate, profile, weights)
        + steep_finish_cost(gain_in_last_third, weights)
        + weights.per_day
    )


def target_hours_for(profile: HikerProfile, *, aggressiveness: float = 0.8) -> float:
    """The day length the plan aims at, as a fraction of the hour budget."""
    if not 0.0 < aggressiveness <= 1.0:
        raise PlanInfeasible("aggressiveness must fall in (0, 1]", aggressiveness=aggressiveness)
    return profile.daily_hour_budget.in_hours * aggressiveness


def describe_cost(
    estimate: LegEstimate,
    camp: Waypoint | None,
    profile: HikerProfile,
    *,
    target_hours: float,
    gain_in_last_third: Distance = Distance.zero(),
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> dict[str, float]:
    """The same figure broken into its terms, for explaining a plan."""
    return {
        "effort": round(weights.effort_deviation * effort_cost(estimate, profile, target_hours), 3),
        "camp": round(camp_cost(camp, weights), 3),
        "late_finish": round(late_finish_cost(estimate, profile, weights), 3),
        "steep_finish": round(steep_finish_cost(gain_in_last_third, weights), 3),
        "per_day": round(weights.per_day, 3),
    }


def total_plan_cost(day_costs: list[float]) -> float:
    if not day_costs:
        raise PlanInfeasible("cannot score an empty plan")
    return sum(day_costs)


def elapsed_budget(profile: HikerProfile) -> Duration:
    """The elapsed time a day is aiming to stay inside."""
    return profile.elapsed_from_moving(profile.daily_hour_budget)
