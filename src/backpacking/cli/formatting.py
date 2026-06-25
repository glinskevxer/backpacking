"""Terminal output helpers.

No colour and no box drawing. This output gets piped, redirected into files and
read over a text only satellite link from a trailhead, and every one of those
breaks on escape codes.
"""

from __future__ import annotations

from collections.abc import Sequence


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Render fixed width columns sized to their contents."""
    if not headers:
        raise ValueError("a table needs at least one column")
    cells = [[str(value) for value in row] for row in rows]
    for row in cells:
        if len(row) != len(headers):
            raise ValueError(f"row has {len(row)} cells but there are {len(headers)} columns")
    widths = [len(header) for header in headers]
    for row in cells:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    lines = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    for row in cells:
        lines.append("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))
    return "\n".join(lines)


def keyed(pairs: dict[str, object]) -> str:
    """Render a mapping as aligned ``key: value`` lines."""
    if not pairs:
        return ""
    width = max(len(key) for key in pairs)
    return "\n".join(f"{key.ljust(width)}  {value}" for key, value in pairs.items())


def miles(value: float) -> str:
    return f"{value:.1f}"


def feet(value: float) -> str:
    return f"{value:.0f}"


def pounds(value: float) -> str:
    return f"{value:.2f}"


def plural(count: int, singular: str, many: str | None = None) -> str:
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {many or singular + 's'}"
