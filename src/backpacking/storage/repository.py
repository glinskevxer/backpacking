"""Repositories: the only code outside :mod:`backpacking.storage` may call.

Everything above this layer works in domain objects. Nothing above it imports a
row class, writes a query, or knows that ``elevation_ft`` is a column name. That
is not architectural purity for its own sake; it is what lets the corridor code
be tested without a database at all, which is why the test suite runs in seconds.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from backpacking.errors import DataSourceError
from backpacking.permits.zones import PermitZone, ZoneMap
from backpacking.plan.itinerary import Itinerary
from backpacking.resupply.towns import ResupplyPoint, TownIndex
from backpacking.storage import mappers
from backpacking.storage.schema import (
    CorridorRow,
    PermitZoneRow,
    PlanRow,
    ResupplyPointRow,
    WaterSourceRow,
)
from backpacking.trail.corridor import Corridor
from backpacking.water.sources import WaterSource, WaterTable


class CorridorRepository:
    """Corridors and everything hanging off one."""

    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def _row(self, slug: str) -> CorridorRow:
        statement = (
            select(CorridorRow)
            .where(CorridorRow.slug == slug)
            .options(
                selectinload(CorridorRow.waypoints),
                selectinload(CorridorRow.segments),
            )
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            raise DataSourceError("no corridor with that slug", slug=slug)
        return row

    def exists(self, slug: str) -> bool:
        statement = select(CorridorRow.id).where(CorridorRow.slug == slug)
        return self.session.execute(statement).scalar_one_or_none() is not None

    def save(self, corridor: Corridor, slug: str, *, region: str = "") -> int:
        """Insert a corridor, or replace the one already under this slug."""
        if self.exists(slug):
            self.delete(slug)
        row = mappers.corridor_to_rows(corridor, slug)
        row.region = region
        self.session.add(row)
        self.session.flush()
        return row.id

    def load(self, slug: str) -> Corridor:
        return mappers.rows_to_corridor(self._row(slug))

    def delete(self, slug: str) -> None:
        row = self.session.execute(
            select(CorridorRow).where(CorridorRow.slug == slug)
        ).scalar_one_or_none()
        if row is None:
            raise DataSourceError("cannot delete a corridor that is not there", slug=slug)
        self.session.delete(row)
        self.session.flush()

    def list_slugs(self) -> tuple[str, ...]:
        statement = select(CorridorRow.slug).order_by(CorridorRow.slug)
        return tuple(self.session.execute(statement).scalars().all())

    def corridor_id(self, slug: str) -> int:
        statement = select(CorridorRow.id).where(CorridorRow.slug == slug)
        found = self.session.execute(statement).scalar_one_or_none()
        if found is None:
            raise DataSourceError("no corridor with that slug", slug=slug)
        return found

    def rename(self, slug: str, name: str) -> None:
        row = self._row(slug)
        row.name = name
        self.session.flush()


class WaterRepository:
    """Water sources for one corridor at a time."""

    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, corridor_id: int, sources: Sequence[WaterSource]) -> None:
        self.session.execute(
            delete(WaterSourceRow).where(WaterSourceRow.corridor_id == corridor_id)
        )
        for source in sources:
            self.session.add(mappers.water_source_to_row(source, corridor_id))
        self.session.flush()

    def load(self, corridor_id: int) -> WaterTable:
        statement = (
            select(WaterSourceRow)
            .where(WaterSourceRow.corridor_id == corridor_id)
            .order_by(WaterSourceRow.mile)
        )
        return mappers.rows_to_water_table(list(self.session.execute(statement).scalars().all()))


class PermitRepository:
    """Permit zones for one corridor at a time."""

    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, corridor_id: int, zones: Sequence[PermitZone]) -> None:
        self.session.execute(
            delete(PermitZoneRow).where(PermitZoneRow.corridor_id == corridor_id)
        )
        for zone in zones:
            self.session.add(mappers.permit_zone_to_row(zone, corridor_id))
        self.session.flush()

    def load(self, corridor_id: int) -> ZoneMap:
        statement = (
            select(PermitZoneRow)
            .where(PermitZoneRow.corridor_id == corridor_id)
            .order_by(PermitZoneRow.start_mile)
        )
        return mappers.rows_to_zone_map(list(self.session.execute(statement).scalars().all()))


class ResupplyRepository:
    """Resupply points for one corridor at a time."""

    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, corridor_id: int, points: Sequence[ResupplyPoint]) -> None:
        self.session.execute(
            delete(ResupplyPointRow).where(ResupplyPointRow.corridor_id == corridor_id)
        )
        for point in points:
            self.session.add(mappers.resupply_to_row(point, corridor_id))
        self.session.flush()

    def load(self, corridor_id: int) -> TownIndex:
        statement = (
            select(ResupplyPointRow)
            .where(ResupplyPointRow.corridor_id == corridor_id)
            .order_by(ResupplyPointRow.mile)
        )
        return mappers.rows_to_town_index(list(self.session.execute(statement).scalars().all()))


class PlanRepository:
    """Saved itineraries."""

    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, itinerary: Itinerary, corridor_id: int, hiker_name: str) -> int:
        row = mappers.itinerary_to_rows(itinerary, corridor_id, hiker_name)
        self.session.add(row)
        self.session.flush()
        return row.id

    def load(self, plan_id: int, corridor: Corridor) -> Itinerary:
        statement = (
            select(PlanRow).where(PlanRow.id == plan_id).options(selectinload(PlanRow.days))
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            raise DataSourceError("no plan with that id", plan_id=plan_id)
        return mappers.rows_to_itinerary(row, corridor)

    def delete(self, plan_id: int) -> None:
        row = self.session.get(PlanRow, plan_id)
        if row is None:
            raise DataSourceError("cannot delete a plan that is not there", plan_id=plan_id)
        self.session.delete(row)
        self.session.flush()

    def list_for_corridor(self, corridor_id: int) -> tuple[tuple[int, str, date], ...]:
        statement = (
            select(PlanRow.id, PlanRow.label, PlanRow.start_date)
            .where(PlanRow.corridor_id == corridor_id)
            .order_by(PlanRow.start_date, PlanRow.id)
        )
        return tuple(
            (row_id, label, start) for row_id, label, start in self.session.execute(statement)
        )

    def starting_between(self, first: date, last: date) -> tuple[int, ...]:
        statement = (
            select(PlanRow.id)
            .where(PlanRow.start_date >= first, PlanRow.start_date <= last)
            .order_by(PlanRow.start_date)
        )
        return tuple(self.session.execute(statement).scalars().all())
