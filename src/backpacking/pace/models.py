"""The hiker, and the shape of a time estimate.

A pace model without a hiker attached is worthless. The same 14 mile day with
3,800 feet of climb is a short afternoon for one person and a full day for
another, and the difference is not fitness alone: it is how long they are
willing to be on their feet, how much they stop, whether they will walk after
dark, and how much weight they are carrying.

:class:`HikerProfile` collects those into one value object, so a plan can be
rebuilt for a different hiker by changing one argument.
"""

from __future__ import annotations

from dataclasses import dataclass

from backpacking.errors import PaceModelError
from backpacking.trail.models import Surface
from backpacking.units import Distance, Duration, Mass


@dataclass(frozen=True, slots=True)
class HikerProfile:
    """Everything about a hiker that changes how long a day takes."""

    name: str = "default"

    #: Speed on level, good tread, carrying the baseline load. This is the one
    #: number most people can estimate about themselves accurately.
    flat_pace_mph: float = 3.0

    #: Hours per day actually walking, before breaks are added.
    max_moving_hours: float = 9.0

    #: Ceiling on a day's climb. Above this the day is refused rather than
    #: slowed, because past a point people stop rather than push on.
    max_daily_gain_ft: float = 6000.0

    #: Fraction of moving time spent stopped: water, food, filtering, views.
    break_fraction: float = 0.18

    #: Base weight plus consumables at the start of a carry. The load model
    #: reads the difference from :attr:`reference_load`.
    reference_load: Mass = Mass.pounds(25.0)

    #: Extra slowing per pound over the reference load, as a fraction.
    load_penalty_per_pound: float = 0.011

    #: Willingness to walk after dark, which buys roughly two more hours.
    night_hiking: bool = False

    #: Elevation above which thin air starts to bite, and how hard.
    altitude_threshold_ft: float = 8000.0
    altitude_penalty_per_1000ft: float = 0.06

    #: Days of load carrying before the legs are trail hardened.
    conditioning_days: int = 10

    def __post_init__(self) -> None:
        if self.flat_pace_mph <= 0.0:
            raise PaceModelError("flat pace must be positive", pace=self.flat_pace_mph)
        if not 0.0 <= self.break_fraction < 1.0:
            raise PaceModelError(
                "break fraction must fall in [0, 1)", break_fraction=self.break_fraction
            )
        if self.max_moving_hours <= 0.0:
            raise PaceModelError(
                "max moving hours must be positive", hours=self.max_moving_hours
            )
        if self.max_daily_gain_ft <= 0.0:
            raise PaceModelError(
                "max daily gain must be positive", gain_ft=self.max_daily_gain_ft
            )
        if self.load_penalty_per_pound < 0.0:
            raise PaceModelError(
                "load penalty must not be negative", penalty=self.load_penalty_per_pound
            )
        if self.conditioning_days < 0:
            raise PaceModelError(
                "conditioning days must not be negative", days=self.conditioning_days
            )

    @property
    def daily_hour_budget(self) -> Duration:
        """Moving hours available, including the bonus for walking after dark."""
        hours = self.max_moving_hours + (2.0 if self.night_hiking else 0.0)
        return Duration.hours(hours)

    def elapsed_from_moving(self, moving: Duration) -> Duration:
        """Add this hiker's break time to a moving time."""
        return Duration.seconds(moving.in_seconds * (1.0 + self.break_fraction))

    def moving_from_elapsed(self, elapsed: Duration) -> Duration:
        return Duration.seconds(elapsed.in_seconds / (1.0 + self.break_fraction))

    def with_pace(self, flat_pace_mph: float) -> HikerProfile:
        return self._replace(flat_pace_mph=flat_pace_mph)

    def with_load(self, reference_load: Mass) -> HikerProfile:
        return self._replace(reference_load=reference_load)

    def _replace(self, **changes: object) -> HikerProfile:
        fields = {
            "name": self.name,
            "flat_pace_mph": self.flat_pace_mph,
            "max_moving_hours": self.max_moving_hours,
            "max_daily_gain_ft": self.max_daily_gain_ft,
            "break_fraction": self.break_fraction,
            "reference_load": self.reference_load,
            "load_penalty_per_pound": self.load_penalty_per_pound,
            "night_hiking": self.night_hiking,
            "altitude_threshold_ft": self.altitude_threshold_ft,
            "altitude_penalty_per_1000ft": self.altitude_penalty_per_1000ft,
            "conditioning_days": self.conditioning_days,
        }
        fields.update(changes)
        return HikerProfile(**fields)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        return f"HikerProfile({self.name!r}, {self.flat_pace_mph:.1f} mph flat)"


@dataclass(frozen=True, slots=True)
class LegEstimate:
    """A time estimate for one stretch, with the terms that produced it."""

    distance: Distance
    gain: Distance
    loss: Distance
    moving_time: Duration
    elapsed_time: Duration
    surface: Surface = Surface.TREAD

    @property
    def average_mph(self) -> float:
        hours = self.moving_time.in_hours
        return 0.0 if hours <= 0.0 else self.distance.in_miles / hours

    @property
    def break_time(self) -> Duration:
        return Duration.seconds(self.elapsed_time.in_seconds - self.moving_time.in_seconds)

    def __add__(self, other: LegEstimate) -> LegEstimate:
        if not isinstance(other, LegEstimate):
            raise TypeError("can only add a LegEstimate to a LegEstimate")
        return LegEstimate(
            distance=self.distance + other.distance,
            gain=self.gain + other.gain,
            loss=self.loss + other.loss,
            moving_time=self.moving_time + other.moving_time,
            elapsed_time=self.elapsed_time + other.elapsed_time,
            surface=self.surface if self.surface is other.surface else Surface.TREAD,
        )

    @classmethod
    def empty(cls) -> LegEstimate:
        return cls(
            distance=Distance.zero(),
            gain=Distance.zero(),
            loss=Distance.zero(),
            moving_time=Duration.zero(),
            elapsed_time=Duration.zero(),
        )

    def __repr__(self) -> str:
        return (
            f"LegEstimate({self.distance.in_miles:.1f} mi, "
            f"+{self.gain.in_feet:.0f} ft, {self.elapsed_time.as_clock()})"
        )
