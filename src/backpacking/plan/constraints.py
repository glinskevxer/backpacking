"""What a plan is allowed to do.

Hard constraints make a day inadmissible; the solver will not produce it at any
price. Soft preferences are expressed as costs in :mod:`backpacking.plan.scoring`
instead, so that a plan which has to be slightly uncomfortable still gets built
rather than failing outright.

Getting this split right is most of the design. A constraint that should have
been a preference makes the solver report infeasible on a trip that is merely
awkward, which is the least useful possible answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backpacking.errors import PlanInfeasible
from backpacking.pace.models import HikerProfile
from backpacking.units import Distance, Duration, Volume


@dataclass(frozen=True, slots=True)
class PlanConstraints:
    """The hard limits a day has to satisfy to be admissible."""

    #: Absolute ceiling on a day, regardless of how easy the terrain is.
    max_daily_miles: float = 32.0

    #: Floor, so the solver does not produce a two mile day to tidy up an
    #: arithmetic remainder.
    min_daily_miles: float = 4.0

    #: Ceiling on a day's climb.
    max_daily_gain: Distance = Distance.feet(6000.0)

    #: Ceiling on elapsed time, breaks included.
    max_daily_elapsed: Duration = Duration.hours(12.0)

    #: Whether every night has to be at a waypoint that permits camping.
    camps_must_be_named: bool = False

    #: Water a hiker can physically carry, which bounds the dry stretches.
    water_capacity: Volume = Volume.liters(4.0)

    #: Days of food the pack will hold.
    max_carry_days: float = 7.0

    #: Trip level limits.
    max_total_days: int | None = None
    must_finish_by: date | None = None

    #: Camps that must be used, and camps that must not be.
    required_camps: frozenset[str] = field(default_factory=frozenset)
    forbidden_camps: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.min_daily_miles < 0.0:
            raise PlanInfeasible("minimum daily mileage must not be negative")
        if self.max_daily_miles <= self.min_daily_miles:
            raise PlanInfeasible(
                "maximum daily mileage must exceed the minimum",
                minimum=self.min_daily_miles,
                maximum=self.max_daily_miles,
            )
        if self.max_daily_gain.in_feet <= 0.0:
            raise PlanInfeasible("maximum daily gain must be positive")
        if self.max_daily_elapsed.in_hours <= 0.0:
            raise PlanInfeasible("maximum daily elapsed time must be positive")
        if self.max_carry_days <= 0.0:
            raise PlanInfeasible("maximum carry must be at least part of a day")
        if self.max_total_days is not None and self.max_total_days < 1:
            raise PlanInfeasible("a trip is at least one day", days=self.max_total_days)
        overlap = self.required_camps & self.forbidden_camps
        if overlap:
            raise PlanInfeasible(
                "a camp cannot be both required and forbidden", camps=sorted(overlap)
            )

    @classmethod
    def for_profile(cls, profile: HikerProfile) -> PlanConstraints:
        """Constraints derived from a hiker rather than set by hand."""
        return cls(
            max_daily_gain=Distance.feet(profile.max_daily_gain_ft),
            max_daily_elapsed=profile.elapsed_from_moving(profile.daily_hour_budget),
        )

    def day_is_admissible(
        self, miles: float, gain: Distance, elapsed: Duration, *, is_final: bool = False
    ) -> bool:
        """Whether a day of this shape is allowed at all.

        The final day of a trip is exempt from the minimum mileage: arriving at
        the terminus is not something to be penalised for being short.
        """
        if miles > self.max_daily_miles:
            return False
        if miles < self.min_daily_miles and not is_final:
            return False
        if gain > self.max_daily_gain:
            return False
        return elapsed <= self.max_daily_elapsed

    def camp_is_allowed(self, camp_id: str | None) -> bool:
        if camp_id is None:
            return not self.camps_must_be_named
        return camp_id not in self.forbidden_camps

    def trip_is_admissible(self, days: int, finish: date) -> bool:
        if self.max_total_days is not None and days > self.max_total_days:
            return False
        return not (self.must_finish_by is not None and finish > self.must_finish_by)

    def relaxed(self, **changes: object) -> PlanConstraints:
        """A copy with some limits loosened, used when a first pass fails."""
        fields = {
            "max_daily_miles": self.max_daily_miles,
            "min_daily_miles": self.min_daily_miles,
            "max_daily_gain": self.max_daily_gain,
            "max_daily_elapsed": self.max_daily_elapsed,
            "camps_must_be_named": self.camps_must_be_named,
            "water_capacity": self.water_capacity,
            "max_carry_days": self.max_carry_days,
            "max_total_days": self.max_total_days,
            "must_finish_by": self.must_finish_by,
            "required_camps": self.required_camps,
            "forbidden_camps": self.forbidden_camps,
        }
        fields.update(changes)
        return PlanConstraints(**fields)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        return (
            f"PlanConstraints({self.min_daily_miles:.0f}-{self.max_daily_miles:.0f} mi, "
            f"<={self.max_daily_gain.in_feet:.0f} ft)"
        )
