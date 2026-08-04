"""FAA-style obstruction lighting on tall structures.

Marking follows the outline of AC 70/7460-1: a flashing beacon at the top of
the structure, plus rings of steady red side lights at intermediate levels
roughly every 150 ft below it. The rules are national - ICAO Annex 14 differs -
so the schemes live in data/obstructions.json rather than in this file, and a
package outside the United States is expected to edit them.

This is scenery, not an obstacle database - see the header note in
data/obstructions.json.
"""

from __future__ import annotations

from ..fsxml import SceneryFile
from ..model import DataError
from .common import Context, resolve_point, ring


def resolve_marking(raw: dict, obstruction: dict, context: str) -> dict:
    """Work out the marking scheme for one structure.

    Precedence is per-obstruction override, then the scheme, then the file
    defaults. A white system is not a colour swap on a red one - it strobes at
    every level, spaces those levels further apart and carries fewer units per
    level - so the scheme gets to override the interval and count, not just the
    fixtures.
    """
    defaults = raw.get("defaults", {})
    schemes = raw.get("marking_schemes", {})

    name = obstruction.get("marking", defaults.get("marking", "red"))
    if name not in schemes:
        known = ", ".join(sorted(schemes)) or "(none defined)"
        raise DataError(f"{context}: unknown marking {name!r}. Known schemes: {known}")
    scheme = schemes[name]

    merged = {
        "name": name,
        "top_fixture": scheme["top_fixture"],
        "side_fixture": scheme["side_fixture"],
        "level_interval_ft": float(
            obstruction.get(
                "level_interval_ft",
                scheme.get("level_interval_ft", defaults.get("level_interval_ft", 150)),
            )
        ),
        "lights_per_level": int(
            obstruction.get(
                "lights_per_level",
                scheme.get("lights_per_level", defaults.get("lights_per_level", 4)),
            )
        ),
    }
    if merged["level_interval_ft"] <= 0:
        raise DataError(
            f"{context}: level_interval_ft must be positive, got {merged['level_interval_ft']}"
        )
    if merged["lights_per_level"] <= 0:
        raise DataError(
            f"{context}: lights_per_level must be positive, got {merged['lights_per_level']}"
        )
    return merged


def generate(ctx: Context) -> SceneryFile:
    raw = ctx.data["obstructions"]

    out = SceneryFile(
        filename="obstruction-lights.xml",
        title="Obstruction lighting",
        description=(
            f"Beacons and side lights on the tall structures of {ctx.region.name}:\n"
            "masts, communication towers and chimneys swept from OpenStreetMap."
        ),
    )

    for obs in raw["obstructions"]:
        oid = obs["id"]
        context = f"obstructions.json:{oid}"
        center = resolve_point(obs, context)

        height_ft = float(obs.get("height_ft", 0))
        if height_ft <= 0:
            raise DataError(f"{context}: height_ft must be positive, got {height_ft}")
        radius = float(obs.get("radius_m", 5.0))
        marking = resolve_marking(raw, obs, context)

        # Top beacon(s). A wide structure gets a beacon at each end of the roof
        # rather than one in the middle, which is how the real marking works.
        beacon_count = int(obs.get("top_beacons", 1))
        for pos, heading in ring(center, beacon_count, radius if beacon_count > 1 else 0.0):
            obj = ctx.place(
                marking["top_fixture"], pos, source_id=oid, kind="obstruction_beacon",
                agl_ft=height_ft, heading=heading,
            )
            if obj is not None:
                out.add(obj)

        if not obs.get("auto_levels", False):
            continue

        # Intermediate levels, working down from just below the top.
        interval = marking["level_interval_ft"]
        level_ft = height_ft - interval
        while level_ft > interval * 0.5:
            for pos, heading in ring(
                center, marking["lights_per_level"], radius, start_bearing=45.0
            ):
                obj = ctx.place(
                    marking["side_fixture"], pos, source_id=oid,
                    kind="obstruction_side_light", agl_ft=level_ft, heading=heading,
                )
                if obj is not None:
                    out.add(obj)
            level_ft -= interval

    return out
