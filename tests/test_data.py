"""Checks over the shipped data and config files themselves.

These are the tests that catch a bad edit to data/ or config/ - the files most
likely to be changed by someone who is not reading tools/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.geo import Point
from tools.model import (
    Bindings,
    BuildProfile,
    DataError,
    Region,
    load_all,
    load_json,
)
from tools.validate import validate_data

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def data():
    return load_all()


class TestEverythingLoads:
    def test_load_all_succeeds(self, data):
        assert set(data) == {"region", "bindings", "profile", "package", "obstructions"}

    def test_the_validator_reports_no_errors(self):
        assert validate_data().errors == []

    def test_every_json_file_is_valid_json(self):
        for path in sorted(REPO_ROOT.glob("**/*.json")):
            if "build" in path.parts or "Packages" in path.parts:
                continue
            json.loads(path.read_text(encoding="utf-8"))


class TestRegion:
    def test_the_region_box_is_the_right_way_up(self, data):
        box = data["region"].box
        assert box["south"] < box["north"]
        assert box["west"] < box["east"]

    def test_the_reference_point_is_inside_the_region(self, data):
        assert data["region"].contains(data["region"].reference)

    def test_every_search_area_sits_inside_the_region(self, data):
        region = data["region"]
        for name, area in region.search_areas.items():
            for lat in (area["south"], area["north"]):
                for lon in (area["west"], area["east"]):
                    assert region.contains(Point(lat, lon)), name

    def test_comment_keys_are_not_treated_as_search_areas(self, data):
        assert not any(name.startswith("$") for name in data["region"].search_areas)

    def test_a_named_search_area_can_be_looked_up(self, data):
        name = next(iter(data["region"].search_areas))
        assert data["region"].search_area(name)

    def test_an_unknown_search_area_lists_the_known_ones(self, data):
        with pytest.raises(DataError, match="Known areas"):
            data["region"].search_area("nowhere")

    def test_an_inverted_box_is_rejected(self, tmp_path):
        path = tmp_path / "region.json"
        path.write_text(json.dumps({
            "region": {"south": 42.0, "west": -72.8, "north": 41.0, "east": -72.6},
            "reference_point": {"lat": 41.5, "lon": -72.7},
        }))
        with pytest.raises(DataError, match="degenerate or inverted"):
            Region.load(path)

    def test_a_search_area_outside_the_region_is_rejected(self, tmp_path):
        path = tmp_path / "region.json"
        path.write_text(json.dumps({
            "region": {"south": 41.0, "west": -72.8, "north": 42.0, "east": -72.6},
            "reference_point": {"lat": 41.5, "lon": -72.7},
            "search_areas": {
                "elsewhere": {"south": 50.0, "west": 0.0, "north": 51.0, "east": 1.0}
            },
        }))
        with pytest.raises(DataError, match="outside the region box"):
            Region.load(path)


class TestBindings:
    def test_every_scheme_fixture_exists_in_the_bindings(self, data):
        bindings = data["bindings"]
        for name, scheme in data["obstructions"]["marking_schemes"].items():
            assert bindings.known(scheme["top_fixture"]), name
            assert bindings.known(scheme["side_fixture"]), name

    def test_the_white_strobe_ships_bound(self, data):
        # The one fixture carried over from the library this grew out of.
        assert "obstruction_white_strobe" in data["bindings"].resolved_names

    def test_the_red_effects_ship_unbound_rather_than_invented(self, data):
        # A fabricated GUID builds cleanly and draws nothing, which is worse
        # than an empty field and a message saying it is empty.
        assert "obstruction_red_beacon" in data["bindings"].unresolved_names
        assert "obstruction_red_steady" in data["bindings"].unresolved_names

    def test_an_unresolved_fixture_returns_no_payload(self, data):
        assert data["bindings"].payload("obstruction_red_beacon") is None

    def test_a_resolved_fixture_returns_a_payload(self, data):
        assert data["bindings"].payload("obstruction_white_strobe") is not None

    def test_an_unknown_fixture_says_where_it_came_from(self, data):
        with pytest.raises(DataError, match="used by obs_test"):
            data["bindings"].payload("no_such_fixture", context="obs_test")

    def test_every_fixture_carries_a_description(self, data):
        for name, spec in data["bindings"].fixtures.items():
            assert spec.get("description"), name

    def test_resolved_without_a_guid_is_rejected(self, tmp_path):
        path = tmp_path / "library_bindings.json"
        path.write_text(json.dumps({
            "fixtures": {"x": {"kind": "library_object", "resolved": True}}
        }))
        with pytest.raises(DataError, match="marked resolved but has no guid"):
            Bindings.load(path)

    def test_resolved_without_an_effect_name_is_rejected(self, tmp_path):
        path = tmp_path / "library_bindings.json"
        path.write_text(json.dumps({
            "fixtures": {"x": {"kind": "effect", "resolved": True}}
        }))
        with pytest.raises(DataError, match="marked resolved but has no effect_name"):
            Bindings.load(path)

    def test_an_unknown_kind_is_rejected(self, tmp_path):
        path = tmp_path / "library_bindings.json"
        path.write_text(json.dumps({"fixtures": {"x": {"kind": "hologram"}}}))
        with pytest.raises(DataError, match="must be 'library_object' or 'effect'"):
            Bindings.load(path)


class TestBuildProfile:
    def test_the_obstruction_feature_is_on(self, data):
        assert data["profile"].enabled("obstructions")

    def test_the_shipped_selectors_are_masts_towers_and_chimneys(self, data):
        selectors = data["profile"].selectors
        values = {tuple(sorted(s.items())) for s in selectors}
        assert (("man_made", "mast"),) in values
        assert (("man_made", "chimney"),) in values
        assert any("tower" in dict(s).get("man_made", "") for s in selectors)

    def test_buildings_are_not_swept_by_default(self, data):
        # Deliberate: the sim lights some of them already, and blind sweeping
        # doubles up. See the comment in config/build_profile.json.
        assert not any("building" in s for s in data["profile"].selectors)

    def test_the_marking_floor_is_the_faa_200_ft(self, data):
        assert data["profile"].min_marked_height_ft == 200.0

    def test_the_exclude_list_exists_and_ignores_comments(self, data):
        assert isinstance(data["profile"].exclude, list)
        assert not any(str(e).startswith("$") for e in data["profile"].exclude)

    def test_unresolved_bindings_are_skipped_not_fatal(self, data):
        # A fresh clone has to build, or nobody ever gets as far as bindings.
        assert not data["profile"].error_on_unresolved

    def test_an_empty_selector_list_is_rejected(self, tmp_path):
        assert _profile_error(tmp_path, {"selectors": []}, "non-empty list")

    def test_a_selector_that_is_not_an_object_is_rejected(self, tmp_path):
        assert _profile_error(tmp_path, {"selectors": ["man_made=mast"]}, "object of OSM tags")

    def test_a_zero_height_floor_is_rejected(self, tmp_path):
        assert _profile_error(tmp_path, {"min_marked_height_ft": 0}, "positive number")

    def test_an_unknown_unresolved_policy_is_rejected(self, tmp_path):
        path = _write_profile(tmp_path, {})
        raw = json.loads(path.read_text())
        raw["bindings"]["on_unresolved"] = "explode"
        path.write_text(json.dumps(raw))
        with pytest.raises(DataError, match="'skip' or 'error'"):
            BuildProfile.load(path)


def _write_profile(tmp_path: Path, sweep_overrides: dict) -> Path:
    raw = load_json(REPO_ROOT / "config" / "build_profile.json")
    raw["sweep"].update(sweep_overrides)
    path = tmp_path / "build_profile.json"
    path.write_text(json.dumps(raw))
    return path


def _profile_error(tmp_path: Path, sweep_overrides: dict, match: str) -> bool:
    path = _write_profile(tmp_path, sweep_overrides)
    with pytest.raises(DataError, match=match):
        BuildProfile.load(path)
    return True


class TestObstructionData:
    def test_it_ships_empty_for_the_sweep_to_fill(self, data):
        # If this ever ships populated, the entries need real provenance in
        # their source fields - see docs/data-sources.md.
        assert data["obstructions"]["obstructions"] == []

    def test_both_marking_schemes_are_defined(self, data):
        assert set(data["obstructions"]["marking_schemes"]) == {"red", "white"}

    def test_the_defaults_match_the_faa_outline(self, data):
        defaults = data["obstructions"]["defaults"]
        assert defaults["level_interval_ft"] == 150
        assert defaults["lights_per_level"] == 4
        assert defaults["marking"] == "red"

    def test_the_file_says_it_is_scenery_not_an_obstacle_database(self, data):
        # The disclaimer is load-bearing, not decoration.
        text = " ".join(data["obstructions"]["$schema_comment"]).lower()
        assert "not use this package as an obstacle database" in text


class TestPackageConfig:
    def test_the_package_name_is_prefixed(self, data):
        # MSFS community packages are conventionally creator-prefixed.
        assert data["package"]["package_name"].startswith("coms-")

    def test_the_version_is_three_part(self, data):
        assert len(data["package"]["package_version"].split(".")) == 3

    def test_the_content_type_is_scenery(self, data):
        assert data["package"]["content_type"] == "SCENERY"
