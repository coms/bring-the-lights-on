# Changelog

## 0.1.0 — unreleased

First cut. Obstruction lighting for tall structures, generated from
OpenStreetMap for any region.

The toolchain grew out of [night-harford](https://github.com/coms/night-harford),
where the same marking machinery ran on hand-curated Hartford data. What is new
here is that the data comes from a sweep rather than from a person, and that the
region is a configuration value rather than the point of the package.

### Added

- `tools/sweep.py` — searches OpenStreetMap for tall structures inside every
  area declared in `data/region.json` and proposes obstruction entries.
  Selectors, the marking floor and the exclusion list are configuration.
- `tools/osm.py` — Overpass client. One query at a time, three-second gap,
  gap doubles for the rest of the run once throttled, retry timing taken from
  the server's `Retry-After` rather than guessed.
- `tools/generators/obstructions.py` — top beacon plus rings of side lights at
  the scheme's interval below it. Red and white schemes, both data-driven.
- Build driver, validator, task runner, packaging and preview.
- 184 tests, all offline.

### Decisions worth knowing

- **A structure whose height OSM does not record is skipped, not defaulted.** A
  beacon at a guessed altitude floats above the mast or sits inside it. Skipped
  structures are reported with their OSM id so they can be added by hand.
- **Masts, communication towers and chimneys only.** Buildings and wind turbines
  are the obvious next step and the two worst things to sweep blind, because the
  sim already lights many of them. `sweep.selectors` opens them up once you have
  checked your region.
- **`sweep.exclude` survives a re-sweep.** Whether the sim already lights a
  structure can only be judged in the sim, so that judgement is recorded once
  rather than made again on every sweep.
- **An empty sweep result changes nothing.** Thin OSM coverage, or an Overpass
  outage, is not a reason to delete what you already have.
- **Two fixtures ship unbound.** A fabricated GUID builds cleanly and draws
  nothing, with no error to explain why.

### Known gaps

- The shipped `data/obstructions.json` is empty; run a sweep to populate it.
- Marking schemes encode FAA AC 70/7460-1. ICAO Annex 14 regions need the
  schemes and `sweep.min_marked_height_ft` edited — no code changes, but no
  presets either.
- Compiling to BGL is untested here: it needs Windows and the MSFS SDK.
