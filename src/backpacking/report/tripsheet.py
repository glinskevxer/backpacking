"""The trip sheet: one page a hiker prints and leaves with somebody.

This is the document that matters if something goes wrong. It has to be legible
on a wet photocopy, it has to say where the hiker expects to be on each date,
and it has to name the exits, because that is what a search starts from.

Deliberately fixed width text rather than markdown or HTML. It gets printed.
"""

from __future__ import annotations

from backpacking.errors import DataSourceError
from backpacking.plan.itinerary import Itinerary
from backpacking.resupply.towns import TownIndex
from backpacking.trail.models import WaypointKind

RULE = "=" * 78
THIN = "-" * 78


def header(itinerary: Itinerary, hiker_name: str, emergency_contact: str) -> list[str]:
    return [
        RULE,
        f"TRIP SHEET  {itinerary.corridor.name}",
        RULE,
        f"Hiker              {hiker_name}",
        f"On trail           {itinerary.start_date.isoformat()} "
        f"to {itinerary.finish_date.isoformat()}",
        f"Route              mile {itinerary.start_mile:.1f} to {itinerary.end_mile:.1f}, "
        f"{itinerary.total_distance.in_miles:.1f} miles",
        f"Emergency contact  {emergency_contact}",
        "",
        "If no contact is made by the day after the finish date, call the",
        "agency covering the section the hiker was last expected in.",
        "",
    ]


def schedule_block(itinerary: Itinerary) -> list[str]:
    lines = [
        "EXPECTED POSITION BY DATE",
        THIN,
        f"{'date':<12}{'day':>4}  {'mile':>7}  {'miles':>6}  camp",
    ]
    for day in itinerary:
        camp = "rest day" if day.is_zero else (day.camp.name if day.camp else "dispersed")
        lines.append(
            f"{day.day.isoformat():<12}{day.index + 1:>4}  "
            f"{day.end_mile:>7.1f}  {day.miles:>6.1f}  {camp}"
        )
    lines.append("")
    return lines


def exits_block(itinerary: Itinerary) -> list[str]:
    """Every road, trailhead and resupply the route passes, with its mileage."""
    exits = [
        waypoint
        for waypoint in itinerary.corridor.waypoints_between(
            itinerary.start_mile, itinerary.end_mile
        )
        if waypoint.kind.is_exit
    ]
    lines = ["EXIT POINTS", THIN, f"{'mile':>7}  {'kind':<10}  name"]
    if not exits:
        lines.append("  none on this section")
    for waypoint in exits:
        lines.append(f"{waypoint.mile:>7.1f}  {waypoint.kind.value:<10}  {waypoint.name}")
    lines.append("")
    return lines


def resupply_block(itinerary: Itinerary, towns: TownIndex | None) -> list[str]:
    if towns is None:
        return []
    points = towns.between(itinerary.start_mile, itinerary.end_mile)
    if not points:
        return []
    lines = ["RESUPPLY AND SERVICES", THIN, f"{'mile':>7}  {'services':<14}  name"]
    for point in points:
        services = point.groceries.label
        if point.has_post_office:
            services += ", post"
        if point.has_lodging:
            services += ", beds"
        lines.append(f"{point.mile:>7.1f}  {services:<14}  {point.name}")
    lines.append("")
    return lines


def water_block(itinerary: Itinerary) -> list[str]:
    """Water sources marked on the corridor itself, as a fallback list."""
    sources = [
        waypoint
        for waypoint in itinerary.corridor.waypoints_between(
            itinerary.start_mile, itinerary.end_mile
        )
        if waypoint.kind is WaypointKind.WATER
    ]
    if not sources:
        return []
    lines = ["WATER ON THE CORRIDOR", THIN]
    for source in sources:
        tag = ", ".join(sorted(source.tags)) or "unrated"
        lines.append(f"{source.mile:>7.1f}  {source.name} ({tag})")
    lines.append("")
    return lines


def render_trip_sheet(
    itinerary: Itinerary,
    *,
    hiker_name: str,
    emergency_contact: str,
    towns: TownIndex | None = None,
) -> str:
    """The whole sheet, in the order somebody reading it needs."""
    if not hiker_name.strip():
        raise DataSourceError("a trip sheet needs a hiker name")
    if not emergency_contact.strip():
        raise DataSourceError("a trip sheet needs an emergency contact")
    lines: list[str] = []
    lines.extend(header(itinerary, hiker_name, emergency_contact))
    lines.extend(schedule_block(itinerary))
    lines.extend(exits_block(itinerary))
    lines.extend(resupply_block(itinerary, towns))
    lines.extend(water_block(itinerary))
    lines.append(RULE)
    return "\n".join(lines) + "\n"
