"""iCalendar export.

A plan is a sequence of dated events, and the phone that is coming on the trip
already has a calendar on it. Exporting the itinerary as ICS means the day's
mileage and camp show up without an app, and it works offline, which matters
more than anything else about the format.

Written by hand rather than with a library, because the subset needed is small
and the folding rules are the only fiddly part.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from backpacking.errors import DataSourceError
from backpacking.plan.itinerary import DayPlan, Itinerary

PRODUCT_ID = "-//backpacking//itinerary//EN"
LINE_LIMIT = 75


def escape(value: str) -> str:
    """Escape the four characters iCalendar treats specially."""
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> list[str]:
    """Split a long line onto continuations, which start with one space."""
    if len(line) <= LINE_LIMIT:
        return [line]
    out = [line[:LINE_LIMIT]]
    rest = line[LINE_LIMIT:]
    while rest:
        out.append(" " + rest[: LINE_LIMIT - 1])
        rest = rest[LINE_LIMIT - 1 :]
    return out


def format_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def day_summary(day: DayPlan, corridor_name: str) -> str:
    if day.is_zero:
        return f"{corridor_name}: zero day"
    where = day.camp.name if day.camp is not None else f"mile {day.end_mile:.1f}"
    return f"{corridor_name}: {day.miles:.1f} mi to {where}"


def day_description(day: DayPlan) -> str:
    if day.is_zero:
        return "Rest day. No mileage planned."
    parts = [
        f"Mile {day.start_mile:.1f} to {day.end_mile:.1f} ({day.miles:.1f} mi)",
        f"Climb {day.estimate.gain.in_feet:.0f} ft, descent {day.estimate.loss.in_feet:.0f} ft",
        f"Estimated {day.elapsed.as_clock()} including breaks",
    ]
    if day.camp is not None:
        parts.append(f"Camp at {day.camp.name} ({day.camp.elevation.in_feet:.0f} ft)")
    if day.resupply_at is not None:
        parts.append(f"Resupply at {day.resupply_at}")
    if day.notes:
        parts.append(day.notes)
    return "\n".join(parts)


def event_uid(itinerary: Itinerary, day: DayPlan) -> str:
    label = itinerary.label or "plan"
    return f"{label}-{itinerary.start_date.isoformat()}-day{day.index + 1}@backpacking"


def to_ics(itinerary: Itinerary, *, generated_at: datetime | None = None) -> str:
    """Render an itinerary as an all day event per day."""
    if len(itinerary) == 0:
        raise DataSourceError("cannot export an empty itinerary")
    stamp = format_timestamp(generated_at or datetime.now(UTC))
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODUCT_ID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(itinerary.corridor.name)}",
    ]
    for day in itinerary:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event_uid(itinerary, day)}",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{format_date(day.day)}",
                f"DTEND;VALUE=DATE:{format_date(day.day + timedelta(days=1))}",
                f"SUMMARY:{escape(day_summary(day, itinerary.corridor.name))}",
                f"DESCRIPTION:{escape(day_description(day))}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(_folded(lines)) + "\r\n"


def _folded(lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        out.extend(fold(line))
    return out


def count_events(ics: str) -> int:
    """How many events a rendered calendar holds, for checking an export."""
    return ics.count("BEGIN:VEVENT")
