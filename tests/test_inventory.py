"""Gear list arithmetic and the weight vocabulary."""

from __future__ import annotations

import pytest

from backpacking.errors import LoadoutError
from backpacking.gear.inventory import Inventory, ItemCategory, PackItem
from backpacking.units import Mass


class TestItemCategory:
    def test_the_big_three_are_shelter_sleep_and_pack(self) -> None:
        big = {c for c in ItemCategory if c.is_big_three}
        assert big == {ItemCategory.SHELTER, ItemCategory.SLEEP, ItemCategory.PACK}

    def test_categories_serialise_as_strings(self) -> None:
        assert ItemCategory.COOK == "cook"


class TestPackItem:
    def test_total_mass_multiplies_by_quantity(self) -> None:
        stakes = PackItem(id="stake", name="Stake", mass=Mass.ounces(0.4), quantity=6)
        assert stakes.total_mass.in_ounces == pytest.approx(2.4)

    def test_a_plain_item_counts_towards_base(self) -> None:
        assert PackItem(id="pot", name="Pot", mass=Mass.ounces(4.0)).counts_towards_base

    def test_worn_items_do_not(self) -> None:
        shoes = PackItem(id="shoes", name="Shoes", mass=Mass.ounces(21.0), worn=True)
        assert not shoes.counts_towards_base

    def test_consumables_do_not(self) -> None:
        fuel = PackItem(id="fuel", name="Fuel", mass=Mass.ounces(8.0), consumable=True)
        assert not fuel.counts_towards_base

    def test_an_item_cannot_be_worn_and_consumable(self) -> None:
        with pytest.raises(LoadoutError, match="worn and consumable"):
            PackItem(id="x", name="X", mass=Mass.ounces(1.0), worn=True, consumable=True)

    def test_a_negative_mass_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            PackItem(id="x", name="X", mass=Mass.ounces(-1.0))

    def test_a_zero_quantity_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="at least one"):
            PackItem(id="x", name="X", mass=Mass.ounces(1.0), quantity=0)

    def test_duplicating_changes_only_the_quantity(self) -> None:
        stake = PackItem(id="stake", name="Stake", mass=Mass.ounces(0.4))
        assert stake.duplicated(8).total_mass.in_ounces == pytest.approx(3.2)
        assert stake.total_mass.in_ounces == pytest.approx(0.4)

    def test_repr_shows_the_quantity_when_it_matters(self) -> None:
        assert repr(PackItem(id="pot", name="Pot", mass=Mass.ounces(4.2))) == "PackItem('pot', 4.2 oz)"
        many = PackItem(id="stake", name="Stake", mass=Mass.ounces(0.4), quantity=6)
        assert repr(many) == "PackItem('stake', 2.4 oz x6)"


class TestInventoryWeights:
    def test_the_reference_list_has_a_believable_base_weight(self, inventory: Inventory) -> None:
        assert inventory.base_weight.in_pounds == pytest.approx(9.08, abs=0.02)

    def test_worn_weight_is_excluded_from_base(self, inventory: Inventory) -> None:
        assert inventory.worn_weight.in_ounces == pytest.approx(31.5)
        assert inventory.base_weight < inventory.skin_out_weight

    def test_skin_out_is_everything(self, inventory: Inventory) -> None:
        expected = (
            inventory.base_weight.in_grams
            + inventory.worn_weight.in_grams
            + inventory.consumable_weight.in_grams
        )
        assert inventory.skin_out_weight.in_grams == pytest.approx(expected)

    def test_the_big_three_dominate_the_base_weight(self, inventory: Inventory) -> None:
        share = inventory.big_three_weight.in_grams / inventory.base_weight.in_grams
        assert share > 0.5

    def test_weight_by_category_sums_to_base(self, inventory: Inventory) -> None:
        total = sum(mass.in_grams for mass in inventory.weight_by_category().values())
        assert total == pytest.approx(inventory.base_weight.in_grams)

    def test_weight_by_category_is_heaviest_first(self, inventory: Inventory) -> None:
        values = [mass.in_grams for mass in inventory.weight_by_category().values()]
        assert values == sorted(values, reverse=True)

    def test_the_heaviest_items_are_where_the_weight_is(self, inventory: Inventory) -> None:
        top = inventory.heaviest(3)
        assert [item.id for item in top] == ["pack", "shelter", "quilt"]

    def test_heaviest_never_lists_a_worn_item(self, inventory: Inventory) -> None:
        assert all(not item.worn for item in inventory.heaviest(20))

    def test_an_empty_inventory_weighs_nothing(self) -> None:
        empty = Inventory()
        assert empty.base_weight.in_grams == pytest.approx(0.0)
        assert len(empty) == 0


class TestInventoryLookup:
    def test_get_by_id(self, inventory: Inventory) -> None:
        assert inventory.get("quilt").mass.in_ounces == pytest.approx(21.5)

    def test_an_unknown_id_raises(self, inventory: Inventory) -> None:
        with pytest.raises(LoadoutError, match="no such item"):
            inventory.get("hammock")

    def test_has(self, inventory: Inventory) -> None:
        assert inventory.has("stove")
        assert not inventory.has("hammock")

    def test_of_category_filters(self, inventory: Inventory) -> None:
        cook = inventory.of_category(ItemCategory.COOK)
        assert {item.id for item in cook} == {"stove", "pot"}

    def test_of_category_accepts_several(self, inventory: Inventory) -> None:
        found = inventory.of_category(ItemCategory.COOK, ItemCategory.WATER)
        assert len(found) == 4

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(LoadoutError, match="duplicate item id"):
            Inventory(
                [
                    PackItem(id="pot", name="Pot", mass=Mass.ounces(4.0)),
                    PackItem(id="pot", name="Pot 2", mass=Mass.ounces(5.0)),
                ]
            )

    def test_iteration_yields_every_item(self, inventory: Inventory) -> None:
        assert len(list(inventory)) == len(inventory)


class TestInventoryEditing:
    def test_adding_an_item_returns_a_new_inventory(self, inventory: Inventory) -> None:
        bigger = inventory.with_item(PackItem(id="umbrella", name="Umbrella", mass=Mass.ounces(8.0)))
        assert bigger.has("umbrella")
        assert not inventory.has("umbrella")

    def test_removing_an_item_lightens_the_base(self, inventory: Inventory) -> None:
        lighter = inventory.without("battery")
        assert lighter.base_weight < inventory.base_weight
        assert not lighter.has("battery")

    def test_removing_something_absent_is_refused(self, inventory: Inventory) -> None:
        with pytest.raises(LoadoutError, match="not there"):
            inventory.without("hammock")

    def test_replacing_models_a_gear_upgrade(self, inventory: Inventory) -> None:
        lighter_pack = PackItem(
            id="pack", name="Frameless pack", mass=Mass.ounces(17.0), category=ItemCategory.PACK
        )
        upgraded = inventory.replacing(lighter_pack)
        saved = inventory.base_weight.in_ounces - upgraded.base_weight.in_ounces
        assert saved == pytest.approx(14.0)
        assert len(upgraded) == len(inventory)

    def test_replacing_something_absent_is_refused(self, inventory: Inventory) -> None:
        with pytest.raises(LoadoutError, match="not there"):
            inventory.replacing(PackItem(id="hammock", name="Hammock", mass=Mass.ounces(12.0)))

    def test_repr(self, inventory: Inventory) -> None:
        assert repr(inventory) == "Inventory(19 items, 9.08 lb base)"
