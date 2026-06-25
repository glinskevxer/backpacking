"""Plan commands: build, save, list, print, check."""

from __future__ import annotations

from datetime import date

import typer

from backpacking.cli.context import CliContext
from backpacking.cli.formatting import keyed, table
from backpacking.permits.validate import suggest_fixes
from backpacking.plan.explain import (
    explain_plan,
    render_costs,
    render_permit_report,
    render_schedule,
    render_summary,
)
from backpacking.plan.scoring import target_hours_for
from backpacking.services.planning import ConstraintSpec, HikerSpec, PlanningService

app = typer.Typer(help="Build, store and check itineraries.")


def _context(ctx: typer.Context) -> CliContext:
    return ctx.obj  # type: ignore[no-any-return]


def _hiker(pace: float, hours: float, gain: float, night: bool, pack_lb: float) -> HikerSpec:
    return HikerSpec(
        name="cli",
        flat_pace_mph=pace,
        max_moving_hours=hours,
        max_daily_gain_ft=gain,
        pack_weight_lb=pack_lb,
        night_hiking=night,
    )


@app.command("build")
def build(
    ctx: typer.Context,
    slug: str = typer.Argument(..., help="corridor to plan over"),
    start: str = typer.Option(..., "--start", help="first day on trail, YYYY-MM-DD"),
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
    try:
        start_date = date.fromisoformat(start)
    except ValueError as exc:
        raise typer.BadParameter("start must be an ISO date such as 2025-07-20") from exc
    context = _context(ctx)
    with context.session() as session:
        service = PlanningService(session)
        spec = _hiker(pace, hours, max_gain, night, pack)
        profile = spec.to_profile()
        request = service.build_request(
            slug,
            start_date,
            hiker=spec,
            constraints=ConstraintSpec(
                max_daily_miles=max_miles,
                max_daily_gain_ft=max_gain,
                max_daily_hours=hours * 1.4,
            ),
            aggressiveness=aggressiveness,
        )
        itinerary = service.build_plan(request)
        typer.echo(render_summary(itinerary, profile))
        typer.echo("")
        typer.echo(render_schedule(itinerary))
        if costs:
            target = target_hours_for(profile, aggressiveness=aggressiveness)
            typer.echo("")
            typer.echo(render_costs(explain_plan(itinerary, profile, target_hours=target)))
        if save:
            plan_id = service.save_plan(itinerary, slug, spec.name)
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
        itinerary = PlanningService(session).load_plan(plan_id, slug)
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
        service = PlanningService(session)
        itinerary = service.load_plan(plan_id, slug)
        report = service.check_permits(itinerary, slug, has_canister=canister, wants_fire=fire)
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
        itinerary = PlanningService(session).load_plan(plan_id, slug)
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
