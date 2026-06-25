"""Mail drops, and the two ways they go wrong.

A mail drop is a box the hiker sends ahead. It is the only option where there is
no store, and it is the only part of a resupply plan with a hard deadline on
both ends: it has to arrive before the hiker does, and it has to be collected
before the holding period runs out.

Both failure modes are real and both are modelled here. General delivery holds
for a fixed number of days and then returns to sender, and a post office is shut
on Sundays and holidays, so an arrival on the wrong day costs a whole extra
night in town.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from backpacking.errors import ResupplyInfeasible
from backpacking.resupply.towns import ResupplyPoint
from backpacking.units import Mass

#: General delivery holds this long before returning a parcel to sender.
DEFAULT_HOLD_DAYS = 30

#: Days a ground parcel takes to cross the country, and the margin worth adding.
DEFAULT_TRANSIT_DAYS = 7
RECOMMENDED_MARGIN_DAYS = 5


@dataclass(frozen=True, slots=True)
class MailDrop:
    """A parcel sent ahead to a resupply point."""

    id: str
    destination: ResupplyPoint
    shipped_on: date
    contents_mass: Mass
    transit_days: int = DEFAULT_TRANSIT_DAYS
    hold_days: int = DEFAULT_HOLD_DAYS
    holidays: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.destination.has_post_office:
            raise ResupplyInfeasible(
                "cannot mail a drop to a stop with no post office",
                drop=self.id,
                point=self.destination.id,
            )
        if self.transit_days < 0:
            raise ResupplyInfeasible("transit days must not be negative", drop=self.id)
        if self.hold_days < 1:
            raise ResupplyInfeasible("hold period must be at least a day", drop=self.id)
        if self.contents_mass.in_grams <= 0.0:
            raise ResupplyInfeasible("a mail drop must contain something", drop=self.id)

    @property
    def arrives_on(self) -> date:
        return self.shipped_on + timedelta(days=self.transit_days)

    @property
    def returns_on(self) -> date:
        return self.arrives_on + timedelta(days=self.hold_days)

    def is_collectable_on(self, when: date) -> bool:
        """Whether the parcel is there, still held, and the counter is open."""
        return self.arrives_on <= when < self.returns_on and self.is_counter_open(when)

    def is_counter_open(self, when: date) -> bool:
        if when in self.holidays:
            return False
        return self.destination.is_open_on(when)

    def collection_window(self) -> tuple[date, date]:
        return self.arrives_on, self.returns_on - timedelta(days=1)

    def first_collectable_from(self, when: date, *, search_days: int = 21) -> date | None:
        """First day from ``when`` the parcel can actually be picked up."""
        for offset in range(search_days):
            candidate = when + timedelta(days=offset)
            if candidate >= self.returns_on:
                return None
            if self.is_collectable_on(candidate):
                return candidate
        return None

    def days_of_slack(self, arrival: date) -> int:
        """Days between the parcel arriving and the hiker doing so.

        Negative means the hiker gets there first and has to wait, which is the
        expensive failure. Positive and large means the hold period is being
        eaten up.
        """
        return (arrival - self.arrives_on).days

    def __repr__(self) -> str:
        return (
            f"MailDrop({self.id!r} -> {self.destination.id}, "
            f"arrives {self.arrives_on.isoformat()})"
        )


def latest_ship_date(
    destination: ResupplyPoint,
    arrival: date,
    *,
    transit_days: int = DEFAULT_TRANSIT_DAYS,
    margin_days: int = RECOMMENDED_MARGIN_DAYS,
) -> date:
    """Last day a parcel can be posted and still beat the hiker with margin."""
    if transit_days < 0 or margin_days < 0:
        raise ResupplyInfeasible(
            "transit and margin must not be negative",
            point=destination.id,
            transit_days=transit_days,
            margin_days=margin_days,
        )
    return arrival - timedelta(days=transit_days + margin_days)


def check_drop(drop: MailDrop, arrival: date) -> list[str]:
    """Problems with collecting this drop on this arrival date."""
    problems: list[str] = []
    if arrival < drop.arrives_on:
        waiting = (drop.arrives_on - arrival).days
        problems.append(
            f"parcel arrives {waiting} day{'s' if waiting > 1 else ''} after the hiker does"
        )
    if arrival >= drop.returns_on:
        late = (arrival - drop.returns_on).days + 1
        problems.append(f"hold period expired {late} day{'s' if late > 1 else ''} before arrival")
    elif not drop.is_counter_open(arrival):
        following = drop.first_collectable_from(arrival)
        if following is None:
            problems.append("counter is closed and the hold period expires before it reopens")
        else:
            problems.append(
                f"counter is closed on arrival, first collection is {following.isoformat()}"
            )
    return problems


def plan_shipping(
    drops: dict[str, tuple[ResupplyPoint, date]],
    *,
    transit_days: int = DEFAULT_TRANSIT_DAYS,
    margin_days: int = RECOMMENDED_MARGIN_DAYS,
) -> dict[str, date]:
    """Ship dates for a whole set of drops, keyed the same way as the input."""
    schedule: dict[str, date] = {}
    for drop_id, (destination, arrival) in drops.items():
        schedule[drop_id] = latest_ship_date(
            destination, arrival, transit_days=transit_days, margin_days=margin_days
        )
    return schedule
