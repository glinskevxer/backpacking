"""Permit zones and what they allow.

A permit zone is a stretch of corridor under one agency's rules. The rules that
recur across agencies, and that a planner has to satisfy simultaneously:

* where camping is allowed at all, and whether it must be at a designated site
* how many consecutive nights may be spent in the zone
* how far from water, trail and trailhead a camp has to be
* whether fires are allowed, often as a function of elevation
* whether a bear canister is required rather than merely advised

Zones abut but do not overlap. A camp exactly on a boundary belongs to the zone
that starts there, matching the convention in
:class:`backpacking.trail.index.MileIndex`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from backpacking.errors import PermitError
from backpacking.units import Distance


class CampingPolicy(StrEnum):
    """How free a hiker is to choose where to sleep."""

    DISPERSED = "dispersed"
    DESIGNATED_ONLY = "designated_only"
    PERMITTED_SITE = "permitted_site"
    NO_CAMPING = "no_camping"

    @property
    def requires_named_site(self) -> bool:
        return self in {CampingPolicy.DESIGNATED_ONLY, CampingPolicy.PERMITTED_SITE}


@dataclass(frozen=True, slots=True)
class PermitZone:
    """One stretch of corridor under one set of rules."""

    id: str
    name: str
    agency: str
    start_mile: float
    end_mile: float
    camping: CampingPolicy = CampingPolicy.DISPERSED
    max_consecutive_nights: int | None = None
    min_distance_from_water: Distance = Distance.zero()
    min_distance_from_trail: Distance = Distance.zero()
    campfires_allowed: bool = True
    campfire_elevation_limit: Distance | None = None
    canister_required: bool = False
    designated_sites: frozenset[str] = field(default_factory=frozenset)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.end_mile <= self.start_mile:
            raise PermitError(
                "permit zone must cover a positive span",
                zone=self.id,
                start_mile=self.start_mile,
                end_mile=self.end_mile,
            )
        if self.max_consecutive_nights is not None and self.max_consecutive_nights < 0:
            raise PermitError(
                "max consecutive nights must not be negative",
                zone=self.id,
                nights=self.max_consecutive_nights,
            )
        if self.camping.requires_named_site and not self.designated_sites:
            raise PermitError(
                "a zone that requires a named site must list its sites", zone=self.id
            )

    @property
    def length(self) -> Distance:
        return Distance.miles(self.end_mile - self.start_mile)

    def contains(self, mile: float) -> bool:
        """Half open on the far end, so abutting zones do not both claim a mile."""
        return self.start_mile <= mile < self.end_mile

    def allows_camp_at(self, mile: float, site_id: str | None) -> bool:
        """Whether a night at this mile, at this site, is permitted by policy."""
        if not self.contains(mile):
            return False
        if self.camping is CampingPolicy.NO_CAMPING:
            return False
        if self.camping.requires_named_site:
            return site_id is not None and site_id in self.designated_sites
        return True

    def allows_fire_at(self, elevation: Distance) -> bool:
        if not self.campfires_allowed:
            return False
        if self.campfire_elevation_limit is None:
            return True
        return elevation <= self.campfire_elevation_limit

    def overlaps(self, other: PermitZone) -> bool:
        return self.start_mile < other.end_mile and other.start_mile < self.end_mile

    def __repr__(self) -> str:
        return (
            f"PermitZone({self.id!r}, {self.start_mile:.1f}-{self.end_mile:.1f} mi, "
            f"{self.camping.value})"
        )


class ZoneMap:
    """Every zone on a corridor, checked for gaps and overlaps on construction."""

    __slots__ = ("_zones",)

    def __init__(self, zones: Sequence[PermitZone], *, allow_gaps: bool = True) -> None:
        ordered = tuple(sorted(zones, key=lambda z: z.start_mile))
        seen: set[str] = set()
        for zone in ordered:
            if zone.id in seen:
                raise PermitError("duplicate permit zone id", zone=zone.id)
            seen.add(zone.id)
        for left, right in zip(ordered, ordered[1:], strict=False):
            if left.overlaps(right):
                raise PermitError(
                    "permit zones overlap", first=left.id, second=right.id
                )
            if not allow_gaps and right.start_mile > left.end_mile:
                raise PermitError(
                    "gap between permit zones",
                    first=left.id,
                    second=right.id,
                    gap_miles=round(right.start_mile - left.end_mile, 2),
                )
        self._zones: tuple[PermitZone, ...] = ordered

    @property
    def zones(self) -> tuple[PermitZone, ...]:
        return self._zones

    def __len__(self) -> int:
        return len(self._zones)

    def __iter__(self) -> Iterator[PermitZone]:
        return iter(self._zones)

    def get(self, zone_id: str) -> PermitZone:
        for zone in self._zones:
            if zone.id == zone_id:
                return zone
        raise PermitError("no such permit zone", zone=zone_id)

    def at(self, mile: float) -> PermitZone | None:
        """The zone containing ``mile``, or None where the corridor is unmanaged."""
        for zone in self._zones:
            if zone.contains(mile):
                return zone
        return None

    def require_at(self, mile: float) -> PermitZone:
        zone = self.at(mile)
        if zone is None:
            raise PermitError("no permit zone covers this mile", mile=mile)
        return zone

    def between(self, start_mile: float, end_mile: float) -> tuple[PermitZone, ...]:
        return tuple(
            zone
            for zone in self._zones
            if zone.end_mile > start_mile and zone.start_mile < end_mile
        )

    def agencies(self) -> tuple[str, ...]:
        found: list[str] = []
        for zone in self._zones:
            if zone.agency not in found:
                found.append(zone.agency)
        return tuple(found)

    def canister_required_between(self, start_mile: float, end_mile: float) -> bool:
        return any(zone.canister_required for zone in self.between(start_mile, end_mile))

    def gaps(self) -> tuple[tuple[float, float], ...]:
        """Unmanaged stretches between zones, which a planner should know about."""
        found: list[tuple[float, float]] = []
        for left, right in zip(self._zones, self._zones[1:], strict=False):
            if right.start_mile > left.end_mile:
                found.append((left.end_mile, right.start_mile))
        return tuple(found)

    def __repr__(self) -> str:
        return f"ZoneMap({len(self._zones)} zones, {len(self.agencies())} agencies)"
