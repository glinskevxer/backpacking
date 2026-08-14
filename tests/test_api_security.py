"""The API key, the body ceiling, CORS and the response headers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backpacking.api.app import create_app
from backpacking.api.security import (
    API_KEY_HEADER,
    UNAUTHENTICATED_PATHS,
    keys_match,
    requires_key,
)
from backpacking.config import Settings
from backpacking.storage.session import Database

KEY = "a-long-enough-api-key-value"


def client_for(database: Database, **overrides: object) -> Iterator[TestClient]:
    settings = Settings(database_url=database.settings.database_url, **overrides)
    with TestClient(create_app(settings, database=database)) as client:
        yield client


@pytest.fixture
def keyed(seeded_database: Database) -> Iterator[TestClient]:
    yield from client_for(seeded_database, api_key=KEY)


@pytest.fixture
def cors(seeded_database: Database) -> Iterator[TestClient]:
    yield from client_for(seeded_database, cors_origins=["https://planner.example.com"])


@pytest.fixture
def tiny(seeded_database: Database) -> Iterator[TestClient]:
    yield from client_for(seeded_database, max_request_bytes=64)


class TestKeyHelpers:
    def test_a_matching_key_passes(self) -> None:
        assert keys_match(KEY, KEY)

    def test_a_wrong_key_fails(self) -> None:
        assert not keys_match("wrong", KEY)

    def test_a_missing_key_fails(self) -> None:
        assert not keys_match(None, KEY)
        assert not keys_match("", KEY)

    def test_a_prefix_of_the_key_fails(self) -> None:
        assert not keys_match(KEY[:-1], KEY)

    def test_the_probe_paths_are_open(self) -> None:
        assert {"/health", "/ready", "/metrics"} == UNAUTHENTICATED_PATHS
        for path in UNAUTHENTICATED_PATHS:
            assert not requires_key(path)

    def test_everything_else_needs_a_key(self) -> None:
        assert requires_key("/corridors")
        assert requires_key("/plans")


class TestNoKeyConfigured:
    def test_the_service_is_open_by_default(self, api: TestClient) -> None:
        assert api.get("/corridors").status_code == 200

    def test_the_app_records_that_it_is_off(self, api: TestClient) -> None:
        assert api.app.state.api_key_enabled is False


class TestKeyConfigured:
    def test_the_app_records_that_it_is_on(self, keyed: TestClient) -> None:
        assert keyed.app.state.api_key_enabled is True

    def test_a_request_without_a_key_is_rejected(self, keyed: TestClient) -> None:
        response = keyed.get("/corridors")
        assert response.status_code == 401
        assert response.json()["code"] == "unauthorized"

    def test_a_request_with_the_key_is_allowed(self, keyed: TestClient) -> None:
        response = keyed.get("/corridors", headers={API_KEY_HEADER: KEY})
        assert response.status_code == 200

    def test_a_wrong_key_is_rejected(self, keyed: TestClient) -> None:
        response = keyed.get("/corridors", headers={API_KEY_HEADER: "nope"})
        assert response.status_code == 401

    def test_health_still_answers_without_one(self, keyed: TestClient) -> None:
        assert keyed.get("/health").status_code == 200
        assert keyed.get("/ready").status_code == 200

    def test_metrics_still_answers_without_one(self, keyed: TestClient) -> None:
        assert keyed.get("/metrics").status_code == 200

    def test_a_write_is_behind_the_key_too(self, keyed: TestClient) -> None:
        body = {"corridor": "crystal-range", "start_date": "2025-07-20"}
        assert keyed.post("/plans", json=body).status_code == 401
        assert keyed.post("/plans", json=body, headers={API_KEY_HEADER: KEY}).status_code == 200

    def test_a_short_key_is_refused_by_settings(self) -> None:
        with pytest.raises(ValueError, match="at least 16 characters"):
            Settings(api_key="short")


class TestBodyLimit:
    def test_a_small_body_passes(self, api: TestClient) -> None:
        body = {"corridor": "crystal-range", "start_date": "2025-07-20"}
        assert api.post("/plans", json=body).status_code == 200

    def test_an_oversized_body_is_refused(self, tiny: TestClient) -> None:
        body = {
            "corridor": "crystal-range",
            "start_date": "2025-07-20",
            "constraints": {"forbidden_camps": ["x" * 400]},
        }
        response = tiny.post("/plans", json=body)
        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"
        assert response.json()["context"]["limit_bytes"] == 64

    def test_a_get_is_unaffected(self, tiny: TestClient) -> None:
        assert tiny.get("/corridors").status_code == 200

    def test_a_bad_content_length_is_a_400(self, tiny: TestClient) -> None:
        response = tiny.request(
            "POST",
            "/plans",
            content=b"{}",
            headers={"content-length": "not-a-number", "content-type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "bad_content_length"

    def test_the_default_ceiling_is_a_megabyte(self) -> None:
        assert Settings().max_request_bytes == 1_048_576

    def test_an_absurd_ceiling_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Settings(max_request_bytes=0)


class TestCors:
    def test_it_is_off_by_default(self, api: TestClient) -> None:
        assert api.app.state.cors_enabled is False
        response = api.get("/corridors", headers={"origin": "https://planner.example.com"})
        assert "access-control-allow-origin" not in response.headers

    def test_a_named_origin_is_allowed(self, cors: TestClient) -> None:
        assert cors.app.state.cors_enabled is True
        response = cors.get("/corridors", headers={"origin": "https://planner.example.com"})
        assert response.headers["access-control-allow-origin"] == ("https://planner.example.com")

    def test_another_origin_is_not(self, cors: TestClient) -> None:
        response = cors.get("/corridors", headers={"origin": "https://elsewhere.test"})
        assert "access-control-allow-origin" not in response.headers

    def test_a_preflight_is_answered(self, cors: TestClient) -> None:
        response = cors.options(
            "/plans",
            headers={
                "origin": "https://planner.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert "POST" in response.headers["access-control-allow-methods"]

    def test_origins_can_be_given_as_a_comma_separated_string(self) -> None:
        settings = Settings(cors_origins="https://a.test, https://b.test")
        assert settings.cors_origins == ["https://a.test", "https://b.test"]

    def test_an_empty_string_yields_no_origins(self) -> None:
        assert Settings(cors_origins="").cors_origins == []


class TestSecurityHeaders:
    def test_the_headers_are_set(self, api: TestClient) -> None:
        headers = api.get("/corridors").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"

    def test_they_are_set_on_errors_too(self, api: TestClient) -> None:
        headers = api.get("/corridors/nowhere").headers
        assert headers["x-content-type-options"] == "nosniff"

    def test_they_do_not_disturb_a_file_download(self, api: TestClient) -> None:
        plan_id = api.post(
            "/plans/save",
            json={"corridor": "crystal-range", "start_date": "2025-07-20"},
        ).json()["plan_id"]
        response = api.get(f"/reports/plan/{plan_id}/calendar?corridor=crystal-range")
        assert response.headers["content-type"].startswith("text/calendar")
        assert "attachment" in response.headers["content-disposition"]
