"""The relational schema.

Two decisions worth stating, because both were arrived at the hard way.

Mileage is stored as a float rather than a scaled integer. Corridor data is
never better than a tenth of a mile and mileage is re-indexed whenever an
alternate is spliced, so exact decimal arithmetic buys nothing and makes every
comparison awkward. Every mile column is indexed, because every query into these
tables is a range scan over mileage.

Elevations, masses and volumes are stored in canonical units with the unit in
the column name, and converted at the mapper. A column called ``elevation``
whose unit lives in a comment is how two of the corridor imports ended up 3.28
times too high.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for every table in the project."""


class CorridorRow(Base):
    __tablename__ = "corridors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    waypoints: Mapped[list[WaypointRow]] = relationship(
        back_populates="corridor",
        cascade="all, delete-orphan",
        order_by="WaypointRow.mile",
    )
    segments: Mapped[list[SegmentRow]] = relationship(
        back_populates="corridor",
        cascade="all, delete-orphan",
        order_by="SegmentRow.start_mile",
    )
    water_sources: Mapped[list[WaterSourceRow]] = relationship(
        back_populates="corridor", cascade="all, delete-orphan", order_by="WaterSourceRow.mile"
    )
    permit_zones: Mapped[list[PermitZoneRow]] = relationship(
        back_populates="corridor",
        cascade="all, delete-orphan",
        order_by="PermitZoneRow.start_mile",
    )
    resupply_points: Mapped[list[ResupplyPointRow]] = relationship(
        back_populates="corridor",
        cascade="all, delete-orphan",
        order_by="ResupplyPointRow.mile",
    )

    def __repr__(self) -> str:
        return f"CorridorRow(id={self.id}, slug={self.slug!r})"


class WaypointRow(Base):
    __tablename__ = "waypoints"
    __table_args__ = (
        UniqueConstraint("corridor_id", "slug", name="uq_waypoint_slug_per_corridor"),
        Index("ix_waypoint_corridor_mile", "corridor_id", "mile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corridor_id: Mapped[int] = mapped_column(ForeignKey("corridors.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    mile: Mapped[float] = mapped_column(Float)
    elevation_ft: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(32), default="landmark")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[str] = mapped_column(String(400), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    corridor: Mapped[CorridorRow] = relationship(back_populates="waypoints")

    def __repr__(self) -> str:
        return f"WaypointRow(slug={self.slug!r}, mile={self.mile})"


class SegmentRow(Base):
    __tablename__ = "segments"
    __table_args__ = (Index("ix_segment_corridor_mile", "corridor_id", "start_mile"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corridor_id: Mapped[int] = mapped_column(ForeignKey("corridors.id", ondelete="CASCADE"))
    start_slug: Mapped[str] = mapped_column(String(120))
    end_slug: Mapped[str] = mapped_column(String(120))
    start_mile: Mapped[float] = mapped_column(Float)
    end_mile: Mapped[float] = mapped_column(Float)
    gain_ft: Mapped[float] = mapped_column(Float, default=0.0)
    loss_ft: Mapped[float] = mapped_column(Float, default=0.0)
    surface: Mapped[str] = mapped_column(String(32), default="tread")
    notes: Mapped[str] = mapped_column(Text, default="")

    corridor: Mapped[CorridorRow] = relationship(back_populates="segments")

    def __repr__(self) -> str:
        return f"SegmentRow({self.start_slug!r} -> {self.end_slug!r})"


class WaterSourceRow(Base):
    __tablename__ = "water_sources"
    __table_args__ = (
        UniqueConstraint("corridor_id", "slug", name="uq_water_slug_per_corridor"),
        Index("ix_water_corridor_mile", "corridor_id", "mile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corridor_id: Mapped[int] = mapped_column(ForeignKey("corridors.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    mile: Mapped[float] = mapped_column(Float)
    reliability: Mapped[str] = mapped_column(String(32), default="seasonal")
    off_trail_miles: Mapped[float] = mapped_column(Float, default=0.0)
    needs_treatment: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    corridor: Mapped[CorridorRow] = relationship(back_populates="water_sources")

    def __repr__(self) -> str:
        return f"WaterSourceRow(slug={self.slug!r}, mile={self.mile})"


class PermitZoneRow(Base):
    __tablename__ = "permit_zones"
    __table_args__ = (
        UniqueConstraint("corridor_id", "slug", name="uq_zone_slug_per_corridor"),
        Index("ix_zone_corridor_mile", "corridor_id", "start_mile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corridor_id: Mapped[int] = mapped_column(ForeignKey("corridors.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    agency: Mapped[str] = mapped_column(String(200))
    start_mile: Mapped[float] = mapped_column(Float)
    end_mile: Mapped[float] = mapped_column(Float)
    camping: Mapped[str] = mapped_column(String(32), default="dispersed")
    max_consecutive_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_water_setback_ft: Mapped[float] = mapped_column(Float, default=0.0)
    campfires_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    campfire_limit_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    canister_required: Mapped[bool] = mapped_column(Boolean, default=False)
    designated_sites: Mapped[str] = mapped_column(String(800), default="")

    corridor: Mapped[CorridorRow] = relationship(back_populates="permit_zones")

    def __repr__(self) -> str:
        return f"PermitZoneRow(slug={self.slug!r})"


class ResupplyPointRow(Base):
    __tablename__ = "resupply_points"
    __table_args__ = (
        UniqueConstraint("corridor_id", "slug", name="uq_resupply_slug_per_corridor"),
        Index("ix_resupply_corridor_mile", "corridor_id", "mile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corridor_id: Mapped[int] = mapped_column(ForeignKey("corridors.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    mile: Mapped[float] = mapped_column(Float)
    groceries: Mapped[int] = mapped_column(Integer, default=0)
    hitch_miles: Mapped[float] = mapped_column(Float, default=0.0)
    walk_in_miles: Mapped[float] = mapped_column(Float, default=0.0)
    shuttle_wait_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    has_post_office: Mapped[bool] = mapped_column(Boolean, default=False)
    has_lodging: Mapped[bool] = mapped_column(Boolean, default=False)
    has_shower: Mapped[bool] = mapped_column(Boolean, default=False)
    open_days: Mapped[str] = mapped_column(String(32), default="0123456")
    notes: Mapped[str] = mapped_column(Text, default="")

    corridor: Mapped[CorridorRow] = relationship(back_populates="resupply_points")

    def __repr__(self) -> str:
        return f"ResupplyPointRow(slug={self.slug!r}, mile={self.mile})"


class PlanRow(Base):
    __tablename__ = "plans"
    __table_args__ = (Index("ix_plan_corridor_start", "corridor_id", "start_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corridor_id: Mapped[int] = mapped_column(ForeignKey("corridors.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(120), default="")
    hiker_name: Mapped[str] = mapped_column(String(120), default="default")
    start_date: Mapped[date] = mapped_column(Date)
    finish_date: Mapped[date] = mapped_column(Date)
    total_miles: Mapped[float] = mapped_column(Float, default=0.0)
    total_gain_ft: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    days: Mapped[list[PlanDayRow]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanDayRow.day_index"
    )

    def __repr__(self) -> str:
        return f"PlanRow(id={self.id}, label={self.label!r})"


class PlanDayRow(Base):
    __tablename__ = "plan_days"
    __table_args__ = (UniqueConstraint("plan_id", "day_index", name="uq_day_index_per_plan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    day_index: Mapped[int] = mapped_column(Integer)
    day: Mapped[date] = mapped_column(Date)
    start_mile: Mapped[float] = mapped_column(Float)
    end_mile: Mapped[float] = mapped_column(Float)
    gain_ft: Mapped[float] = mapped_column(Float, default=0.0)
    loss_ft: Mapped[float] = mapped_column(Float, default=0.0)
    moving_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    camp_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pack_weight_g: Mapped[float] = mapped_column(Float, default=0.0)
    is_zero: Mapped[bool] = mapped_column(Boolean, default=False)
    resupply_at: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    plan: Mapped[PlanRow] = relationship(back_populates="days")

    def __repr__(self) -> str:
        return f"PlanDayRow(plan={self.plan_id}, day={self.day_index})"
