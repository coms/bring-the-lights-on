"""Emitters for the MSFS scenery XML that `fspackagetool` compiles into BGL.

The shape of a scenery file is:

    <FSData version="9.0">
      <SceneryObject lat=".." lon=".." alt=".." ...>
        <LibraryObject name="{GUID}" scale="1.0"/>
      </SceneryObject>
      ...
    </FSData>

Output is built as text rather than through ElementTree so that formatting is
byte-stable between runs. These files land in version control and a diff that
only says "everything moved" because an XML writer reordered attributes is
worse than useless.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Iterable, Optional

FSDATA_VERSION = "9.0"

# Placement altitude below this (metres) is treated as "on the ground" and the
# object gets snapped, rather than floating a few centimetres over the terrain.
GROUND_EPSILON_M = 0.05


@dataclass(frozen=True)
class SceneryObject:
    """One placed object, ready to be written out.

    `payload` is the child element: a library object or an effect. `source_id`
    is carried purely so the build report and the GeoJSON preview can say which
    data entry produced this thing.
    """

    lat: float
    lon: float
    payload: "Payload"
    alt_m: float = 0.0
    heading: float = 0.0
    pitch: float = 0.0
    bank: float = 0.0
    snap_to_ground: bool = True
    snap_to_normal: bool = False
    image_complexity: str = "NORMAL"
    source_id: str = ""
    kind: str = ""

    def to_xml(self, indent: str = "  ") -> str:
        # An object placed above ground level must not be snapped down to it.
        # Every light in this package except a ground-level one is exactly that
        # case, so this is the line that keeps beacons on top of the mast.
        snap = self.snap_to_ground and abs(self.alt_m) < GROUND_EPSILON_M
        attrs = [
            f'lat="{self.lat:.7f}"',
            f'lon="{self.lon:.7f}"',
            f'alt="{self.alt_m:.2f}"',
            'altitudeIsAgl="TRUE"',
            f'pitch="{self.pitch:.2f}"',
            f'bank="{self.bank:.2f}"',
            f'heading="{self.heading:.2f}"',
            f'imageComplexity="{self.image_complexity}"',
            f'snapToGround="{_bool(snap)}"',
            f'snapToNormal="{_bool(self.snap_to_normal)}"',
        ]
        head = f"{indent}<SceneryObject {' '.join(attrs)}>"
        body = self.payload.to_xml(indent + "  ")
        tail = f"{indent}</SceneryObject>"
        return "\n".join([head, body, tail])


class Payload:
    """Base class for the child element inside a <SceneryObject>."""

    def to_xml(self, indent: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class LibraryObject(Payload):
    guid: str
    scale: float = 1.0

    def to_xml(self, indent: str) -> str:
        return f'{indent}<LibraryObject name="{_attr(self.guid)}" scale="{self.scale:.6f}"/>'


@dataclass(frozen=True)
class Effect(Payload):
    effect_name: str
    params: str = ""

    def to_xml(self, indent: str) -> str:
        return (
            f'{indent}<Effect effectName="{_attr(self.effect_name)}" '
            f'effectParams="{_attr(self.params)}"/>'
        )


@dataclass
class SceneryFile:
    """A single .xml destined for PackageSources/scenery/."""

    filename: str
    title: str
    description: str = ""
    objects: list[SceneryObject] = field(default_factory=list)

    def add(self, obj: SceneryObject) -> None:
        self.objects.append(obj)

    def extend(self, objs: Iterable[SceneryObject]) -> None:
        self.objects.extend(objs)

    def __len__(self) -> int:
        return len(self.objects)

    def render(self, *, generator_note: str = "") -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', ""]
        lines.append("<!--")
        lines.append(f"  {self.title}")
        if self.description:
            for para in self.description.splitlines():
                lines.append(f"  {para}")
        lines.append("")
        lines.append("  GENERATED FILE - do not edit by hand.")
        lines.append("  Edit data/*.json or config/*.json and re-run `make build`.")
        if generator_note:
            lines.append(f"  {generator_note}")
        lines.append(f"  Objects: {len(self.objects)}")
        lines.append("-->")
        lines.append("")
        lines.append(f'<FSData version="{FSDATA_VERSION}">')

        # Sorting keeps the file diff-stable regardless of the order the
        # structures happened to come back from Overpass in.
        for obj in sorted(self.objects, key=_sort_key):
            lines.append(obj.to_xml())

        lines.append("</FSData>")
        lines.append("")
        return "\n".join(lines)


def _sort_key(obj: SceneryObject) -> tuple:
    return (obj.source_id, obj.kind, round(obj.lat, 7), round(obj.lon, 7), round(obj.alt_m, 2))


def _bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _attr(value: Optional[str]) -> str:
    return html.escape(value or "", quote=True)
