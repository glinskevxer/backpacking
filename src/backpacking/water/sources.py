"""Water sources and how much they can be trusted.

Reliability is not a property of a source. It is a property of a source in a
month, in a snow year. A creek that runs all summer in a heavy year is a dry
gully in August of a light one, and the difference decides whether a 22 mile
carry exists.

So a source carries a per month reliability curve rather than a single flag, and
every query into the table takes a month and a confidence threshold. A planner
who wants to be careful raises the threshold; one who is willing to gamble on a
report from three days ago lowers it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from backpacking.errors import WaterCarryError
from backpacking.trail.index import MileIndex
from backpacking.units import Distance


class Reliability(StrEnum):
    """The vocabulary trail guides actually use, mapped onto numbers."""

    PERENNIAL = "perennial"
    SEASONAL = "seasonal"
    UNRELIABLE = "unreliable"
    CACHE = "cache"
    DRY = "dry"

    @property
    def confidence(self) -> float:
        """Baseline confidence before the month curve is applied."""
        return _RELIABILITY_CONFIDENCE[self]


_RELIABILITY_CONFIDENCE: dict[Reliability, float] = {
    Reliability.PERENNIAL: 0.98,
    Reliability.SEASONAL: 0.70,
    Reliability.UNRELIABLE: 0.35,
    Reliability.CACHE: 0.50,
    Reliability.DRY: 0.0,
}

#: Snowmelt fed sources peak in early summer and fade. The curve is a multiplier
#: on the baseline confidence, indexed by calendar month.
SEASONAL_CURVE: dict[int, float] = {
    1: 1.00,
    2: 1.00,
    3: 1.00,
    4: 1.00,
    5: 1.00,
    6: 0.95,
    7: 0.75,
    8: 0.55,
    9: 0.45,
    10: 0.60,
    11: 0.85,
    12: 1.00,
}


@dataclass(frozen=True, slots=True)
class WaterSource:
    """A place water can be collected, at a cumulative mile on the corridor."""

    id: str
    name: str
    mile: float
    reliability: Reliability = Reliability.SEASONAL
    off_trail: Distance = Distance.zero()
    descent: Distance = Distance.zero()
    needs_treatment: bool = True
    notes: str = ""
    monthly_override: dict[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mile < 0.0:
            raise WaterCarryError("water source mile must not be negative", source=self.id)
        if self.off_trail.in_miles < 0.0:
            raise WaterCarryError("off trail distance must not be negative", source=self.id)
        for month, value in self.monthly_override.items():
            if month not in SEASONAL_CURVE:
                raise WaterCarryError(
                    "monthly override uses an invalid month", source=self.id, month=month
                )
            if not 0.0 <= value <= 1.0:
                raise WaterCarryError(
                    "monthly override must fall in [0, 1]", source=self.id, month=month
                )

    def confidence(self, month: int) -> float:
        """How likely this source is to hold water in the given month."""
        if month not in SEASONAL_CURVE:
            raise WaterCarryError("month must be 1 through 12", month=month)
        if month in self.monthly_override:
            return self.monthly_override[month]
        if self.reliability is Reliability.PERENNIAL:
            return self.reliability.confidence
        return self.reliability.confidence * SEASONAL_CURVE[month]

    def is_usable(self, month: int, threshold: float = 0.6) -> bool:
        return self.confidence(month) >= threshold

    @property
    def detour_cost_miles(self) -> float:
        """Round trip to reach it, which is what actually costs the hiker time."""
        return self.off_trail.in_miles * 2.0

    def __repr__(self) -> str:
        return f"WaterSource({self.id!r} @ {self.mile:.1f} mi, {self.reliability.value})"


class WaterTable:
    """Every source on a corridor, indexed by mile."""

    __slots__ = ("_sources", "_index")

    def __init__(self, sources: Sequence[WaterSource]) -> None:
        ordered = sorted(sources, key=lambda s: s.mile)
        seen: set[str] = set()
        for source in ordered:
            if source.id in seen:
                raise WaterCarryError("duplicate water source id", source=source.id)
            seen.add(source.id)
        self._sources: tuple[WaterSource, ...] = tuple(ordered)
        miles = _dedupe_ascending([s.mile for s in ordered])
        self._index: MileIndex | None = MileIndex(miles) if miles else None

    @property
    def sources(self) -> tuple[WaterSource, ...]:
        return self._sources

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self) -> Iterable[WaterSource]:
        return iter(self._sources)

    def get(self, source_id: str) -> WaterSource:
        for source in self._sources:
            if source.id == source_id:
                return source
        raise WaterCarryError("no such water source", source=source_id)

    def usable(self, month: int, threshold: float = 0.6) -> tuple[WaterSource, ...]:
        """Sources worth planning around this month, in mile order."""
        return tuple(s for s in self._sources if s.is_usable(month, threshold))

    def between(
        self, start_mile: float, end_mile: float, month: int, threshold: float = 0.6
    ) -> tuple[WaterSource, ...]:
        return tuple(
            s
            for s in self.usable(month, threshold)
            if start_mile <= s.mile <= end_mile
        )

    def next_usable(
        self, mile: float, month: int, threshold: float = 0.6
    ) -> WaterSource | None:
        for source in self.usable(month, threshold):
            if source.mile > mile:
                return source
        return None

    def previous_usable(
        self, mile: float, month: int, threshold: float = 0.6
    ) -> WaterSource | None:
        found = None
        for source in self.usable(month, threshold):
            if source.mile <= mile:
                found = source
            else:
                break
        return found

    def with_source(self, source: WaterSource) -> WaterTable:
        return WaterTable([*self._sources, source])

    def without(self, source_id: str) -> WaterTable:
        return WaterTable([s for s in self._sources if s.id != source_id])

    def for_month(self, when: date, threshold: float = 0.6) -> tuple[WaterSource, ...]:
        return self.usable(when.month, threshold)

    def __repr__(self) -> str:
        if self._index is None:
            return "WaterTable(empty)"
        return f"WaterTable({len(self._sources)} sources, {self._index.first:.1f}-{self._index.last:.1f} mi)"


def _dedupe_ascending(miles: list[float]) -> list[float]:
    """Two sources can share a mile. The index only needs distinct keys."""
    out: list[float] = []
    for mile in miles:
        if not out or mile > out[-1]:
            out.append(mile)
    return out
