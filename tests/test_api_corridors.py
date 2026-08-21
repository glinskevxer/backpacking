"""The corridor and health endpoints, end to end over a real database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(api: TestClient) -> TestClient:
    """The seeded client from conftest, under the name this module uses."""
    return api


class TestHealth:
    def test_health_answers_without_the_database(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readiness_round_trips_a_query(self, client: TestClient) -> None:
        body = client.get("/ready").json()
        assert body["status"] == "ok"
        assert body["database"] == "reachable"

    def test_the_version_is_reported(self, client: TestClient) -> None:
        assert client.get("/health").json()["version"] == "1.0.0"

    def test_every_response_carries_a_timing_header(self, client: TestClient) -> None:
        response = client.get("/health")
        assert "x-response-time-ms" in response.headers
        assert float(response.headers["x-response-time-ms"]) >= 0.0


class TestListCorridors:
    def test_the_stored_corridor_is_listed(self, client: TestClient) -> None:
        body = client.get("/corridors").json()
        assert len(body) == 1
        assert body[0]["slug"] == "crystal-range"
        assert body[0]["length_miles"] == pytest.approx(78.0)

    def test_the_summary_carries_the_climb(self, client: TestClient) -> None:
        body = client.get("/corridors").json()[0]
        assert body["total_gain_ft"] == pytest.approx(9490.0)
        assert body["waypoint_count"] == 20


class TestGetCorridor:
    def test_the_full_corridor_includes_waypoints_and_segments(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range").json()
        assert len(body["waypoints"]) == 20
        assert len(body["segments"]) == 19

    def test_waypoints_carry_their_kind_and_tags(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range").json()
        soda = next(w for w in body["waypoints"] if w["id"] == "soda-springs")
        assert soda["kind"] == "resupply"
        assert soda["tags"] == ["hitch", "post"]

    def test_an_unknown_corridor_is_a_404(self, client: TestClient) -> None:
        response = client.get("/corridors/nowhere")
        assert response.status_code == 404
        assert response.json()["code"] == "data_source_error"


class TestListWaypoints:
    def test_all_waypoints_by_default(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range/waypoints").json()
        assert len(body) == 20

    def test_filtering_by_kind(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range/waypoints?kind=water").json()
        assert len(body) == 5
        assert all(w["kind"] == "water" for w in body)

    def test_filtering_by_mileage(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range/waypoints?from_mile=20&to_mile=45").json()
        assert all(20.0 <= w["mile"] <= 45.0 for w in body)
        assert len(body) == 6

    def test_combining_both_filters(self, client: TestClient) -> None:
        body = client.get(
            "/corridors/crystal-range/waypoints?kind=campsite&from_mile=20&to_mile=60"
        ).json()
        assert [w["id"] for w in body] == ["dry-bench", "whiskey-flat"]

    def test_an_unknown_kind_is_a_422(self, client: TestClient) -> None:
        response = client.get("/corridors/crystal-range/waypoints?kind=helipad")
        assert response.status_code == 422
        assert response.json()["code"] == "corridor_error"

    def test_a_reversed_window_is_a_422(self, client: TestClient) -> None:
        response = client.get("/corridors/crystal-range/waypoints?from_mile=40&to_mile=10")
        assert response.status_code == 422
        assert "precedes" in response.json()["message"]


class TestProfile:
    def test_the_profile_covers_the_corridor(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range/profile").json()
        assert body["miles"][0] == pytest.approx(0.0)
        assert body["miles"][-1] == pytest.approx(78.0)
        assert len(body["miles"]) == len(body["elevation_ft"])

    def test_a_smaller_step_gives_more_samples(self, client: TestClient) -> None:
        coarse = client.get("/corridors/crystal-range/profile?step_miles=5").json()
        fine = client.get("/corridors/crystal-range/profile?step_miles=0.5").json()
        assert len(fine["miles"]) > len(coarse["miles"])

    def test_the_elevations_are_plausible(self, client: TestClient) -> None:
        body = client.get("/corridors/crystal-range/profile").json()
        assert all(6000.0 < value < 10000.0 for value in body["elevation_ft"])

    def test_a_zero_step_is_rejected_by_validation(self, client: TestClient) -> None:
        assert client.get("/corridors/crystal-range/profile?step_miles=0").status_code == 422


class TestDeleteCorridor:
    def test_deleting_removes_it(self, client: TestClient) -> None:
        assert client.delete("/corridors/crystal-range").status_code == 204
        assert client.get("/corridors/crystal-range").status_code == 404
        assert client.get("/corridors").json() == []

    def test_deleting_something_absent_is_a_404(self, client: TestClient) -> None:
        assert client.delete("/corridors/nowhere").status_code == 404


class TestOpenApi:
    def test_the_schema_is_served(self, client: TestClient) -> None:
        body = client.get("/openapi.json").json()
        assert body["info"]["title"] == "backpacking"

    def test_every_router_is_mounted(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        for prefix in ("/corridors", "/plans", "/permits", "/water", "/resupply"):
            assert any(path.startswith(prefix) for path in paths)
