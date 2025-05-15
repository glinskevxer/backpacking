"""Calorie budgets, food weight and the burn down across a carry."""

from __future__ import annotations

import pytest

from backpacking.errors import LoadoutError
from backpacking.food.rations import (
    MAX_ABSORBABLE_KCAL,
    MIN_DAILY_KCAL,
    FoodItem,
    RationPlan,
    daily_requirement,
    describe_density,
    plan_from_items,
    plan_rations,
)
from backpacking.units import Energy, Mass, Volume

BAR = FoodItem(
    id="clif-bar",
    name="Clif Bar",
    mass=Mass.ounces(2.4),
    energy=Energy.kilocalories(260.0),
    volume=Volume.cubic_inches(6.0),
    meal="snack",
)
RAMEN = FoodItem(
    id="ramen",
    name="Instant Ramen",
    mass=Mass.ounces(3.0),
    energy=Energy.kilocalories(380.0),
    volume=Volume.cubic_inches(28.0),
    meal="dinner",
)
OLIVE_OIL = FoodItem(
    id="olive-oil",
    name="Olive Oil",
    mass=Mass.ounces(4.0),
    energy=Energy.kilocalories(1000.0),
    volume=Volume.cubic_inches(7.5),
    meal="supplement",
)


class TestFoodItem:
    def test_density_is_calories_per_ounce(self) -> None:
        assert BAR.density == pytest.approx(260.0 / 2.4)

    def test_olive_oil_is_the_densest_thing_in_the_bag(self) -> None:
        assert OLIVE_OIL.density > RAMEN.density > BAR.density

    def test_dense_enough_uses_the_good_threshold(self) -> None:
        assert OLIVE_OIL.is_dense_enough
        assert RAMEN.is_dense_enough
        assert not BAR.is_dense_enough

    def test_scaling_a_portion_scales_everything(self) -> None:
        double = RAMEN.scaled(2.0)
        assert double.mass.in_ounces == pytest.approx(6.0)
        assert double.energy.in_kilocalories == pytest.approx(760.0)
        assert double.volume is not None
        assert double.volume.in_cubic_inches == pytest.approx(56.0)
        assert double.density == pytest.approx(RAMEN.density)

    def test_scaling_an_item_without_volume_keeps_it_none(self) -> None:
        plain = FoodItem(id="p", name="P", mass=Mass.ounces(1.0), energy=Energy.kilocalories(100.0))
        assert plain.scaled(3.0).volume is None

    def test_a_zero_mass_item_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="mass must be positive"):
            FoodItem(id="x", name="X", mass=Mass.zero(), energy=Energy.kilocalories(100.0))

    def test_negative_energy_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            FoodItem(id="x", name="X", mass=Mass.ounces(1.0), energy=Energy.kilocalories(-1.0))

    def test_a_zero_volume_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="volume must be positive"):
            FoodItem(
                id="x",
                name="X",
                mass=Mass.ounces(1.0),
                energy=Energy.kilocalories(100.0),
                volume=Volume.zero(),
            )

    def test_a_non_positive_portion_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="portion factor must be positive"):
            BAR.scaled(0.0)

    def test_repr(self) -> None:
        assert repr(BAR) == "FoodItem('clif-bar', 2.4 oz, 108 kcal/oz)"


class TestDailyRequirement:
    def test_a_moderate_day(self) -> None:
        needed = daily_requirement(Energy.kilocalories(2400.0))
        assert needed.in_kilocalories == pytest.approx((1800.0 + 2400.0) * 0.85)

    def test_a_bigger_day_needs_more(self) -> None:
        easy = daily_requirement(Energy.kilocalories(1500.0))
        hard = daily_requirement(Energy.kilocalories(4000.0))
        assert hard > easy

    def test_the_floor_holds_on_a_rest_day(self) -> None:
        assert daily_requirement(Energy.zero()).in_kilocalories == pytest.approx(MIN_DAILY_KCAL)

    def test_the_absorption_ceiling_holds(self) -> None:
        huge = daily_requirement(Energy.kilocalories(20000.0))
        assert huge.in_kilocalories == pytest.approx(MAX_ABSORBABLE_KCAL)

    def test_a_bigger_deficit_carries_less(self) -> None:
        careful = daily_requirement(Energy.kilocalories(3000.0), deficit_fraction=0.05)
        lean = daily_requirement(Energy.kilocalories(3000.0), deficit_fraction=0.30)
        assert lean < careful

    def test_a_deficit_of_one_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match=r"\[0, 1\)"):
            daily_requirement(Energy.kilocalories(2000.0), deficit_fraction=1.0)

    def test_negative_burn_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            daily_requirement(Energy.kilocalories(-5.0))


class TestRationPlan:
    def test_a_five_day_carry_weighs_what_it_should(self) -> None:
        plan = plan_rations(5.0, Energy.kilocalories(2800.0), density_kcal_per_oz=125.0)
        assert plan.daily_mass.in_ounces == pytest.approx(3910.0 / 125.0)
        assert plan.total_mass.in_pounds == pytest.approx(9.77, abs=0.02)

    def test_a_denser_bag_weighs_less(self) -> None:
        poor = plan_rations(6.0, Energy.kilocalories(3000.0), density_kcal_per_oz=100.0)
        rich = plan_rations(6.0, Energy.kilocalories(3000.0), density_kcal_per_oz=150.0)
        assert rich.total_mass < poor.total_mass
        assert poor.total_mass.in_pounds - rich.total_mass.in_pounds > 3.0

    def test_total_energy_is_the_daily_figure_times_the_days(self) -> None:
        plan = plan_rations(4.0, Energy.kilocalories(2600.0))
        assert plan.total_energy.in_kilocalories == pytest.approx(
            plan.daily_energy.in_kilocalories * 4.0
        )

    def test_the_bag_empties_as_the_days_pass(self) -> None:
        plan = plan_rations(6.0, Energy.kilocalories(3000.0))
        assert plan.mass_remaining_after(0.0) == plan.total_mass
        assert plan.mass_remaining_after(3.0).in_ounces == pytest.approx(
            plan.total_mass.in_ounces / 2.0
        )
        assert plan.mass_remaining_after(6.0).in_ounces == pytest.approx(0.0)

    def test_the_bag_cannot_go_negative(self) -> None:
        plan = plan_rations(3.0, Energy.kilocalories(3000.0))
        assert plan.mass_remaining_after(10.0).in_ounces == pytest.approx(0.0)

    def test_negative_days_walked_is_refused(self) -> None:
        plan = plan_rations(3.0, Energy.kilocalories(3000.0))
        with pytest.raises(LoadoutError, match="must not be negative"):
            plan.mass_remaining_after(-1.0)

    def test_a_zero_day_plan_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="at least part of a day"):
            RationPlan(days=0.0, daily_energy=Energy.kilocalories(3000.0), density_kcal_per_oz=125.0)

    def test_a_zero_density_plan_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="density must be positive"):
            RationPlan(days=3.0, daily_energy=Energy.kilocalories(3000.0), density_kcal_per_oz=0.0)

    def test_repr(self) -> None:
        plan = plan_rations(5.0, Energy.kilocalories(2800.0), density_kcal_per_oz=125.0)
        assert repr(plan) == "RationPlan(5.0 days, 9.77 lb, 125 kcal/oz)"


class TestPlanFromItems:
    def test_the_plan_takes_its_density_from_the_real_bag(self) -> None:
        plan = plan_from_items(2.0, [BAR, RAMEN, OLIVE_OIL])
        total_kcal = 260.0 + 380.0 + 1000.0
        total_oz = 2.4 + 3.0 + 4.0
        assert plan.density_kcal_per_oz == pytest.approx(total_kcal / total_oz)

    def test_the_daily_energy_is_the_bag_split_over_the_days(self) -> None:
        plan = plan_from_items(2.0, [BAR, RAMEN, OLIVE_OIL])
        assert plan.daily_energy.in_kilocalories == pytest.approx(1640.0 / 2.0)

    def test_the_items_are_kept(self) -> None:
        plan = plan_from_items(2.0, [BAR, RAMEN])
        assert [item.id for item in plan.items] == ["clif-bar", "ramen"]

    def test_an_empty_bag_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="empty food bag"):
            plan_from_items(3.0, [])


class TestDescribeDensity:
    @pytest.mark.parametrize(
        ("density", "word"),
        [(160.0, "excellent"), (145.0, "excellent"), (130.0, "good"), (110.0, "workable"), (80.0, "heavy")],
    )
    def test_the_words_match_the_thresholds(self, density: float, word: str) -> None:
        assert describe_density(density) == word

    def test_olive_oil_is_excellent_and_ramen_is_workable(self) -> None:
        assert describe_density(OLIVE_OIL.density) == "excellent"
        assert describe_density(RAMEN.density) == "good"
        assert describe_density(BAR.density) == "workable"
