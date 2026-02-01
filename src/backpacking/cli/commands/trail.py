"""Commands for the things attached to a corridor: water, permits, resupply."""

from __future__ import annotations

from pathlib import Path

import typer

from backpacking.cli.context import CliContext
from backpacking.cli.formatting import feet, keyed, miles, table
from backpacking.pace.estimator import PaceEstimator
from backpacking.pace.models import HikerProfile
from backpacking.resupply.strategy import plan_resupply, town_time
from backpacking.storage.repository import CorridorRepository
from backpacking.units import Energy, Volume
from backpacking.water.carry import find_dry_stretches, plan_carry

water_app = typer.Typer(help="Water sources and dry stretches.")
permit_app = typer.Typer(help="Permit zones and their rules.")
resupply_app = typer.Typer(help="Resupply points and carry strategy.")


def _context(ctx: typer.Context) -> CliContext:
    return ctx.obj  # type: ignore[no-any-return]


@water_app.command("list")
def list_water(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    month: int = typer.Option(7, "--month", min=1, max=12),
    threshold: float = typer.Option(0.6, "--threshold", min=0.0, max=1.0),
) -> None:
    """Water on a corridor with this month's confidence."""
    context = _context(ctx)
    with context.session() as session:
        corridor_id = CorridorRepository(session).corridor_id(slug)
        sources = context.water(session).load(corridor_id)
    typer.echo(
        table(
            ["mile", "id", "reliability", "confidence", "usable"],
            [
                [
                    miles(source.mile),
                    source.id,
                    source.reliability.value,
                    f"{source.confidence(month):.2f}",
                    "yes" if source.is_usable(month, threshold) else "no",
                ]
                for source in sources
            ],
        )
    )


@water_app.command("gaps")
def water_gaps(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    month: int = typer.Option(7, "--month", min=1, max=12),
    capacity: float = typer.Option(4.0, "--capacity", help="bottle capacity in litres"),
    temperature: float = typer.Option(20.0, "--temp", help="daytime temperature in celsius"),
    pace: float = typer.Option(3.0, "--pace"),
    minimum: float = typer.Option(8.0, "--min-miles"),
) -> None:
    """Dry stretches, sized against a stated capacity."""
    context = _context(ctx)
    with context.session() as session:
        corridors = CorridorRepository(session)
        corridor = corridors.load(slug)
        table_of_water = context.water(session).load(corridors.corridor_id(slug))
    estimator = PaceEstimator(profile=HikerProfile(flat_pace_mph=pace))
    rows = []
    for stretch in find_dry_stretches(
        corridor, table_of_water, month, min_length_miles=minimum
    ):
        carry = plan_carry(
            corridor, estimator, stretch, Volume.liters(capacity), temperature_c=temperature
        )
        rows.append(
            [
                miles(stretch.start_mile),
                miles(stretch.end_mile),
                miles(stretch.length.in_miles),
                f"{carry.required.in_liters:.1f}",
                "ok" if carry.is_feasible else "short",
            ]
        )
    if not rows:
        typer.echo(f"no dry stretches over {minimum} miles in month {month}")
        raise typer.Exit(code=0)
    typer.echo(table(["from", "to", "miles", "litres", "verdict"], rows))


@permit_app.command("list")
def list_zones(ctx: typer.Context, slug: str = typer.Argument(...)) -> None:
    """Permit zones on a corridor."""
    context = _context(ctx)
    with context.session() as session:
        corridor_id = CorridorRepository(session).corridor_id(slug)
        zones = context.permits(session).load(corridor_id)
    typer.echo(
        table(
            ["from", "to", "id", "camping", "canister", "agency"],
            [
                [
                    miles(zone.start_mile),
                    miles(zone.end_mile),
                    zone.id,
                    zone.camping.value,
                    "yes" if zone.canister_required else "no",
                    zone.agency,
                ]
                for zone in zones
            ],
        )
    )


@permit_app.command("at")
def zone_at(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    mile: float = typer.Argument(...),
) -> None:
    """Which zone a mile falls in."""
    context = _context(ctx)
    with context.session() as session:
        corridor_id = CorridorRepository(session).corridor_id(slug)
        zone = context.permits(session).load(corridor_id).at(mile)
    if zone is None:
        typer.echo(f"mile {mile} is not inside any mapped zone")
        raise typer.Exit(code=1)
    typer.echo(
        keyed(
            {
                "zone": zone.id,
                "name": zone.name,
                "agency": zone.agency,
                "camping": zone.camping.value,
                "canister": "required" if zone.canister_required else "not required",
                "fires": "allowed" if zone.campfires_allowed else "prohibited",
            }
        )
    )


@resupply_app.command("list")
def list_resupply(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    full_only: bool = typer.Option(False, "--full-only"),
) -> None:
    """Resupply points on a corridor."""
    context = _context(ctx)
    with context.session() as session:
        corridor_id = CorridorRepository(session).corridor_id(slug)
        index = context.resupply(session).load(corridor_id)
    points = index.full_resupplies() if full_only else index.points
    typer.echo(
        table(
            ["mile", "id", "groceries", "access hrs", "post"],
            [
                [
                    miles(point.mile),
                    point.id,
                    point.groceries.label,
                    f"{point.access_cost().in_hours:.1f}",
                    "yes" if point.has_post_office else "no",
                ]
                for point in points
            ],
        )
    )


@resupply_app.command("strategy")
def resupply_strategy(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    daily: float = typer.Option(18.0, "--daily-miles"),
    max_days: float = typer.Option(7.0, "--max-carry"),
    burn: float = typer.Option(2900.0, "--burn", help="kilocalories burned a day"),
) -> None:
    """Cheapest admissible set of stops."""
    context = _context(ctx)
    with context.session() as session:
        corridors = CorridorRepository(session)
        corridor = corridors.load(slug)
        index = context.resupply(session).load(corridors.corridor_id(slug))
    plan = plan_resupply(
        index,
        corridor.start_mile,
        corridor.end_mile,
        HikerProfile(),
        daily_miles=daily,
        burned_per_day=Energy.kilocalories(burn),
        max_carry_days=max_days,
    )
    typer.echo(
        keyed(
            {
                "stops": ", ".join(stop.id for stop in plan.stops) or "none",
                "town hours": f"{town_time(plan).in_hours:.1f}",
                "longest carry": f"{plan.longest_carry.days:.1f} days",
                "heaviest bag": f"{plan.heaviest_food_bag.in_pounds:.1f} lb",
            }
        )
    )
    typer.echo("")
    typer.echo(
        table(
            ["from", "to", "days", "food lb"],
            [
                [
                    miles(carry.start_mile),
                    miles(carry.end_mile),
                    f"{carry.days:.1f}",
                    f"{carry.food_mass.in_pounds:.1f}",
                ]
                for carry in plan.carries
            ],
        )
    )


@resupply_app.command("export")
def export_strategy(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", "-o"),
    daily: float = typer.Option(18.0, "--daily-miles"),
    max_days: float = typer.Option(7.0, "--max-carry"),
) -> None:
    """Write the carries out as CSV for a shopping list."""
    context = _context(ctx)
    with context.session() as session:
        corridors = CorridorRepository(session)
        corridor = corridors.load(slug)
        index = context.resupply(session).load(corridors.corridor_id(slug))
    plan = plan_resupply(
        index,
        corridor.start_mile,
        corridor.end_mile,
        HikerProfile(),
        daily_miles=daily,
        max_carry_days=max_days,
    )
    lines = ["start_mile,end_mile,days,food_lb,resupply_at"]
    for carry in plan.carries:
        lines.append(
            f"{carry.start_mile:.1f},{carry.end_mile:.1f},{carry.days:.2f},"
            f"{carry.food_mass.in_pounds:.2f},"
            f"{'' if carry.end_point is None else carry.end_point.id}"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out} with {feet(len(plan.carries))} carries")
