"""The rule engine and the report it produces."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backpacking.errors import ValidationFailed
from backpacking.permits.quota import QuotaCalendar
from backpacking.permits.rules import (
    CampfireRule,
    CampingPolicyRule,
    CampNight,
    CanisterRule,
    ConsecutiveNightsRule,
    Severity,
    WaterSetbackRule,
    default_rules,
)
from backpacking.permits.validate import (
    check_entry,
    suggest_fixes,
    validate_nights,
    validate_trip,
)
from backpacking.permits.zones import ZoneMap
from backpacking.units import Distance

START = date(2025, 7, 20)


def night(
    offset: int,
    mile: float,
    site_id: str | None = None,
    **kwargs: object,
) -> CampNight:
    return CampNight(
        night=START + timedelta(days=offset),
        mile=mile,
        site_id=site_id,
        **kwargs,  # type: ignore[arg-type]
    )


def legal_trip() -> list[CampNight]:
    """Four nights that break nothing in the reference zone map."""
    return [
        night(0, 5.1, "haypress-camp", distance_from_water=Distance.feet(300)),
        night(1, 15.3, "clyde-basin", has_canister=True, distance_from_water=Distance.feet(400)),
        night(2, 31.8, "dry-bench", has_canister=True, distance_from_water=Distance.feet(500)),
        night(3, 44.7, None, distance_from_water=Distance.feet(200)),
    ]


class TestCampingPolicyRule:
    def test_a_legal_trip_produces_nothing(self, zone_map: ZoneMap) -> None:
        assert CampingPolicyRule().check(legal_trip(), zone_map) == []

    def test_an_undesignated_camp_in_the_wilderness_is_a_violation(
        self, zone_map: ZoneMap
    ) -> None:
        findings = CampingPolicyRule().check([night(0, 20.0, None)], zone_map)
        assert len(findings) == 1
        assert findings[0].severity is Severity.VIOLATION
        assert "designated site" in findings[0].message

    def test_a_camp_at_a_site_from_another_zone_is_a_violation(
        self, zone_map: ZoneMap
    ) -> None:
        findings = CampingPolicyRule().check([night(0, 20.0, "whiskey-flat")], zone_map)
        assert findings[0].blocks_permit

    def test_dispersed_camping_needs_no_site(self, zone_map: ZoneMap) -> None:
        assert CampingPolicyRule().check([night(0, 4.0, None)], zone_map) == []

    def test_a_camp_outside_every_zone_is_only_an_advisory(self, zone_map: ZoneMap) -> None:
        findings = CampingPolicyRule().check([night(0, 78.0, None)], zone_map)
        assert findings[0].severity is Severity.ADVISORY
        assert not findings[0].blocks_permit


class TestConsecutiveNightsRule:
    def test_three_nights_in_the_wilderness_is_allowed(self, zone_map: ZoneMap) -> None:
        nights = [
            night(0, 15.3, "clyde-basin"),
            night(1, 15.3, "clyde-basin"),
            night(2, 31.8, "dry-bench"),
        ]
        assert ConsecutiveNightsRule().check(nights, zone_map) == []

    def test_a_fourth_night_in_a_row_is_a_violation(self, zone_map: ZoneMap) -> None:
        nights = [night(offset, 15.3, "clyde-basin") for offset in range(4)]
        findings = ConsecutiveNightsRule().check(nights, zone_map)
        assert len(findings) == 1
        assert findings[0].context["nights"] == 4

    def test_leaving_and_returning_resets_the_run(self, zone_map: ZoneMap) -> None:
        nights = [
            night(0, 15.3, "clyde-basin"),
            night(1, 15.3, "clyde-basin"),
            night(2, 4.0),
            night(3, 15.3, "clyde-basin"),
            night(4, 15.3, "clyde-basin"),
        ]
        assert ConsecutiveNightsRule().check(nights, zone_map) == []

    def test_a_zone_with_no_cap_never_fires(self, zone_map: ZoneMap) -> None:
        nights = [night(offset, 4.0) for offset in range(10)]
        assert ConsecutiveNightsRule().check(nights, zone_map) == []

    def test_every_night_past_the_cap_is_reported(self, zone_map: ZoneMap) -> None:
        nights = [night(offset, 15.3, "clyde-basin") for offset in range(6)]
        assert len(ConsecutiveNightsRule().check(nights, zone_map)) == 3


class TestCanisterRule:
    def test_carrying_one_satisfies_the_rule(self, zone_map: ZoneMap) -> None:
        assert CanisterRule().check([night(0, 15.3, "clyde-basin", has_canister=True)], zone_map) == []

    def test_going_without_one_is_a_violation(self, zone_map: ZoneMap) -> None:
        findings = CanisterRule().check([night(0, 15.3, "clyde-basin")], zone_map)
        assert findings[0].blocks_permit
        assert findings[0].zone_id == "crystal-wilderness"

    def test_zones_that_do_not_require_one_are_silent(self, zone_map: ZoneMap) -> None:
        assert CanisterRule().check([night(0, 44.7)], zone_map) == []


class TestCampfireRule:
    def test_no_fire_wanted_means_no_finding(self, zone_map: ZoneMap) -> None:
        assert CampfireRule().check([night(0, 44.7, wants_fire=False)], zone_map) == []

    def test_a_fire_in_a_no_fire_zone_is_a_violation(self, zone_map: ZoneMap) -> None:
        findings = CampfireRule().check([night(0, 44.7, wants_fire=True)], zone_map)
        assert "prohibited" in findings[0].message

    def test_a_fire_above_the_elevation_limit_is_a_violation(self, zone_map: ZoneMap) -> None:
        camp = night(0, 15.3, "clyde-basin", wants_fire=True, elevation=Distance.feet(8600))
        findings = CampfireRule().check([camp], zone_map)
        assert "elevation limit" in findings[0].message
        assert findings[0].context["elevation_ft"] == 8600

    def test_a_fire_below_the_limit_is_fine(self, zone_map: ZoneMap) -> None:
        camp = night(0, 15.3, "clyde-basin", wants_fire=True, elevation=Distance.feet(7600))
        assert CampfireRule().check([camp], zone_map) == []

    def test_a_fire_outside_every_zone_is_not_judged(self, zone_map: ZoneMap) -> None:
        assert CampfireRule().check([night(0, 90.0, wants_fire=True)], zone_map) == []


class TestWaterSetbackRule:
    def test_a_camp_well_back_from_water_is_fine(self, zone_map: ZoneMap) -> None:
        camp = night(0, 15.3, "clyde-basin", distance_from_water=Distance.feet(400))
        assert WaterSetbackRule().check([camp], zone_map) == []

    def test_a_camp_too_close_is_an_advisory(self, zone_map: ZoneMap) -> None:
        camp = night(0, 15.3, "clyde-basin", distance_from_water=Distance.feet(60))
        findings = WaterSetbackRule().check([camp], zone_map)
        assert findings[0].severity is Severity.ADVISORY
        assert findings[0].context["measured_ft"] == 60

    def test_a_zone_with_no_setback_never_fires(self, zone_map: ZoneMap) -> None:
        camp = night(0, 44.7, distance_from_water=Distance.zero())
        assert WaterSetbackRule().check([camp], zone_map) == []


class TestValidateNights:
    def test_a_legal_trip_is_permittable(self, zone_map: ZoneMap) -> None:
        report = validate_nights(legal_trip(), zone_map)
        assert report.is_permittable
        assert report.violations == ()
        assert report.nights_checked == 4

    def test_the_zones_visited_are_listed_in_order(self, zone_map: ZoneMap) -> None:
        report = validate_nights(legal_trip(), zone_map)
        assert report.zones_visited == (
            "echo-front",
            "crystal-wilderness",
            "granite-state-park",
        )

    def test_a_broken_trip_collects_every_violation(self, zone_map: ZoneMap) -> None:
        nights = [
            night(0, 20.0, None),
            night(1, 44.7, wants_fire=True),
        ]
        report = validate_nights(nights, zone_map)
        assert not report.is_permittable
        assert len(report.violations) >= 3

    def test_findings_can_be_filtered_by_night(self, zone_map: ZoneMap) -> None:
        nights = [night(0, 20.0, None), night(1, 44.7)]
        report = validate_nights(nights, zone_map)
        assert all(f.night == START for f in report.findings_on(START))

    def test_findings_can_be_filtered_by_rule(self, zone_map: ZoneMap) -> None:
        report = validate_nights([night(0, 20.0, None)], zone_map)
        assert report.findings_from("bear_canister")
        assert report.findings_from("campfire") == ()

    def test_findings_are_sorted_by_night_then_severity(self, zone_map: ZoneMap) -> None:
        nights = [
            night(0, 15.3, "clyde-basin", has_canister=True, distance_from_water=Distance.feet(10)),
            night(1, 20.0, None),
        ]
        report = validate_nights(nights, zone_map)
        dates = [f.night for f in report.findings]
        assert dates == sorted(d for d in dates if d is not None)

    def test_a_custom_rule_set_can_be_supplied(self, zone_map: ZoneMap) -> None:
        report = validate_nights([night(0, 20.0, None)], zone_map, rules=[CanisterRule()])
        assert len(report.findings) == 1
        assert report.findings[0].rule == "bear_canister"

    def test_the_default_rule_set_has_five_rules(self) -> None:
        assert len(default_rules()) == 5

    def test_summary_reads_cleanly_either_way(self, zone_map: ZoneMap) -> None:
        assert validate_nights(legal_trip(), zone_map).summary() == "4 nights, no findings"
        broken = validate_nights([night(0, 20.0, None)], zone_map)
        assert "violations" in broken.summary()

    def test_raise_if_illegal_stays_quiet_on_a_legal_trip(self, zone_map: ZoneMap) -> None:
        validate_nights(legal_trip(), zone_map).raise_if_illegal()

    def test_raise_if_illegal_carries_the_messages(self, zone_map: ZoneMap) -> None:
        report = validate_nights([night(0, 20.0, None)], zone_map)
        with pytest.raises(ValidationFailed) as caught:
            report.raise_if_illegal()
        assert caught.value.violations
        assert caught.value.context["nights"] == 1

    def test_repr(self, zone_map: ZoneMap) -> None:
        assert repr(validate_nights(legal_trip(), zone_map)) == "PermitReport(4 nights, no findings)"


class TestEntryAndTrip:
    def test_an_available_entry_produces_no_finding(self, quota: QuotaCalendar) -> None:
        assert check_entry(quota, "echo-trailhead", START) is None

    def test_a_full_entry_produces_a_violation(self, quota: QuotaCalendar) -> None:
        full = quota.reserve("echo-trailhead", START, 8)
        finding = check_entry(full, "echo-trailhead", START)
        assert finding is not None
        assert finding.blocks_permit
        assert finding.context["remaining"] == 0

    def test_a_closed_entry_says_so(self, quota: QuotaCalendar) -> None:
        finding = check_entry(quota, "echo-trailhead", date(2025, 7, 4))
        assert finding is not None
        assert "closed" in finding.message

    def test_a_whole_trip_check_folds_the_entry_in(
        self, zone_map: ZoneMap, quota: QuotaCalendar
    ) -> None:
        full = quota.reserve("echo-trailhead", START, 8)
        report = validate_trip(legal_trip(), zone_map, full, "echo-trailhead", START)
        assert not report.is_permittable
        assert report.findings_from("entry_quota")

    def test_a_whole_trip_check_passes_when_everything_is_clear(
        self, zone_map: ZoneMap, quota: QuotaCalendar
    ) -> None:
        report = validate_trip(legal_trip(), zone_map, quota, "echo-trailhead", START)
        assert report.is_permittable

    def test_suggestions_name_a_fix_per_rule(self, zone_map: ZoneMap) -> None:
        report = validate_nights([night(0, 20.0, None), night(1, 20.0, None)], zone_map)
        fixes = suggest_fixes(report)
        assert any("designated site" in fix for fix in fixes)
        assert any("canister" in fix for fix in fixes)
        assert all("2 nights" in fix for fix in fixes)

    def test_a_clean_report_suggests_nothing(self, zone_map: ZoneMap) -> None:
        assert suggest_fixes(validate_nights(legal_trip(), zone_map)) == ()
