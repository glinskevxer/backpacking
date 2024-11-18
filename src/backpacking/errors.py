"""Exception hierarchy shared by every layer.

Errors carry structured context rather than a formatted sentence. The API layer
turns that context into a JSON body and the CLI turns it into a line of text,
so neither of them has to parse a message back apart.
"""

from __future__ import annotations

from typing import Any


class BackpackingError(Exception):
    """Base class for everything this package raises deliberately."""

    #: Stable, machine readable identifier. Subclasses override it.
    code = "backpacking_error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = dict(context)

    def __str__(self) -> str:
        if not self.context:
            return self.message
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.context.items()))
        return f"{self.message} ({rendered})"

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable view used by the API error handler."""
        return {"code": self.code, "message": self.message, "context": dict(self.context)}


class ConfigurationError(BackpackingError):
    """Settings are missing or contradict each other."""

    code = "configuration_error"


class DataSourceError(BackpackingError):
    """An external file could not be read or did not have the expected shape."""

    code = "data_source_error"


class CorridorError(BackpackingError):
    """A corridor is malformed: unsorted miles, duplicate anchors, empty."""

    code = "corridor_error"


class WaypointNotFound(CorridorError):
    """A waypoint was requested by identifier and no such waypoint exists."""

    code = "waypoint_not_found"


class RouteResolutionError(CorridorError):
    """Alternates could not be applied to produce a single linear route."""

    code = "route_resolution_error"


class PaceModelError(BackpackingError):
    """A pace model was asked for a value outside the range it can defend."""

    code = "pace_model_error"


class WaterCarryError(BackpackingError):
    """A dry stretch cannot be covered with the carrying capacity supplied."""

    code = "water_carry_error"


class LoadoutError(BackpackingError):
    """A pack loadout is inconsistent, for example negative consumable mass."""

    code = "loadout_error"


class PermitError(BackpackingError):
    """A permit zone, quota calendar or rule set is malformed."""

    code = "permit_error"


class ResupplyInfeasible(BackpackingError):
    """No admissible set of resupply stops exists for the constraints given."""

    code = "resupply_infeasible"


class PlanInfeasible(BackpackingError):
    """The solver exhausted its search without finding a legal itinerary."""

    code = "plan_infeasible"


class ValidationFailed(BackpackingError):
    """A finished itinerary breaks one or more hard rules."""

    code = "validation_failed"

    def __init__(self, message: str, violations: list[str] | None = None, **context: Any) -> None:
        super().__init__(message, **context)
        self.violations = list(violations or ())
        self.context["violations"] = self.violations
