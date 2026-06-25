"""The tabular corridor format this project stores and exchanges.

GPX carries geometry and no planning metadata. A datasheet carries the planning
metadata and only enough geometry to be useful: the cumulative mile, the spot
elevation, what the point is and how the leg to the next point behaves. It is a
plain CSV so that it can be edited in a spreadsheet on a town day, which is the
only realistic editing environment on a long trail.

Column order is not significant. Unknown columns are preserved on read and
written back out, so a planner can keep their own notes in the same file.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from backpacking.errors import DataSourceError
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Segment, Surface, Waypoint, WaypointKind
from backpacking.units import Distance

REQUIRED_COLUMNS = ("mile", "id", "name", "elevation_ft")
KNOWN_COLUMNS = (
    *REQUIRED_COLUMNS,
    "kind",
    "tags",
    "gain_ft",
    "loss_ft",
    "surface",
    "notes",
)


@dataclass(frozen=True, slots=True)
class DatasheetRow:
    """One line of a datasheet, before it becomes a waypoint and a segment."""

    mile: float
    id: str
    name: str
    elevation_ft: float
    kind: WaypointKind = WaypointKind.LANDMARK
    tags: frozenset[str] = field(default_factory=frozenset)
    gain_ft: float | None = None
    loss_ft: float | None = None
    surface: Surface = Surface.TREAD
    notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def to_waypoint(self) -> Waypoint:
        return Waypoint(
            id=self.id,
            name=self.name,
            mile=self.mile,
            elevation=Distance.feet(self.elevation_ft),
            kind=self.kind,
            tags=self.tags,
            notes=self.notes,
        )


def parse_datasheet(text: str) -> list[DatasheetRow]:
    """Parse a datasheet from CSV text into rows, in file order."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise DataSourceError("datasheet has no header row")
    header = [name.strip() for name in reader.fieldnames]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise DataSourceError(
            "datasheet is missing required columns", missing=missing, header=header
        )
    rows: list[DatasheetRow] = []
    for line_number, raw in enumerate(reader, start=2):
        rows.append(_parse_row({k.strip(): (v or "").strip() for k, v in raw.items()}, line_number))
    if not rows:
        raise DataSourceError("datasheet contains no rows")
    return rows


def _parse_row(raw: dict[str, str], line_number: int) -> DatasheetRow:
    mile = _require_float(raw, "mile", line_number)
    elevation = _require_float(raw, "elevation_ft", line_number)
    identifier = raw.get("id", "")
    name = raw.get("name", "")
    if not identifier:
        raise DataSourceError("datasheet row has no id", line=line_number)
    kind_text = raw.get("kind", "").lower()
    try:
        kind = WaypointKind(kind_text) if kind_text else WaypointKind.LANDMARK
    except ValueError as exc:
        raise DataSourceError("unknown waypoint kind", line=line_number, kind=kind_text) from exc
    surface_text = raw.get("surface", "").lower()
    try:
        surface = Surface(surface_text) if surface_text else Surface.TREAD
    except ValueError as exc:
        raise DataSourceError("unknown surface", line=line_number, surface=surface_text) from exc
    tags = frozenset(t.strip() for t in raw.get("tags", "").split("|") if t.strip())
    extra = {k: v for k, v in raw.items() if k not in KNOWN_COLUMNS and v}
    return DatasheetRow(
        mile=mile,
        id=identifier,
        name=name or identifier,
        elevation_ft=elevation,
        kind=kind,
        tags=tags,
        gain_ft=_optional_float(raw, "gain_ft", line_number),
        loss_ft=_optional_float(raw, "loss_ft", line_number),
        surface=surface,
        notes=raw.get("notes", ""),
        extra=extra,
    )


def _require_float(raw: dict[str, str], column: str, line_number: int) -> float:
    value = raw.get(column, "")
    if not value:
        raise DataSourceError("required column is empty", line=line_number, column=column)
    try:
        return float(value)
    except ValueError as exc:
        raise DataSourceError(
            "column is not a number", line=line_number, column=column, value=value
        ) from exc


def _optional_float(raw: dict[str, str], column: str, line_number: int) -> float | None:
    value = raw.get(column, "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise DataSourceError(
            "column is not a number", line=line_number, column=column, value=value
        ) from exc


def load_datasheet(path: Path) -> list[DatasheetRow]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataSourceError("could not read datasheet", path=str(path)) from exc
    return parse_datasheet(text)


def corridor_from_rows(name: str, rows: Sequence[DatasheetRow]) -> Corridor:
    """Turn parsed rows into a corridor, using measured gain where it is given.

    A row that supplies neither gain nor loss falls back to the elevation
    difference to the next row, which is the same reading
    :meth:`Corridor.from_waypoints` takes.
    """
    ordered = sorted(rows, key=lambda r: r.mile)
    waypoints = [row.to_waypoint() for row in ordered]
    segments: list[Segment] = []
    for row, start, end in zip(ordered, waypoints, waypoints[1:], strict=False):
        delta = end.elevation.in_feet - start.elevation.in_feet
        gain = row.gain_ft if row.gain_ft is not None else max(0.0, delta)
        loss = row.loss_ft if row.loss_ft is not None else max(0.0, -delta)
        segments.append(
            Segment(
                start=start,
                end=end,
                gain=Distance.feet(gain),
                loss=Distance.feet(loss),
                surface=row.surface,
                notes=row.notes,
            )
        )
    return Corridor(name=name, waypoints=tuple(waypoints), segments=tuple(segments))


def load_corridor(path: Path, name: str | None = None) -> Corridor:
    """Read a datasheet straight into a corridor, named after the file by default."""
    rows = load_datasheet(path)
    return corridor_from_rows(name or path.stem.replace("-", " ").title(), rows)


def write_datasheet(rows: Iterable[DatasheetRow]) -> str:
    """Serialise rows back to CSV, keeping any unknown columns they carried."""
    materialised = list(rows)
    if not materialised:
        raise DataSourceError("cannot write a datasheet with no rows")
    extra_columns: list[str] = []
    for row in materialised:
        for column in row.extra:
            if column not in extra_columns:
                extra_columns.append(column)
    header = [*KNOWN_COLUMNS, *extra_columns]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    for row in materialised:
        record: dict[str, str] = {
            "mile": f"{row.mile:g}",
            "id": row.id,
            "name": row.name,
            "elevation_ft": f"{row.elevation_ft:g}",
            "kind": row.kind.value,
            "tags": "|".join(sorted(row.tags)),
            "gain_ft": "" if row.gain_ft is None else f"{row.gain_ft:g}",
            "loss_ft": "" if row.loss_ft is None else f"{row.loss_ft:g}",
            "surface": row.surface.value,
            "notes": row.notes,
        }
        record.update(row.extra)
        writer.writerow(record)
    return buffer.getvalue()


def corridor_to_rows(corridor: Corridor) -> list[DatasheetRow]:
    """The inverse of :func:`corridor_from_rows`, for export."""
    by_start = {segment.start.id: segment for segment in corridor.segments}
    out: list[DatasheetRow] = []
    for waypoint in corridor.waypoints:
        segment = by_start.get(waypoint.id)
        out.append(
            DatasheetRow(
                mile=waypoint.mile,
                id=waypoint.id,
                name=waypoint.name,
                elevation_ft=waypoint.elevation.in_feet,
                kind=waypoint.kind,
                tags=waypoint.tags,
                gain_ft=None if segment is None else segment.gain.in_feet,
                loss_ft=None if segment is None else segment.loss.in_feet,
                surface=Surface.TREAD if segment is None else segment.surface,
                notes=waypoint.notes,
            )
        )
    return out
