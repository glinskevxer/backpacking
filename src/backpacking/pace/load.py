"""What the pack does to pace, and what the walking costs metabolically.

Two separate questions that people conflate:

* How much slower does a heavy pack make you? A linear penalty against a
  reference load is crude but it is what a hiker can actually calibrate, because
  they know what they normally carry and how they felt.
* How many calories does the day burn? That needs a real energy model, because
  the food weight in the pack is derived from it, and the food weight feeds back
  into the load. The Pandolf equation is the standard here.

Keeping them apart matters: the pace penalty is a preference, tuned per hiker,
while the metabolic cost is physics and is not up for negotiation.
"""

from __future__ import annotations

from backpacking.errors import PaceModelError
from backpacking.pace.models import HikerProfile
from backpacking.trail.models import Surface
from backpacking.units import Energy, Mass

#: Pandolf terrain coefficients. Blacktop is 1.0 by definition; the rest are the
#: usual field values, with the trail surfaces this package models mapped on.
TERRAIN_COEFFICIENT: dict[Surface, float] = {
    Surface.ROAD: 1.0,
    Surface.TREAD: 1.2,
    Surface.SAND: 2.1,
    Surface.TALUS: 1.7,
    Surface.SCREE: 1.8,
    Surface.SNOWFIELD: 1.6,
    Surface.BLOWDOWN: 1.5,
    Surface.BUSHWHACK: 2.0,
}

#: Below this the Pandolf equation is being asked about standing still.
MIN_MODELLED_SPEED_MS = 0.1

#: Kilocalories per watt hour, for turning metabolic power into food.
KCAL_PER_WATT_HOUR = 0.8598


def load_factor(profile: HikerProfile, carried: Mass) -> float:
    """Speed multiplier for carrying ``carried`` instead of the reference load.

    Returns 1.0 at the reference load, less above it, more below it. The result
    is floored so that an absurd load slows a hiker rather than stopping time.
    """
    delta_pounds = carried.in_pounds - profile.reference_load.in_pounds
    factor = 1.0 - profile.load_penalty_per_pound * delta_pounds
    return max(0.25, factor)


def altitude_factor(profile: HikerProfile, elevation_ft: float) -> float:
    """Speed multiplier for thin air above the hiker's threshold."""
    above = elevation_ft - profile.altitude_threshold_ft
    if above <= 0.0:
        return 1.0
    penalty = profile.altitude_penalty_per_1000ft * (above / 1000.0)
    return max(0.4, 1.0 - penalty)


def surface_factor(surface: Surface) -> float:
    """Speed multiplier for tread quality."""
    return surface.pace_factor


def pandolf_watts(
    body_mass: Mass,
    load: Mass,
    speed_ms: float,
    grade_percent: float,
    surface: Surface = Surface.TREAD,
) -> float:
    """Metabolic rate in watts, per Pandolf, Givoni and Goldman.

    ``M = 1.5W + 2.0(W + L)(L / W)^2 + n(W + L)(1.5V^2 + 0.35VG)``

    where W is body mass, L is carried load, V is speed in metres per second, G
    is grade as a percentage and n is the terrain coefficient. The equation was
    fitted for level and uphill walking; downhill it overestimates, so a
    correction term is applied below zero grade.
    """
    weight = body_mass.in_kilograms
    carried = load.in_kilograms
    if weight <= 0.0:
        raise PaceModelError("body mass must be positive", body_mass_kg=weight)
    if carried < 0.0:
        raise PaceModelError("carried load must not be negative", load_kg=carried)
    if speed_ms < MIN_MODELLED_SPEED_MS:
        raise PaceModelError(
            "speed is below what the metabolic model describes",
            speed_ms=speed_ms,
            minimum=MIN_MODELLED_SPEED_MS,
        )
    terrain = TERRAIN_COEFFICIENT[surface]
    total = weight + carried
    standing = 1.5 * weight
    load_term = 2.0 * total * (carried / weight) ** 2
    travel = terrain * total * (1.5 * speed_ms**2 + 0.35 * speed_ms * grade_percent)
    watts = standing + load_term + travel
    if grade_percent < 0.0:
        watts -= _downhill_correction(terrain, weight, carried, speed_ms, grade_percent)
    return max(standing, watts)


def _downhill_correction(
    terrain: float, weight: float, carried: float, speed_ms: float, grade_percent: float
) -> float:
    """Santee's correction for descent, which Pandolf alone gets badly wrong."""
    total = weight + carried
    return terrain * (
        (grade_percent * total * speed_ms) / 3.5
        - (total * (grade_percent + 6.0) ** 2 / weight)
        + (25.0 - speed_ms**2)
    )


def energy_cost(
    body_mass: Mass,
    load: Mass,
    speed_ms: float,
    grade_percent: float,
    hours: float,
    surface: Surface = Surface.TREAD,
) -> Energy:
    """Food energy burned walking at these conditions for ``hours``."""
    if hours < 0.0:
        raise PaceModelError("hours must not be negative", hours=hours)
    watts = pandolf_watts(body_mass, load, speed_ms, grade_percent, surface)
    return Energy.kilocalories(watts * hours * KCAL_PER_WATT_HOUR)


def combined_factor(
    profile: HikerProfile,
    carried: Mass,
    surface: Surface,
    elevation_ft: float,
) -> float:
    """Every speed multiplier this module knows about, multiplied together."""
    return (
        load_factor(profile, carried)
        * surface_factor(surface)
        * altitude_factor(profile, elevation_ft)
    )
