"""The rule engine that grades an itinerary against the zones it passes through.

Rules are separate objects rather than branches inside one function for a
practical reason: agencies add rules mid season, and a fire closure or a new
canister requirement has to be expressible without editing the checker. Each
rule sees the whole itinerary, because several of them are only decidable in
context. Consecutive night limits and canister carriage both depend on nights
either side of the one being judged.

Severity matters as much as the finding. A hard violation makes an itinerary
illegal. An advisory is something a ranger would mention and a planner may
knowingly accept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

from backpacking.permits.zones import CampingPolicy, PermitZone, ZoneMap
from backpacking.units import Distance


class Severity(StrEnum):
    """How much a finding matters."""

    VIOLATION = "violation"
    ADVISORY = "advisory"

    @property
    def blocks_permit(self) -> bool:
        return self is Severity.VIOLATION


@dataclass(frozen=True, slots=True)
class CampNight:
    """One night on an itinerary, as the permit rules need to see it."""

    night: date
    mile: float
    site_id: str | None = None
    elevation: Distance = Distance.zero()
    has_canister: bool = False
    wants_fire: bool = False
    distance_from_water: Distance = Distance.zero()

    def __repr__(self) -> str:
        return f"CampNight({self.night.isoformat()} @ {self.mile:.1f} mi)"


@dataclass(frozen=True, slots=True)
class Finding:
    """Something a rule objected to."""

    rule: str
    severity: Severity
    message: str
    night: date | None = None
    zone_id: str | None = None
    context: dict[str, object] = field(default_factory=dict)

    @property
    def blocks_permit(self) -> bool:
        return self.severity.blocks_permit

    def __repr__(self) -> str:
        where = "" if self.night is None else f" on {self.night.isoformat()}"
        return f"Finding({self.rule}{where}: {self.message})"


class Rule(Protocol):
    """Anything that can grade a whole itinerary.

    ``name`` is declared as a property rather than an attribute so that the
    frozen dataclasses below satisfy it. A plain annotation would require a
    settable attribute, which a frozen dataclass field is not.
    """

    @property
    def name(self) -> str:
        """Stable identifier, used to group findings by the rule that raised them."""
        ...

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        """Return every finding this rule has against the itinerary."""
        ...


@dataclass(frozen=True, slots=True)
class CampingPolicyRule:
    """Camps must be legal where they are, and named where that is required."""

    name: str = "camping_policy"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        found: list[Finding] = []
        for camp in nights:
            zone = zones.at(camp.mile)
            if zone is None:
                found.append(
                    Finding(
                        rule=self.name,
                        severity=Severity.ADVISORY,
                        message="camp falls outside every mapped permit zone",
                        night=camp.night,
                        context={"mile": camp.mile},
                    )
                )
                continue
            if zone.camping is CampingPolicy.NO_CAMPING:
                found.append(
                    Finding(
                        rule=self.name,
                        severity=Severity.VIOLATION,
                        message=f"camping is not allowed anywhere in {zone.name}",
                        night=camp.night,
                        zone_id=zone.id,
                    )
                )
            elif zone.camping.requires_named_site and not zone.allows_camp_at(
                camp.mile, camp.site_id
            ):
                found.append(
                    Finding(
                        rule=self.name,
                        severity=Severity.VIOLATION,
                        message=f"{zone.name} allows camping only at a designated site",
                        night=camp.night,
                        zone_id=zone.id,
                        context={"site_id": camp.site_id},
                    )
                )
        return found


@dataclass(frozen=True, slots=True)
class ConsecutiveNightsRule:
    """No more than a zone's limit of nights in a row inside it."""

    name: str = "consecutive_nights"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        found: list[Finding] = []
        run_zone: PermitZone | None = None
        run_length = 0
        run_start: date | None = None
        for camp in nights:
            zone = zones.at(camp.mile)
            if zone is not None and run_zone is not None and zone.id == run_zone.id:
                run_length += 1
            else:
                run_zone = zone
                run_length = 1
                run_start = camp.night
            if (
                run_zone is not None
                and run_zone.max_consecutive_nights is not None
                and run_length > run_zone.max_consecutive_nights
            ):
                found.append(
                    Finding(
                        rule=self.name,
                        severity=Severity.VIOLATION,
                        message=(
                            f"{run_zone.name} allows at most "
                            f"{run_zone.max_consecutive_nights} consecutive nights"
                        ),
                        night=camp.night,
                        zone_id=run_zone.id,
                        context={
                            "nights": run_length,
                            "run_started": None if run_start is None else run_start.isoformat(),
                        },
                    )
                )
        return found


@dataclass(frozen=True, slots=True)
class CanisterRule:
    """A canister has to be carried through every zone that requires one."""

    name: str = "bear_canister"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        found: list[Finding] = []
        for camp in nights:
            zone = zones.at(camp.mile)
            if zone is not None and zone.canister_required and not camp.has_canister:
                found.append(
                    Finding(
                        rule=self.name,
                        severity=Severity.VIOLATION,
                        message=f"{zone.name} requires an approved bear canister",
                        night=camp.night,
                        zone_id=zone.id,
                    )
                )
        return found


@dataclass(frozen=True, slots=True)
class CampfireRule:
    """Fires only where they are allowed, and below any elevation limit."""

    name: str = "campfire"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        found: list[Finding] = []
        for camp in nights:
            if not camp.wants_fire:
                continue
            zone = zones.at(camp.mile)
            if zone is None or zone.allows_fire_at(camp.elevation):
                continue
            reason = (
                "campfires are prohibited"
                if not zone.campfires_allowed
                else "camp is above the campfire elevation limit"
            )
            found.append(
                Finding(
                    rule=self.name,
                    severity=Severity.VIOLATION,
                    message=f"{reason} in {zone.name}",
                    night=camp.night,
                    zone_id=zone.id,
                    context={"elevation_ft": round(camp.elevation.in_feet)},
                )
            )
        return found


@dataclass(frozen=True, slots=True)
class WaterSetbackRule:
    """Camps have to sit back from water by whatever the zone says."""

    name: str = "water_setback"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        found: list[Finding] = []
        for camp in nights:
            zone = zones.at(camp.mile)
            if zone is None or zone.min_distance_from_water.in_feet <= 0.0:
                continue
            if camp.distance_from_water < zone.min_distance_from_water:
                found.append(
                    Finding(
                        rule=self.name,
                        severity=Severity.ADVISORY,
                        message=(
                            f"{zone.name} asks for camps at least "
                            f"{zone.min_distance_from_water.in_feet:.0f} feet from water"
                        ),
                        night=camp.night,
                        zone_id=zone.id,
                        context={"measured_ft": round(camp.distance_from_water.in_feet)},
                    )
                )
        return found


def default_rules() -> tuple[Rule, ...]:
    """The rule set every itinerary is graded against unless told otherwise."""
    rules: list[Rule] = [
        CampingPolicyRule(),
        ConsecutiveNightsRule(),
        CanisterRule(),
        CampfireRule(),
        WaterSetbackRule(),
    ]
    return tuple(rules)
