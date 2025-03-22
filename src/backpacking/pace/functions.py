"""The published walking speed models, kept separate from how we use them.

Three of them are implemented, because they disagree and the disagreement is
informative:

* **Tobler's hiking function** is a smooth exponential in slope, fitted to
  figures from Imhof. It is the only one of the three that speeds up slightly on
  a gentle descent, which matches how walking actually feels.
* **Naismith's rule**, with **Langmuir's** descent corrections, is the hillwalking
  standard: a flat rate plus a fixed penalty per unit of climb. It is crude on
  rolling ground and good on a big steady climb.
* **Munter's method** is the ski touring and alpine convention. It is coarse by
  design, expressed in whole units, and it is what a guide will quote you.

None of them know about surface, load, altitude or tiredness. Those live in
:mod:`backpacking.pace.estimator`, which is the only module that should be
called directly by planning code.
"""

from __future__ import annotations

import math

from backpacking.errors import PaceModelError
from backpacking.units import Distance, Duration

#: Tobler's constants: 6 km/h peak, offset by a 5% downhill slope.
TOBLER_PEAK_KMH = 6.0
TOBLER_DECAY = 3.5
TOBLER_OFFSET = 0.05

#: Naismith: one hour per 3 miles, plus one hour per 2,000 feet of climb.
NAISMITH_FLAT_MPH = 3.0
NAISMITH_FEET_PER_HOUR = 2000.0

#: Langmuir: gentle descent is faster, steep descent is slower.
LANGMUIR_GENTLE_MIN_PER_1000FT = -10.0
LANGMUIR_STEEP_MIN_PER_1000FT = 10.0
LANGMUIR_GENTLE_GRADE = -0.12
LANGMUIR_STEEP_GRADE = -0.22

#: Munter: rate units per hour for travel on foot.
MUNTER_RATE_UPHILL = 4.0
MUNTER_RATE_FLAT = 6.0
MUNTER_RATE_DOWNHILL = 10.0

#: Beyond this the terrain is being climbed rather than walked, and no walking
#: model applies. Callers get an error instead of a number they would trust.
MAX_MODELLED_GRADE = 1.2


def tobler_speed_kmh(grade: float) -> float:
    """Walking speed in km/h for a slope expressed as rise over run."""
    _check_grade(grade)
    return TOBLER_PEAK_KMH * math.exp(-TOBLER_DECAY * abs(grade + TOBLER_OFFSET))


def tobler_speed_mph(grade: float) -> float:
    """The same figure in statute miles per hour."""
    return Distance.kilometers(tobler_speed_kmh(grade)).in_miles


def tobler_time(distance: Distance, grade: float) -> Duration:
    """Time to cover ``distance`` at a constant slope, per Tobler."""
    speed = tobler_speed_kmh(grade)
    if speed <= 0.0:
        raise PaceModelError("tobler speed collapsed to zero", grade=grade)
    return Duration.hours(distance.in_kilometers / speed)


def naismith_time(distance: Distance, gain: Distance) -> Duration:
    """Flat time plus a fixed climbing penalty. Descent is ignored."""
    if gain.in_feet < 0.0:
        raise PaceModelError("naismith gain is a magnitude", gain_ft=gain.in_feet)
    hours = distance.in_miles / NAISMITH_FLAT_MPH + gain.in_feet / NAISMITH_FEET_PER_HOUR
    return Duration.hours(hours)


def langmuir_correction(loss: Distance, grade: float) -> Duration:
    """Langmuir's descent adjustment, negative on gentle ground.

    A gentle descent is quicker than the flat, a steep one is slower, and
    anything between the two thresholds is treated as a wash.
    """
    if loss.in_feet < 0.0:
        raise PaceModelError("langmuir loss is a magnitude", loss_ft=loss.in_feet)
    if grade >= 0.0:
        return Duration.zero()
    thousands = loss.in_feet / 1000.0
    if grade > LANGMUIR_GENTLE_GRADE:
        return Duration.minutes(LANGMUIR_GENTLE_MIN_PER_1000FT * thousands)
    if grade < LANGMUIR_STEEP_GRADE:
        return Duration.minutes(LANGMUIR_STEEP_MIN_PER_1000FT * thousands)
    return Duration.zero()


def naismith_langmuir_time(distance: Distance, gain: Distance, loss: Distance) -> Duration:
    """Naismith with the Langmuir descent correction folded in."""
    run = distance.in_meters
    grade = 0.0 if run == 0.0 else -loss.in_meters / run
    total = naismith_time(distance, gain) + langmuir_correction(loss, grade)
    return Duration.seconds(max(0.0, total.in_seconds))


def munter_units(distance: Distance, gain: Distance, loss: Distance) -> float:
    """Munter rate units: horizontal kilometres plus vertical hundreds of metres."""
    if gain.in_meters < 0.0 or loss.in_meters < 0.0:
        raise PaceModelError("munter gain and loss are magnitudes")
    return distance.in_kilometers + (gain.in_meters + loss.in_meters) / 100.0


def munter_time(distance: Distance, gain: Distance, loss: Distance) -> Duration:
    """Munter time, choosing the rate from whichever component dominates."""
    units = munter_units(distance, gain, loss)
    if gain.in_meters > loss.in_meters and gain.in_meters > 0.0:
        rate = MUNTER_RATE_UPHILL
    elif loss.in_meters > gain.in_meters and loss.in_meters > 0.0:
        rate = MUNTER_RATE_DOWNHILL
    else:
        rate = MUNTER_RATE_FLAT
    return Duration.hours(units / rate)


def grade_from(distance: Distance, rise: Distance) -> float:
    """Slope as rise over run, both in the same units, guarding a zero run."""
    run = distance.in_meters
    if run <= 0.0:
        raise PaceModelError("cannot compute a grade over zero distance")
    return rise.in_meters / run


def _check_grade(grade: float) -> None:
    if grade != grade:
        raise PaceModelError("grade is not a number")
    if abs(grade) > MAX_MODELLED_GRADE:
        raise PaceModelError(
            "grade is beyond what a walking model can describe",
            grade=grade,
            limit=MAX_MODELLED_GRADE,
        )
