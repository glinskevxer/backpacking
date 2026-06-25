"""Will it fit in the canister.

Where bear canisters are required the binding constraint stops being weight and
becomes volume, and the two do not correlate: a week of ramen weighs nothing and
will not fit, a week of olive oil and nut butter fits and is heavy.

The packing question is a one dimensional bin packing, which is NP hard in
general, but the instances here are tiny and the items are compressible in ways
a solver cannot model. So this uses first fit decreasing, which is provably
within 11/9 of optimal plus a constant, and then reports the packing so a human
can override it. Anyone who has actually packed a canister knows the last item
goes in by force.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backpacking.errors import LoadoutError
from backpacking.food.rations import FoodItem
from backpacking.units import Mass, Volume

#: The canisters people actually carry, by model name.
CANISTER_VOLUMES: dict[str, Volume] = {
    "bv425": Volume.cubic_inches(440.0),
    "bv450": Volume.cubic_inches(440.0),
    "bv475": Volume.cubic_inches(650.0),
    "bv500": Volume.cubic_inches(700.0),
    "bearikade-weekender": Volume.cubic_inches(650.0),
    "bearikade-expedition": Volume.cubic_inches(900.0),
    "garcia": Volume.cubic_inches(614.0),
}

CANISTER_MASSES: dict[str, Mass] = {
    "bv425": Mass.ounces(28.0),
    "bv450": Mass.ounces(33.0),
    "bv475": Mass.ounces(36.0),
    "bv500": Mass.ounces(41.0),
    "bearikade-weekender": Mass.ounces(31.0),
    "bearikade-expedition": Mass.ounces(36.0),
    "garcia": Mass.ounces(44.0),
}

#: Nothing packs perfectly. This is the fraction of nominal volume that is
#: realistically usable once the lid has to close.
PACKING_EFFICIENCY = 0.88


@dataclass(frozen=True, slots=True)
class Canister:
    """A bear canister, by model or by explicit volume."""

    model: str
    volume: Volume
    mass: Mass

    @classmethod
    def named(cls, model: str) -> Canister:
        key = model.lower()
        if key not in CANISTER_VOLUMES:
            raise LoadoutError(
                "unknown canister model", model=model, known=sorted(CANISTER_VOLUMES)
            )
        return cls(model=key, volume=CANISTER_VOLUMES[key], mass=CANISTER_MASSES[key])

    @property
    def usable_volume(self) -> Volume:
        return self.volume * PACKING_EFFICIENCY

    def __repr__(self) -> str:
        return f"Canister({self.model!r}, {self.volume.in_cubic_inches:.0f} cu in)"


@dataclass(frozen=True, slots=True)
class PackingResult:
    """What went in, what did not, and how full it ended up."""

    canister: Canister
    packed: tuple[FoodItem, ...]
    left_out: tuple[FoodItem, ...]

    @property
    def packed_volume(self) -> Volume:
        return Volume.milliliters(sum(_volume_of(item).in_milliliters for item in self.packed))

    @property
    def packed_mass(self) -> Mass:
        return Mass.grams(sum(item.mass.in_grams for item in self.packed))

    @property
    def fill_fraction(self) -> float:
        usable = self.canister.usable_volume.in_milliliters
        return 0.0 if usable <= 0.0 else self.packed_volume.in_milliliters / usable

    @property
    def everything_fits(self) -> bool:
        return not self.left_out

    @property
    def overflow_volume(self) -> Volume:
        return Volume.milliliters(sum(_volume_of(item).in_milliliters for item in self.left_out))

    def __repr__(self) -> str:
        verdict = "fits" if self.everything_fits else f"{len(self.left_out)} left out"
        return f"PackingResult({self.canister.model}, {self.fill_fraction:.0%} full, {verdict})"


def pack(canister: Canister, items: Sequence[FoodItem]) -> PackingResult:
    """First fit decreasing into a single canister."""
    for item in items:
        if item.volume is None:
            raise LoadoutError("cannot pack an item with no volume", item=item.id)
    ordered = sorted(items, key=lambda item: _volume_of(item).in_milliliters, reverse=True)
    capacity = canister.usable_volume.in_milliliters
    remaining = capacity
    packed: list[FoodItem] = []
    left_out: list[FoodItem] = []
    for item in ordered:
        needed = _volume_of(item).in_milliliters
        if needed <= remaining:
            packed.append(item)
            remaining -= needed
        else:
            left_out.append(item)
    return PackingResult(canister=canister, packed=tuple(packed), left_out=tuple(left_out))


def days_that_fit(
    canister: Canister,
    daily_volume: Volume,
    *,
    first_day_eaten_out: bool = True,
) -> float:
    """How many days of food at ``daily_volume`` the canister will hold.

    The first day usually does not have to fit: a hiker leaving a trailhead eats
    that day's food out of a pocket, which is worth a day on a tight carry.
    """
    if daily_volume.in_milliliters <= 0.0:
        raise LoadoutError("daily volume must be positive")
    fits = canister.usable_volume.in_milliliters / daily_volume.in_milliliters
    return fits + (1.0 if first_day_eaten_out else 0.0)


def smallest_canister_for(items: Sequence[FoodItem]) -> Canister:
    """The lightest canister that holds this food bag."""
    candidates = sorted(
        (Canister.named(model) for model in CANISTER_VOLUMES),
        key=lambda c: (c.mass.in_grams, c.volume.in_milliliters),
    )
    for canister in candidates:
        if pack(canister, items).everything_fits:
            return canister
    raise LoadoutError(
        "no canister in the table holds this food bag",
        required_cubic_inches=round(sum(_volume_of(item).in_cubic_inches for item in items), 1),
    )


def _volume_of(item: FoodItem) -> Volume:
    if item.volume is None:
        raise LoadoutError("food item has no volume", item=item.id)
    return item.volume
