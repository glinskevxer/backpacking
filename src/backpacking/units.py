"""Typed physical quantities.

Trail data arrives in a mess of units. Datasheets are in statute miles and feet,
GPX is in metres, gear lists are in ounces, bear canisters are sized in cubic
inches and water is carried in litres. Passing bare floats around invites the
kind of mistake that silently plans a 30 kilometre day as a 30 mile day, so
every distance, mass, volume, duration and energy in this package is one of the
classes below.

Each class stores a single canonical float and exposes read only conversions.
They are frozen, hashable and orderable, and arithmetic between two quantities
of the same kind returns the same kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

METERS_PER_MILE = 1609.344
METERS_PER_FOOT = 0.3048
METERS_PER_KILOMETER = 1000.0

GRAMS_PER_OUNCE = 28.349523125
GRAMS_PER_POUND = 453.59237
GRAMS_PER_KILOGRAM = 1000.0

MILLILITERS_PER_LITER = 1000.0
MILLILITERS_PER_CUBIC_INCH = 16.387064
MILLILITERS_PER_FLUID_OUNCE = 29.5735295625

SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, order=True, slots=True)
class _Quantity:
    """Common behaviour for the scalar quantity types below."""

    canonical: float

    def __post_init__(self) -> None:
        if self.canonical != self.canonical:  # NaN check without importing math
            raise ValueError(f"{type(self).__name__} cannot hold NaN")

    def __add__(self, other: Self) -> Self:
        self._require_same_kind(other)
        return type(self)(self.canonical + other.canonical)

    def __sub__(self, other: Self) -> Self:
        self._require_same_kind(other)
        return type(self)(self.canonical - other.canonical)

    def __mul__(self, factor: float) -> Self:
        return type(self)(self.canonical * factor)

    def __rmul__(self, factor: float) -> Self:
        return type(self)(self.canonical * factor)

    def __neg__(self) -> Self:
        return type(self)(-self.canonical)

    def __abs__(self) -> Self:
        return type(self)(abs(self.canonical))

    def __bool__(self) -> bool:
        return self.canonical != 0.0

    def _require_same_kind(self, other: object) -> None:
        if type(other) is not type(self):
            raise TypeError(
                f"cannot combine {type(self).__name__} with "
                f"{type(other).__name__}; convert explicitly first"
            )


@dataclass(frozen=True, order=True, slots=True)
class Distance(_Quantity):
    """A length along the ground, stored in metres."""

    @classmethod
    def meters(cls, value: float) -> Distance:
        return cls(float(value))

    @classmethod
    def kilometers(cls, value: float) -> Distance:
        return cls(float(value) * METERS_PER_KILOMETER)

    @classmethod
    def miles(cls, value: float) -> Distance:
        return cls(float(value) * METERS_PER_MILE)

    @classmethod
    def feet(cls, value: float) -> Distance:
        return cls(float(value) * METERS_PER_FOOT)

    @classmethod
    def zero(cls) -> Distance:
        return cls(0.0)

    @property
    def in_meters(self) -> float:
        return self.canonical

    @property
    def in_kilometers(self) -> float:
        return self.canonical / METERS_PER_KILOMETER

    @property
    def in_miles(self) -> float:
        return self.canonical / METERS_PER_MILE

    @property
    def in_feet(self) -> float:
        return self.canonical / METERS_PER_FOOT

    def __truediv__(self, other: Distance | float) -> float | Distance:
        if isinstance(other, Distance):
            return self.canonical / other.canonical
        return Distance(self.canonical / other)

    def __repr__(self) -> str:
        return f"Distance({self.in_miles:.3f} mi)"


@dataclass(frozen=True, order=True, slots=True)
class Mass(_Quantity):
    """A carried mass, stored in grams."""

    @classmethod
    def grams(cls, value: float) -> Mass:
        return cls(float(value))

    @classmethod
    def kilograms(cls, value: float) -> Mass:
        return cls(float(value) * GRAMS_PER_KILOGRAM)

    @classmethod
    def ounces(cls, value: float) -> Mass:
        return cls(float(value) * GRAMS_PER_OUNCE)

    @classmethod
    def pounds(cls, value: float) -> Mass:
        return cls(float(value) * GRAMS_PER_POUND)

    @classmethod
    def zero(cls) -> Mass:
        return cls(0.0)

    @property
    def in_grams(self) -> float:
        return self.canonical

    @property
    def in_kilograms(self) -> float:
        return self.canonical / GRAMS_PER_KILOGRAM

    @property
    def in_ounces(self) -> float:
        return self.canonical / GRAMS_PER_OUNCE

    @property
    def in_pounds(self) -> float:
        return self.canonical / GRAMS_PER_POUND

    def __repr__(self) -> str:
        return f"Mass({self.in_pounds:.3f} lb)"


@dataclass(frozen=True, order=True, slots=True)
class Volume(_Quantity):
    """A packed or carried volume, stored in millilitres."""

    @classmethod
    def milliliters(cls, value: float) -> Volume:
        return cls(float(value))

    @classmethod
    def liters(cls, value: float) -> Volume:
        return cls(float(value) * MILLILITERS_PER_LITER)

    @classmethod
    def cubic_inches(cls, value: float) -> Volume:
        return cls(float(value) * MILLILITERS_PER_CUBIC_INCH)

    @classmethod
    def fluid_ounces(cls, value: float) -> Volume:
        return cls(float(value) * MILLILITERS_PER_FLUID_OUNCE)

    @classmethod
    def zero(cls) -> Volume:
        return cls(0.0)

    @property
    def in_milliliters(self) -> float:
        return self.canonical

    @property
    def in_liters(self) -> float:
        return self.canonical / MILLILITERS_PER_LITER

    @property
    def in_cubic_inches(self) -> float:
        return self.canonical / MILLILITERS_PER_CUBIC_INCH

    def __repr__(self) -> str:
        return f"Volume({self.in_liters:.3f} L)"


@dataclass(frozen=True, order=True, slots=True)
class Duration(_Quantity):
    """Elapsed time, stored in seconds."""

    @classmethod
    def seconds(cls, value: float) -> Duration:
        return cls(float(value))

    @classmethod
    def minutes(cls, value: float) -> Duration:
        return cls(float(value) * SECONDS_PER_MINUTE)

    @classmethod
    def hours(cls, value: float) -> Duration:
        return cls(float(value) * SECONDS_PER_HOUR)

    @classmethod
    def zero(cls) -> Duration:
        return cls(0.0)

    @property
    def in_seconds(self) -> float:
        return self.canonical

    @property
    def in_minutes(self) -> float:
        return self.canonical / SECONDS_PER_MINUTE

    @property
    def in_hours(self) -> float:
        return self.canonical / SECONDS_PER_HOUR

    def as_clock(self) -> str:
        """Render as ``H:MM``, which is how a datasheet prints a leg time."""
        total_minutes = int(round(self.canonical / SECONDS_PER_MINUTE))
        return f"{total_minutes // 60}:{total_minutes % 60:02d}"

    def __repr__(self) -> str:
        return f"Duration({self.as_clock()})"


@dataclass(frozen=True, order=True, slots=True)
class Energy(_Quantity):
    """Food energy, stored in kilocalories, because that is how food is labelled."""

    @classmethod
    def kilocalories(cls, value: float) -> Energy:
        return cls(float(value))

    @classmethod
    def zero(cls) -> Energy:
        return cls(0.0)

    @property
    def in_kilocalories(self) -> float:
        return self.canonical

    def __repr__(self) -> str:
        return f"Energy({self.canonical:.0f} kcal)"


def speed_mph(distance: Distance, duration: Duration) -> float:
    """Average speed in statute miles per hour."""
    if duration.in_seconds <= 0.0:
        raise ValueError("duration must be positive to compute a speed")
    return distance.in_miles / duration.in_hours


def caloric_density(energy: Energy, mass: Mass) -> float:
    """Kilocalories per ounce, the number every resupply argument turns on."""
    if mass.in_ounces <= 0.0:
        raise ValueError("mass must be positive to compute a caloric density")
    return energy.in_kilocalories / mass.in_ounces
