"""Multi day fatigue, conditioning and recovery.

A single day estimate that ignores the twelve days before it is wrong in a
direction that matters. Two effects pull against each other over a long trail:

* **Accumulated fatigue** builds with consecutive hard days and slows a hiker
  down. It recovers on an easy day and much faster on a zero.
* **Conditioning** builds over weeks and speeds a hiker up. It is why week six
  on a thru hike feels nothing like week one, and it saturates.

The state is carried in :class:`FatigueState`, which is advanced one day at a
time. It is a value object, so a solver can branch on it without copying.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backpacking.errors import PaceModelError
from backpacking.pace.models import HikerProfile

#: A day at this effort neither builds nor sheds fatigue.
NEUTRAL_EFFORT_HOURS = 7.0

#: Ceiling on accumulated fatigue, as a fraction of speed lost.
MAX_FATIGUE = 0.30

#: How much of the day's excess effort converts into fatigue.
FATIGUE_GAIN_RATE = 0.022

#: How much fatigue an easy day sheds, and a full rest day on top of that.
FATIGUE_RECOVERY_RATE = 0.030
ZERO_DAY_RECOVERY = 0.14

#: Ceiling on the conditioning bonus, as a fraction of speed gained.
MAX_CONDITIONING = 0.12


@dataclass(frozen=True, slots=True)
class FatigueState:
    """Where a hiker is after a run of days on trail."""

    day: int = 0
    fatigue: float = 0.0
    conditioning: float = 0.0
    consecutive_days: int = 0

    def __post_init__(self) -> None:
        if self.day < 0:
            raise PaceModelError("day index must not be negative", day=self.day)
        if not 0.0 <= self.fatigue <= MAX_FATIGUE:
            raise PaceModelError("fatigue out of range", fatigue=self.fatigue)
        if not 0.0 <= self.conditioning <= MAX_CONDITIONING:
            raise PaceModelError("conditioning out of range", conditioning=self.conditioning)

    @property
    def speed_factor(self) -> float:
        """Net speed multiplier from tiredness and trail legs together."""
        return max(0.5, 1.0 - self.fatigue + self.conditioning)

    @property
    def is_rested(self) -> bool:
        return self.fatigue < 0.02

    def __repr__(self) -> str:
        return (
            f"FatigueState(day {self.day}, fatigue {self.fatigue:.0%}, "
            f"conditioning {self.conditioning:.0%})"
        )


def advance(state: FatigueState, profile: HikerProfile, effort_hours: float) -> FatigueState:
    """Advance one day of walking at ``effort_hours`` of moving time."""
    if effort_hours < 0.0:
        raise PaceModelError("effort hours must not be negative", hours=effort_hours)
    excess = effort_hours - NEUTRAL_EFFORT_HOURS
    if excess > 0.0:
        fatigue = state.fatigue + excess * FATIGUE_GAIN_RATE
    else:
        fatigue = state.fatigue + excess * FATIGUE_RECOVERY_RATE
    return replace(
        state,
        day=state.day + 1,
        fatigue=_clamp(fatigue, 0.0, MAX_FATIGUE),
        conditioning=_condition(state, profile),
        consecutive_days=state.consecutive_days + 1,
    )


def take_zero(state: FatigueState, profile: HikerProfile) -> FatigueState:
    """Advance one full rest day. Conditioning holds, fatigue drops hard."""
    return replace(
        state,
        day=state.day + 1,
        fatigue=_clamp(state.fatigue - ZERO_DAY_RECOVERY, 0.0, MAX_FATIGUE),
        conditioning=state.conditioning,
        consecutive_days=0,
    )


def _condition(state: FatigueState, profile: HikerProfile) -> float:
    """Conditioning approaches its ceiling on the profile's own timescale."""
    if profile.conditioning_days == 0:
        return MAX_CONDITIONING
    step = MAX_CONDITIONING / profile.conditioning_days
    return _clamp(state.conditioning + step, 0.0, MAX_CONDITIONING)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def project(
    profile: HikerProfile,
    daily_effort_hours: list[float],
    zero_days: set[int] | None = None,
) -> list[FatigueState]:
    """Run a whole itinerary's efforts through the model, day by day.

    ``zero_days`` holds one based day numbers on which no walking happens.
    Returns the state after each day, so the list is the same length as the
    effort list plus any zeros interleaved by index.
    """
    zeros = zero_days or set()
    state = FatigueState()
    out: list[FatigueState] = []
    for index, hours in enumerate(daily_effort_hours, start=1):
        state = take_zero(state, profile) if index in zeros else advance(state, profile, hours)
        out.append(state)
    return out


def sustainable_effort(profile: HikerProfile, state: FatigueState) -> float:
    """Moving hours this hiker can put in today without digging a deeper hole.

    Solving ``advance`` for the effort that leaves fatigue unchanged gives the
    neutral figure; a tired hiker gets less than that so the debt comes down.
    """
    headroom = (MAX_FATIGUE - state.fatigue) / MAX_FATIGUE
    ceiling = profile.daily_hour_budget.in_hours
    return max(2.0, min(ceiling, NEUTRAL_EFFORT_HOURS + headroom * (ceiling - NEUTRAL_EFFORT_HOURS)))
