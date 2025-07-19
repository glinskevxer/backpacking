"""Places to get off trail and buy food.

The thing that makes resupply planning hard is that a stop is not free. Getting
into town costs a hitch, a walk, or a shuttle that runs twice a day; getting out
costs the same again plus whatever the town takes out of the hiker. A stop with
a full grocery three miles off trail can easily cost less than one with a gas
station rack a hundred yards from the trailhead, because the second one forces a
heavier carry either side.

So a resupply point carries what it costs to reach as well as what it offers,
and the strategy module trades those off.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, time
from enum import IntEnum

from backpacking.errors import ResupplyInfeasible
from backpacking.units import Distance, Duration


class ServiceLevel(IntEnum):
    """What can actually be bought, ordered so it can be compared."""

    NONE = 0
    GAS_STATION = 1
    CONVENIENCE = 2
    SMALL_GROCERY = 3
    FULL_GROCERY = 4

    @property
    def supports_full_resupply(self) -> bool:
        """Whether a hiker can put together a whole carry here."""
        return self >= ServiceLevel.SMALL_GROCERY

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").lower()


@dataclass(frozen=True, slots=True)
class ResupplyPoint:
    """One place a hiker can leave the trail to resupply."""

    id: str
    name: str
    mile: float
    groceries: ServiceLevel = ServiceLevel.NONE
    hitch: Distance = Distance.zero()
    walk_in: Distance = Distance.zero()
    shuttle_wait: Duration = Duration.zero()
    has_post_office: bool = False
    has_lodging: bool = False
    has_shower: bool = False
    open_days: frozenset[int] = field(default_factory=lambda: frozenset(range(7)))
    hours: tuple[time, time] | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.mile < 0.0:
            raise ResupplyInfeasible("resupply mile must not be negative", point=self.id)
        if self.hitch.in_miles < 0.0 or self.walk_in.in_miles < 0.0:
            raise ResupplyInfeasible("access distances must not be negative", point=self.id)
        for day in self.open_days:
            if day not in range(7):
                raise ResupplyInfeasible(
                    "open days are Monday zero through Sunday six", point=self.id, day=day
                )
        if self.hours is not None and self.hours[1] <= self.hours[0]:
            raise ResupplyInfeasible("opening hours must span forwards", point=self.id)

    @property
    def is_on_trail(self) -> bool:
        return self.hitch.in_miles == 0.0 and self.walk_in.in_miles == 0.0

    @property
    def supports_full_resupply(self) -> bool:
        return self.groceries.supports_full_resupply

    def access_cost(self, *, hitch_speed_mph: float = 30.0, walk_mph: float = 3.0) -> Duration:
        """Round trip time to get into town and back to the trail."""
        if hitch_speed_mph <= 0.0 or walk_mph <= 0.0:
            raise ResupplyInfeasible("access speeds must be positive", point=self.id)
        hours = (
            2.0 * self.hitch.in_miles / hitch_speed_mph
            + 2.0 * self.walk_in.in_miles / walk_mph
        )
        return Duration.hours(hours) + self.shuttle_wait * 2.0

    def is_open_on(self, when: date) -> bool:
        return when.weekday() in self.open_days

    def next_open_day(self, when: date, *, search_days: int = 14) -> date | None:
        from datetime import timedelta

        for offset in range(search_days):
            candidate = when + timedelta(days=offset)
            if self.is_open_on(candidate):
                return candidate
        return None

    def __repr__(self) -> str:
        return (
            f"ResupplyPoint({self.id!r} @ {self.mile:.1f} mi, {self.groceries.label})"
        )


class TownIndex:
    """Every resupply point on a corridor, in mile order."""

    __slots__ = ("_points",)

    def __init__(self, points: Sequence[ResupplyPoint]) -> None:
        ordered = tuple(sorted(points, key=lambda p: p.mile))
        seen: set[str] = set()
        for point in ordered:
            if point.id in seen:
                raise ResupplyInfeasible("duplicate resupply point id", point=point.id)
            seen.add(point.id)
        self._points: tuple[ResupplyPoint, ...] = ordered

    @property
    def points(self) -> tuple[ResupplyPoint, ...]:
        return self._points

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self) -> Iterator[ResupplyPoint]:
        return iter(self._points)

    def get(self, point_id: str) -> ResupplyPoint:
        for point in self._points:
            if point.id == point_id:
                return point
        raise ResupplyInfeasible("no such resupply point", point=point_id)

    def full_resupplies(self) -> tuple[ResupplyPoint, ...]:
        return tuple(p for p in self._points if p.supports_full_resupply)

    def with_post_office(self) -> tuple[ResupplyPoint, ...]:
        return tuple(p for p in self._points if p.has_post_office)

    def between(self, start_mile: float, end_mile: float) -> tuple[ResupplyPoint, ...]:
        return tuple(p for p in self._points if start_mile <= p.mile <= end_mile)

    def next_after(
        self, mile: float, *, full_only: bool = False
    ) -> ResupplyPoint | None:
        candidates = self.full_resupplies() if full_only else self._points
        for point in candidates:
            if point.mile > mile:
                return point
        return None

    def longest_gap(self, *, full_only: bool = True) -> float:
        """Longest stretch between usable stops, which sizes the biggest carry."""
        candidates = self.full_resupplies() if full_only else self._points
        if len(candidates) < 2:
            raise ResupplyInfeasible(
                "need at least two stops to measure a gap", count=len(candidates)
            )
        return max(
            second.mile - first.mile
            for first, second in zip(candidates, candidates[1:], strict=False)
        )

    def __repr__(self) -> str:
        return f"TownIndex({len(self._points)} points, {len(self.full_resupplies())} full)"
