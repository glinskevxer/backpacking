"""Structured logging, redaction and the metrics registry."""

from __future__ import annotations

import json
import logging

import pytest
import structlog
from fastapi.testclient import TestClient

from backpacking.config import Settings
from backpacking.observability.logging import (
    REDACTION,
    add_service_name,
    bind_request,
    clear_request,
    configure_logging,
    get_logger,
    redact_processor,
    unbind,
)
from backpacking.observability.metrics import (
    DEFAULT_BUCKETS,
    Histogram,
    Metrics,
)


class TestRedaction:
    def test_a_password_never_reaches_the_line(self) -> None:
        event = redact_processor(None, "info", {"password": "hunter2", "user": "ada"})
        assert event["password"] == REDACTION
        assert event["user"] == "ada"

    @pytest.mark.parametrize("key", ["token", "SECRET", "Authorization", "api_key"])
    def test_every_credential_key_is_caught(self, key: str) -> None:
        event = redact_processor(None, "info", {key: "value"})
        assert event[key] == REDACTION

    def test_an_innocent_event_passes_through(self) -> None:
        event = redact_processor(None, "info", {"miles": 18.2})
        assert event == {"miles": 18.2}

    def test_the_service_name_is_added(self) -> None:
        assert add_service_name(None, "info", {})["service"] == "backpacking"

    def test_an_explicit_service_name_wins(self) -> None:
        assert add_service_name(None, "info", {"service": "other"})["service"] == "other"


class TestConfiguration:
    def test_json_output_parses(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(Settings(log_json=True, log_level="INFO"), force=True)
        get_logger("test").info("hello", miles=18.2)
        line = capsys.readouterr().out.strip().splitlines()[-1]
        parsed = json.loads(line)
        assert parsed["event"] == "hello"
        assert parsed["miles"] == 18.2
        assert parsed["service"] == "backpacking"

    def test_console_output_is_not_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(Settings(log_json=False, log_level="INFO"), force=True)
        get_logger("test").info("hello")
        out = capsys.readouterr().out
        assert "hello" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out.strip().splitlines()[-1])

    def test_the_level_is_honoured(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(Settings(log_json=True, log_level="WARNING"), force=True)
        get_logger("test").info("quiet")
        get_logger("test").warning("loud")
        out = capsys.readouterr().out
        assert "loud" in out
        assert "quiet" not in out

    def test_credentials_are_redacted_end_to_end(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(Settings(log_json=True), force=True)
        get_logger("test").info("login", token="abcd1234")
        parsed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert parsed["token"] == REDACTION
        assert "abcd1234" not in json.dumps(parsed)

    def test_an_invalid_level_is_refused_by_settings(self) -> None:
        with pytest.raises(ValueError, match="log_level must be one of"):
            Settings(log_level="chatty")

    def test_the_level_is_upper_cased(self) -> None:
        assert Settings(log_level="debug").log_level == "DEBUG"


class TestContextVars:
    def test_a_bound_request_id_appears_on_every_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(Settings(log_json=True), force=True)
        bind_request("req-123", path="/corridors")
        get_logger("test").info("first")
        get_logger("test").info("second")
        lines = capsys.readouterr().out.strip().splitlines()[-2:]
        for line in lines:
            assert json.loads(line)["request_id"] == "req-123"

    def test_clearing_removes_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(Settings(log_json=True), force=True)
        bind_request("req-123")
        clear_request()
        get_logger("test").info("after")
        assert "request_id" not in json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    def test_unbinding_one_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(Settings(log_json=True), force=True)
        bind_request("req-123", path="/x")
        unbind("path")
        parsed = json.loads(
            (get_logger("test").info("after"), capsys.readouterr().out)[1]
            .strip()
            .splitlines()[-1]
        )
        assert parsed["request_id"] == "req-123"
        assert "path" not in parsed


class TestHistogram:
    def test_observations_land_in_buckets(self) -> None:
        histogram = Histogram(buckets=(0.1, 1.0))
        histogram.observe(0.05)
        histogram.observe(0.5)
        histogram.observe(9.0)
        assert histogram.counts == [1, 1, 1]

    def test_the_mean_is_the_sum_over_the_count(self) -> None:
        histogram = Histogram()
        for value in (1.0, 2.0, 3.0):
            histogram.observe(value)
        assert histogram.mean == pytest.approx(2.0)

    def test_an_empty_histogram_has_a_zero_mean(self) -> None:
        assert Histogram().mean == pytest.approx(0.0)

    def test_the_median_lands_in_the_right_bucket(self) -> None:
        histogram = Histogram(buckets=(0.1, 1.0, 10.0))
        for _ in range(10):
            histogram.observe(0.5)
        assert histogram.quantile(0.5) == pytest.approx(1.0)

    def test_a_quantile_of_an_empty_histogram_is_zero(self) -> None:
        assert Histogram().quantile(0.95) == pytest.approx(0.0)

    def test_an_out_of_range_quantile_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"\(0, 1\]"):
            Histogram().quantile(1.5)

    def test_the_default_buckets_ascend(self) -> None:
        assert list(DEFAULT_BUCKETS) == sorted(DEFAULT_BUCKETS)

    def test_as_dict_reports_the_summary(self) -> None:
        histogram = Histogram()
        histogram.observe(0.02)
        summary = histogram.as_dict()
        assert summary["count"] == pytest.approx(1.0)
        assert set(summary) == {"count", "sum", "mean", "p50", "p95"}


class TestMetrics:
    def test_counters_add_up(self) -> None:
        metrics = Metrics()
        metrics.increment("plans_built")
        metrics.increment("plans_built", 4)
        assert metrics.counter("plans_built") == 5

    def test_an_unseen_counter_is_zero(self) -> None:
        assert Metrics().counter("nothing") == 0

    def test_counters_do_not_go_down(self) -> None:
        with pytest.raises(ValueError, match="do not go down"):
            Metrics().increment("x", -1)

    def test_the_timer_records_seconds(self) -> None:
        metrics = Metrics()
        with metrics.timer("solve"):
            pass
        assert metrics.histogram("solve").observations == 1
        assert metrics.histogram("solve").total >= 0.0

    def test_the_timer_records_even_on_failure(self) -> None:
        metrics = Metrics()
        with pytest.raises(RuntimeError), metrics.timer("solve"):
            raise RuntimeError("boom")
        assert metrics.histogram("solve").observations == 1

    def test_the_snapshot_carries_both_kinds(self) -> None:
        metrics = Metrics()
        metrics.increment("a")
        metrics.observe("b", 0.5)
        snapshot = metrics.snapshot()
        assert snapshot["counters"] == {"a": 1}
        assert "b" in snapshot["histograms"]

    def test_reset_empties_it(self) -> None:
        metrics = Metrics()
        metrics.increment("a")
        metrics.observe("b", 0.5)
        metrics.reset()
        assert metrics.snapshot() == {"counters": {}, "histograms": {}}

    def test_repr(self) -> None:
        metrics = Metrics()
        metrics.increment("a")
        assert repr(metrics) == "Metrics(1 counters, 0 histograms)"


class TestMiddleware:
    def test_a_request_id_comes_back(self, api: TestClient) -> None:
        response = api.get("/health")
        assert response.headers["x-request-id"]

    def test_a_supplied_request_id_is_echoed(self, api: TestClient) -> None:
        response = api.get("/health", headers={"x-request-id": "given-123"})
        assert response.headers["x-request-id"] == "given-123"

    def test_the_timing_header_is_still_there(self, api: TestClient) -> None:
        assert float(api.get("/health").headers["x-response-time-ms"]) >= 0.0

    def test_the_metrics_endpoint_counts_requests(self, api: TestClient) -> None:
        api.get("/health")
        snapshot = api.get("/metrics").json()
        assert snapshot["counters"]["http_requests_total"] >= 1
        assert "http_request_seconds" in snapshot["histograms"]

    def test_status_classes_are_counted_separately(self, api: TestClient) -> None:
        api.get("/corridors/nowhere")
        snapshot = api.get("/metrics").json()
        assert snapshot["counters"].get("http_responses_4xx", 0) >= 1

    def test_the_metrics_endpoint_is_not_in_the_schema(self, api: TestClient) -> None:
        assert "/metrics" not in api.get("/openapi.json").json()["paths"]


@pytest.fixture(autouse=True)
def _restore_logging() -> None:
    """Leave logging as the rest of the suite expects it."""
    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()
