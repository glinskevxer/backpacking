"""Building a shopping list from a ration plan."""

from __future__ import annotations

import pytest

from backpacking.errors import ResupplyInfeasible
from backpacking.food.rations import FoodItem, plan_rations
from backpacking.resupply.shopping import (
    ShoppingLine,
    build_shopping_list,
    render_shopping_list,
)
from backpacking.units import Energy, Mass, Volume


def item(item_id: str, ounces: float, kcal: float, cubic_inches: float = 10.0) -> FoodItem:
    return FoodItem(
        id=item_id,
        name=item_id.replace("-", " ").title(),
        mass=Mass.ounces(ounces),
        energy=Energy.kilocalories(kcal),
        volume=Volume.cubic_inches(cubic_inches),
    )


CATALOGUE = [
    item("olive-oil", 4.0, 1000.0, 7.5),
    item("peanut-butter", 3.0, 500.0, 6.0),
    item("ramen", 3.0, 380.0, 28.0),
    item("clif-bar", 2.4, 260.0, 6.0),
    item("dried-mango", 2.0, 160.0, 9.0),
    item("tortilla", 1.7, 140.0, 8.0),
]


@pytest.fixture
def rations():
    return plan_rations(5.0, Energy.kilocalories(2900.0), density_kcal_per_oz=125.0)


class TestShoppingLine:
    def test_totals_multiply_by_quantity(self) -> None:
        line = ShoppingLine(item=CATALOGUE[0], quantity=3)
        assert line.total_mass.in_ounces == pytest.approx(12.0)
        assert line.total_energy.in_kilocalories == pytest.approx(3000.0)
        assert line.total_volume is not None
        assert line.total_volume.in_cubic_inches == pytest.approx(22.5)

    def test_a_zero_quantity_is_refused(self) -> None:
        with pytest.raises(ResupplyInfeasible, match="at least one item"):
            ShoppingLine(item=CATALOGUE[0], quantity=0)

    def test_an_item_without_volume_has_no_total(self) -> None:
        plain = FoodItem(id="p", name="P", mass=Mass.ounces(1.0), energy=Energy.kilocalories(100.0))
        assert ShoppingLine(item=plain, quantity=2).total_volume is None

    def test_repr(self) -> None:
        assert repr(ShoppingLine(item=CATALOGUE[0], quantity=2)) == ("ShoppingLine('olive-oil' x2)")


class TestBuildShoppingList:
    def test_it_meets_the_calorie_target(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE)
        assert shopping.meets_target
        assert shopping.energy_shortfall.in_kilocalories == pytest.approx(0.0)

    def test_it_does_not_overshoot_by_much(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE, overshoot_fraction=0.05)
        over = shopping.total_energy.in_kilocalories / rations.total_energy.in_kilocalories
        assert over <= 1.05

    def test_it_prefers_the_denser_items(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE)
        chosen = {line.item.id for line in shopping.lines}
        assert "olive-oil" in chosen

    def test_the_per_item_cap_is_respected(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE, max_of_any_item=2)
        assert all(line.quantity <= 2 for line in shopping.lines)

    def test_a_tight_cap_forces_variety(self, rations) -> None:
        loose = build_shopping_list(rations, CATALOGUE, max_of_any_item=20)
        tight = build_shopping_list(rations, CATALOGUE, max_of_any_item=2)
        assert len(tight.lines) >= len(loose.lines)

    def test_the_daily_energy_is_close_to_the_plan(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE)
        assert shopping.daily_energy.in_kilocalories == pytest.approx(
            rations.daily_energy.in_kilocalories, rel=0.06
        )

    def test_a_longer_carry_buys_more(self) -> None:
        short = build_shopping_list(plan_rations(2.0, Energy.kilocalories(2900.0)), CATALOGUE)
        long = build_shopping_list(plan_rations(6.0, Energy.kilocalories(2900.0)), CATALOGUE)
        assert long.item_count() > short.item_count()

    def test_the_total_volume_is_reported(self, rations) -> None:
        assert build_shopping_list(rations, CATALOGUE).total_volume.in_cubic_inches > 0.0

    def test_the_total_mass_is_believable(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE)
        assert 6.0 < shopping.total_mass.in_pounds < 16.0

    def test_an_empty_catalogue_is_refused(self, rations) -> None:
        with pytest.raises(ResupplyInfeasible, match="empty catalogue"):
            build_shopping_list(rations, [])

    def test_a_zero_cap_is_refused(self, rations) -> None:
        with pytest.raises(ResupplyInfeasible, match="at least one"):
            build_shopping_list(rations, CATALOGUE, max_of_any_item=0)

    def test_a_negative_overshoot_is_refused(self, rations) -> None:
        with pytest.raises(ResupplyInfeasible, match="must not be negative"):
            build_shopping_list(rations, CATALOGUE, overshoot_fraction=-0.1)

    def test_a_catalogue_of_only_huge_items_cannot_fit(self) -> None:
        rations = plan_rations(0.5, Energy.kilocalories(1600.0))
        huge = [item("bucket", 200.0, 40000.0)]
        with pytest.raises(ResupplyInfeasible, match="overshoot ceiling"):
            build_shopping_list(rations, huge, overshoot_fraction=0.0)

    def test_repr(self, rations) -> None:
        assert repr(build_shopping_list(rations, CATALOGUE)).startswith("ShoppingList(")


class TestRenderShoppingList:
    def test_every_item_appears(self, rations) -> None:
        shopping = build_shopping_list(rations, CATALOGUE)
        text = render_shopping_list(shopping)
        for line in shopping.lines:
            assert line.item.name in text

    def test_the_columns_line_up(self, rations) -> None:
        text = render_shopping_list(build_shopping_list(rations, CATALOGUE))
        rows = [line for line in text.splitlines() if line and not line.startswith("-")]
        assert len({len(row) for row in rows[:-2]}) <= 2

    def test_the_total_row_is_present(self, rations) -> None:
        text = render_shopping_list(build_shopping_list(rations, CATALOGUE))
        assert "total" in text

    def test_the_days_and_daily_calories_are_stated(self, rations) -> None:
        text = render_shopping_list(build_shopping_list(rations, CATALOGUE))
        assert "5.0 days at" in text

    def test_items_are_listed_alphabetically(self, rations) -> None:
        text = render_shopping_list(build_shopping_list(rations, CATALOGUE))
        names = [
            row.split("  ")[0].strip()
            for row in text.splitlines()[2:]
            if row and not row.startswith("-") and "days at" not in row
        ]
        body = [name for name in names if name and name != "total"]
        assert body == sorted(body)
