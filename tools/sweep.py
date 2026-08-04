"""Sweep OpenStreetMap for tall structures and propose obstruction entries.

    python -m tools.sweep                 # dry run over every declared area
    python -m tools.sweep --apply         # write the result to data/obstructions.json
    python -m tools.sweep --area ridge    # one named search_area only

The sweep proposes; you verify. Two rules keep it honest:

  * A structure whose height OSM does not record is SKIPPED, not defaulted.
    A beacon at a guessed altitude floats above the mast or sits buried inside
    it, and this is scenery people fly at. Skipped structures are listed, with
    their OSM id, so anything worth having can be added by hand.

  * Anything already lit by the simulator belongs in `sweep.exclude` in
    config/build_profile.json. A doubled or slightly offset beacon reads worse
    than no beacon at all, and that judgement can only be made in the sim -
    so the exclude list is how it gets recorded once instead of being
    re-litigated on every re-sweep.

Needs outbound access to an Overpass endpoint, which many sandboxed and
corporate networks block. The build itself never touches the network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import jsonfmt
from .geo import Point, haversine_m, metres_to_feet
from .model import REPO_ROOT, BuildProfile, DataError, Region, load_json
from .osm import (
    DEFAULT_ENDPOINT,
    MIRRORS,
    REQUEST_GAP_S,
    OverpassError,
    Pacer,
    fetch_structures,
    resolve_endpoint,
)

# An OSM structure this close to an existing entry is taken to be the same
# thing, so a hand-made marking choice carries over instead of being reset.
MARKING_CARRYOVER_M = 200.0

# Default ring radius for a swept structure, metres. A mast is a point in OSM;
# this is what separates the side lights of one level from each other.
DEFAULT_RADIUS_M = 5


def _entry_id(index: int) -> str:
    return f"obs_{index + 1:03d}"


def build_entries(
    structures: list[dict],
    existing: list[dict],
    *,
    min_height_ft: float,
    exclude: list[str] | None = None,
    radius_m: float = DEFAULT_RADIUS_M,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn OSM structure records into obstruction entries.

    Returns `(entries, no_height, too_short)` - the proposals, the structures
    OSM has no height for, and the ones below the marking floor. The two
    rejection lists are returned rather than logged so the caller can report
    them and the tests can assert on them.

    Marking is the one field OSM cannot supply: it records that a structure is
    there, not whether the authority had it painted red or strobed white. So an
    OSM structure that lands on top of an existing entry inherits that entry's
    marking, and only genuinely new ones fall back to red.
    """
    excluded = set(exclude or ())
    entries: list[dict] = []
    no_height: list[dict] = []
    too_short: list[dict] = []

    ordered = sorted(structures, key=lambda s: (-s["point"].lat, s["point"].lon))
    for structure in ordered:
        if structure["osm_id"] in excluded:
            continue

        # Height first: without one there is nothing to place a beacon on top
        # of, and no way to tell whether the structure clears the floor.
        if not structure["height_m"]:
            no_height.append(structure)
            continue

        height_ft = metres_to_feet(structure["height_m"])
        if height_ft < min_height_ft:
            too_short.append(structure)
            continue

        point = structure["point"]
        marking = "red"
        nearest = None
        for candidate in existing:
            if "lat" not in candidate:
                continue
            distance = haversine_m(point, Point(candidate["lat"], candidate["lon"]))
            if distance <= MARKING_CARRYOVER_M and (nearest is None or distance < nearest[0]):
                nearest = (distance, candidate)
        if nearest is not None:
            marking = nearest[1].get("marking", "red")

        entries.append({
            "id": _entry_id(len(entries)),
            "name": structure["name"] or f"Structure {len(entries) + 1}",
            "lat": round(point.lat, 6),
            "lon": round(point.lon, 6),
            "height_ft": round(height_ft),
            "radius_m": radius_m,
            "auto_levels": True,
            "top_beacons": 1,
            "marking": marking,
            "source": f"openstreetmap {structure['osm_id']}",
        })
    return entries, no_height, too_short


def _report_rejects(label: str, rejects: list[dict], detail: str) -> None:
    if not rejects:
        return
    print(f"\n  {len(rejects)} {label}:")
    for structure in rejects[:20]:
        name = (structure["name"] or "unnamed")[:42]
        print(f"    {name:<42} {structure['osm_id']}")
    if len(rejects) > 20:
        print(f"    ... and {len(rejects) - 20} more")
    print(f"    {detail}")


def sweep(
    root: Path = REPO_ROOT,
    *,
    area: str | None = None,
    endpoint: str = DEFAULT_ENDPOINT,
    apply: bool = False,
    pacer: Pacer | None = None,
) -> int:
    """Sweep one named area, or the whole region, and rewrite the entries.

    Returns the number of proposed entries. Nothing is written without
    `apply`.
    """
    path = root / "data" / "obstructions.json"
    raw = load_json(path)
    region = Region.load(root / "data" / "region.json")
    profile = BuildProfile.load(root / "config" / "build_profile.json")

    if area:
        boxes = {area: region.search_area(area)}
    elif region.search_areas:
        boxes = dict(region.search_areas)
    else:
        # No search areas declared: sweep everything the package may place in.
        boxes = {region.name: region.box}

    existing = raw.get("obstructions", [])
    found: list[dict] = []
    seen: set[str] = set()

    for name, box in boxes.items():
        print(
            f"  {name}: sweeping {box['south']},{box['west']} .. "
            f"{box['north']},{box['east']} ... ",
            end="", flush=True,
        )
        try:
            structures = fetch_structures(box, profile.selectors, endpoint, pacer=pacer)
        except OverpassError as exc:
            print(f"FAILED\n    {exc}")
            # One area failing is not a reason to throw away the others, and
            # certainly not a reason to write a shortened list to disk.
            return 0
        print(f"{len(structures)} feature(s)")
        # Overlapping search areas would otherwise propose a mast twice.
        for structure in structures:
            if structure["osm_id"] not in seen:
                seen.add(structure["osm_id"])
                found.append(structure)

    if not found:
        print("\n  Nothing returned - keeping what is already there, untouched.")
        print("  Thin OSM coverage is not a reason to delete what you have.")
        return 0

    entries, no_height, too_short = build_entries(
        found,
        existing,
        min_height_ft=profile.min_marked_height_ft,
        exclude=profile.exclude,
    )

    print(f"\n  {len(entries)} structure(s) to light:")
    for entry in entries:
        nearest = min(
            (haversine_m(Point(entry["lat"], entry["lon"]), Point(o["lat"], o["lon"]))
             for o in existing if "lat" in o),
            default=None,
        )
        where = f"{nearest:.0f} m from an existing entry" if nearest is not None else "new"
        print(f"    {entry['name'][:42]:<42} {entry['height_ft']:>4} ft  {where}")

    _report_rejects(
        "with no height in OSM - skipped rather than guessed",
        no_height,
        "Add a height to OSM, or add the entry to data/obstructions.json by hand.",
    )
    _report_rejects(
        f"below the {profile.min_marked_height_ft:.0f} ft marking floor",
        too_short,
        "Below this height marking is generally not required, so they are left unlit.",
    )

    print(f"\n  {len(existing)} existing -> {len(entries)} from OSM")

    if apply:
        raw["obstructions"] = entries
        jsonfmt.write(path, raw)
        print(f"  Wrote {path.relative_to(root)}")
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--area", default=None, metavar="NAME",
        help="one named search_area from data/region.json (default: every one declared)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="write the result to data/obstructions.json. Without this, only the deltas print.",
    )
    parser.add_argument(
        "--endpoint", default=DEFAULT_ENDPOINT,
        help=(
            "Overpass endpoint: a full URL, or one of the known mirrors "
            f"({', '.join(MIRRORS)}). Try another if one is rate-limiting you."
        ),
    )
    parser.add_argument(
        "--gap", type=float, default=REQUEST_GAP_S, metavar="SECONDS",
        help=(
            f"minimum seconds between requests (default {REQUEST_GAP_S:g}). Raise it if the "
            f"endpoint keeps throttling you. A throttle already doubles the gap "
            f"automatically for the rest of the run."
        ),
    )
    args = parser.parse_args(argv)

    endpoint = resolve_endpoint(args.endpoint)
    if endpoint != DEFAULT_ENDPOINT:
        print(f"Endpoint: {endpoint}")
    try:
        pacer = Pacer(args.gap)
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.gap != REQUEST_GAP_S:
        print(f"Pacing: at least {args.gap:g}s between requests")
    if not args.apply:
        print("Dry run - pass --apply to write the results to data/obstructions.json.\n")

    try:
        sweep(REPO_ROOT, area=args.area, endpoint=endpoint, apply=args.apply, pacer=pacer)
    except DataError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1

    if args.apply:
        print("\nCheck the result in the sim, then `make check` before committing.")
        print("Anything the sim already lights belongs in sweep.exclude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
