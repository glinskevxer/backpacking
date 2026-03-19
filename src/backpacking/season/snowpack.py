"""Snow, and when it goes.

The single most consequential input to a mountain itinerary is not the hiker's
pace, it is whether the passes are melted out. A route that is a pleasant walk
in August is a mountaineering exercise in June of a heavy year, and no amount of
pace modelling captures the difference.

What is modelled here is deliberately coarse, because the real thing is not
predictable to better than a week or two:

* **Snow water equivalent as a percent of median** is the one number the
  snow survey publishes and the one number people plan around.
* **Melt out** rises through the season, and the elevation the snow line has
  reached on a given date is a function of that percent and of aspect.
* **Fords** peak with the melt rather than with the snowpack, so the dangerous
  window is the weeks after the snow line passes the basin, not the depth of
  winter.

Everything is expressed for the northern hemisphere Sierra and Cascades, which
is what this was built for. The constants are named so a different range can be
fitted without rereading the code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from backpacking.errors import BackpackingError
from backpacking.units import Distance


class SeasonError(BackpackingError):
    """A snow year or a date is outside what the model describes."""

    code = "season_error"


class Aspect(StrEnum):
    """Which way a slope faces, which changes melt out by weeks."""

    SOUTH = "south"
    WEST = "west"
    EAST = "east"
    NORTH = "north"
    FLAT = "flat"

    @property
    def melt_offset_days(self) -> int:
        """Days later than a flat slope this aspect melts out."""
        return _ASPECT_OFFSET[self]


_ASPECT_OFFSET: dict[Aspect, int] = {
    Aspect.SOUTH: -8,
    Aspect.WEST: -2,
    Aspect.FLAT: 0,
    Aspect.EAST: 4,
    Aspect.NORTH: 14,
}

#: In a median year the snow line sits here on the reference date below.
MEDIAN_SNOW_LINE_FT = 7000.0
REFERENCE_DAY_OF_YEAR = 152  # 1 June

#: Feet the snow line climbs per day through the melt season.
MELT_RATE_FT_PER_DAY = 62.0

#: Feet the snow line shifts per percentage point of snowpack above median.
SNOWPACK_SENSITIVITY_FT = 21.0

#: Beyond these the model is extrapolating and says so.
MIN_MODELLED_PERCENT = 20.0
MAX_MODELLED_PERCENT = 260.0


@dataclass(frozen=True, slots=True)
class SnowYear:
    """One season, described by its April snowpack as a percent of median."""

    year: int
    percent_of_median: float
    peak_date: date | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not MIN_MODELLED_PERCENT <= self.percent_of_median <= MAX_MODELLED_PERCENT:
            raise SeasonError(
                "snowpack percent is outside what the model describes",
                percent=self.percent_of_median,
                minimum=MIN_MODELLED_PERCENT,
                maximum=MAX_MODELLED_PERCENT,
            )
        if self.year < 1900 or self.year > 2200:
            raise SeasonError("snow year is out of range", year=self.year)

    @property
    def is_heavy(self) -> bool:
        return self.percent_of_median >= 120.0

    @property
    def is_light(self) -> bool:
        return self.percent_of_median <= 80.0

    @property
    def descriptor(self) -> str:
        if self.percent_of_median >= 160.0:
            return "exceptional"
        if self.is_heavy:
            return "heavy"
        if self.is_light:
            return "light"
        return "near median"

    def __repr__(self) -> str:
        return f"SnowYear({self.year}, {self.percent_of_median:.0f}% of median)"


def snow_line(snow_year: SnowYear, when: date, aspect: Aspect = Aspect.FLAT) -> Distance:
    """Elevation the snow line has reached on a date, for one aspect.

    Below this the trail is walkable. Above it there is continuous snow, and a
    pass above it needs an axe, traction and a different plan.
    """
    if when.year != snow_year.year:
        raise SeasonError(
            "date is not in this snow year",
            date=when.isoformat(),
            snow_year=snow_year.year,
        )
    days_from_reference = when.timetuple().tm_yday - REFERENCE_DAY_OF_YEAR
    adjusted_days = days_from_reference - aspect.melt_offset_days
    excess_percent = snow_year.percent_of_median - 100.0
    elevation = (
        MEDIAN_SNOW_LINE_FT
        + adjusted_days * MELT_RATE_FT_PER_DAY
        - excess_percent * SNOWPACK_SENSITIVITY_FT
    )
    return Distance.feet(elevation)


def is_snowbound(
    snow_year: SnowYear, when: date, elevation: Distance, aspect: Aspect = Aspect.FLAT
) -> bool:
    """Whether a point at this elevation is still under continuous snow."""
    return elevation > snow_line(snow_year, when, aspect)


def melt_out_date(
    snow_year: SnowYear, elevation: Distance, aspect: Aspect = Aspect.FLAT
) -> date:
    """The date the snow line reaches an elevation, by inverting the model."""
    excess_percent = snow_year.percent_of_median - 100.0
    days_from_reference = (
        elevation.in_feet - MEDIAN_SNOW_LINE_FT + excess_percent * SNOWPACK_SENSITIVITY_FT
    ) / MELT_RATE_FT_PER_DAY + aspect.melt_offset_days
    day_of_year = int(round(REFERENCE_DAY_OF_YEAR + days_from_reference))
    day_of_year = max(1, min(365, day_of_year))
    return date.fromordinal(date(snow_year.year, 1, 1).toordinal() + day_of_year - 1)


def melt_peak_date(snow_year: SnowYear) -> date:
    """When runoff peaks, which is when fords are at their worst.

    Empirically this lands a couple of weeks after the snow line passes the
    typical basin elevation, and later in a heavy year.
    """
    basin = Distance.feet(8000.0)
    return date.fromordinal(
        melt_out_date(snow_year, basin).toordinal()
        + int(round(10.0 + (snow_year.percent_of_median - 100.0) / 12.0))
    )


def ford_hazard(snow_year: SnowYear, when: date, drainage_elevation: Distance) -> float:
    """Hazard from 0 to 1 for a ford draining a basin at this elevation.

    Peaks on the melt peak date and falls away either side. The width of the
    window scales with the snowpack, because a heavy year both raises the peak
    and stretches it.
    """
    if when.year != snow_year.year:
        raise SeasonError(
            "date is not in this snow year", date=when.isoformat(), snow_year=snow_year.year
        )
    peak = melt_peak_date(snow_year)
    spread_days = 18.0 + (snow_year.percent_of_median - 100.0) / 6.0
    spread_days = max(8.0, spread_days)
    offset = (when - peak).days
    magnitude = min(1.0, snow_year.percent_of_median / 160.0)
    elevation_factor = min(1.0, max(0.2, drainage_elevation.in_feet / 9000.0))
    return magnitude * elevation_factor * math.exp(-((offset / spread_days) ** 2))


def describe_hazard(hazard: float) -> str:
    """The words a trail report would use for a hazard value."""
    if hazard >= 0.75:
        return "dangerous"
    if hazard >= 0.5:
        return "serious"
    if hazard >= 0.25:
        return "wet but manageable"
    return "straightforward"
