"""The ``backpacking`` command.

One root application with a sub command per noun. Global options are handled in
the callback so that ``--database`` works the same whatever comes after it,
which is the thing that is most annoying when it is not true.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from backpacking import __version__
from backpacking.cli.commands import corridor, plan, report, trail
from backpacking.cli.context import build_context
from backpacking.errors import BackpackingError

app = typer.Typer(
    help="Itinerary, permit and resupply logistics for long distance trails.",
    no_args_is_help=True,
)
app.add_typer(corridor.app, name="corridor")
app.add_typer(plan.app, name="plan")
app.add_typer(trail.water_app, name="water")
app.add_typer(trail.permit_app, name="permit")
app.add_typer(trail.resupply_app, name="resupply")
app.add_typer(report.app, name="report")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"backpacking {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    database: str | None = typer.Option(
        None, "--database", envvar="BACKPACKING_DATABASE_URL", help="SQLAlchemy URL"
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="suppress progress output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="log at debug level"),
    _version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True
    ),
) -> None:
    """Set up the shared context before any sub command runs."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    ctx.obj = build_context(database, quiet=quiet)
    ctx.call_on_close(ctx.obj.close)


@app.command("init")
def init(
    ctx: typer.Context,
    path: Path | None = typer.Option(None, "--path", help="sqlite file to create"),
) -> None:
    """Create the tables. Deployments run alembic instead."""
    context = ctx.obj
    if path is not None:
        context.settings.database_url = f"sqlite+pysqlite:///{path}"
    context.database.create_all()
    typer.echo(f"initialised {context.settings.database_url}")


def run() -> None:
    """Entry point. Turns a domain error into a message and a non zero exit."""
    try:
        app()
    except BackpackingError as error:
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from error


if __name__ == "__main__":
    run()
