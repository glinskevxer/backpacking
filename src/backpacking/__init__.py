"""Logistics engine for long-distance trail corridors.

The package is split so that the planning maths never depends on transport or
storage. Anything under ``backpacking.trail``, ``backpacking.pace``,
``backpacking.water``, ``backpacking.food``, ``backpacking.permits``,
``backpacking.resupply`` and ``backpacking.plan`` is pure: it takes value
objects and returns value objects. The ``api``, ``cli`` and ``storage``
packages are the only ones allowed to touch the outside world.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
