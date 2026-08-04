"""Preview output, so you can check placement without launching the sim.

Writes two things into build/preview/:

  objects.geojson - every placed object, with its source id and kind. Drop it
                    on geojson.io, or open it in QGIS, to check the beacons
                    landed on the structures they claim to.
  plan.svg        - a self-contained plan view. No tiles, no network, no
                    dependencies: open it in any browser.

A plan view of obstruction lighting is sparse by nature - a few dozen points
rather than a city grid - so what it is good for is spotting the one beacon
that landed in the river.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

from .fsxml import SceneryFile

# Plan view colours, chosen to read against the dark background the way the
# fixtures themselves will.
KIND_STYLE = {
    "obstruction_beacon": ("#ff4d4d", 3.0),
    "obstruction_side_light": ("#ff8080", 1.2),
}
DEFAULT_STYLE = ("#cccccc", 1.0)

SVG_WIDTH = 1600
SVG_MARGIN = 40


def write_preview(files: Iterable[SceneryFile], data: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    objects = [obj for f in files for obj in f.objects]

    (out_dir / "objects.geojson").write_text(
        json.dumps(_geojson(objects), indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "plan.svg").write_text(_svg(objects, data), encoding="utf-8")


def _geojson(objects: list) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(o.lon, 7), round(o.lat, 7)]},
                "properties": {
                    "source_id": o.source_id,
                    "kind": o.kind,
                    "agl_m": round(o.alt_m, 2),
                },
            }
            for o in objects
        ],
    }


def _svg(objects: list, data: dict) -> str:
    if not objects:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>\n'

    lats = [o.lat for o in objects]
    lons = [o.lon for o in objects]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)

    # Equirectangular with a cos(lat) correction: over one region's extent it
    # is visually indistinguishable from a proper projection, and it keeps the
    # file dependency-free.
    mid_lat = math.radians((south + north) / 2)
    lon_scale = math.cos(mid_lat)
    span_x = max((east - west) * lon_scale, 1e-9)
    span_y = max(north - south, 1e-9)

    inner_w = SVG_WIDTH - 2 * SVG_MARGIN
    inner_h = inner_w * span_y / span_x
    height = int(inner_h + 2 * SVG_MARGIN)

    def project(lat: float, lon: float) -> tuple[float, float]:
        x = SVG_MARGIN + ((lon - west) * lon_scale / span_x) * inner_w
        y = SVG_MARGIN + (1 - (lat - south) / span_y) * inner_h
        return x, y

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{height}" '
        f'viewBox="0 0 {SVG_WIDTH} {height}">',
        f'<rect width="{SVG_WIDTH}" height="{height}" fill="#080c14"/>',
        "<g>",
    ]

    # Group by kind so the SVG stays small and the brightest things draw last.
    order = sorted(set(o.kind for o in objects), key=lambda k: KIND_STYLE.get(k, DEFAULT_STYLE)[1])
    for kind in order:
        color, radius = KIND_STYLE.get(kind, DEFAULT_STYLE)
        parts.append(f'<g fill="{color}" fill-opacity="0.85">')
        for obj in objects:
            if obj.kind != kind:
                continue
            x, y = project(obj.lat, obj.lon)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}"/>')
        parts.append("</g>")

    parts.append("</g>")

    region_name = data["region"].name if "region" in data else ""
    parts.append(
        f'<text x="{SVG_MARGIN}" y="{SVG_MARGIN - 14}" fill="#8899aa" '
        f'font-family="monospace" font-size="13">'
        f'{region_name} - {len(objects):,} objects - '
        f'{south:.4f},{west:.4f} to {north:.4f},{east:.4f}</text>'
    )
    legend_y = height - SVG_MARGIN + 6
    x_cursor = SVG_MARGIN
    for kind in order:
        color, _ = KIND_STYLE.get(kind, DEFAULT_STYLE)
        parts.append(f'<circle cx="{x_cursor}" cy="{legend_y - 4}" r="4" fill="{color}"/>')
        parts.append(
            f'<text x="{x_cursor + 10}" y="{legend_y}" fill="#8899aa" '
            f'font-family="monospace" font-size="11">{kind}</text>'
        )
        x_cursor += 22 + 7 * len(kind)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
