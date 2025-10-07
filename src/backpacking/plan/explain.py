"""Rendering a plan so a person can argue with it.

A planner will not trust an itinerary they cannot interrogate, and the useful
question is never "what is the plan" but "why is day three so short". So this
module renders the objective alongside the schedule: what each day cost, which
term dominated, and what the runner up was.

Output is plain text laid out in columns rather than a table library, because
this ends up printed, pasted into a message, and read on a phone in a tent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.permits.validate import PermitReport
from backpacking.plan.itinerary import DayPlan, Itinerary
from backpacking.plan.scoring import DEFAULT_WEIGHTS, ScoringWeights, describe_cost
from backpacking.units import Distance


@dataclass(frozen=True, slots=True)
class DayExplanation:
    """One day, with the cost terms that produced it."""

    day: DayPlan
    terms: dict[str, float]

    @property
    def total(self) -> float:
        return sum(self.terms.values())

    @property
    def dominant_term(self) -> str:
        return max(self.terms, key=lambda key: self.terms[key])

    def __repr__(self) -> str:
        return f"DayExplanation(day {self.day.index}, {self.dominant_term} dominates)"


def explain_day(
    day: DayPlan,
    profile: HikerProfile,
    *,
    target_hours: float,
    gain_in_last_third: Distance = Distance.zero(),
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> DayExplanation:
    """Break one day's cost into its terms."""
    return DayExplanation(
        day=day,
        terms=describe_cost(
            day.estimate,
            day.camp,
            profile,
            target_hours=target_hours,
            gain_in_last_third=gain_in_last_third,
            weights=weights,
        ),
    )


def explain_plan(
    itinerary: Itinerary,
    profile: HikerProfile,
    *,
    target_hours: float,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> tuple[DayExplanation, ...]:
    """Break every day's cost into its terms."""
    return tuple(
        explain_day(day, profile, target_hours=target_hours, weights=weights)
        for day in itinerary
    )


def render_schedule(itinerary: Itinerary) -> str:
    """The itinerary as a fixed width day by day table."""
    lines = [
        f"{itinerary.corridor.name} - {len(itinerary)} days, "
        f"{itinerary.total_distance.in_miles:.1f} mi, "
        f"{itinerary.total_gain.in_feet:.0f} ft of climb",
        "",
        f"{'day':>3}  {'date':<10}  {'miles':>6}  {'gain':>6}  {'time':>5}  camp",
        f"{'':->3}  {'':-<10}  {'':->6}  {'':->6}  {'':->5}  {'':-<24}",
    ]
    for day in itinerary:
        if day.is_zero:
            lines.append(
                f"{day.index + 1:>3}  {day.day.isoformat():<10}  "
                f"{'zero':>6}  {'':>6}  {'':>5}  {day.camp_id or ''}"
            )
            continue
        lines.append(
            f"{day.index + 1:>3}  {day.day.isoformat():<10}  "
            f"{day.miles:>6.1f}  {day.gain.in_feet:>6.0f}  "
            f"{day.elapsed.as_clock():>5}  {day.camp_id or 'wherever you get to'}"
        )
    return "\n".join(lines)


def render_costs(explanations: Sequence[DayExplanation]) -> str:
    """The objective, day by day, so a surprising split can be traced."""
    if not explanations:
        raise PlanInfeasible("cannot render costs for an empty plan")
    columns = list(explanations[0].terms)
    header = f"{'day':>3}  " + "  ".join(f"{name:>11}" for name in columns) + f"  {'total':>7}"
    lines = [header, "-" * len(header)]
    for explanation in explanations:
        cells = "  ".join(f"{explanation.terms[name]:>11.2f}" for name in columns)
        lines.append(f"{explanation.day.index + 1:>3}  {cells}  {explanation.total:>7.2f}")
    grand = sum(explanation.total for explanation in explanations)
    lines.append(f"{'':>3}  " + "  ".join(f"{'':>11}" for _ in columns) + f"  {grand:>7.2f}")
    return "\n".join(lines)


def render_permit_report(report: PermitReport) -> str:
    """The permit findings, grouped so the blocking ones come first."""
    lines = [report.summary()]
    if report.violations:
        lines.append("")
        lines.append("blocking:")
        for finding in report.violations:
            when = "" if finding.night is None else f"{finding.night.isoformat()}  "
            lines.append(f"  {when}{finding.message}")
    if report.advisories:
        lines.append("")
        lines.append("worth knowing:")
        for finding in report.advisories:
            when = "" if finding.night is None else f"{finding.night.isoformat()}  "
            lines.append(f"  {when}{finding.message}")
    return "\n".join(lines)


def render_summary(itinerary: Itinerary, profile: HikerProfile) -> str:
    """The two paragraph version, for the top of a report."""
    longest = itinerary.longest_day
    climb = itinerary.biggest_climb
    return "\n".join(
        [
            f"{len(itinerary)} days from mile {itinerary.start_mile:.1f} "
            f"to mile {itinerary.end_mile:.1f}, starting {itinerary.start_date.isoformat()} "
            f"and finishing {itinerary.finish_date.isoformat()}.",
            f"Averages {itinerary.average_daily_miles:.1f} miles a day for "
            f"{profile.name}, who walks {profile.flat_pace_mph:.1f} mph on the flat.",
            f"The longest day is day {longest.index + 1} at {longest.miles:.1f} miles. "
            f"The biggest climb is day {climb.index + 1} at "
            f"{climb.gain.in_feet:.0f} feet.",
        ]
    )


def render_full_report(
    itinerary: Itinerary,
    profile: HikerProfile,
    *,
    target_hours: float,
    permit_report: PermitReport | None = None,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> str:
    """Everything, in the order a planner reads it."""
    sections = [
        render_summary(itinerary, profile),
        "",
        render_schedule(itinerary),
        "",
        render_costs(explain_plan(itinerary, profile, target_hours=target_hours, weights=weights)),
    ]
    if permit_report is not None:
        sections.extend(["", render_permit_report(permit_report)])
    return "\n".join(sections)
