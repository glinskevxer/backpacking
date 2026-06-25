"""Applying a snow year to a corridor and to an itinerary.

This is where the season model stops being a curve and starts being an answer:
which passes are still under snow on the day the plan reaches them, which fords
are running high, and whether the whole trip should simply start later.

The last question is the one that matters most and the one a planner is least
willing to ask themselves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from backpacking.plan.itinerary import DayPlan, Itinerary
from backpacking.season.snowpack import (
    Aspect,
    SeasonError,
    SnowYear,
    describe_hazard,
    ford_hazard,
    is_snowbound,
    melt_out_date,
    snow_line,
)
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance

#: Hazard at or above which a ford is called out rather than merely noted.
FORD_CONCERN_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class SnowFinding:
    """One place the season model has something to say about."""

    waypoint: Waypoint
    when: date
    kind: str
    severity: float
    message: str

    @property
    def is_serious(self) -> bool:
        return self.severity >= FORD_CONCERN_THRESHOLD

    def __repr__(self) -> str:
        return f"SnowFinding({self.waypoint.id} on {self.when.isoformat()}: {self.kind})"


def snowbound_waypoints(
    corridor: Corridor,
    snow_year: SnowYear,
    when: date,
    *,
    aspect: Aspect = Aspect.NORTH,
    kinds: Sequence[WaypointKind] = (WaypointKind.PASS, WaypointKind.SUMMIT),
) -> tuple[Waypoint, ...]:
    """High points still under continuous snow on a date.

    North aspect by default, because that is the side of a pass a north bound
    hiker descends and it is the side that holds snow.
    """
    wanted = set(kinds)
    return tuple(
        waypoint
        for waypoint in corridor
        if waypoint.kind in wanted and is_snowbound(snow_year, when, waypoint.elevation, aspect)
    )


def corridor_melt_out(
    corridor: Corridor,
    snow_year: SnowYear,
    *,
    aspect: Aspect = Aspect.NORTH,
    kinds: Sequence[WaypointKind] = (WaypointKind.PASS, WaypointKind.SUMMIT),
) -> dict[str, date]:
    """When each high point comes out from under the snow."""
    wanted = set(kinds)
    return {
        waypoint.id: melt_out_date(snow_year, waypoint.elevation, aspect)
        for waypoint in corridor
        if waypoint.kind in wanted
    }


def earliest_walkable_start(
    corridor: Corridor,
    snow_year: SnowYear,
    *,
    aspect: Aspect = Aspect.NORTH,
    margin_days: int = 0,
) -> date:
    """First date every high point on the corridor has melted out."""
    melt = corridor_melt_out(corridor, snow_year, aspect=aspect)
    if not melt:
        raise SeasonError("corridor has no passes or summits to melt out", corridor=corridor.name)
    return max(melt.values()) + timedelta(days=margin_days)


def check_day(
    day: DayPlan,
    corridor: Corridor,
    snow_year: SnowYear,
    *,
    aspect: Aspect = Aspect.NORTH,
) -> list[SnowFinding]:
    """Season findings for one day of an itinerary."""
    found: list[SnowFinding] = []
    line = snow_line(snow_year, day.day, aspect)
    for waypoint in corridor.waypoints_between(day.start_mile, day.end_mile):
        if waypoint.kind in {WaypointKind.PASS, WaypointKind.SUMMIT}:
            if waypoint.elevation > line:
                above = waypoint.elevation.in_feet - line.in_feet
                found.append(
                    SnowFinding(
                        waypoint=waypoint,
                        when=day.day,
                        kind="snowbound",
                        severity=min(1.0, above / 2000.0),
                        message=(
                            f"{waypoint.name} sits {above:.0f} ft above the snow line "
                            f"on {day.day.isoformat()}"
                        ),
                    )
                )
        elif waypoint.kind is WaypointKind.FORD:
            hazard = ford_hazard(snow_year, day.day, waypoint.elevation)
            found.append(
                SnowFinding(
                    waypoint=waypoint,
                    when=day.day,
                    kind="ford",
                    severity=hazard,
                    message=(
                        f"{waypoint.name} is {describe_hazard(hazard)} " f"on {day.day.isoformat()}"
                    ),
                )
            )
    return found


def check_itinerary(
    itinerary: Itinerary, snow_year: SnowYear, *, aspect: Aspect = Aspect.NORTH
) -> tuple[SnowFinding, ...]:
    """Season findings across a whole plan, in day order."""
    found: list[SnowFinding] = []
    for day in itinerary:
        found.extend(check_day(day, itinerary.corridor, snow_year, aspect=aspect))
    return tuple(found)


def serious_findings(findings: Sequence[SnowFinding]) -> tuple[SnowFinding, ...]:
    """Only the findings a planner has to act on, worst first."""
    serious = [finding for finding in findings if finding.is_serious]
    serious.sort(key=lambda finding: finding.severity, reverse=True)
    return tuple(serious)


def suggested_delay(
    itinerary: Itinerary, snow_year: SnowYear, *, aspect: Aspect = Aspect.NORTH
) -> int:
    """Days to push the start back until nothing serious is left.

    Searches forward rather than solving, because the fords are not monotone in
    date: pushing back past the melt peak improves them, but pushing back a
    little makes them worse.
    """
    for delay in range(0, 90):
        shifted = itinerary.shifted_to(itinerary.start_date + timedelta(days=delay))
        if not serious_findings(check_itinerary(shifted, snow_year, aspect=aspect)):
            return delay
    raise SeasonError(
        "no start within ninety days clears every serious finding",
        snow_year=snow_year.year,
        percent=snow_year.percent_of_median,
    )


def summarise(findings: Sequence[SnowFinding]) -> str:
    """One line per serious finding, plus a count of the rest."""
    serious = serious_findings(findings)
    lines = [finding.message for finding in serious]
    remainder = len(findings) - len(serious)
    if remainder:
        lines.append(f"{remainder} further note{'s' if remainder > 1 else ''}")
    return "\n".join(lines) if lines else "nothing of concern for this snow year"


def snow_line_on(snow_year: SnowYear, when: date, aspect: Aspect = Aspect.NORTH) -> Distance:
    """Convenience re-export so callers do not need two imports."""
    return snow_line(snow_year, when, aspect)
