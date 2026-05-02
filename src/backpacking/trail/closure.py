"""Closures, and routing around them.

A closure is the one input that arrives mid trip. A fire starts, an agency shuts
a stretch of trail, and a plan built in March becomes illegal in July. The
handling has to be quick and it has to be honest about the two outcomes: either
an alternate spans the closure, or the section has to be skipped and the hiker
needs to know exactly how much of it.

Closures are half open on the far end, matching every other mileage interval in
this package.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from backpacking.errors import CorridorError, RouteResolutionError
from backpacking.trail.alternates import Alternate, bypassed_span
from backpacking.trail.corridor import Corridor
from backpacking.units import Distance


class ClosureKind(StrEnum):
    """Why a stretch is shut, which decides how firm the closure is."""

    FIRE = "fire"
    FLOOD = "flood"
    WILDLIFE = "wildlife"
    CONSTRUCTION = "construction"
    PRIVATE_LAND = "private_land"
    SEASONAL = "seasonal"

    @property
    def is_hard(self) -> bool:
        """Whether the closure carries a legal penalty rather than advice."""
        return self in {
            ClosureKind.FIRE,
            ClosureKind.PRIVATE_LAND,
            ClosureKind.WILDLIFE,
        }


@dataclass(frozen=True, slots=True)
class Closure:
    """A shut stretch of corridor, with the dates it applies."""

    id: str
    start_mile: float
    end_mile: float
    kind: ClosureKind = ClosureKind.FIRE
    effective_from: date | None = None
    effective_to: date | None = None
    agency: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.end_mile <= self.start_mile:
            raise RouteResolutionError(
                "a closure covers a positive span",
                closure=self.id,
                start_mile=self.start_mile,
                end_mile=self.end_mile,
            )
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise RouteResolutionError(
                "a closure must not end before it starts", closure=self.id
            )

    @property
    def length(self) -> Distance:
        return Distance.miles(self.end_mile - self.start_mile)

    def applies_on(self, when: date) -> bool:
        if self.effective_from is not None and when < self.effective_from:
            return False
        return not (self.effective_to is not None and when > self.effective_to)

    def covers(self, mile: float) -> bool:
        return self.start_mile <= mile < self.end_mile

    def overlaps_span(self, start_mile: float, end_mile: float) -> bool:
        return self.start_mile < end_mile and start_mile < self.end_mile

    def __repr__(self) -> str:
        return (
            f"Closure({self.id!r}, {self.start_mile:.1f}-{self.end_mile:.1f} mi, "
            f"{self.kind.value})"
        )


class ClosureSet:
    """Every closure known for a corridor."""

    __slots__ = ("_closures",)

    def __init__(self, closures: Sequence[Closure] = ()) -> None:
        ordered = tuple(sorted(closures, key=lambda c: c.start_mile))
        seen: set[str] = set()
        for closure in ordered:
            if closure.id in seen:
                raise RouteResolutionError("duplicate closure id", closure=closure.id)
            seen.add(closure.id)
        self._closures: tuple[Closure, ...] = ordered

    def __len__(self) -> int:
        return len(self._closures)

    def __iter__(self) -> Iterator[Closure]:
        return iter(self._closures)

    @property
    def closures(self) -> tuple[Closure, ...]:
        return self._closures

    def get(self, closure_id: str) -> Closure:
        for closure in self._closures:
            if closure.id == closure_id:
                return closure
        raise RouteResolutionError("no such closure", closure=closure_id)

    def active_on(self, when: date, *, hard_only: bool = False) -> tuple[Closure, ...]:
        return tuple(
            closure
            for closure in self._closures
            if closure.applies_on(when) and (not hard_only or closure.kind.is_hard)
        )

    def blocking(self, start_mile: float, end_mile: float, when: date) -> tuple[Closure, ...]:
        """Closures in force on a date that intersect a stretch."""
        return tuple(
            closure
            for closure in self.active_on(when)
            if closure.overlaps_span(start_mile, end_mile)
        )

    def closed_miles(self, when: date) -> float:
        """Total corridor mileage shut on a date, merging overlaps."""
        active = sorted(self.active_on(when), key=lambda c: c.start_mile)
        total = 0.0
        cursor = float("-inf")
        for closure in active:
            start = max(closure.start_mile, cursor)
            if closure.end_mile > start:
                total += closure.end_mile - start
                cursor = closure.end_mile
        return total

    def __repr__(self) -> str:
        return f"ClosureSet({len(self._closures)} closures)"


def alternates_covering(
    corridor: Corridor, closure: Closure, alternates: Sequence[Alternate]
) -> tuple[Alternate, ...]:
    """Alternates whose bypassed span fully contains a closure."""
    covering: list[Alternate] = []
    for alternate in alternates:
        try:
            start, end = bypassed_span(corridor, alternate)
        except CorridorError:
            # Either the alternate names a waypoint this corridor does not have,
            # or it rejoins before it departs. Both mean it is not a candidate.
            continue
        if start <= closure.start_mile and end >= closure.end_mile:
            covering.append(alternate)
    return tuple(covering)


def choose_detour(
    corridor: Corridor, closure: Closure, alternates: Sequence[Alternate]
) -> Alternate:
    """The shortest alternate that spans a closure, preferring official ones."""
    covering = alternates_covering(corridor, closure, alternates)
    if not covering:
        raise RouteResolutionError(
            "no alternate spans this closure",
            closure=closure.id,
            start_mile=closure.start_mile,
            end_mile=closure.end_mile,
        )
    return min(covering, key=lambda alternate: (not alternate.official, alternate.length_miles))


@dataclass(frozen=True, slots=True)
class SkipReport:
    """What has to be skipped when nothing routes around a closure."""

    closure: Closure
    skipped: Distance
    resume_at: float

    def __repr__(self) -> str:
        return (
            f"SkipReport({self.closure.id}, skip {self.skipped.in_miles:.1f} mi, "
            f"resume at {self.resume_at:.1f})"
        )


def skip_for(corridor: Corridor, closure: Closure) -> SkipReport:
    """Describe walking around a closure by road rather than on the corridor."""
    if closure.end_mile > corridor.end_mile:
        raise RouteResolutionError(
            "closure runs past the end of the corridor",
            closure=closure.id,
            end_mile=closure.end_mile,
            corridor_end=corridor.end_mile,
        )
    return SkipReport(
        closure=closure,
        skipped=closure.length,
        resume_at=closure.end_mile,
    )
