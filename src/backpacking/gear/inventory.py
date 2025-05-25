"""The gear list.

The vocabulary here is not arbitrary, it is what the weight arguments turn on:

* **Base weight** is everything in the pack that is not consumed. It is the
  number people compare, because it is the only one that does not depend on how
  long the carry is.
* **Worn weight** is what is on the body rather than in the pack. It is
  excluded from base weight by convention, which is why comparing base weights
  between two people is less informative than it sounds.
* **Consumables** are food, water and fuel. They dominate on a long carry and
  they are the only part of the load that changes as the days pass.

Skin out weight is all three, and it is the honest one.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from backpacking.errors import LoadoutError
from backpacking.units import Mass, Volume


class ItemCategory(StrEnum):
    """The usual gear list headings."""

    SHELTER = "shelter"
    SLEEP = "sleep"
    PACK = "pack"
    CLOTHING = "clothing"
    COOK = "cook"
    WATER = "water"
    NAVIGATION = "navigation"
    SAFETY = "safety"
    ELECTRONICS = "electronics"
    CONSUMABLE = "consumable"
    OTHER = "other"

    @property
    def is_big_three(self) -> bool:
        """Shelter, sleep and pack: where weight is actually saved."""
        return self in {ItemCategory.SHELTER, ItemCategory.SLEEP, ItemCategory.PACK}


@dataclass(frozen=True, slots=True)
class PackItem:
    """One line on the gear list."""

    id: str
    name: str
    mass: Mass
    category: ItemCategory = ItemCategory.OTHER
    quantity: int = 1
    worn: bool = False
    consumable: bool = False
    volume: Volume | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.mass.in_grams < 0.0:
            raise LoadoutError("item mass must not be negative", item=self.id)
        if self.quantity < 1:
            raise LoadoutError("item quantity must be at least one", item=self.id)
        if self.worn and self.consumable:
            raise LoadoutError("an item cannot be both worn and consumable", item=self.id)

    @property
    def total_mass(self) -> Mass:
        return self.mass * self.quantity

    @property
    def counts_towards_base(self) -> bool:
        return not self.worn and not self.consumable

    def duplicated(self, quantity: int) -> PackItem:
        return PackItem(
            id=self.id,
            name=self.name,
            mass=self.mass,
            category=self.category,
            quantity=quantity,
            worn=self.worn,
            consumable=self.consumable,
            volume=self.volume,
            notes=self.notes,
        )

    def __repr__(self) -> str:
        suffix = f" x{self.quantity}" if self.quantity > 1 else ""
        return f"PackItem({self.id!r}, {self.total_mass.in_ounces:.1f} oz{suffix})"


class Inventory:
    """A whole gear list, with the weight questions people actually ask."""

    __slots__ = ("_items",)

    def __init__(self, items: Sequence[PackItem] = ()) -> None:
        seen: set[str] = set()
        for item in items:
            if item.id in seen:
                raise LoadoutError("duplicate item id in inventory", item=item.id)
            seen.add(item.id)
        self._items: tuple[PackItem, ...] = tuple(items)

    @property
    def items(self) -> tuple[PackItem, ...]:
        return self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[PackItem]:
        return iter(self._items)

    def get(self, item_id: str) -> PackItem:
        for item in self._items:
            if item.id == item_id:
                return item
        raise LoadoutError("no such item in inventory", item=item_id)

    def has(self, item_id: str) -> bool:
        return any(item.id == item_id for item in self._items)

    def of_category(self, *categories: ItemCategory) -> tuple[PackItem, ...]:
        wanted = set(categories)
        return tuple(item for item in self._items if item.category in wanted)

    @property
    def base_weight(self) -> Mass:
        return _sum_mass(item for item in self._items if item.counts_towards_base)

    @property
    def worn_weight(self) -> Mass:
        return _sum_mass(item for item in self._items if item.worn)

    @property
    def consumable_weight(self) -> Mass:
        return _sum_mass(item for item in self._items if item.consumable)

    @property
    def skin_out_weight(self) -> Mass:
        return _sum_mass(self._items)

    @property
    def big_three_weight(self) -> Mass:
        return _sum_mass(
            item
            for item in self._items
            if item.category.is_big_three and item.counts_towards_base
        )

    def weight_by_category(self) -> dict[ItemCategory, Mass]:
        """Base weight split by heading, heaviest first when iterated."""
        totals: dict[ItemCategory, float] = {}
        for item in self._items:
            if not item.counts_towards_base:
                continue
            totals[item.category] = totals.get(item.category, 0.0) + item.total_mass.in_grams
        ordered = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
        return {category: Mass.grams(grams) for category, grams in ordered}

    def heaviest(self, limit: int = 5) -> tuple[PackItem, ...]:
        """The items worth arguing about, base weight only."""
        candidates = [item for item in self._items if item.counts_towards_base]
        candidates.sort(key=lambda item: item.total_mass.in_grams, reverse=True)
        return tuple(candidates[:limit])

    def with_item(self, item: PackItem) -> Inventory:
        return Inventory([*self._items, item])

    def without(self, item_id: str) -> Inventory:
        if not self.has(item_id):
            raise LoadoutError("cannot remove an item that is not there", item=item_id)
        return Inventory([item for item in self._items if item.id != item_id])

    def replacing(self, item: PackItem) -> Inventory:
        """Swap an item of the same id, which is how a gear upgrade is modelled."""
        if not self.has(item.id):
            raise LoadoutError("cannot replace an item that is not there", item=item.id)
        return Inventory([item if existing.id == item.id else existing for existing in self._items])

    def __repr__(self) -> str:
        return f"Inventory({len(self._items)} items, {self.base_weight.in_pounds:.2f} lb base)"


def _sum_mass(items: Iterable[PackItem]) -> Mass:
    return Mass.grams(sum(item.total_mass.in_grams for item in items))
