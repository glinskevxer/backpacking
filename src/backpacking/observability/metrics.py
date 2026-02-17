"""A small in process metrics registry.

Deliberately not a Prometheus client. This service is one process behind a load
balancer and the useful questions are "how long does the solver take" and "how
often does a plan come back infeasible", both of which are answerable from a
counter and a histogram that can be dumped over an endpoint.

Everything is thread safe, because the API runs the solver in a worker thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

#: Bucket edges in seconds. Chosen around what the solver actually takes.
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


@dataclass(slots=True)
class Histogram:
    """Bucketed observations, plus the count and sum needed for a mean."""

    buckets: tuple[float, ...] = DEFAULT_BUCKETS
    counts: list[int] = field(default_factory=list)
    total: float = 0.0
    observations: int = 0

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0] * (len(self.buckets) + 1)

    def observe(self, value: float) -> None:
        self.observations += 1
        self.total += value
        for index, edge in enumerate(self.buckets):
            if value <= edge:
                self.counts[index] += 1
                return
        self.counts[-1] += 1

    @property
    def mean(self) -> float:
        return 0.0 if self.observations == 0 else self.total / self.observations

    def quantile(self, fraction: float) -> float:
        """Upper edge of the bucket the given quantile falls in."""
        if not 0.0 < fraction <= 1.0:
            raise ValueError("quantile fraction must fall in (0, 1]")
        if self.observations == 0:
            return 0.0
        target = fraction * self.observations
        running = 0
        for index, count in enumerate(self.counts):
            running += count
            if running >= target:
                return self.buckets[index] if index < len(self.buckets) else float("inf")
        return float("inf")

    def as_dict(self) -> dict[str, float]:
        return {
            "count": float(self.observations),
            "sum": round(self.total, 6),
            "mean": round(self.mean, 6),
            "p50": self.quantile(0.5),
            "p95": self.quantile(0.95),
        }


class Metrics:
    """Counters and histograms, keyed by name."""

    __slots__ = ("_counters", "_histograms", "_lock")

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("counters do not go down")
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            histogram = self._histograms.get(name)
            if histogram is None:
                histogram = Histogram()
                self._histograms[name] = histogram
            histogram.observe(value)

    def histogram(self, name: str) -> Histogram:
        with self._lock:
            return self._histograms.setdefault(name, Histogram())

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        """Time a block and record it in seconds."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - started)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "histograms": {
                    name: histogram.as_dict() for name, histogram in self._histograms.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    def __repr__(self) -> str:
        with self._lock:
            return f"Metrics({len(self._counters)} counters, {len(self._histograms)} histograms)"


#: The process wide registry. Passing one around explicitly is better, but the
#: middleware and the solver do not share a call stack.
REGISTRY = Metrics()


def increment(name: str, amount: int = 1) -> None:
    REGISTRY.increment(name, amount)


def observe(name: str, value: float) -> None:
    REGISTRY.observe(name, value)


@contextmanager
def timer(name: str) -> Iterator[None]:
    with REGISTRY.timer(name):
        yield
