"""Shared fixtures.

The corridor built here is fictional but shaped like a real datasheet: a
78 mile point to point with two resupply road crossings, a long dry stretch in
the middle, three named passes and a mix of designated and dispersed camping.
Every test that needs a corridor uses this one so that a change in the shape
shows up everywhere at once.
"""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.gear.inventory import Inventory, ItemCategory, PackItem
from backpacking.pace.estimator import PaceEstimator
from backpacking.resupply.towns import ResupplyPoint, ServiceLevel, TownIndex
from backpacking.permits.quota import EntryPoint, QuotaCalendar, QuotaWindow
from backpacking.permits.zones import CampingPolicy, PermitZone, ZoneMap
from backpacking.pace.models import HikerProfile
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Segment, Surface, Waypoint, WaypointKind
from backpacking.units import Distance, Duration, Mass
from backpacking.water.sources import Reliability, WaterSource, WaterTable


def wp(
    waypoint_id: str,
    name: str,
    mile: float,
    elevation_ft: float,
    kind: WaypointKind = WaypointKind.LANDMARK,
    *,
    tags: set[str] | None = None,
) -> Waypoint:
    """Terse waypoint builder for tests."""
    return Waypoint(
        id=waypoint_id,
        name=name,
        mile=mile,
        elevation=Distance.feet(elevation_ft),
        kind=kind,
        tags=frozenset(tags or set()),
    )


SPEC: list[tuple[str, str, float, float, WaypointKind, set[str]]] = [
    ("echo-trailhead", "Echo Lake Trailhead", 0.0, 7420, WaypointKind.TRAILHEAD, set()),
    ("tamarack-creek", "Tamarack Creek", 2.4, 7680, WaypointKind.WATER, {"reliable"}),
    ("haypress-camp", "Haypress Camp", 5.1, 8010, WaypointKind.CAMPSITE, {"designated"}),
    ("lake-aloha-inlet", "Lake Aloha Inlet", 8.7, 8180, WaypointKind.WATER, {"reliable"}),
    ("mosquito-pass", "Mosquito Pass", 11.9, 8620, WaypointKind.PASS, set()),
    ("clyde-basin", "Clyde Basin", 15.3, 8040, WaypointKind.CAMPSITE, {"designated"}),
    ("rubicon-spring", "Rubicon Spring", 18.0, 7710, WaypointKind.WATER, {"seasonal"}),
    ("barker-road", "Barker Pass Road", 23.6, 7650, WaypointKind.ROAD, {"hitch"}),
    ("twin-peaks-junction", "Twin Peaks Junction", 27.2, 8100, WaypointKind.JUNCTION, set()),
    ("dry-bench", "Dry Bench", 31.8, 8340, WaypointKind.CAMPSITE, {"dispersed"}),
    ("granite-chief", "Granite Chief", 36.5, 9010, WaypointKind.SUMMIT, set()),
    ("five-lakes-creek", "Five Lakes Creek", 40.1, 7480, WaypointKind.WATER, {"reliable"}),
    ("whiskey-flat", "Whiskey Flat", 44.7, 7220, WaypointKind.CAMPSITE, {"designated"}),
    ("mule-ear-pass", "Mule Ear Pass", 49.3, 8480, WaypointKind.PASS, set()),
    ("squaw-ford", "Squaw Creek Ford", 52.0, 7300, WaypointKind.FORD, {"seasonal"}),
    ("soda-springs", "Soda Springs Road", 57.4, 6870, WaypointKind.RESUPPLY, {"hitch", "post"}),
    ("castle-saddle", "Castle Saddle", 62.9, 7960, WaypointKind.CAMPSITE, {"dispersed"}),
    ("basin-outlet", "Basin Outlet", 66.4, 7540, WaypointKind.WATER, {"reliable"}),
    ("paradise-shelter", "Paradise Shelter", 70.8, 7180, WaypointKind.SHELTER, {"designated"}),
    ("donner-pass", "Donner Pass Trailhead", 78.0, 7090, WaypointKind.TRAILHEAD, set()),
]


def build_corridor() -> Corridor:
    """The reference corridor, with measured rather than derived gain and loss."""
    waypoints = [wp(i, n, m, e, k, tags=t) for i, n, m, e, k, t in SPEC]
    rough: dict[str, tuple[float, float, Surface]] = {
        "echo-trailhead": (340, 80, Surface.TREAD),
        "tamarack-creek": (410, 80, Surface.TREAD),
        "haypress-camp": (300, 130, Surface.TREAD),
        "lake-aloha-inlet": (620, 180, Surface.TALUS),
        "mosquito-pass": (240, 820, Surface.TALUS),
        "clyde-basin": (180, 510, Surface.TREAD),
        "rubicon-spring": (700, 760, Surface.TREAD),
        "barker-road": (620, 170, Surface.TREAD),
        "twin-peaks-junction": (520, 280, Surface.TREAD),
        "dry-bench": (940, 270, Surface.TREAD),
        "granite-chief": (210, 1740, Surface.SCREE),
        "five-lakes-creek": (390, 650, Surface.TREAD),
        "whiskey-flat": (1420, 160, Surface.TREAD),
        "mule-ear-pass": (150, 1330, Surface.TALUS),
        "squaw-ford": (300, 730, Surface.TREAD),
        "soda-springs": (1290, 200, Surface.TREAD),
        "castle-saddle": (120, 540, Surface.TREAD),
        "basin-outlet": (260, 620, Surface.TREAD),
        "paradise-shelter": (480, 570, Surface.TREAD),
    }
    segments = []
    for start, end in zip(waypoints, waypoints[1:], strict=False):
        gain_ft, loss_ft, surface = rough[start.id]
        segments.append(
            Segment(
                start=start,
                end=end,
                gain=Distance.feet(gain_ft),
                loss=Distance.feet(loss_ft),
                surface=surface,
            )
        )
    return Corridor(name="Crystal Range Traverse", waypoints=tuple(waypoints), segments=tuple(segments))


@pytest.fixture
def corridor() -> Corridor:
    return build_corridor()


@pytest.fixture
def short_corridor() -> Corridor:
    """A three waypoint corridor for tests that do not need the full shape."""
    waypoints = [
        wp("start", "Start", 0.0, 5000, WaypointKind.TRAILHEAD),
        wp("middle", "Middle", 4.0, 6200, WaypointKind.CAMPSITE),
        wp("finish", "Finish", 9.0, 5400, WaypointKind.TRAILHEAD),
    ]
    return Corridor.from_waypoints("Short", waypoints)


@pytest.fixture
def hiker() -> HikerProfile:
    """A competent but not fast hiker, calibrated at 2.7 mph on the flat."""
    return HikerProfile(
        name="reference",
        flat_pace_mph=2.7,
        max_moving_hours=9.0,
        max_daily_gain_ft=6000.0,
        break_fraction=0.18,
        reference_load=Mass.pounds(26.0),
    )


@pytest.fixture
def estimator(hiker: HikerProfile) -> PaceEstimator:
    return PaceEstimator(profile=hiker)


WATER_SPEC: list[tuple[str, str, float, Reliability, float]] = [
    ("tamarack-creek", "Tamarack Creek", 2.4, Reliability.PERENNIAL, 0.0),
    ("lake-aloha-inlet", "Lake Aloha Inlet", 8.7, Reliability.PERENNIAL, 0.0),
    ("clyde-spring", "Clyde Basin Spring", 15.4, Reliability.SEASONAL, 0.1),
    ("rubicon-spring", "Rubicon Spring", 18.0, Reliability.SEASONAL, 0.2),
    ("barker-tank", "Barker Cattle Tank", 23.8, Reliability.UNRELIABLE, 0.3),
    ("five-lakes-creek", "Five Lakes Creek", 40.1, Reliability.PERENNIAL, 0.0),
    ("whiskey-seep", "Whiskey Flat Seep", 44.9, Reliability.SEASONAL, 0.05),
    ("squaw-ford", "Squaw Creek Ford", 52.0, Reliability.PERENNIAL, 0.0),
    ("soda-tap", "Soda Springs Spigot", 57.4, Reliability.PERENNIAL, 0.0),
    ("basin-outlet", "Basin Outlet", 66.4, Reliability.PERENNIAL, 0.0),
    ("paradise-creek", "Paradise Creek", 70.9, Reliability.SEASONAL, 0.15),
]


def build_water_table() -> WaterTable:
    """Water for the reference corridor, with a real dry stretch mid trail.

    The 23.8 to 40.1 gap is the interesting one: 16.3 miles with nothing usable
    in it once the cattle tank drops below threshold, which it does from July.
    """
    return WaterTable(
        [
            WaterSource(
                id=source_id,
                name=name,
                mile=mile,
                reliability=reliability,
                off_trail=Distance.miles(off_trail),
            )
            for source_id, name, mile, reliability, off_trail in WATER_SPEC
        ]
    )


@pytest.fixture
def water() -> WaterTable:
    return build_water_table()


GEAR_SPEC: list[tuple[str, str, float, ItemCategory, bool, bool]] = [
    ("pack", "Sixty litre pack", 31.0, ItemCategory.PACK, False, False),
    ("quilt", "Twenty degree quilt", 21.5, ItemCategory.SLEEP, False, False),
    ("pad", "Inflatable pad", 13.0, ItemCategory.SLEEP, False, False),
    ("shelter", "Two person tarp tent", 26.0, ItemCategory.SHELTER, False, False),
    ("stakes", "Titanium stakes", 2.4, ItemCategory.SHELTER, False, False),
    ("stove", "Canister stove", 2.6, ItemCategory.COOK, False, False),
    ("pot", "Titanium pot", 4.2, ItemCategory.COOK, False, False),
    ("filter", "Squeeze filter", 3.0, ItemCategory.WATER, False, False),
    ("bottles", "Two litre bottles", 2.2, ItemCategory.WATER, False, False),
    ("puffy", "Down jacket", 11.0, ItemCategory.CLOTHING, False, False),
    ("rain-shell", "Rain shell", 7.5, ItemCategory.CLOTHING, False, False),
    ("headlamp", "Headlamp", 3.1, ItemCategory.ELECTRONICS, False, False),
    ("battery", "Ten thousand mAh battery", 6.8, ItemCategory.ELECTRONICS, False, False),
    ("first-aid", "First aid and repair", 5.4, ItemCategory.SAFETY, False, False),
    ("beacon", "Satellite messenger", 3.5, ItemCategory.SAFETY, False, False),
    ("maps", "Printed maps", 2.0, ItemCategory.NAVIGATION, False, False),
    ("shirt", "Sun shirt", 6.0, ItemCategory.CLOTHING, True, False),
    ("shorts", "Hiking shorts", 4.5, ItemCategory.CLOTHING, True, False),
    ("shoes", "Trail runners", 21.0, ItemCategory.CLOTHING, True, False),
]


def build_inventory() -> Inventory:
    """A conventional lightweight three season list, worn items included."""
    return Inventory(
        [
            PackItem(
                id=item_id,
                name=name,
                mass=Mass.ounces(ounces),
                category=category,
                worn=worn,
                consumable=consumable,
            )
            for item_id, name, ounces, category, worn, consumable in GEAR_SPEC
        ]
    )


@pytest.fixture
def inventory() -> Inventory:
    return build_inventory()


def build_zone_map() -> ZoneMap:
    """Four zones across the reference corridor, under three agencies.

    The wilderness zone in the middle is the strict one: designated sites only,
    a three night cap, canisters required and no fires above 8,000 feet. It is
    where every interesting permit conflict happens.
    """
    return ZoneMap(
        [
            PermitZone(
                id="echo-front",
                name="Echo Front Country",
                agency="Eldorado National Forest",
                start_mile=0.0,
                end_mile=8.7,
                camping=CampingPolicy.DISPERSED,
                min_distance_from_water=Distance.feet(100),
                campfires_allowed=True,
            ),
            PermitZone(
                id="crystal-wilderness",
                name="Crystal Range Wilderness",
                agency="Eldorado National Forest",
                start_mile=8.7,
                end_mile=36.5,
                camping=CampingPolicy.DESIGNATED_ONLY,
                max_consecutive_nights=3,
                min_distance_from_water=Distance.feet(200),
                campfires_allowed=True,
                campfire_elevation_limit=Distance.feet(8000),
                canister_required=True,
                designated_sites=frozenset({"clyde-basin", "dry-bench", "haypress-camp"}),
            ),
            PermitZone(
                id="granite-state-park",
                name="Granite Chief State Park",
                agency="California State Parks",
                start_mile=36.5,
                end_mile=57.4,
                camping=CampingPolicy.DISPERSED,
                max_consecutive_nights=5,
                campfires_allowed=False,
            ),
            PermitZone(
                id="donner-north",
                name="Donner North",
                agency="Tahoe National Forest",
                start_mile=57.4,
                end_mile=78.0,
                camping=CampingPolicy.DISPERSED,
                campfires_allowed=True,
            ),
        ]
    )


def build_quota_calendar() -> QuotaCalendar:
    """Two entry points, one quotaed through the summer and one open."""
    return QuotaCalendar(
        [
            EntryPoint(
                id="echo-trailhead",
                name="Echo Lake Trailhead",
                mile=0.0,
                zone_id="echo-front",
                windows=(
                    QuotaWindow(date(2025, 6, 15), date(2025, 9, 15), daily_limit=12, walk_up_reserved=4),
                ),
                closures=frozenset({date(2025, 7, 4)}),
            ),
            EntryPoint(
                id="barker-road",
                name="Barker Pass Road",
                mile=23.6,
                zone_id="crystal-wilderness",
            ),
        ]
    )


@pytest.fixture
def zone_map() -> ZoneMap:
    return build_zone_map()


@pytest.fixture
def quota() -> QuotaCalendar:
    return build_quota_calendar()


def build_town_index() -> TownIndex:
    """Three usable stops and two that only sell crisps and fuel canisters."""
    return TownIndex(
        [
            ResupplyPoint(
                id="echo-chalet",
                name="Echo Chalet",
                mile=0.3,
                groceries=ServiceLevel.CONVENIENCE,
                walk_in=Distance.miles(0.2),
                has_post_office=False,
                open_days=frozenset({4, 5, 6}),
            ),
            ResupplyPoint(
                id="tahoma",
                name="Tahoma",
                mile=23.6,
                groceries=ServiceLevel.SMALL_GROCERY,
                hitch=Distance.miles(7.0),
                has_post_office=True,
                has_lodging=True,
                has_shower=True,
                open_days=frozenset(range(6)),
            ),
            ResupplyPoint(
                id="alpine-store",
                name="Alpine Meadows Store",
                mile=40.4,
                groceries=ServiceLevel.GAS_STATION,
                hitch=Distance.miles(2.5),
            ),
            ResupplyPoint(
                id="soda-springs",
                name="Soda Springs",
                mile=57.4,
                groceries=ServiceLevel.FULL_GROCERY,
                hitch=Distance.miles(4.0),
                shuttle_wait=Duration.minutes(20.0),
                has_post_office=True,
                has_lodging=True,
                open_days=frozenset(range(6)),
            ),
            ResupplyPoint(
                id="donner-summit",
                name="Donner Summit Lodge",
                mile=77.6,
                groceries=ServiceLevel.SMALL_GROCERY,
                hitch=Distance.miles(1.5),
                has_lodging=True,
            ),
        ]
    )


@pytest.fixture
def towns() -> TownIndex:
    return build_town_index()
