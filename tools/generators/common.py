"""Shared placement helpers and the context object passed to the generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from ..fsxml import SceneryObject
from ..geo import Point, destination, feet_to_metres, normalize_heading
from ..model import Bindings, BuildProfile, DataError, Region


@dataclass
class Context:
    """Everything a generator needs, assembled once by the build driver."""

    region: Region
    bindings: Bindings
    profile: BuildProfile
    data: dict
    # Objects rejected for falling outside the declared region, by source id.
    out_of_region: list[tuple[str, Point]] = field(default_factory=list)
    # Fixtures requested but not bound, by source id.
    skipped: dict[str, int] = field(default_factory=dict)

    def note_skip(self, source_id: str) -> None:
        self.skipped[source_id] = self.skipped.get(source_id, 0) + 1

    def place(
        self,
        fixture: str,
        point: Point,
        *,
        source_id: str,
        kind: str,
        agl_ft: float = 0.0,
        heading: float = 0.0,
    ) -> Optional[SceneryObject]:
        """Build one scenery object, or None if it cannot or should not exist.

        Returns None when the fixture has no binding yet, and drops - with a
        record - anything that lands outside the package's declared region.
        """
        if not self.region.contains(point):
            self.out_of_region.append((source_id, point))
            return None

        payload = self.bindings.payload(fixture, context=source_id)
        if payload is None:
            self.note_skip(source_id)
            return None

        return SceneryObject(
            lat=point.lat,
            lon=point.lon,
            alt_m=feet_to_metres(agl_ft),
            heading=normalize_heading(heading),
            payload=payload,
            snap_to_ground=self.profile.snap_to_ground,
            image_complexity=self.profile.image_complexity,
            source_id=source_id,
            kind=kind,
        )


def ring(
    center: Point,
    count: int,
    radius_m: float,
    *,
    start_bearing: float = 0.0,
    aim: str = "inward",
) -> Iterator[tuple[Point, float]]:
    """Yield `count` positions evenly spaced on a circle about `center`.

    The heading returned points at the centre for `aim="inward"` or away from
    it for `aim="outward"`. Side lights ring the structure they mark, so a
    radius of zero - one light, dead centre - is legitimate and common.
    """
    if count <= 0:
        return
    if radius_m < 0:
        raise DataError(f"ring radius must not be negative, got {radius_m}")

    step = 360.0 / count
    for i in range(count):
        bearing = normalize_heading(start_bearing + i * step)
        pos = destination(center, bearing, radius_m)
        heading = normalize_heading(bearing + 180.0) if aim == "inward" else bearing
        yield pos, heading


def resolve_point(entry: dict, context: str) -> Point:
    """Get a position from an obstruction entry."""
    if "lat" not in entry or "lon" not in entry:
        raise DataError(f"{context}: needs both lat and lon")

    lat, lon = float(entry["lat"]), float(entry["lon"])
    if not -90.0 <= lat <= 90.0:
        raise DataError(f"{context}: out-of-range latitude {lat}")
    if not -180.0 <= lon <= 180.0:
        raise DataError(f"{context}: out-of-range longitude {lon}")
    return Point(lat, lon)


__all__ = ["Context", "resolve_point", "ring"]
