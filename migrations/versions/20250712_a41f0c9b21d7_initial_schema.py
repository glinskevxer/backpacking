"""initial schema

Revision ID: a41f0c9b21d7
Revises:
Create Date: 2025-07-12 09:14:22.481093+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a41f0c9b21d7"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corridors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_corridors_slug", "corridors", ["slug"], unique=True)

    op.create_table(
        "waypoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("corridor_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("mile", sa.Float(), nullable=False),
        sa.Column("elevation_ft", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("tags", sa.String(length=400), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["corridor_id"], ["corridors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corridor_id", "slug", name="uq_waypoint_slug_per_corridor"),
    )
    op.create_index("ix_waypoint_corridor_mile", "waypoints", ["corridor_id", "mile"])

    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("corridor_id", sa.Integer(), nullable=False),
        sa.Column("start_slug", sa.String(length=120), nullable=False),
        sa.Column("end_slug", sa.String(length=120), nullable=False),
        sa.Column("start_mile", sa.Float(), nullable=False),
        sa.Column("end_mile", sa.Float(), nullable=False),
        sa.Column("gain_ft", sa.Float(), nullable=False),
        sa.Column("loss_ft", sa.Float(), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["corridor_id"], ["corridors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_segment_corridor_mile", "segments", ["corridor_id", "start_mile"])

    op.create_table(
        "water_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("corridor_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("mile", sa.Float(), nullable=False),
        sa.Column("reliability", sa.String(length=32), nullable=False),
        sa.Column("off_trail_miles", sa.Float(), nullable=False),
        sa.Column("needs_treatment", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["corridor_id"], ["corridors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corridor_id", "slug", name="uq_water_slug_per_corridor"),
    )
    op.create_index("ix_water_corridor_mile", "water_sources", ["corridor_id", "mile"])

    op.create_table(
        "permit_zones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("corridor_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("agency", sa.String(length=200), nullable=False),
        sa.Column("start_mile", sa.Float(), nullable=False),
        sa.Column("end_mile", sa.Float(), nullable=False),
        sa.Column("camping", sa.String(length=32), nullable=False),
        sa.Column("max_consecutive_nights", sa.Integer(), nullable=True),
        sa.Column("min_water_setback_ft", sa.Float(), nullable=False),
        sa.Column("campfires_allowed", sa.Boolean(), nullable=False),
        sa.Column("campfire_limit_ft", sa.Float(), nullable=True),
        sa.Column("canister_required", sa.Boolean(), nullable=False),
        sa.Column("designated_sites", sa.String(length=800), nullable=False),
        sa.ForeignKeyConstraint(["corridor_id"], ["corridors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corridor_id", "slug", name="uq_zone_slug_per_corridor"),
    )
    op.create_index("ix_zone_corridor_mile", "permit_zones", ["corridor_id", "start_mile"])

    op.create_table(
        "resupply_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("corridor_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("mile", sa.Float(), nullable=False),
        sa.Column("groceries", sa.Integer(), nullable=False),
        sa.Column("hitch_miles", sa.Float(), nullable=False),
        sa.Column("walk_in_miles", sa.Float(), nullable=False),
        sa.Column("shuttle_wait_minutes", sa.Float(), nullable=False),
        sa.Column("has_post_office", sa.Boolean(), nullable=False),
        sa.Column("has_lodging", sa.Boolean(), nullable=False),
        sa.Column("has_shower", sa.Boolean(), nullable=False),
        sa.Column("open_days", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["corridor_id"], ["corridors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corridor_id", "slug", name="uq_resupply_slug_per_corridor"),
    )
    op.create_index("ix_resupply_corridor_mile", "resupply_points", ["corridor_id", "mile"])

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("corridor_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("hiker_name", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("finish_date", sa.Date(), nullable=False),
        sa.Column("total_miles", sa.Float(), nullable=False),
        sa.Column("total_gain_ft", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["corridor_id"], ["corridors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_corridor_start", "plans", ["corridor_id", "start_date"])

    op.create_table(
        "plan_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("start_mile", sa.Float(), nullable=False),
        sa.Column("end_mile", sa.Float(), nullable=False),
        sa.Column("gain_ft", sa.Float(), nullable=False),
        sa.Column("loss_ft", sa.Float(), nullable=False),
        sa.Column("moving_seconds", sa.Float(), nullable=False),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False),
        sa.Column("camp_slug", sa.String(length=120), nullable=True),
        sa.Column("pack_weight_g", sa.Float(), nullable=False),
        sa.Column("is_zero", sa.Boolean(), nullable=False),
        sa.Column("resupply_at", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "day_index", name="uq_day_index_per_plan"),
    )


def downgrade() -> None:
    op.drop_table("plan_days")
    op.drop_index("ix_plan_corridor_start", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_resupply_corridor_mile", table_name="resupply_points")
    op.drop_table("resupply_points")
    op.drop_index("ix_zone_corridor_mile", table_name="permit_zones")
    op.drop_table("permit_zones")
    op.drop_index("ix_water_corridor_mile", table_name="water_sources")
    op.drop_table("water_sources")
    op.drop_index("ix_segment_corridor_mile", table_name="segments")
    op.drop_table("segments")
    op.drop_index("ix_waypoint_corridor_mile", table_name="waypoints")
    op.drop_table("waypoints")
    op.drop_index("ix_corridors_slug", table_name="corridors")
    op.drop_table("corridors")
