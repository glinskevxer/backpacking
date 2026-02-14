"""Round tripping every domain object through the database."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session

from backpacking.config import Settings
from backpacking.errors import DataSourceError
from backpacking.pace.models import HikerProfile
from backpacking.permits.zones import CampingPolicy, ZoneMap
from backpacking.plan.itinerary import Itinerary
from backpacking.plan.solver import PlanRequest, solve
from backpacking.resupply.towns import ServiceLevel, TownIndex
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.schema import WaypointRow
from backpacking.storage.session import Database
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Surface, WaypointKind
from backpacking.water.sources import Reliability, WaterTable

START = date(2025, 7, 20)


@pytest.fixture
def database(memory_database: Database) -> Database:
    return memory_database


@pytest.fixture
def session(database: Database) -> Iterator[Session]:
    with database.session() as session:
        yield session


class TestCorridorRepository:
    def test_a_corridor_round_trips(self, session: Session, corridor: Corridor) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        loaded = repo.load("crystal-range")
        assert loaded.name == corridor.name
        assert [w.id for w in loaded] == [w.id for w in corridor]
        assert loaded.length.in_miles == pytest.approx(corridor.length.in_miles)

    def test_elevations_survive_the_round_trip(
        self, session: Session, corridor: Corridor
    ) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        loaded = repo.load("crystal-range")
        for original in corridor:
            assert loaded.waypoint(original.id).elevation.in_feet == pytest.approx(
                original.elevation.in_feet
            )

    def test_segment_profiles_survive(self, session: Session, corridor: Corridor) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        loaded = repo.load("crystal-range")
        assert loaded.total_gain().in_feet == pytest.approx(corridor.total_gain().in_feet)
        assert loaded.total_loss().in_feet == pytest.approx(corridor.total_loss().in_feet)

    def test_kinds_tags_and_surfaces_survive(
        self, session: Session, corridor: Corridor
    ) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        loaded = repo.load("crystal-range")
        assert loaded.waypoint("mosquito-pass").kind is WaypointKind.PASS
        assert loaded.waypoint("soda-springs").tags == frozenset({"hitch", "post"})
        assert loaded.segments[3].surface is Surface.TALUS

    def test_saving_twice_replaces_rather_than_duplicates(
        self, session: Session, corridor: Corridor
    ) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        repo.save(corridor.renamed("Crystal Range North"), "crystal-range")
        assert repo.load("crystal-range").name == "Crystal Range North"
        assert repo.list_slugs() == ("crystal-range",)

    def test_exists_and_list_slugs(self, session: Session, corridor: Corridor) -> None:
        repo = CorridorRepository(session)
        assert not repo.exists("crystal-range")
        repo.save(corridor, "crystal-range")
        repo.save(corridor, "another")
        assert repo.exists("crystal-range")
        assert repo.list_slugs() == ("another", "crystal-range")

    def test_loading_an_absent_corridor_raises(self, session: Session) -> None:
        with pytest.raises(DataSourceError, match="no corridor with that slug"):
            CorridorRepository(session).load("nowhere")

    def test_deleting_removes_the_waypoints_too(
        self, session: Session, corridor: Corridor
    ) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        repo.delete("crystal-range")
        session.flush()
        left = session.query(WaypointRow).count()
        assert left == 0

    def test_deleting_something_absent_raises(self, session: Session) -> None:
        with pytest.raises(DataSourceError, match="not there"):
            CorridorRepository(session).delete("nowhere")

    def test_renaming(self, session: Session, corridor: Corridor) -> None:
        repo = CorridorRepository(session)
        repo.save(corridor, "crystal-range")
        repo.rename("crystal-range", "Renamed")
        assert repo.load("crystal-range").name == "Renamed"

    def test_corridor_id_lookup(self, session: Session, corridor: Corridor) -> None:
        repo = CorridorRepository(session)
        saved = repo.save(corridor, "crystal-range")
        assert repo.corridor_id("crystal-range") == saved

    def test_an_unknown_id_lookup_raises(self, session: Session) -> None:
        with pytest.raises(DataSourceError, match="no corridor with that slug"):
            CorridorRepository(session).corridor_id("nowhere")


class TestWaterRepository:
    def test_water_round_trips(
        self, session: Session, corridor: Corridor, water: WaterTable
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = WaterRepository(session)
        repo.save(corridor_id, list(water))
        loaded = repo.load(corridor_id)
        assert len(loaded) == len(water)
        assert loaded.get("rubicon-spring").reliability is Reliability.SEASONAL

    def test_off_trail_distance_survives(
        self, session: Session, corridor: Corridor, water: WaterTable
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = WaterRepository(session)
        repo.save(corridor_id, list(water))
        assert repo.load(corridor_id).get("barker-tank").off_trail.in_miles == pytest.approx(0.3)

    def test_saving_twice_replaces(
        self, session: Session, corridor: Corridor, water: WaterTable
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = WaterRepository(session)
        repo.save(corridor_id, list(water))
        repo.save(corridor_id, list(water)[:3])
        assert len(repo.load(corridor_id)) == 3

    def test_an_empty_table_loads_as_empty(self, session: Session, corridor: Corridor) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        assert len(WaterRepository(session).load(corridor_id)) == 0


class TestPermitRepository:
    def test_zones_round_trip(
        self, session: Session, corridor: Corridor, zone_map: ZoneMap
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PermitRepository(session)
        repo.save(corridor_id, list(zone_map))
        loaded = repo.load(corridor_id)
        assert len(loaded) == len(zone_map)
        assert loaded.agencies() == zone_map.agencies()

    def test_the_strict_zone_keeps_its_rules(
        self, session: Session, corridor: Corridor, zone_map: ZoneMap
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PermitRepository(session)
        repo.save(corridor_id, list(zone_map))
        wilderness = repo.load(corridor_id).get("crystal-wilderness")
        assert wilderness.camping is CampingPolicy.DESIGNATED_ONLY
        assert wilderness.max_consecutive_nights == 3
        assert wilderness.canister_required
        assert wilderness.designated_sites == frozenset(
            {"clyde-basin", "dry-bench", "haypress-camp"}
        )

    def test_the_campfire_elevation_limit_survives(
        self, session: Session, corridor: Corridor, zone_map: ZoneMap
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PermitRepository(session)
        repo.save(corridor_id, list(zone_map))
        limit = repo.load(corridor_id).get("crystal-wilderness").campfire_elevation_limit
        assert limit is not None
        assert limit.in_feet == pytest.approx(8000.0)

    def test_a_zone_without_a_limit_stays_none(
        self, session: Session, corridor: Corridor, zone_map: ZoneMap
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PermitRepository(session)
        repo.save(corridor_id, list(zone_map))
        assert repo.load(corridor_id).get("donner-north").campfire_elevation_limit is None


class TestResupplyRepository:
    def test_points_round_trip(
        self, session: Session, corridor: Corridor, towns: TownIndex
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = ResupplyRepository(session)
        repo.save(corridor_id, list(towns))
        loaded = repo.load(corridor_id)
        assert len(loaded) == len(towns)
        assert loaded.get("soda-springs").groceries is ServiceLevel.FULL_GROCERY

    def test_access_details_survive(
        self, session: Session, corridor: Corridor, towns: TownIndex
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = ResupplyRepository(session)
        repo.save(corridor_id, list(towns))
        soda = repo.load(corridor_id).get("soda-springs")
        assert soda.hitch.in_miles == pytest.approx(4.0)
        assert soda.shuttle_wait.in_minutes == pytest.approx(20.0)

    def test_open_days_survive(
        self, session: Session, corridor: Corridor, towns: TownIndex
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = ResupplyRepository(session)
        repo.save(corridor_id, list(towns))
        assert repo.load(corridor_id).get("echo-chalet").open_days == frozenset({4, 5, 6})


class TestPlanRepository:
    @pytest.fixture
    def plan(self, corridor: Corridor, hiker: HikerProfile) -> Itinerary:
        return solve(PlanRequest(corridor=corridor, profile=hiker, start_date=START))

    def test_a_plan_round_trips(
        self, session: Session, corridor: Corridor, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PlanRepository(session)
        plan_id = repo.save(plan, corridor_id, hiker.name)
        loaded = repo.load(plan_id, corridor)
        assert len(loaded) == len(plan)
        assert loaded.start_date == plan.start_date
        assert loaded.total_distance.in_miles == pytest.approx(plan.total_distance.in_miles)

    def test_the_day_estimates_survive(
        self, session: Session, corridor: Corridor, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PlanRepository(session)
        loaded = repo.load(repo.save(plan, corridor_id, hiker.name), corridor)
        for original, restored in zip(plan, loaded, strict=True):
            assert restored.estimate.gain.in_feet == pytest.approx(original.estimate.gain.in_feet)
            assert restored.elapsed.in_seconds == pytest.approx(original.elapsed.in_seconds)

    def test_camps_are_reattached_to_the_corridor(
        self, session: Session, corridor: Corridor, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PlanRepository(session)
        loaded = repo.load(repo.save(plan, corridor_id, hiker.name), corridor)
        assert [day.camp_id for day in loaded] == [day.camp_id for day in plan]

    def test_plans_are_listed_for_a_corridor(
        self, session: Session, corridor: Corridor, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PlanRepository(session)
        repo.save(plan, corridor_id, hiker.name)
        repo.save(plan.shifted_to(date(2025, 8, 1)), corridor_id, hiker.name)
        listed = repo.list_for_corridor(corridor_id)
        assert len(listed) == 2
        assert [row[2] for row in listed] == [START, date(2025, 8, 1)]

    def test_plans_can_be_found_by_start_window(
        self, session: Session, corridor: Corridor, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PlanRepository(session)
        repo.save(plan, corridor_id, hiker.name)
        repo.save(plan.shifted_to(date(2025, 9, 1)), corridor_id, hiker.name)
        assert len(repo.starting_between(date(2025, 7, 1), date(2025, 7, 31))) == 1

    def test_deleting_a_plan(
        self, session: Session, corridor: Corridor, plan: Itinerary, hiker: HikerProfile
    ) -> None:
        corridor_id = CorridorRepository(session).save(corridor, "crystal-range")
        repo = PlanRepository(session)
        plan_id = repo.save(plan, corridor_id, hiker.name)
        repo.delete(plan_id)
        with pytest.raises(DataSourceError, match="no plan with that id"):
            repo.load(plan_id, corridor)

    def test_deleting_an_absent_plan_raises(self, session: Session) -> None:
        with pytest.raises(DataSourceError, match="not there"):
            PlanRepository(session).delete(9999)


class TestDatabase:
    def test_the_session_scope_commits_on_success(
        self, database: Database, corridor: Corridor
    ) -> None:
        with database.session() as session:
            CorridorRepository(session).save(corridor, "crystal-range")
        with database.session() as session:
            assert CorridorRepository(session).exists("crystal-range")

    def test_the_session_scope_rolls_back_on_failure(
        self, database: Database, corridor: Corridor
    ) -> None:
        with pytest.raises(RuntimeError), database.session() as session:
            CorridorRepository(session).save(corridor, "crystal-range")
            raise RuntimeError("something went wrong")
        with database.session() as session:
            assert not CorridorRepository(session).exists("crystal-range")

    def test_repr_hides_credentials(self, database: Database) -> None:
        assert "sqlite" in repr(database)

    def test_drop_all_removes_the_tables(self, database: Database) -> None:
        database.drop_all()
        database.create_all()
        with database.session() as session:
            assert CorridorRepository(session).list_slugs() == ()
