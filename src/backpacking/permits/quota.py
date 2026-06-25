"""Entry quotas.

Quota systems are the reason a plan cannot simply start on the day the hiker is
free. They cap the number of parties starting from a given trailhead into a
given zone on a given date, and they do it per entry, not per night: once a
party is in, the quota does not care where they sleep.

Two things make this awkward and both are modelled here. Quotas vary by date
within a season rather than being one number, and a fraction of each day's
allocation is usually held back for walk ups, which is not available to a plan
made in advance.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from backpacking.errors import PermitError


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    """A date range with one daily allocation."""

    start: date
    end: date
    daily_limit: int
    walk_up_reserved: int = 0

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise PermitError(
                "quota window must not end before it starts",
                start=self.start.isoformat(),
                end=self.end.isoformat(),
            )
        if self.daily_limit < 0:
            raise PermitError("daily limit must not be negative", limit=self.daily_limit)
        if self.walk_up_reserved < 0:
            raise PermitError(
                "walk up reservation must not be negative", reserved=self.walk_up_reserved
            )
        if self.walk_up_reserved > self.daily_limit:
            raise PermitError(
                "walk up reservation cannot exceed the daily limit",
                reserved=self.walk_up_reserved,
                limit=self.daily_limit,
            )

    @property
    def advance_limit(self) -> int:
        """Permits obtainable before the trip, after the walk up hold back."""
        return self.daily_limit - self.walk_up_reserved

    def covers(self, when: date) -> bool:
        return self.start <= when <= self.end

    def __repr__(self) -> str:
        return (
            f"QuotaWindow({self.start.isoformat()}..{self.end.isoformat()}, "
            f"{self.advance_limit}/{self.daily_limit})"
        )


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """A trailhead that permits are issued for, with its quota calendar."""

    id: str
    name: str
    mile: float
    zone_id: str
    windows: tuple[QuotaWindow, ...] = ()
    closures: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        ordered = sorted(self.windows, key=lambda w: w.start)
        for left, right in itertools.pairwise(ordered):
            if right.start <= left.end:
                raise PermitError(
                    "quota windows overlap",
                    entry=self.id,
                    first=left.start.isoformat(),
                    second=right.start.isoformat(),
                )

    def window_for(self, when: date) -> QuotaWindow | None:
        for window in self.windows:
            if window.covers(when):
                return window
        return None

    def is_open(self, when: date) -> bool:
        """Outside every window the trailhead is unquotaed, not closed."""
        return when not in self.closures

    def advance_capacity(self, when: date) -> int | None:
        """Permits available in advance, or None where no quota applies."""
        if not self.is_open(when):
            return 0
        window = self.window_for(when)
        return None if window is None else window.advance_limit

    def __repr__(self) -> str:
        return f"EntryPoint({self.id!r} @ {self.mile:.1f} mi, {len(self.windows)} windows)"


class QuotaCalendar:
    """Entry points and what has already been taken, for one season."""

    __slots__ = ("_entries", "_taken")

    def __init__(
        self,
        entries: Sequence[EntryPoint],
        taken: dict[tuple[str, date], int] | None = None,
    ) -> None:
        seen: set[str] = set()
        for entry in entries:
            if entry.id in seen:
                raise PermitError("duplicate entry point id", entry=entry.id)
            seen.add(entry.id)
        self._entries: tuple[EntryPoint, ...] = tuple(entries)
        self._taken: dict[tuple[str, date], int] = dict(taken or {})

    @property
    def entries(self) -> tuple[EntryPoint, ...]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[EntryPoint]:
        return iter(self._entries)

    def entry(self, entry_id: str) -> EntryPoint:
        for candidate in self._entries:
            if candidate.id == entry_id:
                return candidate
        raise PermitError("no such entry point", entry=entry_id)

    def taken_on(self, entry_id: str, when: date) -> int:
        return self._taken.get((entry_id, when), 0)

    def remaining(self, entry_id: str, when: date) -> int | None:
        """Permits still available, or None where the entry is unquotaed."""
        capacity = self.entry(entry_id).advance_capacity(when)
        if capacity is None:
            return None
        return max(0, capacity - self.taken_on(entry_id, when))

    def is_available(self, entry_id: str, when: date, party_size: int = 1) -> bool:
        if party_size < 1:
            raise PermitError("party size must be at least one", party_size=party_size)
        left = self.remaining(entry_id, when)
        return True if left is None else left >= party_size

    def reserve(self, entry_id: str, when: date, party_size: int = 1) -> QuotaCalendar:
        """Take permits, returning a new calendar. Refuses to oversubscribe."""
        if not self.is_available(entry_id, when, party_size):
            raise PermitError(
                "not enough permits left on this date",
                entry=entry_id,
                date=when.isoformat(),
                requested=party_size,
                remaining=self.remaining(entry_id, when),
            )
        updated = dict(self._taken)
        key = (entry_id, when)
        updated[key] = updated.get(key, 0) + party_size
        return QuotaCalendar(self._entries, updated)

    def first_available(
        self,
        entry_id: str,
        earliest: date,
        *,
        party_size: int = 1,
        search_days: int = 60,
    ) -> date | None:
        """First date from ``earliest`` with room, searching forward."""
        if search_days < 1:
            raise PermitError("search window must be at least one day", days=search_days)
        for offset in range(search_days):
            candidate = earliest + timedelta(days=offset)
            if self.is_available(entry_id, candidate, party_size):
                return candidate
        return None

    def availability(self, entry_id: str, start: date, days: int) -> dict[date, int | None]:
        """Remaining permits for each of ``days`` dates from ``start``."""
        if days < 1:
            raise PermitError("availability window must be at least one day", days=days)
        return {
            start + timedelta(days=offset): self.remaining(entry_id, start + timedelta(days=offset))
            for offset in range(days)
        }

    def __repr__(self) -> str:
        return f"QuotaCalendar({len(self._entries)} entries, {len(self._taken)} reservations)"
