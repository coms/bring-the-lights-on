"""Tests for the OSM sweep.

The sweep is where this package differs most from the Hartford original it grew
out of, and the difference is a judgement call worth pinning down: a structure
whose height OSM does not record is SKIPPED rather than given a default. These
tests exist so nobody quietly reinstates the fallback.
"""

from __future__ import annotations

import pytest

from tools.geo import Point
from tools.sweep import MARKING_CARRYOVER_M, build_entries


def structure(lat=41.80, lon=-72.80, height_m=100.0, name="Test mast", osm_id="node/1"):
    """One OSM structure record, as tools.osm.fetch_structures returns them."""
    return {
        "point": Point(lat, lon),
        "name": name,
        "operator": None,
        "height_m": height_m,
        "osm_id": osm_id,
    }


class TestHeightIsRequired:
    def test_a_structure_with_no_height_is_skipped(self):
        entries, no_height, _ = build_entries(
            [structure(height_m=None)], [], min_height_ft=200.0
        )
        assert entries == []
        assert len(no_height) == 1

    def test_the_skipped_structure_is_reported_with_its_osm_id(self):
        _, no_height, _ = build_entries(
            [structure(height_m=None, osm_id="way/99")], [], min_height_ft=200.0
        )
        assert no_height[0]["osm_id"] == "way/99"

    def test_a_structure_with_a_height_is_kept(self):
        entries, no_height, _ = build_entries(
            [structure(height_m=100.0)], [], min_height_ft=200.0
        )
        assert len(entries) == 1
        assert no_height == []

    def test_heights_convert_to_feet(self):
        entries, _, _ = build_entries([structure(height_m=100.0)], [], min_height_ft=200.0)
        assert entries[0]["height_ft"] == 328

    def test_no_entry_ever_carries_an_assumed_height(self):
        entries, _, _ = build_entries(
            [structure(height_m=None), structure(height_m=120.0, osm_id="node/2")],
            [], min_height_ft=200.0,
        )
        assert len(entries) == 1
        assert all("$height_note" not in entry for entry in entries)


class TestMarkingFloor:
    def test_a_structure_below_the_floor_is_left_unlit(self):
        # 50 m is about 164 ft, below the 200 ft FAA floor.
        entries, _, too_short = build_entries(
            [structure(height_m=50.0)], [], min_height_ft=200.0
        )
        assert entries == []
        assert len(too_short) == 1

    def test_a_structure_above_the_floor_is_lit(self):
        entries, _, too_short = build_entries(
            [structure(height_m=70.0)], [], min_height_ft=200.0
        )
        assert len(entries) == 1
        assert too_short == []

    def test_the_floor_is_configurable(self):
        # The same structure, under an ICAO-style 45 m floor.
        entries, _, _ = build_entries([structure(height_m=50.0)], [], min_height_ft=147.0)
        assert len(entries) == 1

    def test_the_floor_and_the_missing_height_are_reported_separately(self):
        entries, no_height, too_short = build_entries(
            [structure(height_m=None, osm_id="node/1"),
             structure(height_m=10.0, osm_id="node/2"),
             structure(height_m=200.0, osm_id="node/3")],
            [], min_height_ft=200.0,
        )
        assert len(entries) == 1
        assert len(no_height) == 1
        assert len(too_short) == 1


class TestMarkingCarryover:
    def test_a_new_structure_defaults_to_red(self):
        entries, _, _ = build_entries([structure(height_m=100.0)], [], min_height_ft=200.0)
        assert entries[0]["marking"] == "red"

    def test_a_structure_on_top_of_an_existing_entry_inherits_its_marking(self):
        existing = [{"id": "obs_001", "lat": 41.80, "lon": -72.80, "marking": "white"}]
        entries, _, _ = build_entries(
            [structure(lat=41.80, lon=-72.80, height_m=100.0)], existing, min_height_ft=200.0
        )
        assert entries[0]["marking"] == "white"

    def test_a_distant_existing_entry_does_not_donate_its_marking(self):
        existing = [{"id": "obs_001", "lat": 41.90, "lon": -72.90, "marking": "white"}]
        entries, _, _ = build_entries(
            [structure(lat=41.80, lon=-72.80, height_m=100.0)], existing, min_height_ft=200.0
        )
        assert entries[0]["marking"] == "red"

    def test_the_nearest_existing_entry_wins(self):
        existing = [
            {"id": "far", "lat": 41.8010, "lon": -72.80, "marking": "white"},
            {"id": "near", "lat": 41.8001, "lon": -72.80, "marking": "red"},
        ]
        entries, _, _ = build_entries(
            [structure(lat=41.80, lon=-72.80, height_m=100.0)], existing, min_height_ft=200.0
        )
        assert entries[0]["marking"] == "red"

    def test_an_existing_entry_with_no_coordinates_is_ignored(self):
        existing = [{"id": "obs_001", "marking": "white"}]
        entries, _, _ = build_entries(
            [structure(height_m=100.0)], existing, min_height_ft=200.0
        )
        assert entries[0]["marking"] == "red"

    def test_the_carryover_radius_is_what_it_claims(self):
        assert MARKING_CARRYOVER_M == 200.0


class TestExclude:
    def test_an_excluded_structure_is_not_proposed(self):
        entries, no_height, too_short = build_entries(
            [structure(height_m=100.0, osm_id="way/42")],
            [], min_height_ft=200.0, exclude=["way/42"],
        )
        assert entries == []
        # Excluded is a decision already made, not a rejection to report again.
        assert no_height == []
        assert too_short == []

    def test_other_structures_survive_an_exclusion(self):
        entries, _, _ = build_entries(
            [structure(height_m=100.0, osm_id="way/42"),
             structure(height_m=100.0, osm_id="way/43", name="Keeper")],
            [], min_height_ft=200.0, exclude=["way/42"],
        )
        assert [e["name"] for e in entries] == ["Keeper"]

    def test_an_exclusion_survives_a_re_sweep(self):
        # The whole point: the sim-checked decision is not re-litigated when
        # the same structure comes back from OSM a second time.
        found = [structure(height_m=100.0, osm_id="way/42")]
        first, _, _ = build_entries(found, [], min_height_ft=200.0, exclude=["way/42"])
        second, _, _ = build_entries(found, first, min_height_ft=200.0, exclude=["way/42"])
        assert first == [] and second == []

    def test_no_exclusions_is_the_same_as_an_empty_list(self):
        found = [structure(height_m=100.0)]
        assert build_entries(found, [], min_height_ft=200.0, exclude=None)[0] == \
            build_entries(found, [], min_height_ft=200.0, exclude=[])[0]


class TestEntryShape:
    def test_ids_are_sequential_and_stable(self):
        entries, _, _ = build_entries(
            [structure(lat=41.80, height_m=100.0, osm_id="node/1"),
             structure(lat=41.81, height_m=100.0, osm_id="node/2")],
            [], min_height_ft=200.0,
        )
        assert [e["id"] for e in entries] == ["obs_001", "obs_002"]

    def test_ids_skip_no_numbers_when_a_structure_is_rejected(self):
        # A rejected structure must not leave a hole in the numbering.
        entries, _, _ = build_entries(
            [structure(lat=41.82, height_m=100.0, osm_id="node/1"),
             structure(lat=41.81, height_m=None, osm_id="node/2"),
             structure(lat=41.80, height_m=100.0, osm_id="node/3")],
            [], min_height_ft=200.0,
        )
        assert [e["id"] for e in entries] == ["obs_001", "obs_002"]

    def test_output_is_ordered_north_to_south(self):
        entries, _, _ = build_entries(
            [structure(lat=41.70, height_m=100.0, osm_id="node/1", name="South"),
             structure(lat=41.90, height_m=100.0, osm_id="node/2", name="North")],
            [], min_height_ft=200.0,
        )
        assert [e["name"] for e in entries] == ["North", "South"]

    def test_an_unnamed_structure_gets_a_placeholder(self):
        entries, _, _ = build_entries(
            [structure(height_m=100.0, name=None)], [], min_height_ft=200.0
        )
        assert entries[0]["name"] == "Structure 1"

    def test_provenance_records_the_osm_id(self):
        entries, _, _ = build_entries(
            [structure(height_m=100.0, osm_id="way/7")], [], min_height_ft=200.0
        )
        assert entries[0]["source"] == "openstreetmap way/7"

    def test_entries_are_marked_for_automatic_levels(self):
        entries, _, _ = build_entries([structure(height_m=100.0)], [], min_height_ft=200.0)
        assert entries[0]["auto_levels"] is True
        assert entries[0]["top_beacons"] == 1

    def test_coordinates_are_rounded_to_six_places(self):
        entries, _, _ = build_entries(
            [structure(lat=41.8000004999, lon=-72.7999995, height_m=100.0)],
            [], min_height_ft=200.0,
        )
        assert entries[0]["lat"] == 41.8
        assert len(str(entries[0]["lat"]).split(".")[-1]) <= 6

    def test_an_empty_sweep_produces_nothing_rather_than_failing(self):
        assert build_entries([], [], min_height_ft=200.0) == ([], [], [])
