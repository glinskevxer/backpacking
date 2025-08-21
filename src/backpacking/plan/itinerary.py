"""The itinerary, and the day that makes it up.

An itinerary is a sequence of days, each ending at a camp. It is the artifact
everything else in this package exists to produce or to check, so it deliberately
knows nothing about how it was built. A hand written itinerary and one out of the
solver are the same object and go through the same validation.

Days are addressed by index rather than by date, because zero days and town days
break the one to one mapping between days walked and dates elapsed.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import LegEstimate
from backpacking.permits.rules import CampNight
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Waypoint
from backpacking.units import Distance, Duration, Mass


@dataclass(frozen=True, slots=True)
class DayPlan:
    """One day of an itinerary."""

    index: int
    day: date
    start_mile: float
    end_mile: float
    estimate: LegEstimate
    camp: Waypoint | None = None
    pack_weight: Mass = Mass.zero()
    is_zero: bool = False
    resupply_at: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.index < 0:
            raise PlanInfeasible("day index must not be negative", index=self.index)
        if self.end_mile < self.start_mile:
            raise PlanInfeasible(
                "a day must not walk backwards",
                index=self.index,
                start_mile=self.start_mile,
                end_mile=self.end_mile,
            )
        if self.is_zero and self.end_mile != self.start_mile:
            raise PlanInfeasible(
                "a zero day covers no ground", index=self.index, miles=self.miles
            )

    @property
    def miles(self) -> float:
        return self.end_mile - self.start_mile

    @property
    def distance(self) -> Distance:
        return Distance.miles(self.miles)

    @property
    def gain(self) -> Distance:
        return self.estimate.gain

    @property
    def elapsed(self) -> Duration:
        return self.estimate.elapsed_time

    @property
    def camp_id(self) -> str | None:
        return None if self.camp is None else self.camp.id

    def to_camp_night(
        self,
        *,
        has_canister: bool = False,
        wants_fire: bool = False,
        distance_from_water: Distance = Distance.zero(),
    ) -> CampNight:
        """The view of this day the permit rules need."""
        return CampNight(
            night=self.day,
            mile=self.end_mile,
            site_id=self.camp_id,
            elevation=Distance.zero() if self.camp is None else self.camp.elevation,
            has_canister=has_canister,
            wants_fire=wants_fire,
            distance_from_water=distance_from_water,
        )

    def __repr__(self) -> str:
        if self.is_zero:
            return f"DayPlan({self.index}, {self.day.isoformat()}, zero)"
        return (
            f"DayPlan({self.index}, {self.day.isoformat()}, "
            f"{self.miles:.1f} mi to {self.camp_id or 'unnamed'})"
        )


@dataclass(frozen=True, slots=True)
class Itinerary:
    """A whole trip: an ordered run of days over one corridor."""

    corridor: Corridor
    days: tuple[DayPlan, ...]
    label: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.days:
            raise PlanInfeasible("an itinerary needs at least one day", corridor=self.corridor.name)
        for position, day in enumerate(self.days):
            if day.index != position:
                raise PlanInfeasible(
                    "day indices must run from zero without gaps",
                    expected=position,
                    found=day.index,
                )
        for first, second in zip(self.days, self.days[1:], strict=False):
            if second.start_mile != first.end_mile:
                raise PlanInfeasible(
                    "days must join end to end",
                    first_day=first.index,
                    first_end=first.end_mile,
                    second_start=second.start_mile,
                )
            if second.day <= first.day:
                raise PlanInfeasible(
                    "dates must advance", first_day=first.index, date=second.day.isoformat()
                )

    def __len__(self) -> int:
        return len(self.days)

    def __iter__(self) -> Iterator[DayPlan]:
        return iter(self.days)

    def __getitem__(self, index: int) -> DayPlan:
        return self.days[index]

    @property
    def start_date(self) -> date:
        return self.days[0].day

    @property
    def finish_date(self) -> date:
        return self.days[-1].day

    @property
    def start_mile(self) -> float:
        return self.days[0].start_mile

    @property
    def end_mile(self) -> float:
        return self.days[-1].end_mile

    @property
    def total_distance(self) -> Distance:
        return Distance.miles(self.end_mile - self.start_mile)

    @property
    def total_gain(self) -> Distance:
        return Distance.feet(sum(day.estimate.gain.in_feet for day in self.days))

    @property
    def total_elapsed(self) -> Duration:
        return Duration.seconds(sum(day.elapsed.in_seconds for day in self.days))

    @property
    def walking_days(self) -> tuple[DayPlan, ...]:
        return tuple(day for day in self.days if not day.is_zero)

    @property
    def zero_days(self) -> tuple[DayPlan, ...]:
        return tuple(day for day in self.days if day.is_zero)

    @property
    def average_daily_miles(self) -> float:
        walking = self.walking_days
        if not walking:
            return 0.0
        return sum(day.miles for day in walking) / len(walking)

    @property
    def longest_day(self) -> DayPlan:
        return max(self.days, key=lambda day: day.miles)

    @property
    def biggest_climb(self) -> DayPlan:
        return max(self.days, key=lambda day: day.estimate.gain.in_feet)

    @property
    def resupply_days(self) -> tuple[DayPlan, ...]:
        return tuple(day for day in self.days if day.resupply_at is not None)

    def day_on(self, when: date) -> DayPlan | None:
        for day in self.days:
            if day.day == when:
                return day
        return None

    def camp_nights(self, **kwargs: object) -> tuple[CampNight, ...]:
        """Every night of the trip, for the permit checker."""
        return tuple(day.to_camp_night(**kwargs) for day in self.days)  # type: ignore[arg-type]

    def mile_on_day(self, index: int) -> float:
        if not 0 <= index < len(self.days):
            raise PlanInfeasible("no such day in this itinerary", index=index)
        return self.days[index].end_mile

    def covers_whole_corridor(self) -> bool:
        return (
            self.start_mile == self.corridor.start_mile
            and self.end_mile == self.corridor.end_mile
        )

    def with_zero_day_after(self, index: int) -> Itinerary:
        """Insert a rest day after ``index``, pushing every later date back."""
        if not 0 <= index < len(self.days):
            raise PlanInfeasible("no such day to rest after", index=index)
        anchor = self.days[index]
        rest = DayPlan(
            index=index + 1,
            day=anchor.day + timedelta(days=1),
            start_mile=anchor.end_mile,
            end_mile=anchor.end_mile,
            estimate=LegEstimate.empty(),
            camp=anchor.camp,
            pack_weight=anchor.pack_weight,
            is_zero=True,
            notes="rest day",
        )
        rebuilt: list[DayPlan] = list(self.days[: index + 1])
        rebuilt.append(rest)
        for position, day in enumerate(self.days[index + 1 :], start=index + 2):
            rebuilt.append(_reindexed(day, position, day.day + timedelta(days=1)))
        return Itinerary(
            corridor=self.corridor, days=tuple(rebuilt), label=self.label, metadata=self.metadata
        )

    def shifted_to(self, new_start: date) -> Itinerary:
        """The same itinerary starting on a different date."""
        offset = new_start - self.start_date
        rebuilt = tuple(_reindexed(day, day.index, day.day + offset) for day in self.days)
        return Itinerary(
            corridor=self.corridor, days=rebuilt, label=self.label, metadata=self.metadata
        )

    def __repr__(self) -> str:
        return (
            f"Itinerary({self.corridor.name!r}, {len(self.days)} days, "
            f"{self.total_distance.in_miles:.1f} mi)"
        )


def _reindexed(day: DayPlan, index: int, when: date) -> DayPlan:
    return DayPlan(
        index=index,
        day=when,
        start_mile=day.start_mile,
        end_mile=day.end_mile,
        estimate=day.estimate,
        camp=day.camp,
        pack_weight=day.pack_weight,
        is_zero=day.is_zero,
        resupply_at=day.resupply_at,
        notes=day.notes,
    )


def build_itinerary(
    corridor: Corridor, days: Sequence[DayPlan], *, label: str = ""
) -> Itinerary:
    """Convenience constructor that renumbers days from zero."""
    renumbered = tuple(
        _reindexed(day, index, day.day) for index, day in enumerate(days)
    )
    return Itinerary(corridor=corridor, days=renumbered, label=label)
