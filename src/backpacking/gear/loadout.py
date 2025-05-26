"""What the pack weighs at any moment of a carry.

A single "pack weight" number is a fiction. The pack leaving a resupply and the
pack arriving at the next one differ by six pounds or more, and the pace model
is sensitive to that difference, so a plan built on the average is optimistic in
the first half and pessimistic in the second.

:class:`Loadout` therefore answers weight as a function of elapsed days and of
how much water is being carried at that moment, and the solver asks it once per
leg rather than once per trip.
"""

from __future__ import annotations

from dataclasses import dataclass

from backpacking.errors import LoadoutError
from backpacking.food.rations import RationPlan
from backpacking.gear.inventory import Inventory
from backpacking.units import Mass, Volume

#: Water is one kilogram per litre, near enough for any pack.
GRAMS_PER_LITER_WATER = 1000.0

#: Stove fuel burn for a hiker cooking one hot meal a day.
FUEL_GRAMS_PER_DAY = 14.0


@dataclass(frozen=True, slots=True)
class Loadout:
    """A gear list plus the consumables for one carry."""

    inventory: Inventory
    rations: RationPlan
    fuel_start: Mass = Mass.zero()
    carried_water: Volume = Volume.zero()

    def __post_init__(self) -> None:
        if self.fuel_start.in_grams < 0.0:
            raise LoadoutError("fuel mass must not be negative")
        if self.carried_water.in_milliliters < 0.0:
            raise LoadoutError("carried water must not be negative")

    @property
    def base_weight(self) -> Mass:
        return self.inventory.base_weight

    @property
    def start_weight(self) -> Mass:
        """Pack weight walking away from the resupply, bottles full as configured."""
        return self.weight_after(0.0)

    @property
    def finish_weight(self) -> Mass:
        """Pack weight arriving at the next resupply, bottles empty."""
        return self.weight_after(self.rations.days, water=Volume.zero())

    def food_after(self, days_walked: float) -> Mass:
        return self.rations.mass_remaining_after(days_walked)

    def fuel_after(self, days_walked: float) -> Mass:
        if days_walked < 0.0:
            raise LoadoutError("days walked must not be negative", days=days_walked)
        burned = FUEL_GRAMS_PER_DAY * min(days_walked, self.rations.days)
        return Mass.grams(max(0.0, self.fuel_start.in_grams - burned))

    def weight_after(self, days_walked: float, *, water: Volume | None = None) -> Mass:
        """Total pack weight after ``days_walked``, excluding worn items."""
        held = self.carried_water if water is None else water
        return Mass.grams(
            self.base_weight.in_grams
            + self.food_after(days_walked).in_grams
            + self.fuel_after(days_walked).in_grams
            + held.in_liters * GRAMS_PER_LITER_WATER
        )

    def average_weight(self, samples: int = 9) -> Mass:
        """Mean pack weight over the carry, sampled evenly.

        Used where a single figure is genuinely wanted, such as reporting. The
        solver does not use it, because the whole point is that it varies.
        """
        if samples < 2:
            raise LoadoutError("need at least two samples for an average", samples=samples)
        step = self.rations.days / (samples - 1)
        total = sum(self.weight_after(step * index).in_grams for index in range(samples))
        return Mass.grams(total / samples)

    def with_water(self, water: Volume) -> Loadout:
        return Loadout(
            inventory=self.inventory,
            rations=self.rations,
            fuel_start=self.fuel_start,
            carried_water=water,
        )

    def with_rations(self, rations: RationPlan) -> Loadout:
        return Loadout(
            inventory=self.inventory,
            rations=rations,
            fuel_start=self.fuel_start,
            carried_water=self.carried_water,
        )

    def exceeds(self, limit: Mass) -> bool:
        return self.start_weight > limit

    def describe(self) -> dict[str, float]:
        """Pounds by component at the start of the carry, for reporting."""
        return {
            "base": round(self.base_weight.in_pounds, 2),
            "food": round(self.food_after(0.0).in_pounds, 2),
            "fuel": round(self.fuel_start.in_pounds, 2),
            "water": round(
                Mass.grams(self.carried_water.in_liters * GRAMS_PER_LITER_WATER).in_pounds, 2
            ),
            "total": round(self.start_weight.in_pounds, 2),
        }

    def __repr__(self) -> str:
        return (
            f"Loadout({self.base_weight.in_pounds:.1f} lb base, "
            f"{self.start_weight.in_pounds:.1f} lb start, "
            f"{self.rations.days:.1f} days)"
        )


def fuel_for(days: float, *, grams_per_day: float = FUEL_GRAMS_PER_DAY) -> Mass:
    """Fuel to carry for a given number of days, rounded up to a sane margin."""
    if days < 0.0:
        raise LoadoutError("days must not be negative", days=days)
    return Mass.grams(days * grams_per_day * 1.15)


def water_mass(volume: Volume) -> Mass:
    return Mass.grams(volume.in_liters * GRAMS_PER_LITER_WATER)
