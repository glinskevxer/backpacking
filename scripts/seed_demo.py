#!/usr/bin/env python
"""Load a small sample corridor so a fresh checkout has something to plan over.

Not test fixtures. The numbers here are made up but the shape is real, and the
point is that ``make seed && make serve`` gives a working service rather than an
empty database and a 404.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from backpacking.config import Settings
from backpacking.permits.zones import CampingPolicy, PermitZone
from backpacking.resupply.towns import ResupplyPoint, ServiceLevel
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Waypoint, WaypointKind
from backpacking.units import Distance
from backpacking.water.sources import Reliability, WaterSource

SLUG = "sample-traverse"

WAYPOINTS: list[tuple[str, str, float, float, WaypointKind]] = [
    ("south-trailhead", "South Trailhead", 0.0, 6400, WaypointKind.TRAILHEAD),
    ("willow-creek", "Willow Creek", 3.2, 6800, WaypointKind.WATER),
    ("bench-camp", "Bench Camp", 7.4, 7550, WaypointKind.CAMPSITE),
    ("saddle-pass", "Saddle Pass", 11.8, 8900, WaypointKind.PASS),
    ("mirror-lake", "Mirror Lake", 15.1, 8100, WaypointKind.CAMPSITE),
    ("forest-road", "Forest Road 22", 21.0, 6900, WaypointKind.ROAD),
    ("stony-ford", "Stony Ford", 25.6, 6500, WaypointKind.FORD),
    ("high-camp", "High Camp", 30.2, 8250, WaypointKind.CAMPSITE),
    ("north-trailhead", "North Trailhead", 36.0, 6700, WaypointKind.TRAILHEAD),
]

WATER: list[tuple[str, str, float, Reliability]] = [
    ("willow-creek-src", "Willow Creek", 3.2, Reliability.PERENNIAL),
    ("bench-spring", "Bench Spring", 7.6, Reliability.SEASONAL),
    ("mirror-lake-src", "Mirror Lake", 15.1, Reliability.PERENNIAL),
    ("stony-ford-src", "Stony Ford", 25.6, Reliability.PERENNIAL),
]


def build_corridor() -> Corridor:
    waypoints = [
        Waypoint(
            id=slug,
            name=name,
            mile=mile,
            elevation=Distance.feet(elevation),
            kind=kind,
        )
        for slug, name, mile, elevation, kind in WAYPOINTS
    ]
    return Corridor.from_waypoints("Sample Traverse", waypoints)


def seed(database_url: str | None, *, replace: bool) -> int:
    settings = Settings(database_url=database_url) if database_url else Settings()
    database = Database(settings)
    database.create_all()
    with database.session() as session:
        corridors = CorridorRepository(session)
        if corridors.exists(SLUG) and not replace:
            print(f"{SLUG} is already loaded, pass --replace to overwrite")
            return 1
        corridor_id = corridors.save(build_corridor(), SLUG, region="demo")
        WaterRepository(session).save(
            corridor_id,
            [
                WaterSource(id=slug, name=name, mile=mile, reliability=reliability)
                for slug, name, mile, reliability in WATER
            ],
        )
        PermitRepository(session).save(
            corridor_id,
            [
                PermitZone(
                    id="south-front",
                    name="South Front Country",
                    agency="Demo Forest",
                    start_mile=0.0,
                    end_mile=11.8,
                ),
                PermitZone(
                    id="high-wilderness",
                    name="High Wilderness",
                    agency="Demo Forest",
                    start_mile=11.8,
                    end_mile=36.0,
                    camping=CampingPolicy.DESIGNATED_ONLY,
                    max_consecutive_nights=2,
                    canister_required=True,
                    designated_sites=frozenset({"mirror-lake", "high-camp"}),
                ),
            ],
        )
        ResupplyRepository(session).save(
            corridor_id,
            [
                ResupplyPoint(
                    id="junction-store",
                    name="Junction Store",
                    mile=21.0,
                    groceries=ServiceLevel.SMALL_GROCERY,
                    hitch=Distance.miles(3.0),
                    has_post_office=True,
                )
            ],
        )
    database.dispose()
    print(f"loaded {SLUG}: {len(WAYPOINTS)} waypoints, {len(WATER)} water sources")
    print(f"try: backpacking plan build {SLUG} --start {date.today().isoformat()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="SQLAlchemy URL, defaults to the configured one")
    parser.add_argument("--replace", action="store_true", help="overwrite an existing load")
    args = parser.parse_args()
    return seed(args.database, replace=args.replace)


if __name__ == "__main__":
    sys.exit(main())
