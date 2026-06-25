"""The permit, water and resupply endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BODY = {
    "corridor": "crystal-range",
    "start_date": "2025-07-20",
    "hiker": {"name": "reference", "flat_pace_mph": 2.7},
}


class TestPermitZones:
    def test_every_zone_is_listed(self, api: TestClient) -> None:
        body = api.get("/permits/zones/crystal-range").json()
        assert len(body) == 4
        assert body[0]["id"] == "echo-front"

    def test_zones_carry_their_rules(self, api: TestClient) -> None:
        body = api.get("/permits/zones/crystal-range").json()
        wilderness = next(z for z in body if z["id"] == "crystal-wilderness")
        assert wilderness["canister_required"] is True
        assert wilderness["max_consecutive_nights"] == 3
        assert wilderness["camping"] == "designated_only"

    def test_the_zone_at_a_mile(self, api: TestClient) -> None:
        body = api.get("/permits/zones/crystal-range/at?mile=15.3").json()
        assert body["zone"] == "crystal-wilderness"

    def test_an_unmanaged_mile_reports_nothing(self, api: TestClient) -> None:
        body = api.get("/permits/zones/crystal-range/at?mile=78").json()
        assert body["zone"] is None

    def test_a_negative_mile_is_rejected(self, api: TestClient) -> None:
        assert api.get("/permits/zones/crystal-range/at?mile=-1").status_code == 422

    def test_the_corridor_has_no_unmanaged_gaps(self, api: TestClient) -> None:
        assert api.get("/permits/gaps/crystal-range").json() == []

    def test_canister_requirement_over_a_window(self, api: TestClient) -> None:
        body = api.get("/permits/canister/crystal-range?from_mile=10&to_mile=20").json()
        assert body["required"] is True
        assert body["zones"] == ["crystal-wilderness"]

    def test_a_window_with_no_canister_zone(self, api: TestClient) -> None:
        body = api.get("/permits/canister/crystal-range?from_mile=60&to_mile=70").json()
        assert body["required"] is False
        assert body["zones"] == []

    def test_the_season_summary(self, api: TestClient) -> None:
        body = api.get("/permits/season/crystal-range?on=2025-07-20").json()
        assert body["zones"] == 4
        assert body["canister_zones"] == ["crystal-wilderness"]
        assert body["no_fire_zones"] == ["granite-state-park"]
        assert len(body["agencies"]) == 3


class TestPermitCheck:
    def test_a_plan_without_a_canister_is_not_permittable(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        body = api.get(f"/permits/check/{plan_id}?corridor=crystal-range").json()
        assert body["permittable"] is False
        assert any(f["rule"] == "bear_canister" for f in body["violations"])

    def test_carrying_a_canister_clears_that_rule(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        body = api.get(f"/permits/check/{plan_id}?corridor=crystal-range&has_canister=true").json()
        assert not any(f["rule"] == "bear_canister" for f in body["violations"])

    def test_the_report_names_the_zones_visited(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        body = api.get(f"/permits/check/{plan_id}?corridor=crystal-range").json()
        assert "crystal-wilderness" in body["zones_visited"]

    def test_the_report_suggests_fixes(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        body = api.get(f"/permits/check/{plan_id}?corridor=crystal-range").json()
        assert any("canister" in suggestion for suggestion in body["suggestions"])

    def test_wanting_a_fire_adds_findings(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        without = api.get(f"/permits/check/{plan_id}?corridor=crystal-range").json()
        with_fire = api.get(
            f"/permits/check/{plan_id}?corridor=crystal-range&wants_fire=true"
        ).json()
        assert len(with_fire["violations"]) >= len(without["violations"])

    def test_checking_an_absent_plan_is_a_404(self, api: TestClient) -> None:
        assert api.get("/permits/check/9999?corridor=crystal-range").status_code == 404


class TestWater:
    def test_every_source_is_listed_with_its_confidence(self, api: TestClient) -> None:
        body = api.get("/water/crystal-range?month=7").json()
        assert len(body) == 11
        assert all(0.0 <= source["confidence"] <= 1.0 for source in body)

    def test_august_thins_the_usable_sources(self, api: TestClient) -> None:
        june = api.get("/water/crystal-range?month=6&usable_only=true").json()
        august = api.get("/water/crystal-range?month=8&usable_only=true").json()
        assert len(august) < len(june)

    def test_lowering_the_threshold_brings_sources_back(self, api: TestClient) -> None:
        strict = api.get("/water/crystal-range?month=8&usable_only=true&threshold=0.6").json()
        loose = api.get("/water/crystal-range?month=8&usable_only=true&threshold=0.2").json()
        assert len(loose) > len(strict)

    def test_an_invalid_month_is_rejected(self, api: TestClient) -> None:
        assert api.get("/water/crystal-range?month=13").status_code == 422

    def test_dry_stretches_are_reported(self, api: TestClient) -> None:
        body = api.get("/water/crystal-range/gaps?month=6").json()
        assert body
        assert body[0]["length_miles"] > 8.0
        assert "liters_required" in body[0]

    def test_a_bigger_capacity_makes_a_gap_feasible(self, api: TestClient) -> None:
        small = api.get("/water/crystal-range/gaps?month=6&capacity_liters=2").json()
        large = api.get("/water/crystal-range/gaps?month=6&capacity_liters=20").json()
        assert not small[0]["fits_capacity"]
        assert large[0]["fits_capacity"]

    def test_heat_raises_the_requirement(self, api: TestClient) -> None:
        mild = api.get("/water/crystal-range/gaps?month=6&temperature_c=12").json()
        hot = api.get("/water/crystal-range/gaps?month=6&temperature_c=38").json()
        assert hot[0]["liters_required"] > mild[0]["liters_required"]

    def test_water_needed_for_an_arbitrary_stretch(self, api: TestClient) -> None:
        body = api.get("/water/crystal-range/needed?from_mile=0&to_mile=15.3").json()
        assert body["miles"] == pytest.approx(15.3)
        assert body["liters"] > 1.0

    def test_camping_en_route_needs_more(self, api: TestClient) -> None:
        dry = api.get("/water/crystal-range/needed?from_mile=0&to_mile=20").json()
        camp = api.get(
            "/water/crystal-range/needed?from_mile=0&to_mile=20&camping_en_route=true"
        ).json()
        assert camp["liters"] > dry["liters"]


class TestResupply:
    def test_every_point_is_listed(self, api: TestClient) -> None:
        body = api.get("/resupply/crystal-range").json()
        assert len(body) == 5

    def test_only_three_support_a_full_resupply(self, api: TestClient) -> None:
        body = api.get("/resupply/crystal-range?full_only=true").json()
        assert len(body) == 3
        assert all(point["supports_full_resupply"] for point in body)

    def test_access_hours_are_reported(self, api: TestClient) -> None:
        body = api.get("/resupply/crystal-range").json()
        soda = next(p for p in body if p["id"] == "soda-springs")
        assert soda["access_hours"] > 0.0
        assert soda["has_post_office"] is True

    def test_the_strategy_picks_stops(self, api: TestClient) -> None:
        body = api.get("/resupply/crystal-range/strategy?max_carry_days=3").json()
        assert body["stops"]
        assert body["longest_carry_days"] <= 3.0

    def test_a_generous_carry_needs_no_stops(self, api: TestClient) -> None:
        body = api.get("/resupply/crystal-range/strategy?max_carry_days=20").json()
        assert body["stops"] == []
        assert len(body["carries"]) == 1

    def test_an_impossible_carry_limit_is_a_409(self, api: TestClient) -> None:
        response = api.get("/resupply/crystal-range/strategy?max_carry_days=0.6")
        assert response.status_code == 409
        assert response.json()["code"] == "resupply_infeasible"

    def test_the_longest_gap_is_reported(self, api: TestClient) -> None:
        body = api.get("/resupply/crystal-range/gap").json()
        assert body["longest_gap_miles"] == pytest.approx(33.8)

    def test_counting_every_stop_shrinks_the_gap(self, api: TestClient) -> None:
        full = api.get("/resupply/crystal-range/gap?full_only=true").json()
        every = api.get("/resupply/crystal-range/gap?full_only=false").json()
        assert every["longest_gap_miles"] < full["longest_gap_miles"]
