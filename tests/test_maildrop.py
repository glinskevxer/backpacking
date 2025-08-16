"""Mail drop timing against transit, hold periods and counter hours."""

from __future__ import annotations

from datetime import date

import pytest

from backpacking.errors import ResupplyInfeasible
from backpacking.resupply.maildrop import (
    DEFAULT_HOLD_DAYS,
    MailDrop,
    check_drop,
    latest_ship_date,
    plan_shipping,
)
from backpacking.resupply.towns import ResupplyPoint, ServiceLevel, TownIndex
from backpacking.units import Mass

SHIPPED = date(2025, 7, 1)


@pytest.fixture
def drop(towns: TownIndex) -> MailDrop:
    return MailDrop(
        id="soda-box",
        destination=towns.get("soda-springs"),
        shipped_on=SHIPPED,
        contents_mass=Mass.pounds(9.0),
    )


class TestMailDrop:
    def test_arrival_is_shipping_plus_transit(self, drop: MailDrop) -> None:
        assert drop.arrives_on == date(2025, 7, 8)

    def test_the_hold_period_runs_from_arrival(self, drop: MailDrop) -> None:
        assert drop.returns_on == date(2025, 8, 7)
        assert (drop.returns_on - drop.arrives_on).days == DEFAULT_HOLD_DAYS

    def test_the_collection_window_excludes_the_return_day(self, drop: MailDrop) -> None:
        first, last = drop.collection_window()
        assert first == date(2025, 7, 8)
        assert last == date(2025, 8, 6)

    def test_collectable_inside_the_window_on_an_open_day(self, drop: MailDrop) -> None:
        assert drop.is_collectable_on(date(2025, 7, 10))

    def test_not_collectable_before_it_arrives(self, drop: MailDrop) -> None:
        assert not drop.is_collectable_on(date(2025, 7, 7))

    def test_not_collectable_after_it_goes_back(self, drop: MailDrop) -> None:
        assert not drop.is_collectable_on(date(2025, 8, 7))

    def test_not_collectable_when_the_counter_is_shut(self, drop: MailDrop) -> None:
        assert not drop.is_collectable_on(date(2025, 7, 13))

    def test_a_holiday_shuts_the_counter(self, towns: TownIndex) -> None:
        july_fourth = MailDrop(
            id="box",
            destination=towns.get("soda-springs"),
            shipped_on=date(2025, 6, 20),
            contents_mass=Mass.pounds(8.0),
            holidays=frozenset({date(2025, 7, 4)}),
        )
        assert not july_fourth.is_counter_open(date(2025, 7, 4))
        assert july_fourth.is_counter_open(date(2025, 7, 3))

    def test_first_collectable_steps_past_a_closed_day(self, drop: MailDrop) -> None:
        assert drop.first_collectable_from(date(2025, 7, 13)) == date(2025, 7, 14)

    def test_first_collectable_returns_none_past_the_hold(self, drop: MailDrop) -> None:
        assert drop.first_collectable_from(date(2025, 8, 10)) is None

    def test_slack_is_positive_when_the_parcel_beats_the_hiker(self, drop: MailDrop) -> None:
        assert drop.days_of_slack(date(2025, 7, 15)) == 7

    def test_slack_is_negative_when_the_hiker_arrives_first(self, drop: MailDrop) -> None:
        assert drop.days_of_slack(date(2025, 7, 5)) == -3

    def test_a_stop_with_no_post_office_is_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="no post office"):
            MailDrop(
                id="box",
                destination=towns.get("alpine-store"),
                shipped_on=SHIPPED,
                contents_mass=Mass.pounds(5.0),
            )

    def test_an_empty_parcel_is_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="must contain something"):
            MailDrop(
                id="box",
                destination=towns.get("soda-springs"),
                shipped_on=SHIPPED,
                contents_mass=Mass.zero(),
            )

    def test_a_zero_hold_period_is_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="at least a day"):
            MailDrop(
                id="box",
                destination=towns.get("soda-springs"),
                shipped_on=SHIPPED,
                contents_mass=Mass.pounds(5.0),
                hold_days=0,
            )

    def test_negative_transit_is_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="must not be negative"):
            MailDrop(
                id="box",
                destination=towns.get("soda-springs"),
                shipped_on=SHIPPED,
                contents_mass=Mass.pounds(5.0),
                transit_days=-1,
            )

    def test_repr(self, drop: MailDrop) -> None:
        assert repr(drop) == "MailDrop('soda-box' -> soda-springs, arrives 2025-07-08)"


class TestLatestShipDate:
    def test_it_backs_off_transit_and_margin(self, towns: TownIndex) -> None:
        assert latest_ship_date(towns.get("soda-springs"), date(2025, 7, 20)) == date(2025, 7, 8)

    def test_a_longer_transit_pushes_it_earlier(self, towns: TownIndex) -> None:
        soda = towns.get("soda-springs")
        assert latest_ship_date(soda, date(2025, 7, 20), transit_days=14) < latest_ship_date(
            soda, date(2025, 7, 20)
        )

    def test_no_margin_ships_later(self, towns: TownIndex) -> None:
        soda = towns.get("soda-springs")
        assert latest_ship_date(soda, date(2025, 7, 20), margin_days=0) == date(2025, 7, 13)

    def test_negative_transit_is_refused(self, towns: TownIndex) -> None:
        with pytest.raises(ResupplyInfeasible, match="must not be negative"):
            latest_ship_date(towns.get("soda-springs"), date(2025, 7, 20), transit_days=-1)


class TestCheckDrop:
    def test_a_well_timed_arrival_has_no_problems(self, drop: MailDrop) -> None:
        assert check_drop(drop, date(2025, 7, 10)) == []

    def test_arriving_before_the_parcel_is_reported(self, drop: MailDrop) -> None:
        problems = check_drop(drop, date(2025, 7, 5))
        assert len(problems) == 1
        assert "3 days after the hiker" in problems[0]

    def test_arriving_a_day_early_reads_singular(self, drop: MailDrop) -> None:
        assert "1 day after the hiker" in check_drop(drop, date(2025, 7, 7))[0]

    def test_arriving_after_the_hold_expires_is_reported(self, drop: MailDrop) -> None:
        problems = check_drop(drop, date(2025, 8, 10))
        assert any("hold period expired" in problem for problem in problems)

    def test_arriving_on_a_closed_day_names_the_next_collection(self, drop: MailDrop) -> None:
        problems = check_drop(drop, date(2025, 7, 13))
        assert "first collection is 2025-07-14" in problems[0]


class TestPlanShipping:
    def test_it_returns_one_date_per_drop(self, towns: TownIndex) -> None:
        schedule = plan_shipping(
            {
                "tahoma-box": (towns.get("tahoma"), date(2025, 7, 14)),
                "soda-box": (towns.get("soda-springs"), date(2025, 7, 22)),
            }
        )
        assert set(schedule) == {"tahoma-box", "soda-box"}
        assert schedule["tahoma-box"] == date(2025, 7, 2)
        assert schedule["soda-box"] == date(2025, 7, 10)

    def test_an_empty_plan_is_empty(self) -> None:
        assert plan_shipping({}) == {}

    def test_a_slower_service_ships_everything_earlier(self, towns: TownIndex) -> None:
        drops = {"box": (towns.get("tahoma"), date(2025, 7, 14))}
        assert plan_shipping(drops, transit_days=14)["box"] < plan_shipping(drops)["box"]

    def test_a_gas_station_stop_can_still_be_scheduled_if_it_has_mail(self) -> None:
        posted = ResupplyPoint(
            id="cabin",
            name="Cabin",
            mile=30.0,
            groceries=ServiceLevel.NONE,
            has_post_office=True,
        )
        assert plan_shipping({"box": (posted, date(2025, 8, 1))})["box"] == date(2025, 7, 20)
