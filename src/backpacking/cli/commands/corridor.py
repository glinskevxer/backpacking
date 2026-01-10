"""Corridor commands: import, list, inspect, export."""

from __future__ import annotations

from pathlib import Path

import typer

from backpacking.cli.context import CliContext
from backpacking.cli.formatting import feet, keyed, miles, table
from backpacking.trail.datasheet import (
    corridor_from_rows,
    corridor_to_rows,
    load_datasheet,
    write_datasheet,
)
from backpacking.trail.elevation import ElevationProfile, ElevationSample, grade_histogram
from backpacking.trail.gpx import load_gpx
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance

app = typer.Typer(help="Import, inspect and export trail corridors.")


def _context(ctx: typer.Context) -> CliContext:
    return ctx.obj  # type: ignore[no-any-return]


@app.command("import")
def import_corridor(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="datasheet CSV to read"),
    slug: str = typer.Option(..., "--slug", "-s", help="identifier to store it under"),
    name: str | None = typer.Option(None, "--name", help="display name"),
    region: str = typer.Option("", "--region"),
) -> None:
    """Read a datasheet and store it as a corridor."""
    rows = load_datasheet(path)
    corridor = corridor_from_rows(name or path.stem.replace("-", " ").title(), rows)
    context = _context(ctx)
    with context.corridors() as repository:
        repository.save(corridor, slug, region=region)
    typer.echo(
        f"stored {slug}: {len(corridor)} waypoints over {miles(corridor.length.in_miles)} miles"
    )


@app.command("import-gpx")
def import_gpx(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="GPX file to read"),
    slug: str = typer.Option(..., "--slug", "-s"),
    track: str | None = typer.Option(None, "--track", help="track name, longest by default"),
) -> None:
    """Read a GPX track and store its waypoints as a corridor."""
    document = load_gpx(path)
    chosen = document.track(track) if track else document.primary
    cumulative = chosen.cumulative_miles()
    waypoints = [
        Waypoint(
            id=f"point-{index:04d}",
            name=f"Mile {mile:.1f}",
            mile=mile,
            elevation=point.elevation or Distance.zero(),
            kind=WaypointKind.LANDMARK,
            position=point,
        )
        for index, (mile, point) in enumerate(zip(cumulative, chosen.points, strict=False))
    ]
    from backpacking.trail.corridor import Corridor

    corridor = Corridor.from_waypoints(chosen.name, waypoints)
    context = _context(ctx)
    with context.corridors() as repository:
        repository.save(corridor, slug)
    typer.echo(f"stored {slug} from track {chosen.name!r}: {len(corridor)} points")


@app.command("list")
def list_corridors(ctx: typer.Context) -> None:
    """Every stored corridor."""
    context = _context(ctx)
    with context.corridors() as repository:
        slugs = repository.list_slugs()
        rows = []
        for slug in slugs:
            corridor = repository.load(slug)
            rows.append(
                [
                    slug,
                    corridor.name,
                    miles(corridor.length.in_miles),
                    len(corridor),
                    feet(corridor.total_gain().in_feet),
                ]
            )
    if not rows:
        typer.echo("no corridors stored")
        raise typer.Exit(code=0)
    typer.echo(table(["slug", "name", "miles", "points", "gain ft"], rows))


@app.command("show")
def show_corridor(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    kind: str | None = typer.Option(None, "--kind", help="filter waypoints by kind"),
) -> None:
    """One corridor, with its waypoints."""
    context = _context(ctx)
    with context.corridors() as repository:
        corridor = repository.load(slug)
    waypoints = corridor.waypoints
    if kind is not None:
        waypoints = corridor.of_kind(WaypointKind(kind))
    typer.echo(
        keyed(
            {
                "name": corridor.name,
                "length": f"{miles(corridor.length.in_miles)} mi",
                "gain": f"{feet(corridor.total_gain().in_feet)} ft",
                "loss": f"{feet(corridor.total_loss().in_feet)} ft",
                "waypoints": len(corridor),
            }
        )
    )
    typer.echo("")
    typer.echo(
        table(
            ["mile", "id", "kind", "elev ft", "name"],
            [
                [miles(w.mile), w.id, w.kind.value, feet(w.elevation.in_feet), w.name]
                for w in waypoints
            ],
        )
    )


@app.command("profile")
def corridor_profile(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    step: float = typer.Option(1.0, "--step", help="sampling interval in miles"),
) -> None:
    """Grade distribution of a stored corridor."""
    context = _context(ctx)
    with context.corridors() as repository:
        corridor = repository.load(slug)
    samples = []
    cursor = corridor.start_mile
    while cursor < corridor.end_mile:
        samples.append(ElevationSample(cursor, corridor.elevation_at(cursor)))
        cursor += step
    samples.append(ElevationSample(corridor.end_mile, corridor.elevation_at(corridor.end_mile)))
    histogram = grade_histogram(ElevationProfile(samples), [-0.15, -0.05, 0.05, 0.15])
    typer.echo(
        table(
            ["grade band", "miles"],
            [[label, miles(value)] for label, value in histogram.items()],
        )
    )


@app.command("export")
def export_corridor(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", "-o", help="datasheet CSV to write"),
) -> None:
    """Write a stored corridor back out as a datasheet."""
    context = _context(ctx)
    with context.corridors() as repository:
        corridor = repository.load(slug)
    out.write_text(write_datasheet(corridor_to_rows(corridor)), encoding="utf-8")
    typer.echo(f"wrote {out} with {len(corridor)} rows")


@app.command("delete")
def delete_corridor(
    ctx: typer.Context,
    slug: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="skip the confirmation"),
) -> None:
    """Remove a corridor and everything attached to it."""
    if not yes:
        typer.confirm(f"delete corridor {slug} and everything on it?", abort=True)
    context = _context(ctx)
    with context.corridors() as repository:
        repository.delete(slug)
    typer.echo(f"deleted {slug}")
