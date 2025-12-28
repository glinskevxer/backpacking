"""Plan endpoints, including the failures a client should expect."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BODY = {
    "corridor": "crystal-range",
    "start_date": "2025-07-20",
    "hiker": {"name": "reference", "flat_pace_mph": 2.7, "pack_weight_lb": 26.0},
}


class TestBuildPlan:
    def test_a_plan_comes_back(self, api: TestClient) -> None:
        response = api.post("/plans", json=BODY)
        assert response.status_code == 200
        body = response.json()
        assert body["corridor"] == "crystal-range"
        assert body["total_miles"] == pytest.approx(78.0)

    def test_the_days_tile_the_corridor(self, api: TestClient) -> None:
        days = api.post("/plans", json=BODY).json()["days"]
        assert days[0]["start_mile"] == pytest.approx(0.0)
        assert days[-1]["end_mile"] == pytest.approx(78.0)
        for first, second in zip(days, days[1:], strict=False):
            assert first["end_mile"] == pytest.approx(second["start_mile"])

    def test_every_day_reports_its_hours(self, api: TestClient) -> None:
        days = api.post("/plans", json=BODY).json()["days"]
        assert all(day["elapsed_hours"] >= day["moving_hours"] for day in days)
        assert all(day["moving_hours"] > 0.0 for day in days)

    def test_a_section_can_be_planned(self, api: TestClient) -> None:
        body = {**BODY, "start_mile": 23.6, "end_mile": 57.4}
        plan = api.post("/plans", json=body).json()
        assert plan["days"][0]["start_mile"] == pytest.approx(23.6)
        assert plan["days"][-1]["end_mile"] == pytest.approx(57.4)

    def test_a_faster_hiker_takes_fewer_days(self, api: TestClient) -> None:
        slow = api.post("/plans", json={**BODY, "hiker": {"flat_pace_mph": 2.1}}).json()
        fast = api.post("/plans", json={**BODY, "hiker": {"flat_pace_mph": 3.8}}).json()
        assert len(fast["days"]) <= len(slow["days"])

    def test_constraints_are_honoured(self, api: TestClient) -> None:
        body = {**BODY, "constraints": {"max_daily_miles": 12.0, "min_daily_miles": 4.0}}
        plan = api.post("/plans", json=body).json()
        assert all(day["miles"] <= 12.0 for day in plan["days"])

    def test_a_forbidden_camp_is_avoided(self, api: TestClient) -> None:
        body = {**BODY, "constraints": {"forbidden_camps": ["clyde-basin"]}}
        plan = api.post("/plans", json=body).json()
        assert "clyde-basin" not in {day["camp_id"] for day in plan["days"]}

    def test_an_unknown_corridor_is_a_404(self, api: TestClient) -> None:
        response = api.post("/plans", json={**BODY, "corridor": "nowhere"})
        assert response.status_code == 404

    def test_an_impossible_constraint_is_a_409(self, api: TestClient) -> None:
        body = {**BODY, "constraints": {"max_daily_miles": 1.5, "min_daily_miles": 0.5}}
        response = api.post("/plans", json=body)
        assert response.status_code == 409
        assert response.json()["code"] == "plan_infeasible"

    def test_a_bad_pace_is_rejected_by_validation(self, api: TestClient) -> None:
        response = api.post("/plans", json={**BODY, "hiker": {"flat_pace_mph": -1.0}})
        assert response.status_code == 422

    def test_a_missing_start_date_is_rejected(self, api: TestClient) -> None:
        response = api.post("/plans", json={"corridor": "crystal-range"})
        assert response.status_code == 422


class TestSaveAndLoad:
    def test_saving_returns_an_id(self, api: TestClient) -> None:
        response = api.post("/plans/save", json=BODY)
        assert response.status_code == 201
        assert response.json()["plan_id"] > 0

    def test_a_saved_plan_can_be_loaded(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        loaded = api.get(f"/plans/{plan_id}?corridor=crystal-range").json()
        assert loaded["total_miles"] == pytest.approx(78.0)
        assert len(loaded["days"]) > 0

    def test_the_loaded_plan_matches_the_built_one(self, api: TestClient) -> None:
        built = api.post("/plans", json=BODY).json()
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        loaded = api.get(f"/plans/{plan_id}?corridor=crystal-range").json()
        assert [day["end_mile"] for day in loaded["days"]] == [
            day["end_mile"] for day in built["days"]
        ]

    def test_plans_are_listed_for_a_corridor(self, api: TestClient) -> None:
        api.post("/plans/save", json=BODY)
        api.post("/plans/save", json={**BODY, "start_date": "2025-08-01"})
        listed = api.get("/plans?corridor=crystal-range").json()
        assert len(listed) == 2
        assert listed[0]["start_date"] == "2025-07-20"

    def test_an_unknown_plan_is_a_404(self, api: TestClient) -> None:
        assert api.get("/plans/9999?corridor=crystal-range").status_code == 404

    def test_a_plan_can_be_deleted(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        assert api.delete(f"/plans/{plan_id}").status_code == 204
        assert api.get(f"/plans/{plan_id}?corridor=crystal-range").status_code == 404

    def test_deleting_an_absent_plan_is_a_404(self, api: TestClient) -> None:
        assert api.delete("/plans/9999").status_code == 404


class TestSchedule:
    def test_the_schedule_is_plain_text(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        response = api.get(f"/plans/{plan_id}/schedule?corridor=crystal-range")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")

    def test_the_schedule_names_the_corridor_and_the_days(self, api: TestClient) -> None:
        plan_id = api.post("/plans/save", json=BODY).json()["plan_id"]
        text = api.get(f"/plans/{plan_id}/schedule?corridor=crystal-range").text
        assert "Crystal Range Traverse" in text
        assert "2025-07-20" in text


class TestExplain:
    def test_one_row_per_day(self, api: TestClient) -> None:
        plan = api.post("/plans", json=BODY).json()
        terms = api.post("/plans/explain", json=BODY).json()
        assert len(terms) == len(plan["days"])

    def test_every_term_is_present(self, api: TestClient) -> None:
        terms = api.post("/plans/explain", json=BODY).json()
        assert set(terms[0]) == {"effort", "camp", "late_finish", "steep_finish", "per_day"}

    def test_the_terms_are_numbers(self, api: TestClient) -> None:
        terms = api.post("/plans/explain", json=BODY).json()
        assert all(isinstance(value, int | float) for value in terms[0].values())
