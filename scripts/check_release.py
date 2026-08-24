#!/usr/bin/env python
"""Refuse to tag a release the repository is not actually ready for.

Everything here has gone wrong at least once, and every one of the failures is
silent until somebody deploys: a version that does not match the tag, a
migration that was never generated for a model change, a workflow that no longer
references a file, an entry point that does not import.

Run it before tagging. Exits non zero and says which check failed.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import pathlib
import re
import sys
import tomllib
from collections.abc import Callable
from importlib.metadata import packages_distributions

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Works from a checkout as well as from an installed package, because the most
# useful time to run this is before anything has been installed.
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

#: Modules that must import cleanly, because something outside calls each one.
ENTRY_POINTS = (
    "backpacking.api.app",
    "backpacking.api.main",
    "backpacking.cli.main",
    "backpacking.services.planning",
    "backpacking.storage.session",
)

#: Files a workflow or the packaging references, which must exist.
REFERENCED_FILES = (
    "alembic.ini",
    "Dockerfile",
    "docker-compose.yml",
    "gunicorn.conf.py",
    "pyproject.toml",
    "scripts/seed_demo.py",
    "scripts/check_tests.py",
    "src/backpacking/py.typed",
    ".github/workflows/ci.yml",
    ".github/workflows/docker.yml",
    ".github/workflows/security.yml",
)


def read_pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def check_version_matches_package() -> list[str]:
    """The version in pyproject and the one in ``__init__`` have to agree."""
    declared = str(read_pyproject()["project"]["version"])  # type: ignore[index]
    source = (ROOT / "src/backpacking/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', source)
    if match is None:
        return ["__version__ is not declared in backpacking/__init__.py"]
    if match.group(1) != declared:
        return [
            f"version mismatch: pyproject says {declared}, "
            f"backpacking.__version__ says {match.group(1)}"
        ]
    return []


def check_version_is_a_release() -> list[str]:
    declared = str(read_pyproject()["project"]["version"])  # type: ignore[index]
    if not re.fullmatch(r"\d+\.\d+\.\d+", declared):
        return [f"version {declared} is not a plain release version"]
    return []


def check_entry_points_import() -> list[str]:
    problems: list[str] = []
    for module in ENTRY_POINTS:
        try:
            importlib.import_module(module)
        except Exception as error:
            problems.append(f"{module} does not import: {error}")
    return problems


def check_referenced_files_exist() -> list[str]:
    return [
        f"{name} is referenced by the build or a workflow but is missing"
        for name in REFERENCED_FILES
        if not (ROOT / name).exists()
    ]


def check_every_model_has_a_migration() -> list[str]:
    """Every table in the schema must appear in at least one migration."""
    try:
        from backpacking.storage.schema import Base
    except ImportError as error:
        return [f"cannot read the schema to compare against migrations: {error}"]

    versions = ROOT / "migrations" / "versions"
    if not versions.is_dir():
        return ["migrations/versions is missing"]
    text = "\n".join(path.read_text(encoding="utf-8") for path in versions.glob("*.py"))
    return [
        f"table {table} has no create_table in any migration"
        for table in sorted(Base.metadata.tables)
        if f'"{table}"' not in text
    ]


def declared_distributions() -> set[str]:
    """Every distribution named in pyproject, normalised for comparison."""
    project = read_pyproject()["project"]
    declared: list[str] = list(project["dependencies"])  # type: ignore[index]
    for extra in project.get("optional-dependencies", {}).values():  # type: ignore[union-attr]
        declared.extend(extra)
    return {
        requirement.split("==")[0].split("[")[0].strip().lower().replace("_", "-")
        for requirement in declared
    }


def imported_third_party_modules() -> set[str]:
    """Top level modules that ``src`` imports and does not ship itself."""
    found: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {
        module
        for module in found
        if module not in sys.stdlib_module_names and module != "backpacking"
    }


def check_every_import_is_declared() -> list[str]:
    """Nothing may be imported that pyproject does not ask to be installed.

    This is the check that would have caught structlog. It was imported by the
    logging module, installed by hand in the development environment, and named
    nowhere in the packaging, so every fresh install was broken and nothing
    local noticed. A transitive dependency counts as undeclared too: importing
    starlette because fastapi happens to pull it in works right up until fastapi
    stops pulling it in.
    """
    declared = declared_distributions()
    dist_map = packages_distributions()
    problems: list[str] = []
    for module in sorted(imported_third_party_modules()):
        dists = dist_map.get(module, [])
        if not dists:
            problems.append(f"{module} is imported but is not installed, so it cannot be checked")
        elif not any(d.lower().replace("_", "-") in declared for d in dists):
            problems.append(
                f"{module} is imported but not declared " f"(provided by {', '.join(dists)})"
            )
    return problems


def check_pinned_dependencies() -> list[str]:
    """Runtime dependencies are pinned, so two deploys are the same deploy."""
    project = read_pyproject()["project"]
    declared: list[str] = list(project["dependencies"])  # type: ignore[index]
    for extra in project.get("optional-dependencies", {}).values():  # type: ignore[union-attr]
        declared.extend(extra)
    unpinned = [
        requirement
        for requirement in declared
        if "==" not in requirement and not requirement.startswith("#")
    ]
    return [f"dependency is not pinned: {requirement}" for requirement in unpinned]


CHECKS: tuple[tuple[str, Callable[[], list[str]]], ...] = (
    ("version agrees between pyproject and the package", check_version_matches_package),
    ("version is a plain release version", check_version_is_a_release),
    ("entry points import", check_entry_points_import),
    ("referenced files exist", check_referenced_files_exist),
    ("every table has a migration", check_every_model_has_a_migration),
    ("every import is declared", check_every_import_is_declared),
    ("dependencies are pinned", check_pinned_dependencies),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="only report failures")
    args = parser.parse_args()

    failures = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failures += 1
            print(f"FAIL  {label}", file=sys.stderr)
            for problem in problems:
                print(f"        {problem}", file=sys.stderr)
        elif not args.quiet:
            print(f"ok    {label}")

    if failures:
        print(f"\n{failures} check(s) failed", file=sys.stderr)
        return 1
    if not args.quiet:
        print("\nready to tag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
