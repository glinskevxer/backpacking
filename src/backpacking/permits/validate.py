"""Running the rule set and reporting the answer.

The report is deliberately not a boolean. A planner needs to know which nights
are illegal, which are merely frowned upon, and what the cheapest fix is, and a
false return value carries none of that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from backpacking.errors import ValidationFailed
from backpacking.permits.quota import QuotaCalendar
from backpacking.permits.rules import CampNight, Finding, Rule, Severity, default_rules
from backpacking.permits.zones import ZoneMap


@dataclass(frozen=True, slots=True)
class PermitReport:
    """Everything the rule set had to say about one itinerary."""

    findings: tuple[Finding, ...]
    nights_checked: int
    zones_visited: tuple[str, ...]

    @property
    def violations(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.VIOLATION)

    @property
    def advisories(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ADVISORY)

    @property
    def is_permittable(self) -> bool:
        return not self.violations

    def findings_on(self, night: date) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.night == night)

    def findings_from(self, rule_name: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.rule == rule_name)

    def summary(self) -> str:
        if self.is_permittable and not self.advisories:
            return f"{self.nights_checked} nights, no findings"
        return (
            f"{self.nights_checked} nights, {len(self.violations)} violations, "
            f"{len(self.advisories)} advisories"
        )

    def raise_if_illegal(self) -> None:
        if not self.is_permittable:
            raise ValidationFailed(
                "itinerary breaks permit rules",
                violations=[f.message for f in self.violations],
                nights=self.nights_checked,
            )

    def __repr__(self) -> str:
        return f"PermitReport({self.summary()})"


def validate_nights(
    nights: Sequence[CampNight],
    zones: ZoneMap,
    rules: Sequence[Rule] | None = None,
) -> PermitReport:
    """Run every rule over the itinerary and collect what they find."""
    applied = tuple(rules) if rules is not None else default_rules()
    findings: list[Finding] = []
    for rule in applied:
        findings.extend(rule.check(nights, zones))
    findings.sort(key=_finding_sort_key)
    visited: list[str] = []
    for camp in nights:
        zone = zones.at(camp.mile)
        if zone is not None and zone.id not in visited:
            visited.append(zone.id)
    return PermitReport(
        findings=tuple(findings),
        nights_checked=len(nights),
        zones_visited=tuple(visited),
    )


def _finding_sort_key(finding: Finding) -> tuple[date, int, str]:
    ordinal = date.min if finding.night is None else finding.night
    return ordinal, 0 if finding.severity is Severity.VIOLATION else 1, finding.rule


def check_entry(
    calendar: QuotaCalendar,
    entry_id: str,
    start: date,
    party_size: int = 1,
) -> Finding | None:
    """One finding if the start date cannot be permitted at this trailhead."""
    if calendar.is_available(entry_id, start, party_size):
        return None
    remaining = calendar.remaining(entry_id, start)
    entry = calendar.entry(entry_id)
    if not entry.is_open(start):
        message = f"{entry.name} is closed on this date"
    else:
        message = f"{entry.name} has {remaining} permits left and the party needs {party_size}"
    return Finding(
        rule="entry_quota",
        severity=Severity.VIOLATION,
        message=message,
        night=start,
        context={"entry": entry_id, "remaining": remaining, "party_size": party_size},
    )


def validate_trip(
    nights: Sequence[CampNight],
    zones: ZoneMap,
    calendar: QuotaCalendar,
    entry_id: str,
    start: date,
    *,
    party_size: int = 1,
    rules: Sequence[Rule] | None = None,
) -> PermitReport:
    """Zone rules plus the entry quota, which is the whole permit question."""
    report = validate_nights(nights, zones, rules)
    entry_finding = check_entry(calendar, entry_id, start, party_size)
    if entry_finding is None:
        return report
    findings = sorted([*report.findings, entry_finding], key=_finding_sort_key)
    return PermitReport(
        findings=tuple(findings),
        nights_checked=report.nights_checked,
        zones_visited=report.zones_visited,
    )


def suggest_fixes(report: PermitReport) -> tuple[str, ...]:
    """Plain sentences a planner can act on, one per distinct rule that fired."""
    by_rule: dict[str, int] = {}
    for finding in report.violations:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
    advice = {
        "camping_policy": "move the camp to a designated site inside the zone",
        "consecutive_nights": "split the stay by camping in the neighbouring zone for a night",
        "bear_canister": "carry an approved canister for the whole of this section",
        "campfire": "plan a stoveless or stove only evening at this camp",
        "entry_quota": "start a day either side, or enter from a different trailhead",
        "water_setback": "move the camp back from the water",
    }
    return tuple(
        f"{advice.get(rule, 'resolve the finding')} ({count} night{'s' if count > 1 else ''})"
        for rule, count in sorted(by_rule.items())
    )
