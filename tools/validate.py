"""Standalone checks over the data files and the generated scenery XML.

    python -m tools.validate

Runs independently of the build so it can be pointed at a checkout that has
already been built, e.g. in CI. Checks fall into two groups:

  data     - ids unique, coordinates in region, fixtures and schemes resolve
  output   - generated XML is well-formed and every coordinate is in range
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .geo import Point, haversine_m
from .model import REPO_ROOT, DataError, load_all

# Two marked structures closer together than this are almost always the same
# thing swept twice - a mast tagged as both a node and a way, say.
MIN_SEPARATION_M = 25.0

# Taller than this and the height tag is far more likely to be wrong than the
# structure to be real: the tallest structure ever built is about 2,720 ft.
MAX_PLAUSIBLE_HEIGHT_FT = 3000.0


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_data(root: Path = REPO_ROOT) -> Report:
    report = Report()
    data = load_all(root)
    region = data["region"]
    bindings = data["bindings"]
    raw = data["obstructions"]

    schemes = raw.get("marking_schemes", {})
    if not schemes:
        report.error("obstructions.json: no marking_schemes defined")

    # Every fixture a scheme names has to exist in the bindings file, whether
    # or not it is resolved yet - an unresolved fixture is a gap, a misspelled
    # one is a bug.
    for name, scheme in schemes.items():
        for role in ("top_fixture", "side_fixture"):
            fixture = scheme.get(role)
            if not fixture:
                report.error(f"obstructions.json:marking_schemes.{name}: missing {role}")
            elif not bindings.known(fixture):
                report.error(
                    f"obstructions.json:marking_schemes.{name}.{role}: unknown fixture "
                    f"type {fixture!r}"
                )

    seen_ids: dict[str, str] = {}
    placed: list[tuple[str, Point]] = []

    for obs in raw.get("obstructions", []):
        where = f"obstructions.json:{obs.get('id', '<no id>')}"
        entry_id = obs.get("id")
        if not entry_id:
            report.error(f"{where}: entry has no id")
            continue
        if entry_id in seen_ids:
            report.error(f"duplicate id {entry_id!r} in {where}")
        seen_ids[entry_id] = where

        if "lat" not in obs or "lon" not in obs:
            report.error(f"{where}: needs both lat and lon")
            continue
        point = Point(float(obs["lat"]), float(obs["lon"]))
        if not region.contains(point):
            report.error(
                f"{where}: ({point.lat:.5f}, {point.lon:.5f}) is outside the declared region"
            )

        height_ft = float(obs.get("height_ft", 0))
        if height_ft <= 0:
            report.error(f"{where}: height_ft must be positive, got {height_ft}")
        elif height_ft > MAX_PLAUSIBLE_HEIGHT_FT:
            report.warn(
                f"{where}: {height_ft:.0f} ft is taller than any structure ever built - "
                f"check the OSM height tag"
            )

        marking = obs.get("marking", raw.get("defaults", {}).get("marking", "red"))
        if marking not in schemes:
            report.error(f"{where}: unknown marking {marking!r}")

        if not obs.get("source"):
            report.warn(f"{where}: has no source field, so its provenance is unrecorded")

        for other_id, other in placed:
            if haversine_m(point, other) < MIN_SEPARATION_M:
                report.warn(
                    f"{where}: {haversine_m(point, other):.0f} m from {other_id} - "
                    f"the same structure swept twice?"
                )
        placed.append((entry_id, point))

    if not placed:
        report.warn(
            "no obstructions defined yet - run `python -m tools.sweep --apply` to "
            "populate data/obstructions.json"
        )

    return report


def validate_output(root: Path = REPO_ROOT) -> Report:
    """Check the generated XML, if it has been built."""
    report = Report()
    scenery_dir = root / "PackageSources" / "scenery"
    if not scenery_dir.exists():
        report.warn("PackageSources/scenery does not exist yet - run `make build` first")
        return report

    files = sorted(scenery_dir.glob("*.xml"))
    if not files:
        report.warn("PackageSources/scenery contains no .xml files")

    for path in files:
        rel = path.relative_to(root)
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            report.error(f"{rel}: not well-formed XML: {exc}")
            continue

        root_el = tree.getroot()
        if root_el.tag != "FSData":
            report.error(f"{rel}: root element is <{root_el.tag}>, expected <FSData>")
            continue

        for i, obj in enumerate(root_el.findall("SceneryObject")):
            try:
                lat = float(obj.get("lat", "nan"))
                lon = float(obj.get("lon", "nan"))
            except ValueError:
                report.error(f"{rel}: object {i} has unparseable lat/lon")
                continue
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                report.error(f"{rel}: object {i} at ({lat}, {lon}) is off the planet")
            if len(list(obj)) != 1:
                report.error(
                    f"{rel}: object {i} has {len(list(obj))} child elements, expected exactly 1"
                )
            # A light placed above the ground must not be snapped down to it.
            # This is the failure that puts every beacon in the package at
            # ground level, and it is invisible until you are in the sim.
            if float(obj.get("alt", "0")) > 0.05 and obj.get("snapToGround") == "TRUE":
                report.error(
                    f"{rel}: object {i} is {obj.get('alt')} m AGL but snapToGround is TRUE"
                )

    return report


def main(argv: list[str] | None = None) -> int:
    try:
        data_report = validate_data()
    except DataError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    output_report = validate_output()

    errors = data_report.errors + output_report.errors
    warnings = data_report.warnings + output_report.warnings

    for warning in warnings:
        print(f"  warn:  {warning}")
    for error in errors:
        print(f"  ERROR: {error}")

    print()
    print(f"  {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
