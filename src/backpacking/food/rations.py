"""Turning a day's effort into a weight of food.

The chain is: effort gives calories, calories divided by caloric density gives
weight, weight goes back into the pack and slows the hiker down, which changes
the effort. Two passes are enough to settle it in practice, and this module does
not iterate further, because the input uncertainty dwarfs the difference.

Caloric density is the lever that matters. Food at 100 kcal per ounce and food
at 160 kcal per ounce differ by four pounds over a six day carry, which is more
than most people save by replacing a tent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from backpacking.errors import LoadoutError
from backpacking.units import Energy, Mass, Volume, caloric_density

#: A hiker at rest still burns this much before a step is taken.
BASAL_KCAL_PER_DAY = 1800.0

#: Practical floor and ceiling on what a body will absorb on trail. Beyond the
#: ceiling the extra food is dead weight, which is why long trails end in a
#: deficit no matter how much is carried.
MIN_DAILY_KCAL = 1600.0
MAX_ABSORBABLE_KCAL = 5500.0

#: Density thresholds people plan around, in kilocalories per ounce.
POOR_DENSITY = 100.0
GOOD_DENSITY = 125.0
EXCELLENT_DENSITY = 145.0


@dataclass(frozen=True, slots=True)
class FoodItem:
    """One thing in the food bag."""

    id: str
    name: str
    mass: Mass
    energy: Energy
    volume: Volume | None = None
    meal: str = "snack"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.mass.in_grams <= 0.0:
            raise LoadoutError("food item mass must be positive", item=self.id)
        if self.energy.in_kilocalories < 0.0:
            raise LoadoutError("food item energy must not be negative", item=self.id)
        if self.volume is not None and self.volume.in_milliliters <= 0.0:
            raise LoadoutError("food item volume must be positive", item=self.id)

    @property
    def density(self) -> float:
        """Kilocalories per ounce."""
        return caloric_density(self.energy, self.mass)

    @property
    def is_dense_enough(self) -> bool:
        return self.density >= GOOD_DENSITY

    def scaled(self, factor: float) -> FoodItem:
        """The same item in a different portion size."""
        if factor <= 0.0:
            raise LoadoutError("portion factor must be positive", item=self.id, factor=factor)
        return FoodItem(
            id=self.id,
            name=self.name,
            mass=self.mass * factor,
            energy=self.energy * factor,
            volume=None if self.volume is None else self.volume * factor,
            meal=self.meal,
            notes=self.notes,
        )

    def __repr__(self) -> str:
        return f"FoodItem({self.id!r}, {self.mass.in_ounces:.1f} oz, {self.density:.0f} kcal/oz)"


@dataclass(frozen=True, slots=True)
class RationPlan:
    """What one carry between resupplies demands."""

    days: float
    daily_energy: Energy
    density_kcal_per_oz: float
    items: tuple[FoodItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.days <= 0.0:
            raise LoadoutError("a ration plan covers at least part of a day", days=self.days)
        if self.density_kcal_per_oz <= 0.0:
            raise LoadoutError(
                "caloric density must be positive", density=self.density_kcal_per_oz
            )

    @property
    def total_energy(self) -> Energy:
        return self.daily_energy * self.days

    @property
    def total_mass(self) -> Mass:
        """Weight of the food bag, from the energy and the density."""
        return Mass.ounces(self.total_energy.in_kilocalories / self.density_kcal_per_oz)

    @property
    def daily_mass(self) -> Mass:
        return Mass.ounces(self.daily_energy.in_kilocalories / self.density_kcal_per_oz)

    def mass_remaining_after(self, days_walked: float) -> Mass:
        """Food still in the pack after ``days_walked``, never below zero."""
        if days_walked < 0.0:
            raise LoadoutError("days walked must not be negative", days=days_walked)
        left = max(0.0, self.days - days_walked)
        return Mass.ounces(self.daily_mass.in_ounces * left)

    def __repr__(self) -> str:
        return (
            f"RationPlan({self.days:.1f} days, {self.total_mass.in_pounds:.2f} lb, "
            f"{self.density_kcal_per_oz:.0f} kcal/oz)"
        )


def daily_requirement(
    burned: Energy,
    *,
    basal_kcal: float = BASAL_KCAL_PER_DAY,
    deficit_fraction: float = 0.15,
) -> Energy:
    """Calories to carry per day, given what the walking burns.

    A deficit is planned deliberately. Nobody carries their full requirement on a
    long trail: the body makes up the difference from reserves and from town
    food, and carrying the full figure costs more in pack weight than it returns.
    """
    if burned.in_kilocalories < 0.0:
        raise LoadoutError("burned energy must not be negative")
    if not 0.0 <= deficit_fraction < 1.0:
        raise LoadoutError(
            "deficit fraction must fall in [0, 1)", deficit_fraction=deficit_fraction
        )
    total = (basal_kcal + burned.in_kilocalories) * (1.0 - deficit_fraction)
    clamped = min(MAX_ABSORBABLE_KCAL, max(MIN_DAILY_KCAL, total))
    return Energy.kilocalories(clamped)


def plan_rations(
    days: float,
    burned_per_day: Energy,
    *,
    density_kcal_per_oz: float = GOOD_DENSITY,
    deficit_fraction: float = 0.15,
) -> RationPlan:
    """Build a ration plan for one carry."""
    return RationPlan(
        days=days,
        daily_energy=daily_requirement(burned_per_day, deficit_fraction=deficit_fraction),
        density_kcal_per_oz=density_kcal_per_oz,
    )


def plan_from_items(days: float, items: Sequence[FoodItem]) -> RationPlan:
    """Build a plan from a real food bag rather than from an average density."""
    if not items:
        raise LoadoutError("cannot build a ration plan from an empty food bag")
    total_energy = Energy.kilocalories(sum(item.energy.in_kilocalories for item in items))
    total_mass = Mass.grams(sum(item.mass.in_grams for item in items))
    return RationPlan(
        days=days,
        daily_energy=Energy.kilocalories(total_energy.in_kilocalories / days),
        density_kcal_per_oz=caloric_density(total_energy, total_mass),
        items=tuple(items),
    )


def describe_density(density_kcal_per_oz: float) -> str:
    """The word a planner would use for this density."""
    if density_kcal_per_oz >= EXCELLENT_DENSITY:
        return "excellent"
    if density_kcal_per_oz >= GOOD_DENSITY:
        return "good"
    if density_kcal_per_oz >= POOR_DENSITY:
        return "workable"
    return "heavy"
