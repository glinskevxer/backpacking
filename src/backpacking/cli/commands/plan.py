"""Plan commands: build, save, list, print, check."""

from __future__ import annotations

from datetime import date

import typer

from backpacking.cli.context import CliContext
from backpacking.cli.formatting import keyed, table
from backpacking.pace.models import HikerProfile
from backpacking.permits.validate import suggest_fixes, validate_nights
from backpacking.plan.constraints import PlanConstraints
from backpacking.plan.explain import (
    explain_plan,
    render_costs,
    render_permit_report,
    render_schedule,
    render_summary,
)
from backpacking.plan.scoring import target_hours_for
from backpacking.plan.solver import PlanRequest, solve
from backpacking.units import Distance, Duration, Mass

app = typer.Typer(help="Build, store and check itineraries.")


def _context(ctx: typer.Context) -> CliContext:
    return ctx.obj  # type: ignore[no-any-return]


def _profile(
    name: str, pace: float, hours: float, gain: float, night: bool, pack_lb: float
) -> HikerProfile:
    return HikerProfile(
        name=name,
        flat_pace_mph=pace,
        max_moving_hours=hours,
        max_daily_gain_ft=gain,
        reference_load=Mass.pounds(pack_lb),
        night_hiking=night,
    )


@app.command("build")
def build(
    ctx: typer.Context,
    slug: str = typer.Argument(..., help="corridor to plan over"),
    start: date = typer.Option(..., "--start", help="first day on trail"),
    pace: float = typer.Option(3.0, "--pace", help="flat pace in mph"),
    hours: float = typer.Option(9.0, "--hours", help="moving hours a day"),
    pack: float = typer.Option(26.0, "--pack", help="pack weight in pounds"),
    max_miles: float = typer.Option(32.0, "--max-miles"),
    max_gain: float = typer.Option(6000.0, "--max-gain", help="daily climb ceiling in feet"),
    night: bool = typer.Option(False, "--night", help="willing to walk after dark"),
    aggressiveness: float = typer.Option(0.8, "--push", help="fraction of the hour budget"),
    costs: bool = typer.Option(False, "--costs", help="show the objective per day"),
    save: bool = typer.Option(False, "--save", help="store the plan"),
) -> None:
    """Build an itinerary and print it."""
    context = _context(ctx)
    with context.session() as session:
        from backpacking.storage.repository import CorridorRepository

        corridors = CorridorRepository(session)
        corridor = corridors.load(slug)
        profile = _profile("cli", pace, hours, max_gain, night, pack)
        request = PlanRequest(
            corridor=corridor,
            profile=profile,
            start_date=start,
            constraints=PlanConstraints(
                max_daily_miles=max_miles,
                max_daily_gain=Distance.feet(max_gain),
                max_daily_elapsed=Duration.hours(hours * 1.4),
            ),
            aggressiveness=aggressiveness,
            pack_weight=Mass.pounds(pack),
        )
        itinerary = solve(request)
        typer.echo(render_summary(itinerary, profile))
        typer.echo("")
        typer.echo(render_schedule(itinerary))
        if costs:
            target = target_hours_for(profile, aggressiveness=aggressiveness)
            typer.echo("")
            typer.echo(render_costs(explain_plan(itinerary, profile, target_hours=target)))
        if save:
            plan_id = context.plans(session).save(
                itinerary, corridors.corridor_id(slug), profile.name
            )
            typer.echo("")
            typer.echo(f"saved as plan {plan_id}")


@app.command("list")
def list_plans(ctx: typer.Context, slug: str = typer.Argument(...)) -> None:
    """Stored plans for one corridor."""
    context = _context(ctx)
    with context.session() as session:
        from backpacking.storage.repository import CorridorRepository

        corridor_id = CorridorRepository(session).corridor_id(slug)
        rows = context.plans(session).list_for_corridor(corridor_id)
    if not rows:
        typer.echo(f"no plans stored for {slug}")
        raise typer.Exit(code=0)
    typer.echo(
        table(
            ["id", "label", "start"],
            [[plan_id, label or "-", start.isoformat()] for plan_id, label, start in rows],
        )
    )


@app.command("show")
def show_plan(
    ctx: typer.Context,
    plan_id: int = typer.Argument(...),
    slug: str = typer.Option(..., "--corridor", "-c"),
) -> None:
    """Print a stored plan."""
    context = _context(ctx)
    with context.session() as session:
        from backpacking.storage.repository import CorridorRepository

        corridor = CorridorRepository(session).load(slug)
        itinerary = context.plans(session).load(plan_id, corridor)
    typer.echo(render_schedule(itinerary))


@app.command("check")
def check_plan(
    ctx: typer.Context,
    plan_id: int = typer.Argument(...),
    slug: str = typer.Option(..., "--corridor", "-c"),
    canister: bool = typer.Option(False, "--canister", help="carrying an approved canister"),
    fire: bool = typer.Option(False, "--fire", help="planning campfires"),
) -> None:
    """Grade a stored plan against the corridor's permit rules."""
    context = _context(ctx)
    with context.session() as session:
        from backpacking.storage.repository import CorridorRepository

        corridors = CorridorRepository(session)
        corridor = corridors.load(slug)
        itinerary = context.plans(session).load(plan_id, corridor)
        zones = context.permits(session).load(corridors.corridor_id(slug))
    report = validate_nights(
        itinerary.camp_nights(has_canister=canister, wants_fire=fire), zones
    )
    typer.echo(render_permit_report(report))
    fixes = suggest_fixes(report)
    if fixes:
        typer.echo("")
        typer.echo("try:")
        for fix in fixes:
            typer.echo(f"  {fix}")
    if not report.is_permittable:
        raise typer.Exit(code=1)


@app.command("delete")
def delete_plan(ctx: typer.Context, plan_id: int = typer.Argument(...)) -> None:
    """Remove a stored plan."""
    context = _context(ctx)
    with context.session() as session:
        context.plans(session).delete(plan_id)
    typer.echo(f"deleted plan {plan_id}")


@app.command("stats")
def plan_stats(
    ctx: typer.Context,
    plan_id: int = typer.Argument(...),
    slug: str = typer.Option(..., "--corridor", "-c"),
) -> None:
    """Headline numbers for a stored plan."""
    context = _context(ctx)
    with context.session() as session:
        from backpacking.storage.repository import CorridorRepository

        corridor = CorridorRepository(session).load(slug)
        itinerary = context.plans(session).load(plan_id, corridor)
    typer.echo(
        keyed(
            {
                "days": len(itinerary),
                "miles": f"{itinerary.total_distance.in_miles:.1f}",
                "gain ft": f"{itinerary.total_gain.in_feet:.0f}",
                "average day": f"{itinerary.average_daily_miles:.1f} mi",
                "longest day": f"day {itinerary.longest_day.index + 1}, "
                f"{itinerary.longest_day.miles:.1f} mi",
                "biggest climb": f"day {itinerary.biggest_climb.index + 1}, "
                f"{itinerary.biggest_climb.gain.in_feet:.0f} ft",
            }
        )
    )
