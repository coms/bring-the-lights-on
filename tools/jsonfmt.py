"""JSON writing that keeps the data files reviewable.

`json.dumps(indent=2)` puts every element of every array on its own line, which
turns a coordinate pair into three lines of noise and makes the diff after
`sweep --apply` harder to read than it needs to be. Pairs belong on one line.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Matches a two-number array that indent-mode has broken across lines.
_PAIR = re.compile(
    r"\[\s*\n\s*(-?\d+(?:\.\d+)?),\s*\n\s*(-?\d+(?:\.\d+)?)\s*\n\s*\]"
)


def dumps(payload, *, indent: int = 2) -> str:
    """Serialise with indentation, but collapse `[lat, lon]` pairs inline."""
    text = json.dumps(payload, indent=indent, ensure_ascii=False)
    # Repeat until stable: a pair can sit inside another collapsed structure.
    while True:
        collapsed = _PAIR.sub(r"[\1, \2]", text)
        if collapsed == text:
            return collapsed + "\n"
        text = collapsed


def write(path: Path, payload) -> None:
    path.write_text(dumps(payload), encoding="utf-8")
