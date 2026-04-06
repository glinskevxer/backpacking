"""Reshaping a finished itinerary.

The solver optimises the objective it is given, and there are two things a
planner routinely wants that do not belong in that objective at all.

The first is rest. Whether to take a zero is a decision about the trip rather
than about the terrain, and folding it into the day cost would mean the solver
trading a rest day against a campsite, which is not a trade anybody makes.

The second is town. A resupply stop lands where the towns are, not where the
mileage wants it, and forcing the day splitter to land exactly on a road
crossing distorts every day either side of it.

So both are applied afterwards, to a plan that is already legal.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from backpacking.errors import PlanInfeasible
from backpacking.pace.fatigue import FatigueState, advance
from backpacking.pace.models import HikerProfile
from backpacking.plan.itinerary import DayPlan, Itinerary
from backpacking.resupply.towns import ResupplyPoint

#: Fatigue at or above which a rest day is worth inserting.
REST_THRESHOLD = 0.18

#: Never insert a rest day inside this many days of the finish.
MIN_DAYS_BEFORE_FINISH = 2


def fatigue_curve(itinerary: Itinerary, profile: HikerProfile) -> list[FatigueState]:
    """The fatigue state after each day of an existing plan."""
    state = FatigueState()
    out: list[FatigueState] = []
    for day in itinerary:
        hours = 0.0 if day.is_zero else day.estimate.moving_time.in_hours
        state = advance(state, profile, hours)
        out.append(state)
    return out


def worst_fatigue(itinerary: Itinerary, profile: HikerProfile) -> float:
    curve = fatigue_curve(itinerary, profile)
    return max((state.fatigue for state in curve), default=0.0)


def suggest_rest_days(
    itinerary: Itinerary,
    profile: HikerProfile,
    *,
    threshold: float = REST_THRESHOLD,
) -> tuple[int, ...]:
    """Day indices after which a rest day would do the most good.

    One suggestion per crossing of the threshold rather than one per day over
    it, because inserting a rest resets the accumulation and the later days
    would no longer qualify.
    """
    if not 0.0 < threshold < 1.0:
        raise PlanInfeasible("rest threshold must fall in (0, 1)", threshold=threshold)
    curve = fatigue_curve(itinerary, profile)
    suggestions: list[int] = []
    below = True
    for index, state in enumerate(curve):
        if index > len(itinerary) - MIN_DAYS_BEFORE_FINISH - 1:
            break
        if state.fatigue >= threshold and below:
            suggestions.append(index)
            below = False
        elif state.fatigue < threshold * 0.6:
            below = True
    return tuple(suggestions)


def insert_rest_days(itinerary: Itinerary, after: Sequence[int]) -> Itinerary:
    """Insert rest days after the given indices, latest first so they hold."""
    rebuilt = itinerary
    for index in sorted(set(after), reverse=True):
        rebuilt = rebuilt.with_zero_day_after(index)
    return rebuilt


def rebalance_for_rest(
    itinerary: Itinerary,
    profile: HikerProfile,
    *,
    threshold: float = REST_THRESHOLD,
    max_rest_days: int = 3,
) -> Itinerary:
    """Add rest days until nothing crosses the threshold, up to a cap."""
    if max_rest_days < 0:
        raise PlanInfeasible("rest day cap must not be negative", cap=max_rest_days)
    rebuilt = itinerary
    for _ in range(max_rest_days):
        suggestions = suggest_rest_days(rebuilt, profile, threshold=threshold)
        if not suggestions:
            break
        rebuilt = insert_rest_days(rebuilt, suggestions[:1])
    return rebuilt


def mark_resupply(
    itinerary: Itinerary, stops: Sequence[ResupplyPoint], *, tolerance_miles: float = 3.0
) -> Itinerary:
    """Annotate the day that passes each stop, without moving any day.

    A stop is attached to the first day whose walked range covers it, so a stop
    reached at lunchtime is recorded on that day rather than the previous night.
    """
    if tolerance_miles < 0.0:
        raise PlanInfeasible("tolerance must not be negative", tolerance=tolerance_miles)
    annotations: dict[int, str] = {}
    for stop in stops:
        for day in itinerary:
            if day.is_zero:
                continue
            if day.start_mile - tolerance_miles <= stop.mile <= day.end_mile + tolerance_miles:
                annotations.setdefault(day.index, stop.id)
                break
    if not annotations:
        return itinerary
    rebuilt = tuple(
        _with_resupply(day, annotations[day.index]) if day.index in annotations else day
        for day in itinerary
    )
    return Itinerary(
        corridor=itinerary.corridor,
        days=rebuilt,
        label=itinerary.label,
        metadata=itinerary.metadata,
    )


def add_town_day(itinerary: Itinerary, after: int, *, note: str = "town day") -> Itinerary:
    """A zero day that is explicitly for town rather than for rest."""
    rebuilt = itinerary.with_zero_day_after(after)
    days = list(rebuilt.days)
    inserted = days[after + 1]
    days[after + 1] = DayPlan(
        index=inserted.index,
        day=inserted.day,
        start_mile=inserted.start_mile,
        end_mile=inserted.end_mile,
        estimate=inserted.estimate,
        camp=inserted.camp,
        pack_weight=inserted.pack_weight,
        is_zero=True,
        resupply_at=inserted.resupply_at,
        notes=note,
    )
    return Itinerary(
        corridor=rebuilt.corridor,
        days=tuple(days),
        label=rebuilt.label,
        metadata=rebuilt.metadata,
    )


def compress_to_deadline(itinerary: Itinerary, latest_finish: "object") -> Itinerary:
    """Drop rest days, latest first, until the plan meets a finish date."""
    from datetime import date as date_type

    if not isinstance(latest_finish, date_type):
        raise PlanInfeasible("latest finish must be a date")
    rebuilt = itinerary
    while rebuilt.finish_date > latest_finish:
        zeros = rebuilt.zero_days
        if not zeros:
            raise PlanInfeasible(
                "cannot meet the deadline without walking further each day",
                finish=rebuilt.finish_date.isoformat(),
                deadline=latest_finish.isoformat(),
            )
        rebuilt = _drop_day(rebuilt, zeros[-1].index)
    return rebuilt


def _drop_day(itinerary: Itinerary, index: int) -> Itinerary:
    kept: list[DayPlan] = []
    for day in itinerary:
        if day.index == index:
            continue
        position = len(kept)
        shift = 1 if day.index > index else 0
        kept.append(
            DayPlan(
                index=position,
                day=day.day - timedelta(days=shift),
                start_mile=day.start_mile,
                end_mile=day.end_mile,
                estimate=day.estimate,
                camp=day.camp,
                pack_weight=day.pack_weight,
                is_zero=day.is_zero,
                resupply_at=day.resupply_at,
                notes=day.notes,
            )
        )
    if not kept:
        raise PlanInfeasible("cannot drop the only day of a plan", index=index)
    return Itinerary(
        corridor=itinerary.corridor,
        days=tuple(kept),
        label=itinerary.label,
        metadata=itinerary.metadata,
    )


def _with_resupply(day: DayPlan, stop_id: str) -> DayPlan:
    return DayPlan(
        index=day.index,
        day=day.day,
        start_mile=day.start_mile,
        end_mile=day.end_mile,
        estimate=day.estimate,
        camp=day.camp,
        pack_weight=day.pack_weight,
        is_zero=day.is_zero,
        resupply_at=stop_id,
        notes=day.notes,
    )
