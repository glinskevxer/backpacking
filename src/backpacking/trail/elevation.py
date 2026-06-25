"""Elevation profiles and the climbs found in them.

Raw elevation from a consumer GPS wanders by several feet between samples, so
summing every positive step inflates a day's climb by a third or more. The gain
figures here are computed with a hysteresis threshold: a run of samples only
counts as a climb once it has risen past the threshold, and only ends once it
has fallen back past it. That is what published trail profiles do, and it is why
two datasheets for the same trail rarely agree on total gain.
"""

from __future__ import annotations

import itertools
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from backpacking.errors import CorridorError
from backpacking.units import Distance

#: Default hysteresis threshold. Ten feet is the usual convention for foot
#: travel and is roughly the vertical noise floor of a barometric altimeter.
DEFAULT_GAIN_THRESHOLD_FT = 10.0


@dataclass(frozen=True, slots=True)
class ElevationSample:
    """One elevation reading at a cumulative mile."""

    mile: float
    elevation: Distance

    def __post_init__(self) -> None:
        if self.mile < 0.0:
            raise CorridorError("elevation sample mile must not be negative", mile=self.mile)


@dataclass(frozen=True, slots=True)
class Climb:
    """A sustained ascent or descent found in a profile."""

    start_mile: float
    end_mile: float
    start_elevation: Distance
    end_elevation: Distance

    @property
    def length(self) -> Distance:
        return Distance.miles(self.end_mile - self.start_mile)

    @property
    def change(self) -> Distance:
        return Distance.feet(self.end_elevation.in_feet - self.start_elevation.in_feet)

    @property
    def is_ascent(self) -> bool:
        return self.change.in_feet > 0.0

    @property
    def average_grade(self) -> float:
        run = self.length.in_meters
        return 0.0 if run == 0.0 else self.change.in_meters / run

    @property
    def feet_per_mile(self) -> float:
        miles = self.length.in_miles
        return 0.0 if miles == 0.0 else abs(self.change.in_feet) / miles

    def __repr__(self) -> str:
        arrow = "up" if self.is_ascent else "down"
        return (
            f"Climb({self.start_mile:.1f}-{self.end_mile:.1f} mi, "
            f"{arrow} {abs(self.change.in_feet):.0f} ft)"
        )


class ElevationProfile:
    """An ordered run of elevation samples with the queries a planner needs."""

    __slots__ = ("_miles", "_samples")

    def __init__(self, samples: Sequence[ElevationSample]) -> None:
        ordered = sorted(samples, key=lambda s: s.mile)
        if len(ordered) < 2:
            raise CorridorError(
                "an elevation profile needs at least two samples", count=len(ordered)
            )
        for previous, current in itertools.pairwise(ordered):
            if current.mile == previous.mile:
                raise CorridorError("duplicate mile in elevation profile", mile=current.mile)
        self._samples: tuple[ElevationSample, ...] = tuple(ordered)
        self._miles: tuple[float, ...] = tuple(s.mile for s in ordered)

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[float, float]]) -> ElevationProfile:
        """Build from ``(mile, elevation_in_feet)`` tuples."""
        return cls([ElevationSample(mile, Distance.feet(feet)) for mile, feet in pairs])

    @property
    def samples(self) -> tuple[ElevationSample, ...]:
        return self._samples

    @property
    def start_mile(self) -> float:
        return self._miles[0]

    @property
    def end_mile(self) -> float:
        return self._miles[-1]

    def __len__(self) -> int:
        return len(self._samples)

    def elevation_at(self, mile: float) -> Distance:
        """Linear interpolation, clamped to the ends of the profile."""
        if mile <= self.start_mile:
            return self._samples[0].elevation
        if mile >= self.end_mile:
            return self._samples[-1].elevation
        index = bisect_left(self._miles, mile)
        if self._miles[index] == mile:
            return self._samples[index].elevation
        before = self._samples[index - 1]
        after = self._samples[index]
        fraction = (mile - before.mile) / (after.mile - before.mile)
        rise = after.elevation.in_feet - before.elevation.in_feet
        return Distance.feet(before.elevation.in_feet + rise * fraction)

    def slice(self, start_mile: float, end_mile: float) -> ElevationProfile:
        """Sub profile with interpolated endpoints so the ends are exact."""
        if end_mile <= start_mile:
            raise CorridorError(
                "profile slice must advance", start_mile=start_mile, end_mile=end_mile
            )
        inner = [s for s in self._samples if start_mile < s.mile < end_mile]
        return ElevationProfile(
            [
                ElevationSample(start_mile, self.elevation_at(start_mile)),
                *inner,
                ElevationSample(end_mile, self.elevation_at(end_mile)),
            ]
        )

    def resample(self, step_miles: float) -> ElevationProfile:
        """Even spacing, which is what the pace integrator wants."""
        if step_miles <= 0.0:
            raise CorridorError("resample step must be positive", step_miles=step_miles)
        out: list[ElevationSample] = []
        mile = self.start_mile
        while mile < self.end_mile:
            out.append(ElevationSample(mile, self.elevation_at(mile)))
            mile += step_miles
        out.append(ElevationSample(self.end_mile, self.elevation_at(self.end_mile)))
        return ElevationProfile(out)

    def gain(self, threshold_ft: float = DEFAULT_GAIN_THRESHOLD_FT) -> Distance:
        up, _ = self._accumulate(threshold_ft)
        return Distance.feet(up)

    def loss(self, threshold_ft: float = DEFAULT_GAIN_THRESHOLD_FT) -> Distance:
        _, down = self._accumulate(threshold_ft)
        return Distance.feet(down)

    def _accumulate(self, threshold_ft: float) -> tuple[float, float]:
        """Hysteresis filtered gain and loss, both returned as positive feet.

        The state machine holds a reference level, the running extreme since
        that reference, and a direction. A reversal only counts once it exceeds
        the threshold, at which point the run just completed is banked and the
        extreme becomes the new reference.
        """
        if threshold_ft < 0.0:
            raise CorridorError("gain threshold must not be negative", threshold=threshold_ft)
        elevations = [s.elevation.in_feet for s in self._samples]
        total_up = 0.0
        total_down = 0.0
        reference = elevations[0]
        extreme = elevations[0]
        highest = elevations[0]
        lowest = elevations[0]
        direction = 0
        for here in elevations[1:]:
            if direction == 0:
                highest = max(highest, here)
                lowest = min(lowest, here)
                if here - lowest > threshold_ft:
                    direction = 1
                    reference = lowest
                    extreme = here
                elif highest - here > threshold_ft:
                    direction = -1
                    reference = highest
                    extreme = here
            elif direction == 1:
                if here > extreme:
                    extreme = here
                elif extreme - here > threshold_ft:
                    total_up += extreme - reference
                    reference = extreme
                    extreme = here
                    direction = -1
            elif here < extreme:
                extreme = here
            elif here - extreme > threshold_ft:
                total_down += reference - extreme
                reference = extreme
                extreme = here
                direction = 1
        if direction == 1:
            total_up += max(0.0, extreme - reference)
        elif direction == -1:
            total_down += max(0.0, reference - extreme)
        else:
            net = elevations[-1] - reference
            if net > 0.0:
                total_up += net
            else:
                total_down += -net
        return total_up, total_down

    def raw_gain(self) -> Distance:
        """Unfiltered gain, kept so a caller can see how much noise there is."""
        total = 0.0
        for previous, current in zip(self._samples, self._samples[1:], strict=False):
            step = current.elevation.in_feet - previous.elevation.in_feet
            if step > 0.0:
                total += step
        return Distance.feet(total)

    def climbs(self, min_change_ft: float = 300.0) -> tuple[Climb, ...]:
        """Sustained ascents and descents of at least ``min_change_ft``.

        Same state machine as :meth:`_accumulate`, but it keeps the samples
        rather than the levels so each run can report where it started and
        ended. Runs shorter than the threshold are folded into their neighbours.
        """
        found: list[Climb] = []

        def emit(start: ElevationSample, finish: ElevationSample) -> None:
            change = abs(finish.elevation.in_feet - start.elevation.in_feet)
            if change >= min_change_ft and finish.mile > start.mile:
                found.append(
                    Climb(
                        start_mile=start.mile,
                        end_mile=finish.mile,
                        start_elevation=start.elevation,
                        end_elevation=finish.elevation,
                    )
                )

        first = self._samples[0]
        reference = extreme = highest = lowest = first
        direction = 0
        for sample in self._samples[1:]:
            here = sample.elevation.in_feet
            if direction == 0:
                if here > highest.elevation.in_feet:
                    highest = sample
                if here < lowest.elevation.in_feet:
                    lowest = sample
                if here - lowest.elevation.in_feet > min_change_ft:
                    direction = 1
                    reference = lowest
                    extreme = sample
                elif highest.elevation.in_feet - here > min_change_ft:
                    direction = -1
                    reference = highest
                    extreme = sample
            elif direction == 1:
                if here > extreme.elevation.in_feet:
                    extreme = sample
                elif extreme.elevation.in_feet - here > min_change_ft:
                    emit(reference, extreme)
                    reference, extreme, direction = extreme, sample, -1
            elif here < extreme.elevation.in_feet:
                extreme = sample
            elif here - extreme.elevation.in_feet > min_change_ft:
                emit(reference, extreme)
                reference, extreme, direction = extreme, sample, 1
        if direction == 0:
            emit(reference, self._samples[-1])
        else:
            emit(reference, extreme)
        return tuple(found)

    def steepest_mile(self) -> tuple[float, float]:
        """Start mile of the hardest single mile, and its gain in feet."""
        best_start = self.start_mile
        best_gain = 0.0
        mile = self.start_mile
        while mile + 1.0 <= self.end_mile:
            gain = self.elevation_at(mile + 1.0).in_feet - self.elevation_at(mile).in_feet
            if gain > best_gain:
                best_gain = gain
                best_start = mile
            mile += 0.1
        return best_start, best_gain

    def __repr__(self) -> str:
        return (
            f"ElevationProfile({len(self._samples)} samples, "
            f"{self.start_mile:.1f}-{self.end_mile:.1f} mi)"
        )


def grade_histogram(
    profile: ElevationProfile, bin_edges: Sequence[float], step_miles: float = 0.1
) -> dict[str, float]:
    """Miles spent in each grade band, keyed by a readable label.

    ``bin_edges`` are grades as fractions, ascending, and the returned mapping
    covers everything below the first edge and above the last as well.
    """
    if not bin_edges:
        raise CorridorError("grade histogram needs at least one bin edge")
    if list(bin_edges) != sorted(bin_edges):
        raise CorridorError("grade histogram bin edges must ascend")
    labels = _histogram_labels(bin_edges)
    tally = dict.fromkeys(labels, 0.0)
    sampled = profile.resample(step_miles)
    for previous, current in zip(sampled.samples, sampled.samples[1:], strict=False):
        run = Distance.miles(current.mile - previous.mile).in_meters
        if run <= 0.0:
            continue
        rise = current.elevation.in_meters - previous.elevation.in_meters
        grade = rise / run
        index = 0
        while index < len(bin_edges) and grade >= bin_edges[index]:
            index += 1
        tally[labels[index]] += current.mile - previous.mile
    return tally


def _histogram_labels(bin_edges: Sequence[float]) -> list[str]:
    labels = [f"<{bin_edges[0]:+.0%}"]
    for low, high in itertools.pairwise(bin_edges):
        labels.append(f"{low:+.0%}..{high:+.0%}")
    labels.append(f">{bin_edges[-1]:+.0%}")
    return labels
