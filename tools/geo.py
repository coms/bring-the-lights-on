"""Geodesy helpers for placing scenery objects on the WGS84 ellipsoid.

Everything here works in decimal degrees and metres. At the scale a single
sweep area covers - tens of kilometres - a spherical earth model is accurate to
well under a metre, far below the placement precision of OpenStreetMap data, so
we use the mean earth radius throughout.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# IUGG mean radius of the WGS84 ellipsoid.
EARTH_RADIUS_M = 6371008.8


class Point(NamedTuple):
    """A geographic position in decimal degrees."""

    lat: float
    lon: float

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"({self.lat:.6f}, {self.lon:.6f})"


def normalize_heading(deg: float) -> float:
    """Wrap a heading into [0, 360)."""
    return deg % 360.0


def haversine_m(a: Point, b: Point) -> float:
    """Great-circle distance between two points, in metres."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def destination(origin: Point, bearing_deg: float, distance_m: float) -> Point:
    """Point reached by travelling `distance_m` from `origin` on `bearing_deg`."""
    if distance_m == 0.0:
        return origin
    ang = distance_m / EARTH_RADIUS_M
    brg = math.radians(bearing_deg)
    lat1, lon1 = math.radians(origin.lat), math.radians(origin.lon)

    sin_lat2 = math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg)
    lat2 = math.asin(max(-1.0, min(1.0, sin_lat2)))
    y = math.sin(brg) * math.sin(ang) * math.cos(lat1)
    x = math.cos(ang) - math.sin(lat1) * sin_lat2
    lon2 = lon1 + math.atan2(y, x)

    # Keep longitude in [-180, 180).
    lon_deg = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return Point(math.degrees(lat2), lon_deg)


def bbox_contains(bbox: dict, point: Point, *, margin_deg: float = 0.0) -> bool:
    """Whether a point falls inside a `{south,west,north,east}` box."""
    return (
        bbox["south"] - margin_deg <= point.lat <= bbox["north"] + margin_deg
        and bbox["west"] - margin_deg <= point.lon <= bbox["east"] + margin_deg
    )


def feet_to_metres(feet: float) -> float:
    return feet * 0.3048


def metres_to_feet(metres: float) -> float:
    return metres / 0.3048
