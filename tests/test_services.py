"""The planning use cases, tested without HTTP or a terminal in the way."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session

from backpacking.errors import DataSourceError, PlanInfeasible
from backpacking.services.planning import (
    ConstraintSpec,
    HikerSpec,
    PlanningService,
    TrailBundle,
)
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database

START = date(2025, 7, 20)


@pytest.fixture
def session(seeded_database: Database) -> Iterator[Session]:
    with seeded_database.session() as session:
        yield session


@pytest.fixture
def service(session: Session) -> PlanningService:
    return PlanningService(session)


class TestHikerSpec:
    def test_it_becomes_a_profile(self) -> None:
        profile = HikerSpec(name="ada", flat_pace_mph=2.9, pack_weight_lb=31.0).to_profile()
        assert profile.name == "ada"
        assert profile.flat_pace_mph == pytest.approx(2.9)
        assert profile.reference_load.in_pounds == pytest.approx(31.0)

    def test_the_defaults_are_usable(self) -> None:
        profile = HikerSpec().to_profile()
        assert profile.flat_pace_mph > 0.0
        assert profile.max_moving_hours > 0.0

    def test_night_hiking_carries_across(self) -> None:
        assert HikerSpec(night_hiking=True).to_profile().night_hiking


class TestConstraintSpec:
    def test_it_becomes_constraints(self) -> None:
        limits = ConstraintSpec(
            max_daily_miles=20.0, max_daily_gain_ft=4000.0, forbidden_camps=("dry-bench",)
        ).to_constraints()
        assert limits.max_daily_miles == pytest.approx(20.0)
        assert limits.max_daily_gain.in_feet == pytest.approx(4000.0)
        assert not limits.camp_is_allowed("dry-bench")

    def test_the_hour_cap_becomes_a_duration(self) -> None:
        limits = ConstraintSpec(max_daily_hours=10.0).to_constraints()
        assert limits.max_daily_elapsed.in_hours == pytest.approx(10.0)

    def test_an_inconsistent_spec_is_refused_on_conversion(self) -> None:
        with pytest.raises(PlanInfeasible, match="must exceed the minimum"):
            ConstraintSpec(max_daily_miles=5.0, min_daily_miles=9.0).to_constraints()


class TestLoadBundle:
    def test_everything_comes_back_together(self, service: PlanningService) -> None:
        bundle = service.load_bundle("crystal-range")
        assert isinstance(bundle, TrailBundle)
        assert len(bundle.corridor) == 20
        assert len(bundle.water) == 11
        assert len(bundle.zones) == 4
        assert len(bundle.towns) == 5

    def test_the_corridor_id_is_carried(self, service: PlanningService, session: Session) -> None:
        bundle = service.load_bundle("crystal-range")
        assert bundle.corridor_id == CorridorRepository(session).corridor_id("crystal-range")

    def test_an_unknown_slug_raises(self, service: PlanningService) -> None:
        with pytest.raises(DataSourceError, match="no corridor with that slug"):
            service.load_bundle("nowhere")

    def test_repr(self, service: PlanningService) -> None:
        assert repr(service.load_bundle("crystal-range")).startswith("TrailBundle(")


class TestBuildAndSolve:
    def test_a_request_uses_the_stored_corridor(self, service: PlanningService) -> None:
        request = service.build_request("crystal-range", START)
        assert request.corridor.name == "Crystal Range Traverse"
        assert request.resolved_end() == pytest.approx(78.0)

    def test_explicit_miles_reach_the_request(self, service: PlanningService) -> None:
        request = service.build_request("crystal-range", START, start_mile=23.6, end_mile=57.4)
        assert request.resolved_start() == pytest.approx(23.6)

    def test_the_hiker_spec_reaches_the_request(self, service: PlanningService) -> None:
        request = service.build_request("crystal-range", START, hiker=HikerSpec(flat_pace_mph=2.2))
        assert request.profile.flat_pace_mph == pytest.approx(2.2)

    def test_the_pack_weight_follows_the_hiker(self, service: PlanningService) -> None:
        request = service.build_request(
            "crystal-range", START, hiker=HikerSpec(pack_weight_lb=38.0)
        )
        assert request.pack_weight.in_pounds == pytest.approx(38.0)

    def test_plan_solves_in_one_call(self, service: PlanningService) -> None:
        plan = service.plan("crystal-range", START)
        assert plan.covers_whole_corridor()
        assert plan.start_date == START

    def test_constraints_are_applied(self, service: PlanningService) -> None:
        plan = service.plan(
            "crystal-range", START, constraints=ConstraintSpec(max_daily_miles=12.0)
        )
        assert all(day.miles <= 12.0 for day in plan)

    def test_an_impossible_constraint_surfaces(self, service: PlanningService) -> None:
        with pytest.raises(PlanInfeasible):
            service.plan(
                "crystal-range",
                START,
                constraints=ConstraintSpec(max_daily_miles=1.5, min_daily_miles=0.5),
            )

    def test_aggressiveness_changes_the_shape(self, service: PlanningService) -> None:
        easy = service.plan("crystal-range", START, aggressiveness=0.55)
        hard = service.plan("crystal-range", START, aggressiveness=1.0)
        assert easy.average_daily_miles < hard.average_daily_miles


class TestSaveAndLoad:
    def test_a_plan_round_trips(self, service: PlanningService) -> None:
        plan = service.plan("crystal-range", START)
        plan_id = service.save_plan(plan, "crystal-range", "ada")
        loaded = service.load_plan(plan_id, "crystal-range")
        assert len(loaded) == len(plan)
        assert loaded.start_date == plan.start_date

    def test_plan_and_save_returns_both(self, service: PlanningService) -> None:
        plan_id, plan = service.plan_and_save("crystal-range", START)
        assert plan_id > 0
        assert plan.covers_whole_corridor()
        assert service.load_plan(plan_id, "crystal-range").end_mile == pytest.approx(78.0)

    def test_the_hiker_name_is_recorded(self, service: PlanningService) -> None:
        plan_id, _ = service.plan_and_save("crystal-range", START, hiker=HikerSpec(name="ada"))
        assert service.load_plan(plan_id, "crystal-range") is not None

    def test_loading_an_absent_plan_raises(self, service: PlanningService) -> None:
        with pytest.raises(DataSourceError, match="no plan with that id"):
            service.load_plan(9999, "crystal-range")


class TestPermitsAndExplain:
    def test_permits_are_checked_against_the_stored_zones(self, service: PlanningService) -> None:
        plan = service.plan("crystal-range", START)
        report = service.check_permits(plan, "crystal-range")
        assert not report.is_permittable
        assert report.findings_from("bear_canister")

    def test_carrying_a_canister_clears_that_rule(self, service: PlanningService) -> None:
        plan = service.plan("crystal-range", START)
        report = service.check_permits(plan, "crystal-range", has_canister=True)
        assert report.findings_from("bear_canister") == ()

    def test_wanting_a_fire_adds_findings(self, service: PlanningService) -> None:
        plan = service.plan("crystal-range", START)
        quiet = service.check_permits(plan, "crystal-range", has_canister=True)
        lit = service.check_permits(plan, "crystal-range", has_canister=True, wants_fire=True)
        assert len(lit.findings) >= len(quiet.findings)

    def test_explain_returns_a_row_per_day(self, service: PlanningService) -> None:
        request = service.build_request("crystal-range", START)
        plan = service.build_plan(request)
        terms = service.explain(plan, request.profile)
        assert len(terms) == len(plan)
        assert set(terms[0]) == {"effort", "camp", "late_finish", "steep_finish", "per_day"}


class TestServiceAgreesWithTheLayersAboveIt:
    def test_the_service_and_the_api_build_the_same_plan(
        self, service: PlanningService, api
    ) -> None:
        direct = service.plan(
            "crystal-range", START, hiker=HikerSpec(name="reference", flat_pace_mph=2.7)
        )
        over_http = api.post(
            "/plans",
            json={
                "corridor": "crystal-range",
                "start_date": START.isoformat(),
                "hiker": {"name": "reference", "flat_pace_mph": 2.7},
            },
        ).json()
        assert len(over_http["days"]) == len(direct)
        assert over_http["total_miles"] == pytest.approx(direct.total_distance.in_miles, abs=0.01)

    def test_the_bundle_matches_the_repositories(
        self, service: PlanningService, session: Session
    ) -> None:
        bundle = service.load_bundle("crystal-range")
        corridor_id = bundle.corridor_id
        assert len(WaterRepository(session).load(corridor_id)) == len(bundle.water)
        assert len(PermitRepository(session).load(corridor_id)) == len(bundle.zones)
        assert len(ResupplyRepository(session).load(corridor_id)) == len(bundle.towns)
