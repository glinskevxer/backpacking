"""Report commands: export a plan, check a season, compare two plans."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from backpacking.analysis.compare import compare_plans, render_delta
from backpacking.cli.context import CliContext
from backpacking.report.calendar import to_ics
from backpacking.report.serialize import plan_to_dict, to_json
from backpacking.report.tripsheet import render_trip_sheet
from backpacking.season.conditions import (
    check_itinerary,
    corridor_melt_out,
    earliest_walkable_start,
    summarise,
)
from backpacking.season.snowpack import SnowYear
from backpacking.storage.repository import CorridorRepository

app = typer.Typer(help="Export plans and check them against the season.")


def _context(ctx: typer.Context) -> CliContext:
    return ctx.obj  # type: ignore[no-any-return]


@app.command("json")
def export_json(
    ctx: typer.Context,
    plan_id: int = typer.Argument(...),
    slug: str = typer.Option(..., "--corridor", "-c"),
    out: Path | None = typer.Option(None, "--out", "-o", help="write to a file"),
) -> None:
    """Write a plan out as archival JSON."""
    context = _context(ctx)
    with context.session() as session:
        corridor = CorridorRepository(session).load(slug)
        itinerary = context.plans(session).load(plan_id, corridor)
    body = to_json(plan_to_dict(itinerary, slug))
    if out is None:
        typer.echo(body)
    else:
        out.write_text(body, encoding="utf-8")
        typer.echo(f"wrote {out}")


@app.command("calendar")
def export_calendar(
    ctx: typer.Context,
    plan_id: int = typer.Argument(...),
    slug: str = typer.Option(..., "--corridor", "-c"),
    out: Path = typer.Option(..., "--out", "-o"),
) -> None:
    """Write a plan out as an ICS calendar."""
    context = _context(ctx)
    with context.session() as session:
        corridor = CorridorRepository(session).load(slug)
        itinerary = context.plans(session).load(plan_id, corridor)
    out.write_text(to_ics(itinerary), encoding="utf-8")
    typer.echo(f"wrote {out} with {len(itinerary)} events")


@app.command("tripsheet")
def export_trip_sheet(
    ctx: typer.Context,
    plan_id: int = typer.Argument(...),
    slug: str = typer.Option(..., "--corridor", "-c"),
    hiker: str = typer.Option(..., "--hiker", help="who is walking"),
    contact: str = typer.Option(..., "--contact", help="emergency contact"),
    out: Path | None = typer.Option(None, "--out", "-o"),
) -> None:
    """Write the one page sheet to leave with somebody."""
    context = _context(ctx)
    with context.session() as session:
        corridors = CorridorRepository(session)
        corridor = corridors.load(slug)
        itinerary = context.plans(session).load(plan_id, corridor)
        towns = context.resupply(session).load(corridors.corridor_id(slug))
    text = render_trip_sheet(
        itinerary, hiker_name=hiker, emergency_contact=contact, towns=towns
    )
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")


@app.command("season")
def season(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    year: int = typer.Option(..., "--year"),
    percent: float = typer.Option(..., "--percent", help="snowpack as percent of median"),
    plan_id: int | None = typer.Option(None, "--plan", help="check a stored plan too"),
) -> None:
    """Melt out dates, and optionally what they mean for a stored plan."""
    context = _context(ctx)
    snow_year = SnowYear(year=year, percent_of_median=percent)
    with context.session() as session:
        corridor = CorridorRepository(session).load(slug)
        itinerary = (
            None if plan_id is None else context.plans(session).load(plan_id, corridor)
        )
    typer.echo(f"{year} is a {snow_year.descriptor} year at {percent:.0f}% of median")
    typer.echo("")
    for waypoint_id, when in sorted(
        corridor_melt_out(corridor, snow_year).items(), key=lambda pair: pair[1]
    ):
        typer.echo(f"  {when.isoformat()}  {waypoint_id}")
    typer.echo("")
    typer.echo(
        f"earliest start with everything melted: "
        f"{earliest_walkable_start(corridor, snow_year).isoformat()}"
    )
    if itinerary is not None:
        typer.echo("")
        typer.echo(summarise(check_itinerary(itinerary, snow_year)))


@app.command("compare")
def compare(
    ctx: typer.Context,
    baseline_id: int = typer.Argument(..., help="the plan to compare against"),
    candidate_id: int = typer.Argument(..., help="the plan being considered"),
    slug: str = typer.Option(..., "--corridor", "-c"),
) -> None:
    """Show what differs between two stored plans."""
    context = _context(ctx)
    with context.session() as session:
        corridor = CorridorRepository(session).load(slug)
        plans = context.plans(session)
        baseline = plans.load(baseline_id, corridor)
        candidate = plans.load(candidate_id, corridor)
    typer.echo(render_delta(compare_plans(baseline, candidate)))


@app.command("melt")
def melt(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    year: int = typer.Option(..., "--year"),
    percent: float = typer.Option(100.0, "--percent"),
    margin: int = typer.Option(0, "--margin", help="days of margin after melt out"),
) -> None:
    """Just the earliest walkable start date."""
    context = _context(ctx)
    with context.session() as session:
        corridor = CorridorRepository(session).load(slug)
    snow_year = SnowYear(year=year, percent_of_median=percent)
    when: date = earliest_walkable_start(corridor, snow_year, margin_days=margin)
    typer.echo(when.isoformat())
