"""Loading and validation for the package's data and configuration files.

The generator goes through here, so a malformed data file fails once, loudly,
with the offending id in the message, instead of producing a scenery file full
of beacons at (0, 0).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .fsxml import Effect, LibraryObject, Payload
from .geo import Point, bbox_contains

REPO_ROOT = Path(__file__).resolve().parent.parent


class DataError(Exception):
    """A data or configuration file is wrong in a way we can name precisely."""


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise DataError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DataError(
            f"{path}: invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}"
        ) from exc


def require(mapping: dict, key: str, context: str) -> Any:
    if key not in mapping:
        raise DataError(f"{context}: missing required field '{key}'")
    return mapping[key]


def _check_box(box: dict, context: str) -> None:
    for side in ("south", "west", "north", "east"):
        require(box, side, context)
    if box["south"] >= box["north"] or box["west"] >= box["east"]:
        raise DataError(f"{context}: degenerate or inverted bounding box")


# --------------------------------------------------------------------------
# Region
# --------------------------------------------------------------------------


@dataclass
class Region:
    """Where this package is allowed to place objects, and where it sweeps.

    `box` is the hard boundary: anything the generator emits outside it is a
    build error. That guard exists because a dropped minus sign on a longitude
    looks completely normal and puts a beacon in western China.
    """

    name: str
    box: dict
    reference: Point
    search_areas: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Region":
        raw = load_json(path)
        box = require(raw, "region", "region.json")
        _check_box(box, "region.json:region")

        search_areas = {
            name: area
            for name, area in raw.get("search_areas", {}).items()
            if not name.startswith("$")
        }
        for name, area in search_areas.items():
            context = f"region.json:search_areas.{name}"
            _check_box(area, context)
            # A search area outside the region would sweep for structures this
            # package is then not allowed to place.
            for corner_lat in (area["south"], area["north"]):
                for corner_lon in (area["west"], area["east"]):
                    if not bbox_contains(box, Point(corner_lat, corner_lon)):
                        raise DataError(f"{context}: extends outside the region box")

        ref = require(raw, "reference_point", "region.json")
        return cls(
            name=raw.get("name", "unnamed region"),
            box=box,
            reference=Point(ref["lat"], ref["lon"]),
            search_areas=search_areas,
        )

    def search_area(self, name: str) -> dict:
        """A named bounding box that the sweep searches for structures."""
        if name not in self.search_areas:
            known = ", ".join(sorted(self.search_areas)) or "(none defined)"
            raise DataError(
                f"region.json: search_areas.{name} is not defined. Known areas: {known}"
            )
        return self.search_areas[name]

    def contains(self, point: Point) -> bool:
        """Whether a point is anywhere this package is allowed to place objects."""
        return bbox_contains(self.box, point)


# --------------------------------------------------------------------------
# Fixture bindings
# --------------------------------------------------------------------------


@dataclass
class Bindings:
    """Resolves logical fixture names to something the sim can draw.

    Unresolved fixtures are counted rather than substituted. A missing binding
    is a gap in the package, and the build report says exactly how big a gap it
    is, in objects.
    """

    fixtures: dict
    unresolved_hits: Counter = field(default_factory=Counter)
    resolved_hits: Counter = field(default_factory=Counter)

    @classmethod
    def load(cls, path: Path) -> "Bindings":
        raw = load_json(path)
        fixtures = require(raw, "fixtures", "library_bindings.json")

        for name, spec in fixtures.items():
            kind = require(spec, "kind", f"library_bindings.json:{name}")
            if kind not in ("library_object", "effect"):
                raise DataError(
                    f"library_bindings.json:{name}: kind must be 'library_object' or "
                    f"'effect', got {kind!r}"
                )
            if spec.get("resolved"):
                # Claiming resolved without supplying the thing is the one
                # inconsistency that would silently produce a broken package.
                if kind == "library_object" and not spec.get("guid"):
                    raise DataError(
                        f"library_bindings.json:{name}: marked resolved but has no guid"
                    )
                if kind == "effect" and not spec.get("effect_name"):
                    raise DataError(
                        f"library_bindings.json:{name}: marked resolved but has no effect_name"
                    )
        return cls(fixtures=fixtures)

    def known(self, name: str) -> bool:
        return name in self.fixtures

    def payload(self, name: str, *, context: str = "") -> Optional[Payload]:
        """Build the payload for a fixture, or None if it is not bound yet."""
        spec = self.fixtures.get(name)
        if spec is None:
            where = f" (used by {context})" if context else ""
            raise DataError(
                f"unknown fixture type {name!r}{where}. Add it to "
                f"config/library_bindings.json or fix the reference."
            )
        if not spec.get("resolved"):
            self.unresolved_hits[name] += 1
            return None

        self.resolved_hits[name] += 1
        if spec["kind"] == "library_object":
            return LibraryObject(guid=spec["guid"], scale=float(spec.get("scale", 1.0)))
        return Effect(effect_name=spec["effect_name"])

    @property
    def unresolved_names(self) -> list[str]:
        return sorted(name for name, spec in self.fixtures.items() if not spec.get("resolved"))

    @property
    def resolved_names(self) -> list[str]:
        return sorted(name for name, spec in self.fixtures.items() if spec.get("resolved"))


# --------------------------------------------------------------------------
# Build profile
# --------------------------------------------------------------------------

DEFAULT_SELECTORS = [
    {"man_made": "mast"},
    {"man_made": "tower", "tower:type": "communication"},
    {"man_made": "chimney"},
]


@dataclass
class BuildProfile:
    raw: dict

    @classmethod
    def load(cls, path: Path) -> "BuildProfile":
        raw = load_json(path)
        for section in ("features", "limits", "placement", "bindings", "sweep", "output"):
            require(raw, section, "build_profile.json")

        policy = raw["bindings"].get("on_unresolved", "skip")
        if policy not in ("skip", "error"):
            raise DataError(
                f"build_profile.json: bindings.on_unresolved must be 'skip' or 'error', "
                f"got {policy!r}"
            )

        selectors = raw["sweep"].get("selectors", DEFAULT_SELECTORS)
        if not isinstance(selectors, list) or not selectors:
            raise DataError("build_profile.json: sweep.selectors must be a non-empty list")
        for selector in selectors:
            if not isinstance(selector, dict) or not selector:
                raise DataError(
                    f"build_profile.json: each sweep selector must be a non-empty "
                    f"object of OSM tags, got {selector!r}"
                )

        floor = raw["sweep"].get("min_marked_height_ft", 200.0)
        if not isinstance(floor, (int, float)) or floor <= 0:
            raise DataError(
                f"build_profile.json: sweep.min_marked_height_ft must be a positive "
                f"number, got {floor!r}"
            )
        return cls(raw=raw)

    def enabled(self, feature: str) -> bool:
        return bool(self.raw["features"].get(feature, False))

    @property
    def selectors(self) -> list[dict]:
        return self.raw["sweep"].get("selectors", DEFAULT_SELECTORS)

    @property
    def min_marked_height_ft(self) -> float:
        return float(self.raw["sweep"].get("min_marked_height_ft", 200.0))

    @property
    def exclude(self) -> list[str]:
        """OSM ids the sweep must never propose - see docs/data-sources.md.

        This is how "the sim already lights that one" gets recorded once
        instead of being re-litigated on every re-sweep.
        """
        return [e for e in self.raw["sweep"].get("exclude", []) if not str(e).startswith("$")]

    @property
    def max_total_objects(self) -> int:
        return int(self.raw["limits"]["max_total_objects"])

    @property
    def warn_total_objects(self) -> int:
        return int(self.raw["limits"]["warn_total_objects"])

    @property
    def image_complexity(self) -> str:
        return str(self.raw["placement"].get("image_complexity", "NORMAL"))

    @property
    def snap_to_ground(self) -> bool:
        return bool(self.raw["placement"].get("snap_to_ground", True))

    @property
    def error_on_unresolved(self) -> bool:
        return self.raw["bindings"].get("on_unresolved") == "error"

    @property
    def scenery_dir(self) -> Path:
        return REPO_ROOT / self.raw["output"]["scenery_dir"]

    @property
    def preview_dir(self) -> Path:
        return REPO_ROOT / self.raw["output"].get("preview_dir", "build/preview")

    @property
    def write_preview(self) -> bool:
        return bool(self.raw["output"].get("write_geojson_preview", False))


def load_all(root: Path = REPO_ROOT) -> dict:
    """Load every data and config file the build needs, in one place."""
    return {
        "region": Region.load(root / "data" / "region.json"),
        "bindings": Bindings.load(root / "config" / "library_bindings.json"),
        "profile": BuildProfile.load(root / "config" / "build_profile.json"),
        "package": load_json(root / "config" / "package.json"),
        "obstructions": load_json(root / "data" / "obstructions.json"),
    }
