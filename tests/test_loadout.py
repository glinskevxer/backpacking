"""Pack weight across a carry, and the burn down of food and fuel."""

from __future__ import annotations

import pytest

from backpacking.errors import LoadoutError
from backpacking.food.rations import plan_rations
from backpacking.gear.inventory import Inventory
from backpacking.gear.loadout import (
    FUEL_GRAMS_PER_DAY,
    Loadout,
    fuel_for,
    water_mass,
)
from backpacking.units import Energy, Mass, Volume


@pytest.fixture
def loadout(inventory: Inventory) -> Loadout:
    return Loadout(
        inventory=inventory,
        rations=plan_rations(5.0, Energy.kilocalories(2900.0), density_kcal_per_oz=125.0),
        fuel_start=fuel_for(5.0),
        carried_water=Volume.liters(2.0),
    )


class TestStartAndFinish:
    def test_the_start_weight_is_the_heaviest_moment(self, loadout: Loadout) -> None:
        assert loadout.start_weight > loadout.finish_weight
        assert loadout.start_weight == loadout.weight_after(0.0)

    def test_the_finish_weight_is_base_plus_the_unburned_fuel_margin(
        self, loadout: Loadout
    ) -> None:
        margin = loadout.fuel_after(loadout.rations.days)
        assert loadout.finish_weight.in_grams == pytest.approx(
            loadout.base_weight.in_grams + margin.in_grams
        )
        assert 0.0 < margin.in_grams < 20.0

    def test_the_carry_costs_several_pounds(self, loadout: Loadout) -> None:
        shed = loadout.start_weight.in_pounds - loadout.finish_weight.in_pounds
        assert shed > 12.0

    def test_the_start_weight_is_in_a_believable_range(self, loadout: Loadout) -> None:
        assert 22.0 < loadout.start_weight.in_pounds < 30.0

    def test_base_weight_passes_through_from_the_inventory(
        self, loadout: Loadout, inventory: Inventory
    ) -> None:
        assert loadout.base_weight == inventory.base_weight


class TestBurnDown:
    def test_food_falls_linearly(self, loadout: Loadout) -> None:
        full = loadout.food_after(0.0).in_ounces
        assert loadout.food_after(2.5).in_ounces == pytest.approx(full / 2.0)
        assert loadout.food_after(5.0).in_ounces == pytest.approx(0.0)

    def test_food_cannot_go_negative(self, loadout: Loadout) -> None:
        assert loadout.food_after(40.0).in_ounces == pytest.approx(0.0)

    def test_fuel_burns_at_the_stated_rate(self, loadout: Loadout) -> None:
        burned = loadout.fuel_start.in_grams - loadout.fuel_after(3.0).in_grams
        assert burned == pytest.approx(3.0 * FUEL_GRAMS_PER_DAY)

    def test_fuel_stops_burning_at_the_end_of_the_carry(self, loadout: Loadout) -> None:
        assert loadout.fuel_after(5.0) == loadout.fuel_after(20.0)

    def test_fuel_cannot_go_negative(self, inventory: Inventory) -> None:
        thin = Loadout(
            inventory=inventory,
            rations=plan_rations(9.0, Energy.kilocalories(2900.0)),
            fuel_start=Mass.grams(10.0),
        )
        assert thin.fuel_after(9.0).in_grams == pytest.approx(0.0)

    def test_negative_days_are_refused(self, loadout: Loadout) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            loadout.fuel_after(-1.0)

    def test_weight_falls_every_day(self, loadout: Loadout) -> None:
        weights = [loadout.weight_after(day).in_grams for day in range(6)]
        assert weights == sorted(weights, reverse=True)


class TestWater:
    def test_water_is_a_kilogram_a_litre(self) -> None:
        assert water_mass(Volume.liters(2.0)).in_kilograms == pytest.approx(2.0)

    def test_carried_water_shows_up_in_the_weight(self, loadout: Loadout) -> None:
        dry = loadout.weight_after(0.0, water=Volume.zero())
        wet = loadout.weight_after(0.0, water=Volume.liters(3.0))
        assert wet.in_grams - dry.in_grams == pytest.approx(3000.0)

    def test_the_configured_water_is_the_default(self, loadout: Loadout) -> None:
        assert loadout.weight_after(1.0) == loadout.weight_after(1.0, water=Volume.liters(2.0))

    def test_swapping_the_water_returns_a_new_loadout(self, loadout: Loadout) -> None:
        heavier = loadout.with_water(Volume.liters(5.0))
        assert heavier.start_weight > loadout.start_weight
        assert loadout.carried_water.in_liters == pytest.approx(2.0)

    def test_negative_water_is_refused(self, inventory: Inventory) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            Loadout(
                inventory=inventory,
                rations=plan_rations(3.0, Energy.kilocalories(2500.0)),
                carried_water=Volume.liters(-1.0),
            )

    def test_negative_fuel_is_refused(self, inventory: Inventory) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            Loadout(
                inventory=inventory,
                rations=plan_rations(3.0, Energy.kilocalories(2500.0)),
                fuel_start=Mass.grams(-1.0),
            )


class TestAverageAndReporting:
    def test_the_average_sits_between_the_ends(self, loadout: Loadout) -> None:
        average = loadout.average_weight()
        assert loadout.finish_weight < average < loadout.start_weight

    def test_more_samples_do_not_move_it_much(self, loadout: Loadout) -> None:
        coarse = loadout.average_weight(samples=3).in_pounds
        fine = loadout.average_weight(samples=25).in_pounds
        assert coarse == pytest.approx(fine, abs=0.6)

    def test_one_sample_is_refused(self, loadout: Loadout) -> None:
        with pytest.raises(LoadoutError, match="at least two samples"):
            loadout.average_weight(samples=1)

    def test_describe_breaks_the_start_weight_apart(self, loadout: Loadout) -> None:
        parts = loadout.describe()
        assert set(parts) == {"base", "food", "fuel", "water", "total"}
        assert parts["total"] == pytest.approx(
            parts["base"] + parts["food"] + parts["fuel"] + parts["water"], abs=0.02
        )

    def test_exceeds_compares_the_start_weight(self, loadout: Loadout) -> None:
        assert loadout.exceeds(Mass.pounds(20.0))
        assert not loadout.exceeds(Mass.pounds(60.0))

    def test_swapping_rations_changes_the_carry(self, loadout: Loadout) -> None:
        longer = loadout.with_rations(
            plan_rations(9.0, Energy.kilocalories(2900.0), density_kcal_per_oz=125.0)
        )
        assert longer.start_weight > loadout.start_weight

    def test_repr(self, loadout: Loadout) -> None:
        assert repr(loadout).startswith("Loadout(9.1 lb base,")
        assert repr(loadout).endswith("5.0 days)")


class TestFuelFor:
    def test_it_carries_a_margin(self) -> None:
        assert fuel_for(5.0).in_grams == pytest.approx(5.0 * FUEL_GRAMS_PER_DAY * 1.15)

    def test_a_longer_carry_needs_more(self) -> None:
        assert fuel_for(9.0) > fuel_for(4.0)

    def test_zero_days_needs_none(self) -> None:
        assert fuel_for(0.0).in_grams == pytest.approx(0.0)

    def test_negative_days_are_refused(self) -> None:
        with pytest.raises(LoadoutError, match="must not be negative"):
            fuel_for(-1.0)

    def test_the_burn_rate_can_be_overridden(self) -> None:
        assert fuel_for(4.0, grams_per_day=20.0) > fuel_for(4.0)
