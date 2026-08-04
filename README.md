# Bring The Lights On

FAA-style obstruction lighting on tall structures for **Microsoft Flight
Simulator 2024**, generated from OpenStreetMap for any region you point it at.

Masts, communication towers and chimneys, marked the way the regulations
describe: a flashing beacon on top and rings of steady side lights every 150 ft
below it. At night, correctly marked obstacles are how you read vertical
development from the cockpit — a ridge of broadcast masts is the first thing you
pick up on the approach, and an unlit one is a hole in the picture.

You give it a bounding box. It sweeps OSM, proposes the structures worth
lighting, and builds the scenery.

---

## Read this first

Two things are deliberately not automatic, because both are judgement calls that
only you can make.

**The package decides *where* every light goes. It does not ship the 3D models
and effects that decide *what* each light looks like.** Those are bound to a
model library you already have, in `config/library_bindings.json`. Out of the
box one of three fixtures is bound, so a fresh clone builds and installs
successfully and renders the white strobes and nothing else. That is on purpose:
a fabricated GUID produces a package that compiles without complaint and then
draws nothing at all, with no error to tell you why.

```
$ python -m tools.tasks bindings
1/3 fixture bindings resolved
```

Filling in the other two is a ten-minute job with the sim's Object Inspector
open — start with [docs/bindings.md](docs/bindings.md).

**The sweep proposes; you verify.** MSFS lights some tall structures itself, and
a doubled or slightly offset beacon reads worse than no beacon at all. Check
your region in the sim and record anything already lit in `sweep.exclude` — see
[docs/data-sources.md](docs/data-sources.md).

---

## Quick start

Needs Python 3.11+ and nothing else. Works on Windows, macOS and Linux:

```
python -m tools.tasks sweep      # find tall structures in OSM (needs network)
python -m tools.tasks build      # generate scenery XML from data/ and config/
python -m tools.tasks check      # validate + test + dry run
python -m tools.tasks bindings   # see what still needs a model or effect
python -m tools.tasks preview    # build, plus an SVG plan view for your browser
python -m tools.tasks help       # every task
```

`make build`, `make check` and so on work too — on Windows through the bundled
`make.cmd`, elsewhere through the Makefile. Both are thin wrappers around the
same task runner. **Windows has no `make` of its own**, so if you have moved the
repository or are calling from another directory, use the `python -m tools.tasks`
form.

Then, with MSFS 2024 and its SDK installed:

```
fspackagetool.exe bring-the-lights-on.xml
```

and copy `Packages\coms-bring-the-lights-on\` into your Community folder. Full
instructions in [docs/building.md](docs/building.md).

Generating the XML needs Python. Compiling to a `.bgl` needs Windows and the SDK.

---

## Pointing it at your region

Everything visible is data-driven. Edit `data/region.json`:

```json
{
  "name": "Greater Hartford, CT",
  "region": { "south": 41.640, "west": -72.870, "north": 41.960, "east": -72.530 },
  "search_areas": {
    "metacomet_ridge": { "south": 41.750, "west": -72.830, "north": 41.870, "east": -72.760 }
  },
  "reference_point": { "lat": 41.766390, "lon": -72.673060 }
}
```

`region` is the hard boundary — anything generated outside it is a build error,
which is the cheapest guard against a dropped minus sign putting a beacon in
western China. `search_areas` are the boxes the sweep actually searches; declare
a few narrow ones around the places that carry tall structures rather than one
box over a whole metropolitan area, or you will pay in objects for every chimney
on every apartment block. Remove the block entirely to sweep the whole region.

It ships configured for greater Hartford, Connecticut, because that is a region
whose answer is already known — run a sweep there and you can see what a correct
result looks like before pointing it somewhere you cannot check.

```
$ python -m tools.sweep --apply
  metacomet_ridge: sweeping 41.75,-72.83 .. 41.87,-72.76 ... 9 feature(s)
```

## How it fits together

```
data/region.json     where this package applies, and where to search
data/obstructions.json   what to light          (swept, then hand-checked)
config/*.json        marking floor, selectors, what each light looks like
      │
      │  tools/  — geodesy, Overpass sweep, generator, validation
      ▼
PackageSources/scenery/*.xml     MSFS FSData scenery XML  (generated, committed)
      │
      │  fspackagetool.exe  (Windows + MSFS SDK)
      ▼
Packages/coms-bring-the-lights-on/     installable package
```

The generator never touches disk and never touches the network, so the whole
placement pipeline is directly testable — there are 184 tests over the geodesy,
the Overpass client, the sweep and the generator, and every one of them runs
offline.

## Two flavours of marking

AC 70/7460-1 allows a structure to be marked with red lights or with
medium-intensity white strobes, and both are in common use. The white scheme is
not a colour swap on the red one — it strobes at every level including the top,
spaces those levels 250 ft apart rather than 150, and carries three units per
level rather than four. Both live in `data/obstructions.json`, and nothing in
`tools/` hard-codes either.

**Outside the United States those numbers are wrong.** ICAO Annex 14 marks from
45 m rather than 200 ft and spaces levels differently. Edit the schemes and
`sweep.min_marked_height_ft`; the code does not care which standard you encode.

## What OSM can and cannot tell you

The sweep asks OSM for `man_made=mast`, `man_made=tower` with
`tower:type=communication`, and `man_made=chimney`. Those three are the
best-tagged classes and the least likely to collide with lighting the sim
already draws.

**A structure whose height OSM does not record is skipped, not given a default.**
A beacon at a guessed altitude floats above the mast or sits buried inside it,
and this is scenery people fly at. Skipped structures are listed with their OSM
id so you can add the ones you care about by hand:

```
  3 with no height in OSM - skipped rather than guessed:
    Rocky Hill tower                     way/38472913
    Add a height to OSM, or add the entry to data/obstructions.json by hand.
```

Marking colour is the other thing OSM cannot supply — it records that a
structure is there, not what the authority had it painted or lit with. New
structures are proposed as red; a swept structure landing on an existing entry
inherits whatever you chose for it.

**This is scenery, not an obstacle database.** Heights are contributed tags, not
surveyed AGL/AMSL obstacle data. Do not fly off it.

## Tuning

Object count is the frame-rate lever. In `config/build_profile.json`:

```json
"sweep": { "min_marked_height_ft": 200.0 }
```

Every marked structure costs one beacon plus a ring of four side lights per
150 ft below the top, so a 500 ft mast is 13 objects and raising the floor thins
the package fast.

## Contributing

`python -m tools.tasks check` (or `make check`) before committing — it runs the
validator, the tests and a dry-run build. The validator will tell you, by id and
field, exactly which data entry is wrong.

## Licence

MIT — see [LICENSE](LICENSE).

Data pulled by `tools/sweep.py` is derived from OpenStreetMap, © OpenStreetMap
contributors, licensed under the ODbL. Attribution and share-alike terms apply
to that data if you redistribute it. Details in
[docs/data-sources.md](docs/data-sources.md).

Not affiliated with Microsoft, Asobo Studio, the FAA, ICAO, or any of the
organisations whose structures are lit.
