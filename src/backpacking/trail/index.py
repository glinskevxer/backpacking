"""The mile index that every corridor lookup goes through.

This started out as four bisect calls scattered through ``Corridor``. Pulling it
out is not tidying for its own sake: the permit, water and resupply modules all
need the same bracketing behaviour over their own mile keyed tables, and the
subtle part, which end of a boundary a query belongs to, has to be answered the
same way everywhere or two modules will disagree about which zone a camp is in.

The convention, stated once and relied on everywhere: a mile that falls exactly
on a boundary belongs to the interval that starts there.
"""

from __future__ import annotations

import itertools
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Bracket:
    """The pair of index positions surrounding a mile, and whether it is exact."""

    before: int
    after: int
    exact: bool


class MileIndex:
    """A sorted, strictly ascending run of mile keys with the queries over it."""

    __slots__ = ("_miles",)

    def __init__(self, miles: Sequence[float]) -> None:
        if len(miles) < 1:
            raise ValueError("a mile index needs at least one key")
        for previous, current in itertools.pairwise(miles):
            if current <= previous:
                raise ValueError(f"mile index keys must ascend, got {previous} then {current}")
        self._miles: tuple[float, ...] = tuple(miles)

    @property
    def miles(self) -> tuple[float, ...]:
        return self._miles

    @property
    def first(self) -> float:
        return self._miles[0]

    @property
    def last(self) -> float:
        return self._miles[-1]

    def __len__(self) -> int:
        return len(self._miles)

    def contains(self, mile: float) -> bool:
        return self.first <= mile <= self.last

    def interval_for(self, mile: float) -> int:
        """Index of the interval containing ``mile``, clamped into range.

        Interval ``i`` runs from key ``i`` to key ``i + 1``, so the answer is
        always in ``[0, len - 2]`` for an index with two or more keys.
        """
        if len(self._miles) < 2:
            return 0
        position = bisect_right(self._miles, mile) - 1
        return min(max(position, 0), len(self._miles) - 2)

    def bracket(self, mile: float) -> Bracket:
        """The positions either side of ``mile``, with exactness reported."""
        position = bisect_left(self._miles, mile)
        if position < len(self._miles) and self._miles[position] == mile:
            return Bracket(before=position, after=position, exact=True)
        before = max(0, position - 1)
        after = min(position, len(self._miles) - 1)
        return Bracket(before=before, after=after, exact=False)

    def nearest(self, mile: float) -> int:
        """Position of the closest key, breaking ties towards the earlier one."""
        position = bisect_left(self._miles, mile)
        if position == 0:
            return 0
        if position == len(self._miles):
            return len(self._miles) - 1
        before = self._miles[position - 1]
        after = self._miles[position]
        return position - 1 if (mile - before) <= (after - mile) else position

    def first_after(self, mile: float) -> int | None:
        """Position of the first key strictly greater than ``mile``."""
        position = bisect_right(self._miles, mile)
        return None if position >= len(self._miles) else position

    def span(self, start_mile: float, end_mile: float) -> tuple[int, int]:
        """Half open position range covering every key in ``[start, end]``."""
        left = bisect_left(self._miles, start_mile)
        right = bisect_right(self._miles, end_mile)
        return left, right

    def fraction_within(self, mile: float) -> tuple[int, float]:
        """Interval index and how far into it ``mile`` sits, as ``[0, 1]``."""
        index = self.interval_for(mile)
        if len(self._miles) < 2:
            return index, 0.0
        low = self._miles[index]
        high = self._miles[index + 1]
        width = high - low
        if width <= 0.0:
            return index, 0.0
        return index, min(1.0, max(0.0, (mile - low) / width))

    def __repr__(self) -> str:
        return f"MileIndex({len(self._miles)} keys, {self.first:.1f}-{self.last:.1f})"
