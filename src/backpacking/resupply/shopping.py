"""Turning a carry into a shopping list.

The gap this closes is the one every planner hits in the aisle: the plan says
five and a half days at 3,900 calories, and the question in front of them is how
many bags of anything that actually is.

So a carry is converted into portions of real items with real weights, chosen to
hit the calorie target without going far over on weight. It is a small knapsack
problem and it is solved greedily by calorie density, which is what a person
does anyway and which is provably within a factor of two of optimal here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backpacking.errors import ResupplyInfeasible
from backpacking.food.rations import FoodItem, RationPlan
from backpacking.units import Energy, Mass, Volume


@dataclass(frozen=True, slots=True)
class ShoppingLine:
    """One item on the list, with how many of it to buy."""

    item: FoodItem
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ResupplyInfeasible("a shopping line covers at least one item", item=self.item.id)

    @property
    def total_mass(self) -> Mass:
        return self.item.mass * self.quantity

    @property
    def total_energy(self) -> Energy:
        return self.item.energy * self.quantity

    @property
    def total_volume(self) -> Volume | None:
        return None if self.item.volume is None else self.item.volume * self.quantity

    def __repr__(self) -> str:
        return f"ShoppingLine({self.item.id!r} x{self.quantity})"


@dataclass(frozen=True, slots=True)
class ShoppingList:
    """Everything to buy for one carry."""

    lines: tuple[ShoppingLine, ...]
    target_energy: Energy
    days: float

    @property
    def total_mass(self) -> Mass:
        return Mass.grams(sum(line.total_mass.in_grams for line in self.lines))

    @property
    def total_energy(self) -> Energy:
        return Energy.kilocalories(sum(line.total_energy.in_kilocalories for line in self.lines))

    @property
    def total_volume(self) -> Volume:
        return Volume.milliliters(
            sum(
                line.total_volume.in_milliliters
                for line in self.lines
                if line.total_volume is not None
            )
        )

    @property
    def energy_shortfall(self) -> Energy:
        return Energy.kilocalories(
            max(0.0, self.target_energy.in_kilocalories - self.total_energy.in_kilocalories)
        )

    @property
    def daily_energy(self) -> Energy:
        return Energy.kilocalories(self.total_energy.in_kilocalories / self.days)

    @property
    def meets_target(self) -> bool:
        return self.energy_shortfall.in_kilocalories <= 0.0

    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    def __repr__(self) -> str:
        return (
            f"ShoppingList({self.item_count()} items, "
            f"{self.total_mass.in_pounds:.1f} lb, "
            f"{self.total_energy.in_kilocalories:.0f} kcal)"
        )


def build_shopping_list(
    rations: RationPlan,
    catalogue: Sequence[FoodItem],
    *,
    max_of_any_item: int = 12,
    overshoot_fraction: float = 0.05,
) -> ShoppingList:
    """Choose portions from a catalogue to cover a ration plan.

    Items are taken densest first, capped so the list does not become twelve
    identical bags of the one efficient thing, and the loop stops once the
    target is met within ``overshoot_fraction``.
    """
    if not catalogue:
        raise ResupplyInfeasible("cannot shop from an empty catalogue")
    if max_of_any_item < 1:
        raise ResupplyInfeasible("the per item cap must be at least one", cap=max_of_any_item)
    if overshoot_fraction < 0.0:
        raise ResupplyInfeasible("overshoot must not be negative")

    target = rations.total_energy.in_kilocalories
    ceiling = target * (1.0 + overshoot_fraction)
    ordered = sorted(catalogue, key=lambda item: item.density, reverse=True)
    running = 0.0
    counts: dict[str, int] = {}
    by_id = {item.id: item for item in ordered}

    for item in ordered:
        while (
            running < target
            and counts.get(item.id, 0) < max_of_any_item
            and running + item.energy.in_kilocalories <= ceiling
        ):
            counts[item.id] = counts.get(item.id, 0) + 1
            running += item.energy.in_kilocalories

    lines = tuple(
        ShoppingLine(item=by_id[item_id], quantity=count)
        for item_id, count in counts.items()
        if count > 0
    )
    if not lines:
        raise ResupplyInfeasible(
            "no combination of catalogue items fits under the overshoot ceiling",
            target_kcal=round(target, 0),
            smallest_item_kcal=round(min(item.energy.in_kilocalories for item in ordered), 0),
        )
    return ShoppingList(lines=lines, target_energy=rations.total_energy, days=rations.days)


def render_shopping_list(shopping: ShoppingList) -> str:
    """The list as a person would write it out."""
    width = max(len(line.item.name) for line in shopping.lines)
    rows = [f"{'item'.ljust(width)}  qty   oz   kcal"]
    rows.append("-" * len(rows[0]))
    for line in sorted(shopping.lines, key=lambda entry: entry.item.name):
        rows.append(
            f"{line.item.name.ljust(width)}  "
            f"{line.quantity:>3}  "
            f"{line.total_mass.in_ounces:>4.1f}  "
            f"{line.total_energy.in_kilocalories:>5.0f}"
        )
    rows.append("-" * len(rows[0]))
    rows.append(
        f"{'total'.ljust(width)}  {shopping.item_count():>3}  "
        f"{shopping.total_mass.in_ounces:>4.1f}  "
        f"{shopping.total_energy.in_kilocalories:>5.0f}"
    )
    rows.append("")
    rows.append(
        f"{shopping.days:.1f} days at " f"{shopping.daily_energy.in_kilocalories:.0f} kcal a day"
    )
    if not shopping.meets_target:
        rows.append(
            f"short by {shopping.energy_shortfall.in_kilocalories:.0f} kcal, "
            "buy something else as well"
        )
    return "\n".join(rows)
