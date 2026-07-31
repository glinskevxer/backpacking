#!/usr/bin/env python
"""Refuse a commit that leaves a test focused, skipped or commented out.

Every one of these has been pushed at least once and every one of them makes the
suite quietly stop covering something. They are trivial to catch mechanically
and impossible to catch by reading a diff.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

FOCUS = re.compile(r"^\s*@pytest\.mark\.only\b")
SKIP = re.compile(r"^\s*@pytest\.mark\.(skip|skipif)\b")
XFAIL = re.compile(r"^\s*@pytest\.mark\.xfail\b")
DEBUG = re.compile(r"^\s*(breakpoint\(\)|import pdb|pdb\.set_trace\(\))")
COMMENTED = re.compile(r"^\s*#\s*def test_\w+")

ALLOW = "check-tests: allow"


def scan(path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if ALLOW in line:
            continue
        if FOCUS.match(line):
            problems.append(f"{path}:{number}: focused test left in place")
        elif SKIP.match(line):
            problems.append(f"{path}:{number}: skipped test, add '{ALLOW}' if deliberate")
        elif XFAIL.match(line):
            problems.append(f"{path}:{number}: xfail left in place")
        elif DEBUG.match(line):
            problems.append(f"{path}:{number}: debugger call left in place")
        elif COMMENTED.match(line):
            problems.append(f"{path}:{number}: commented out test")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check, defaults to tests/")
    args = parser.parse_args()
    targets = (
        [pathlib.Path(p) for p in args.paths]
        if args.paths
        else sorted(pathlib.Path("tests").rglob("test_*.py"))
    )
    problems: list[str] = []
    for path in targets:
        if path.suffix == ".py" and path.exists():
            problems.extend(scan(path))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"checked {len(targets)} test files, nothing left behind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
