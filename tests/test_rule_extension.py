"""Extending the permit rule set from outside the package.

The rule engine is the one place an agency specific rule has to be pluggable:
new restrictions appear mid season and nobody wants to release a version to
express one. These tests pin the contract a caller has to satisfy, which is
exactly the contract the ``Rule`` protocol declares.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from backpacking.permits.rules import (
    CampNight,
    CanisterRule,
    Finding,
    Rule,
    Severity,
    default_rules,
)
from backpacking.permits.validate import validate_nights
from backpacking.permits.zones import ZoneMap
from backpacking.units import Distance

START = date(2025, 7, 20)


@dataclass(frozen=True, slots=True)
class MaximumElevationRule:
    """A custom rule: no camping above a stated elevation.

    Written as a frozen dataclass, which is what every built in rule is, so if
    this satisfies the protocol then so do theirs.
    """

    ceiling: Distance
    name: str = "maximum_elevation"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        return [
            Finding(
                rule=self.name,
                severity=Severity.VIOLATION,
                message=(
                    f"camp at {camp.elevation.in_feet:.0f} ft is above the "
                    f"{self.ceiling.in_feet:.0f} ft ceiling"
                ),
                night=camp.night,
            )
            for camp in nights
            if camp.elevation > self.ceiling
        ]


class QuietHoursRule:
    """A rule written as a plain class rather than a dataclass."""

    name = "quiet_hours"

    def check(self, nights: Sequence[CampNight], zones: ZoneMap) -> list[Finding]:
        return [
            Finding(
                rule=self.name,
                severity=Severity.ADVISORY,
                message="shelter camps fill up, arrive before dusk",
                night=camp.night,
            )
            for camp in nights
            if camp.site_id == "paradise-shelter"
        ]


def night(offset: int, mile: float, elevation_ft: float, site: str | None = None) -> CampNight:
    return CampNight(
        night=START + timedelta(days=offset),
        mile=mile,
        site_id=site,
        elevation=Distance.feet(elevation_ft),
        has_canister=True,
    )


class TestProtocolConformance:
    def test_a_frozen_dataclass_rule_satisfies_the_protocol(self) -> None:
        rule: Rule = MaximumElevationRule(ceiling=Distance.feet(9000))
        assert rule.name == "maximum_elevation"

    def test_a_plain_class_rule_satisfies_it_too(self) -> None:
        rule: Rule = QuietHoursRule()
        assert rule.name == "quiet_hours"

    def test_every_built_in_rule_satisfies_it(self) -> None:
        rules: list[Rule] = list(default_rules())
        assert len(rules) == 5
        assert all(isinstance(rule.name, str) and rule.name for rule in rules)

    def test_rule_names_are_unique(self) -> None:
        names = [rule.name for rule in default_rules()]
        assert len(names) == len(set(names))


class TestCustomRuleInAction:
    def test_a_custom_rule_fires_on_its_own(self, zone_map: ZoneMap) -> None:
        rule = MaximumElevationRule(ceiling=Distance.feet(8200))
        findings = rule.check([night(0, 15.3, 8600, "clyde-basin")], zone_map)
        assert len(findings) == 1
        assert "above the 8200 ft ceiling" in findings[0].message

    def test_it_stays_quiet_below_the_ceiling(self, zone_map: ZoneMap) -> None:
        rule = MaximumElevationRule(ceiling=Distance.feet(9000))
        assert rule.check([night(0, 15.3, 8040, "clyde-basin")], zone_map) == []

    def test_it_can_be_added_to_the_default_set(self, zone_map: ZoneMap) -> None:
        rules = [*default_rules(), MaximumElevationRule(ceiling=Distance.feet(8000))]
        report = validate_nights([night(0, 15.3, 8600, "clyde-basin")], zone_map, rules)
        assert report.findings_from("maximum_elevation")
        assert not report.is_permittable

    def test_the_built_in_rules_still_run_alongside_it(self, zone_map: ZoneMap) -> None:
        rules = [*default_rules(), MaximumElevationRule(ceiling=Distance.feet(8000))]
        camp = CampNight(
            night=START, mile=15.3, site_id="clyde-basin", elevation=Distance.feet(8600)
        )
        report = validate_nights([camp], zone_map, rules)
        assert report.findings_from("bear_canister")
        assert report.findings_from("maximum_elevation")

    def test_an_advisory_rule_does_not_block_a_permit(self, zone_map: ZoneMap) -> None:
        report = validate_nights(
            [night(0, 70.8, 7180, "paradise-shelter")],
            zone_map,
            [QuietHoursRule()],
        )
        assert report.advisories
        assert report.is_permittable

    def test_replacing_the_set_entirely_works(self, zone_map: ZoneMap) -> None:
        report = validate_nights(
            [night(0, 15.3, 8600, "clyde-basin")], zone_map, [CanisterRule()]
        )
        assert len(report.findings) == 0

    def test_an_empty_rule_set_finds_nothing(self, zone_map: ZoneMap) -> None:
        report = validate_nights([night(0, 15.3, 8600, "clyde-basin")], zone_map, [])
        assert report.findings == ()
        assert report.is_permittable
        assert report.nights_checked == 1

    def test_the_zones_visited_are_still_reported(self, zone_map: ZoneMap) -> None:
        report = validate_nights([night(0, 15.3, 8600, "clyde-basin")], zone_map, [])
        assert report.zones_visited == ("crystal-wilderness",)


class TestPackageIsTyped:
    def test_the_marker_file_ships(self) -> None:
        import backpacking

        root = __import__("pathlib").Path(backpacking.__file__).parent
        assert (root / "py.typed").exists()

    @pytest.mark.parametrize(
        "module",
        [
            "backpacking.units",
            "backpacking.geo",
            "backpacking.trail.corridor",
            "backpacking.plan.solver",
            "backpacking.services.planning",
        ],
    )
    def test_the_public_modules_import(self, module: str) -> None:
        assert __import__(module, fromlist=["__name__"]) is not None
