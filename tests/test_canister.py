"""Canister volumes and the first fit decreasing packing."""

from __future__ import annotations

import pytest

from backpacking.errors import LoadoutError
from backpacking.food.canister import (
    CANISTER_VOLUMES,
    PACKING_EFFICIENCY,
    Canister,
    days_that_fit,
    pack,
    smallest_canister_for,
)
from backpacking.food.rations import FoodItem
from backpacking.units import Energy, Mass, Volume


def food(item_id: str, cubic_inches: float, ounces: float = 3.0) -> FoodItem:
    return FoodItem(
        id=item_id,
        name=item_id.replace("-", " ").title(),
        mass=Mass.ounces(ounces),
        energy=Energy.kilocalories(ounces * 125.0),
        volume=Volume.cubic_inches(cubic_inches),
    )


class TestCanister:
    def test_a_known_model_resolves(self) -> None:
        bv500 = Canister.named("bv500")
        assert bv500.volume.in_cubic_inches == pytest.approx(700.0)
        assert bv500.mass.in_ounces == pytest.approx(41.0)

    def test_the_lookup_is_case_insensitive(self) -> None:
        assert Canister.named("BV500").model == "bv500"

    def test_an_unknown_model_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="unknown canister model"):
            Canister.named("bv900")

    def test_usable_volume_discounts_for_packing(self) -> None:
        bv500 = Canister.named("bv500")
        assert bv500.usable_volume.in_cubic_inches == pytest.approx(700.0 * PACKING_EFFICIENCY)

    def test_every_model_has_a_mass(self) -> None:
        for model in CANISTER_VOLUMES:
            assert Canister.named(model).mass.in_ounces > 0.0

    def test_the_expedition_is_the_biggest(self) -> None:
        biggest = max(CANISTER_VOLUMES, key=lambda m: CANISTER_VOLUMES[m].in_cubic_inches)
        assert biggest == "bearikade-expedition"

    def test_repr(self) -> None:
        assert repr(Canister.named("bv450")) == "Canister('bv450', 440 cu in)"

    def test_a_canister_can_be_built_by_hand(self) -> None:
        custom = Canister(
            model="ursack", volume=Volume.cubic_inches(650.0), mass=Mass.ounces(13.0)
        )
        assert custom.usable_volume.in_cubic_inches == pytest.approx(572.0)


class TestPack:
    def test_a_small_bag_fits_with_room_to_spare(self) -> None:
        result = pack(Canister.named("bv500"), [food("a", 40.0), food("b", 60.0)])
        assert result.everything_fits
        assert result.fill_fraction < 0.2
        assert result.overflow_volume.in_cubic_inches == pytest.approx(0.0)

    def test_an_oversized_bag_leaves_items_out(self) -> None:
        items = [food(f"day-{i}", 120.0) for i in range(8)]
        result = pack(Canister.named("bv450"), items)
        assert not result.everything_fits
        assert len(result.left_out) > 0
        assert result.overflow_volume.in_cubic_inches > 0.0

    def test_the_packed_volume_never_exceeds_the_usable_volume(self) -> None:
        items = [food(f"day-{i}", 95.0) for i in range(10)]
        result = pack(Canister.named("bv500"), items)
        assert result.packed_volume <= result.canister.usable_volume

    def test_big_items_go_in_first(self) -> None:
        items = [food("small", 20.0), food("huge", 500.0), food("medium", 100.0)]
        result = pack(Canister.named("bearikade-expedition"), items)
        assert [item.id for item in result.packed] == ["huge", "medium", "small"]

    def test_first_fit_decreasing_beats_the_naive_order(self) -> None:
        items = [food("a", 300.0), food("b", 250.0), food("c", 40.0)]
        result = pack(Canister.named("bv500"), items)
        assert result.everything_fits
        assert result.fill_fraction > 0.9

    def test_packed_mass_sums_the_packed_items(self) -> None:
        result = pack(Canister.named("bv500"), [food("a", 40.0, 4.0), food("b", 60.0, 6.0)])
        assert result.packed_mass.in_ounces == pytest.approx(10.0)

    def test_an_item_without_volume_is_refused(self) -> None:
        no_volume = FoodItem(
            id="loose", name="Loose", mass=Mass.ounces(2.0), energy=Energy.kilocalories(250.0)
        )
        with pytest.raises(LoadoutError, match="no volume"):
            pack(Canister.named("bv500"), [no_volume])

    def test_an_empty_bag_packs_trivially(self) -> None:
        result = pack(Canister.named("bv500"), [])
        assert result.everything_fits
        assert result.fill_fraction == pytest.approx(0.0)

    def test_repr_says_whether_it_fits(self) -> None:
        good = pack(Canister.named("bv500"), [food("a", 40.0)])
        assert repr(good).endswith("fits)")
        bad = pack(Canister.named("bv425"), [food(f"d{i}", 200.0) for i in range(5)])
        assert "left out" in repr(bad)


class TestDaysThatFit:
    def test_a_typical_daily_volume_in_a_bv500(self) -> None:
        days = days_that_fit(Canister.named("bv500"), Volume.cubic_inches(100.0))
        assert days == pytest.approx(700.0 * PACKING_EFFICIENCY / 100.0 + 1.0)

    def test_the_first_day_bonus_can_be_turned_off(self) -> None:
        with_bonus = days_that_fit(Canister.named("bv500"), Volume.cubic_inches(100.0))
        without = days_that_fit(
            Canister.named("bv500"), Volume.cubic_inches(100.0), first_day_eaten_out=False
        )
        assert with_bonus == pytest.approx(without + 1.0)

    def test_a_bigger_canister_holds_more_days(self) -> None:
        small = days_that_fit(Canister.named("bv425"), Volume.cubic_inches(90.0))
        big = days_that_fit(Canister.named("bearikade-expedition"), Volume.cubic_inches(90.0))
        assert big > small

    def test_a_zero_daily_volume_is_refused(self) -> None:
        with pytest.raises(LoadoutError, match="daily volume must be positive"):
            days_that_fit(Canister.named("bv500"), Volume.zero())


class TestSmallestCanisterFor:
    def test_a_short_carry_gets_the_lightest_canister(self) -> None:
        chosen = smallest_canister_for([food("a", 100.0), food("b", 120.0)])
        assert chosen.model == "bv425"

    def test_a_long_carry_needs_a_bigger_one(self) -> None:
        items = [food(f"day-{i}", 105.0) for i in range(7)]
        chosen = smallest_canister_for(items)
        assert chosen.volume.in_cubic_inches >= 650.0

    def test_the_chosen_canister_actually_holds_the_bag(self) -> None:
        items = [food(f"day-{i}", 85.0) for i in range(6)]
        chosen = smallest_canister_for(items)
        assert pack(chosen, items).everything_fits

    def test_an_impossible_bag_is_reported(self) -> None:
        items = [food(f"day-{i}", 200.0) for i in range(12)]
        with pytest.raises(LoadoutError, match="no canister in the table"):
            smallest_canister_for(items)
