"""Comparing two itineraries.

A planner does not build one plan, they build six and then cannot remember what
changed between the third and the fifth. Two days apart, a pound heavier, one
fewer town stop: the differences are small individually and decisive together.

The comparison is deliberately asymmetric in its language. One plan is the
baseline and the other is the candidate, and every number is reported as what
the candidate does relative to the baseline, because that is the question.
"""

from __future__ import annotations

from dataclasses import dataclass

from backpacking.errors import PlanInfeasible
from backpacking.plan.itinerary import DayPlan, Itinerary
from backpacking.units import Distance, Duration


@dataclass(frozen=True, slots=True)
class DayDelta:
    """How one day differs between two plans."""

    index: int
    baseline: DayPlan | None
    candidate: DayPlan | None

    @property
    def is_added(self) -> bool:
        return self.baseline is None

    @property
    def is_removed(self) -> bool:
        return self.candidate is None

    @property
    def miles_delta(self) -> float:
        base = 0.0 if self.baseline is None else self.baseline.miles
        other = 0.0 if self.candidate is None else self.candidate.miles
        return other - base

    @property
    def camp_changed(self) -> bool:
        base = None if self.baseline is None else self.baseline.camp_id
        other = None if self.candidate is None else self.candidate.camp_id
        return base != other

    def __repr__(self) -> str:
        if self.is_added:
            return f"DayDelta({self.index}: added)"
        if self.is_removed:
            return f"DayDelta({self.index}: removed)"
        return f"DayDelta({self.index}: {self.miles_delta:+.1f} mi)"


@dataclass(frozen=True, slots=True)
class PlanDelta:
    """Everything that differs between a baseline plan and a candidate."""

    baseline_label: str
    candidate_label: str
    day_count_delta: int
    distance_delta: Distance
    gain_delta: Distance
    elapsed_delta: Duration
    average_daily_delta: float
    zero_day_delta: int
    days: tuple[DayDelta, ...]

    @property
    def is_shorter_trip(self) -> bool:
        return self.day_count_delta < 0

    @property
    def changed_days(self) -> tuple[DayDelta, ...]:
        return tuple(
            delta
            for delta in self.days
            if delta.is_added
            or delta.is_removed
            or delta.camp_changed
            or abs(delta.miles_delta) > 0.05
        )

    @property
    def is_identical(self) -> bool:
        return not self.changed_days and self.day_count_delta == 0

    def __repr__(self) -> str:
        return (
            f"PlanDelta({self.candidate_label!r} vs {self.baseline_label!r}, "
            f"{self.day_count_delta:+d} days, "
            f"{self.distance_delta.in_miles:+.1f} mi)"
        )


def compare_plans(baseline: Itinerary, candidate: Itinerary) -> PlanDelta:
    """Compare two plans over the same corridor."""
    if baseline.corridor.name != candidate.corridor.name:
        raise PlanInfeasible(
            "cannot compare plans over different corridors",
            baseline=baseline.corridor.name,
            candidate=candidate.corridor.name,
        )
    longest = max(len(baseline), len(candidate))
    days = tuple(
        DayDelta(
            index=index,
            baseline=baseline[index] if index < len(baseline) else None,
            candidate=candidate[index] if index < len(candidate) else None,
        )
        for index in range(longest)
    )
    return PlanDelta(
        baseline_label=baseline.label or "baseline",
        candidate_label=candidate.label or "candidate",
        day_count_delta=len(candidate) - len(baseline),
        distance_delta=candidate.total_distance - baseline.total_distance,
        gain_delta=candidate.total_gain - baseline.total_gain,
        elapsed_delta=candidate.total_elapsed - baseline.total_elapsed,
        average_daily_delta=candidate.average_daily_miles - baseline.average_daily_miles,
        zero_day_delta=len(candidate.zero_days) - len(baseline.zero_days),
        days=days,
    )


def render_delta(delta: PlanDelta) -> str:
    """The comparison as a person would read it out."""
    if delta.is_identical:
        return f"{delta.candidate_label} is the same plan as {delta.baseline_label}"
    lines = [
        f"{delta.candidate_label} against {delta.baseline_label}",
        "",
        f"  days           {delta.day_count_delta:+d}",
        f"  distance       {delta.distance_delta.in_miles:+.1f} mi",
        f"  climb          {delta.gain_delta.in_feet:+.0f} ft",
        f"  time on feet   {delta.elapsed_delta.in_hours:+.1f} h",
        f"  average day    {delta.average_daily_delta:+.1f} mi",
        f"  rest days      {delta.zero_day_delta:+d}",
        "",
    ]
    changed = delta.changed_days
    if not changed:
        lines.append("  no day changed by more than a rounding error")
        return "\n".join(lines)
    lines.append(f"  {len(changed)} day{'s' if len(changed) > 1 else ''} changed:")
    for day in changed:
        if day.is_added:
            lines.append(f"    day {day.index + 1} added")
        elif day.is_removed:
            lines.append(f"    day {day.index + 1} removed")
        else:
            note = " and camps elsewhere" if day.camp_changed else ""
            lines.append(f"    day {day.index + 1} {day.miles_delta:+.1f} mi{note}")
    return "\n".join(lines)


def rank_plans(plans: list[Itinerary], *, prefer_fewer_days: bool = True) -> list[Itinerary]:
    """Order candidate plans, best first, by the two things people care about.

    Fewer days first if that is what is wanted, then a gentler longest day,
    because two plans of the same length are separated by their worst day.
    """
    if not plans:
        raise PlanInfeasible("cannot rank an empty list of plans")
    direction = 1 if prefer_fewer_days else -1
    return sorted(
        plans,
        key=lambda plan: (direction * len(plan), plan.longest_day.miles),
    )
