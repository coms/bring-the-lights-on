# Data sources, accuracy and licensing

## Where the data comes from

Everything in `data/obstructions.json` is produced by `python -m tools.sweep`,
which queries the [Overpass API](https://overpass-api.de/) for structures inside
the areas declared in `data/region.json`. Each entry records its origin:

```json
"source": "openstreetmap way/38472913"
```

Nothing is hand-digitized, and nothing is invented. An entry with no `source`
field was added by hand, and the validator warns about it — not because that is
wrong, but because provenance that is not written down stops existing the moment
you forget it.

## What the sweep asks for

| Selector | Catches |
|---|---|
| `man_made=mast` | Guyed and free-standing broadcast and comms masts |
| `man_made=tower` + `tower:type=communication` | The same structures, tagged the other way |
| `man_made=chimney` | Industrial stacks |

Masts are tagged inconsistently between `mast` and `tower`, so both are asked
for; taking only one misses real structures.

**Buildings and wind turbines are deliberately not swept.** They are the obvious
things to add and the two worst things to add blind — see "Duplicate lighting"
below. Add them in `sweep.selectors` once you have checked your region in the
sim, not before.

## Accuracy, and what this is not

**This is scenery, not an obstacle database. Do not fly off it.**

- **Positions** are OSM node or way-centre coordinates. Good — usually within a
  few metres — but contributed, not surveyed.
- **Heights** are OSM `height`, `tower:height` or `building:height` tags. These
  are structure heights in the contributor's best judgement. They are not
  AGL/AMSL obstacle data, they are not verified against any authority's obstacle
  file, and some of them are wrong.
- **Coverage** is whatever OSM has. A real mast that nobody has mapped will not
  appear, and the sweep cannot tell you about it.
- **Marking colour** is not in OSM at all. Every new structure is proposed as
  red, which is the more common scheme but is a guess for any individual
  structure.

### Missing heights are skipped, not guessed

A structure whose height OSM does not record is left out entirely, and reported:

```
  3 with no height in OSM - skipped rather than guessed:
    Rocky Hill tower                          way/38472913
```

The alternative — filling in a regional default — is how you end up with a
beacon floating 100 ft above a mast, or buried inside it. Neither is visible
from the code, only from the cockpit. If you know the real height, add the entry
by hand, or better, add the height to OSM so everyone gets it.

## Duplicate lighting

**The one thing that will make this package look worse than not having it.**

MSFS 2024 already lights some tall structures itself: wind turbines have their
own beacons, and photogrammetry and autogen towers sometimes come with lighting
baked in. A second beacon a few metres from the sim's own reads as a smear or a
double-flash, which is worse than a structure that is simply unlit.

The sweep cannot detect this. Only you can, in the sim. When you find one:

```json
"sweep": {
  "exclude": ["way/38472913", "node/1029384756"]
}
```

in `config/build_profile.json`. The exclude list is checked on every sweep, so
the decision survives a re-sweep instead of being made again every time. This is
also why the shipped selectors are the three classes least likely to collide —
mast, communication tower and chimney are where stock coverage is thinnest.

## Re-sweeping

`python -m tools.sweep --apply` **replaces** the whole `obstructions` list.
Anything hand-added is lost. Two things survive:

- **Exclusions**, because they live in `config/build_profile.json`.
- **Marking choices**, because a swept structure landing within 200 m of an
  existing entry inherits that entry's `marking`.

A sweep that returns nothing changes nothing. Thin OSM coverage — or an Overpass
outage — is not a reason to delete what you already have, so an empty result
leaves the file alone and says so.

## Licensing

OpenStreetMap data is © OpenStreetMap contributors, licensed under the
[Open Database License](https://opendatacommons.org/licenses/odbl/). Once you
run a sweep, the contents of `data/obstructions.json` are derived from it.

If you redistribute the package, or this repository with swept data in it, the
ODbL's attribution and share-alike terms apply to that data. In practice: credit
OpenStreetMap in your package description, and keep derived data available under
the same terms. The toolchain itself is MIT and unaffected.

## Being a good Overpass citizen

Overpass is a free shared service run on donated hardware. `tools/osm.py` sends
one query at a time with a three-second gap, doubles the gap for the rest of the
run once an instance throttles it, and takes its retry timing from the server's
own `Retry-After` header rather than guessing.

If you are sweeping a large region, raise `--gap` rather than lowering it. If one
mirror is busy, `--endpoint kumi` (or `fr`, or `ru`) moves to another rather than
hammering the first.
