"""The one entry point planning code should use to ask how long something takes.

The published models in :mod:`backpacking.pace.functions` answer a narrow
question: how fast does an unencumbered walker move on a given slope. Turning
that into a usable estimate means applying, in order, the surface, the load, the
altitude, the hiker's own calibration against the model, and finally the state
they are in after however many days they have already walked.

Order matters only in that they all multiply, so the result is the same either
way, but stating the order keeps the code honest about what has been applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backpacking.errors import PaceModelError
from backpacking.pace.fatigue import FatigueState
from backpacking.pace.functions import (
    grade_from,
    munter_time,
    naismith_langmuir_time,
    tobler_speed_mph,
)
from backpacking.pace.load import altitude_factor, load_factor, surface_factor
from backpacking.pace.models import HikerProfile, LegEstimate
from backpacking.trail.corridor import Corridor
from backpacking.trail.models import Segment, Surface
from backpacking.units import Distance, Duration, Mass

#: Segments are integrated in pieces no longer than this, so that a long leg
#: with one averaged grade does not hide a steep half.
INTEGRATION_STEP_MILES = 0.25


class PaceModel(StrEnum):
    """Which published model to build the estimate on."""

    TOBLER = "tobler"
    NAISMITH = "naismith"
    MUNTER = "munter"


@dataclass(frozen=True, slots=True)
class PaceEstimator:
    """Estimates leg times for one hiker under one model."""

    profile: HikerProfile
    model: PaceModel = PaceModel.TOBLER

    def base_time(self, distance: Distance, gain: Distance, loss: Distance) -> Duration:
        """Model time before any of this hiker's adjustments are applied."""
        if distance.in_miles < 0.0:
            raise PaceModelError("distance must not be negative", miles=distance.in_miles)
        if distance.in_miles == 0.0:
            return Duration.zero()
        if self.model is PaceModel.NAISMITH:
            return naismith_langmuir_time(distance, gain, loss)
        if self.model is PaceModel.MUNTER:
            return munter_time(distance, gain, loss)
        rise = Distance.feet(gain.in_feet - loss.in_feet)
        speed = tobler_speed_mph(grade_from(distance, rise))
        return Duration.hours(distance.in_miles / speed)

    def calibration(self) -> float:
        """How this hiker compares with the model's own flat pace.

        Tobler puts level walking at about 3.13 mph. A hiker who knows they walk
        2.7 mph on the flat is a factor of 0.86 slower than the model
        everywhere, which is a far better assumption than pretending the model
        was written about them.
        """
        model_flat_mph = tobler_speed_mph(0.0)
        return self.profile.flat_pace_mph / model_flat_mph

    def estimate_segment(
        self,
        segment: Segment,
        *,
        carried: Mass | None = None,
        state: FatigueState | None = None,
    ) -> LegEstimate:
        """Estimate one corridor segment end to end."""
        load = carried if carried is not None else self.profile.reference_load
        mean_elevation_ft = (
            segment.start.elevation.in_feet + segment.end.elevation.in_feet
        ) / 2.0
        moving = self._adjusted_time(
            distance=segment.length,
            gain=segment.gain,
            loss=segment.loss,
            surface=segment.surface,
            elevation_ft=mean_elevation_ft,
            load=load,
            state=state,
        )
        return LegEstimate(
            distance=segment.length,
            gain=segment.gain,
            loss=segment.loss,
            moving_time=moving,
            elapsed_time=self.profile.elapsed_from_moving(moving),
            surface=segment.surface,
        )

    def estimate_span(
        self,
        corridor: Corridor,
        start_mile: float,
        end_mile: float,
        *,
        carried: Mass | None = None,
        state: FatigueState | None = None,
    ) -> LegEstimate:
        """Estimate an arbitrary stretch, prorating the segments at either end."""
        if end_mile < start_mile:
            raise PaceModelError(
                "span must advance", start_mile=start_mile, end_mile=end_mile
            )
        if end_mile == start_mile:
            return LegEstimate.empty()
        load = carried if carried is not None else self.profile.reference_load
        total = LegEstimate.empty()
        for segment in corridor.segments_between(start_mile, end_mile):
            low = max(start_mile, segment.start.mile)
            high = min(end_mile, segment.end.mile)
            overlap = high - low
            if overlap <= 0.0:
                continue
            share = overlap / segment.length.in_miles
            piece_gain = Distance.feet(segment.gain.in_feet * share)
            piece_loss = Distance.feet(segment.loss.in_feet * share)
            piece_distance = Distance.miles(overlap)
            elevation_ft = (
                corridor.elevation_at(low).in_feet + corridor.elevation_at(high).in_feet
            ) / 2.0
            moving = self._adjusted_time(
                distance=piece_distance,
                gain=piece_gain,
                loss=piece_loss,
                surface=segment.surface,
                elevation_ft=elevation_ft,
                load=load,
                state=state,
            )
            total = total + LegEstimate(
                distance=piece_distance,
                gain=piece_gain,
                loss=piece_loss,
                moving_time=moving,
                elapsed_time=self.profile.elapsed_from_moving(moving),
                surface=segment.surface,
            )
        return total

    def reachable_mile(
        self,
        corridor: Corridor,
        start_mile: float,
        budget: Duration,
        *,
        carried: Mass | None = None,
        state: FatigueState | None = None,
        tolerance_miles: float = 0.05,
    ) -> float:
        """How far along the corridor this hiker gets on ``budget`` of moving time.

        A bisection rather than a forward march, because the estimate is
        monotone in distance and the solver calls this for every candidate day.
        """
        if budget.in_seconds <= 0.0:
            return start_mile
        low = start_mile
        high = corridor.end_mile
        whole = self.estimate_span(
            corridor, start_mile, high, carried=carried, state=state
        )
        if whole.moving_time <= budget:
            return high
        while high - low > tolerance_miles:
            middle = (low + high) / 2.0
            spent = self.estimate_span(
                corridor, start_mile, middle, carried=carried, state=state
            ).moving_time
            if spent > budget:
                high = middle
            else:
                low = middle
        return low

    def _adjusted_time(
        self,
        *,
        distance: Distance,
        gain: Distance,
        loss: Distance,
        surface: Surface,
        elevation_ft: float,
        load: Mass,
        state: FatigueState | None,
    ) -> Duration:
        base = self.base_time(distance, gain, loss)
        factor = (
            self.calibration()
            * surface_factor(surface)
            * load_factor(self.profile, load)
            * altitude_factor(self.profile, elevation_ft)
        )
        if state is not None:
            factor *= state.speed_factor
        if factor <= 0.0:
            raise PaceModelError("adjustment factors collapsed to zero", factor=factor)
        return Duration.seconds(base.in_seconds / factor)
