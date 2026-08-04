"""Tests for the obstruction generator - the whole point of the package.

What matters here is that a structure's marking comes out as the FAA describes
it: a beacon on top, side lights ringed below at the scheme's interval, and the
red and white schemes differing in more than colour.
"""

from __future__ import annotations

import copy

import pytest

from tools.generators import obstructions
from tools.generators.common import Context, resolve_point, ring
from tools.generators.obstructions import resolve_marking
from tools.geo import Point, haversine_m
from tools.model import DataError


def _entry(**overrides):
    entry = {
        "id": "obs_test",
        "name": "Test mast",
        "lat": 41.80,
        "lon": -72.80,
        "height_ft": 450,
        "radius_m": 5,
        "auto_levels": True,
        "top_beacons": 1,
        "marking": "red",
    }
    entry.update(overrides)
    return entry


def _generate(ctx, *entries):
    """Run the generator over a synthetic obstruction list.

    The entries are swapped into the context that was passed in, rather than
    into a copy, so that what the generator records on the way through - out of
    region, skipped fixtures - is visible to the caller afterwards.
    """
    data = copy.deepcopy(ctx.data["obstructions"])
    data["obstructions"] = list(entries)
    ctx.data = {**ctx.data, "obstructions": data}
    return obstructions.generate(ctx)


class TestResolveMarking:
    def test_the_default_scheme_is_red(self, marking_schemes):
        marking = resolve_marking(marking_schemes, {}, "test")
        assert marking["name"] == "red"

    def test_red_uses_a_beacon_on_top_and_steady_lights_below(self, marking_schemes):
        marking = resolve_marking(marking_schemes, {"marking": "red"}, "test")
        assert marking["top_fixture"] == "obstruction_red_beacon"
        assert marking["side_fixture"] == "obstruction_red_steady"

    def test_white_strobes_at_every_level(self, marking_schemes):
        # Not a colour swap: the same fixture top and side.
        marking = resolve_marking(marking_schemes, {"marking": "white"}, "test")
        assert marking["top_fixture"] == marking["side_fixture"]

    def test_white_spaces_its_levels_further_apart(self, marking_schemes):
        red = resolve_marking(marking_schemes, {"marking": "red"}, "test")
        white = resolve_marking(marking_schemes, {"marking": "white"}, "test")
        assert white["level_interval_ft"] > red["level_interval_ft"]

    def test_white_carries_fewer_units_per_level(self, marking_schemes):
        red = resolve_marking(marking_schemes, {"marking": "red"}, "test")
        white = resolve_marking(marking_schemes, {"marking": "white"}, "test")
        assert white["lights_per_level"] < red["lights_per_level"]

    def test_an_entry_can_override_the_interval(self, marking_schemes):
        marking = resolve_marking(marking_schemes, {"level_interval_ft": 75}, "test")
        assert marking["level_interval_ft"] == 75

    def test_an_entry_can_override_the_count(self, marking_schemes):
        marking = resolve_marking(marking_schemes, {"lights_per_level": 8}, "test")
        assert marking["lights_per_level"] == 8

    def test_an_entry_override_beats_the_scheme(self, marking_schemes):
        marking = resolve_marking(
            marking_schemes, {"marking": "white", "lights_per_level": 6}, "test"
        )
        assert marking["lights_per_level"] == 6

    def test_an_unknown_scheme_names_the_ones_that_exist(self, marking_schemes):
        with pytest.raises(DataError, match="Known schemes: red, white"):
            resolve_marking(marking_schemes, {"marking": "chartreuse"}, "test")

    def test_a_zero_interval_is_rejected(self, marking_schemes):
        # It would otherwise loop forever generating levels.
        with pytest.raises(DataError, match="must be positive"):
            resolve_marking(marking_schemes, {"level_interval_ft": 0}, "test")

    def test_a_negative_interval_is_rejected(self, marking_schemes):
        with pytest.raises(DataError, match="must be positive"):
            resolve_marking(marking_schemes, {"level_interval_ft": -150}, "test")

    def test_a_zero_light_count_is_rejected(self, marking_schemes):
        with pytest.raises(DataError, match="must be positive"):
            resolve_marking(marking_schemes, {"lights_per_level": 0}, "test")


class TestGeneratedMarking:
    def test_a_structure_gets_a_beacon_on_top(self, bound_context):
        scenery = _generate(bound_context, _entry(auto_levels=False))
        beacons = [o for o in scenery.objects if o.kind == "obstruction_beacon"]
        assert len(beacons) == 1

    def test_the_beacon_sits_at_the_structure_height(self, bound_context):
        scenery = _generate(bound_context, _entry(height_ft=450, auto_levels=False))
        beacon = next(o for o in scenery.objects if o.kind == "obstruction_beacon")
        assert beacon.alt_m == pytest.approx(450 * 0.3048, rel=1e-6)

    def test_a_beacon_above_ground_is_never_snapped_down_to_it(self, bound_context):
        # The failure that would put every light in the package on the ground.
        scenery = _generate(bound_context, _entry(auto_levels=False))
        assert 'snapToGround="FALSE"' in scenery.objects[0].to_xml()

    def test_auto_levels_off_means_no_side_lights(self, bound_context):
        scenery = _generate(bound_context, _entry(auto_levels=False))
        assert not [o for o in scenery.objects if o.kind == "obstruction_side_light"]

    def test_side_lights_are_generated_below_the_top(self, bound_context):
        scenery = _generate(bound_context, _entry(height_ft=450))
        sides = [o for o in scenery.objects if o.kind == "obstruction_side_light"]
        assert sides
        beacon = next(o for o in scenery.objects if o.kind == "obstruction_beacon")
        assert all(o.alt_m < beacon.alt_m for o in sides)

    def test_the_number_of_levels_follows_the_height(self, bound_context):
        # 450 ft at 150 ft intervals: levels at 300 and 150.
        scenery = _generate(bound_context, _entry(height_ft=450))
        sides = [o for o in scenery.objects if o.kind == "obstruction_side_light"]
        levels = {round(o.alt_m, 2) for o in sides}
        assert len(levels) == 2

    def test_a_taller_structure_gets_more_levels(self, bound_context):
        short = _generate(bound_context, _entry(height_ft=300))
        tall = _generate(bound_context, _entry(height_ft=900))
        assert len(tall.objects) > len(short.objects)

    def test_four_side_lights_ring_each_level_by_default(self, bound_context):
        scenery = _generate(bound_context, _entry(height_ft=450))
        sides = [o for o in scenery.objects if o.kind == "obstruction_side_light"]
        assert len(sides) == 8  # two levels of four

    def test_a_structure_too_short_for_a_level_gets_only_a_beacon(self, bound_context):
        scenery = _generate(bound_context, _entry(height_ft=100))
        assert [o.kind for o in scenery.objects] == ["obstruction_beacon"]

    def test_two_top_beacons_are_spread_across_the_roof(self, bound_context):
        scenery = _generate(
            bound_context, _entry(top_beacons=2, radius_m=25, auto_levels=False)
        )
        beacons = [o for o in scenery.objects if o.kind == "obstruction_beacon"]
        assert len(beacons) == 2
        apart = haversine_m(
            Point(beacons[0].lat, beacons[0].lon), Point(beacons[1].lat, beacons[1].lon)
        )
        assert apart == pytest.approx(50, rel=0.05)  # two radii apart

    def test_a_single_top_beacon_sits_dead_centre(self, bound_context):
        scenery = _generate(bound_context, _entry(radius_m=25, auto_levels=False))
        beacon = scenery.objects[0]
        assert (beacon.lat, beacon.lon) == pytest.approx((41.80, -72.80))

    def test_a_white_structure_strobes_at_its_own_spacing(self, bound_context):
        scenery = _generate(bound_context, _entry(marking="white", height_ft=1000))
        sides = [o for o in scenery.objects if o.kind == "obstruction_side_light"]
        levels = sorted({round(o.alt_m / 0.3048) for o in sides})
        # 250 ft apart: 750, 500, 250.
        assert levels == [250, 500, 750]

    def test_a_white_level_carries_three_units(self, bound_context):
        scenery = _generate(bound_context, _entry(marking="white", height_ft=500))
        sides = [o for o in scenery.objects if o.kind == "obstruction_side_light"]
        assert len(sides) == 3

    def test_every_object_carries_its_source_id(self, bound_context):
        scenery = _generate(bound_context, _entry(id="obs_named"))
        assert all(o.source_id == "obs_named" for o in scenery.objects)

    def test_a_zero_height_is_rejected(self, bound_context):
        with pytest.raises(DataError, match="height_ft must be positive"):
            _generate(bound_context, _entry(height_ft=0))

    def test_a_negative_height_is_rejected(self, bound_context):
        with pytest.raises(DataError, match="height_ft must be positive"):
            _generate(bound_context, _entry(height_ft=-100))

    def test_a_structure_outside_the_region_is_dropped_and_recorded(self, bound_context):
        _generate(bound_context, _entry(lat=0.0, lon=0.0))
        assert bound_context.out_of_region

    def test_an_unresolved_fixture_skips_rather_than_faking(self):
        from tools.model import load_all

        data = load_all()  # nothing stubbed: the red effects are unbound
        ctx = Context(
            region=data["region"], bindings=data["bindings"],
            profile=data["profile"], data=data,
        )
        scenery = _generate(ctx, _entry(marking="red"))
        assert len(scenery) == 0
        assert ctx.skipped


class TestRing:
    CENTER = Point(41.80, -72.80)

    def test_it_yields_the_requested_count(self):
        assert len(list(ring(self.CENTER, 4, 10.0))) == 4

    def test_a_zero_radius_puts_everything_at_the_centre(self):
        positions = [p for p, _ in ring(self.CENTER, 3, 0.0)]
        assert all(p == self.CENTER for p in positions)

    def test_every_position_is_the_radius_from_the_centre(self):
        for pos, _ in ring(self.CENTER, 6, 25.0):
            assert haversine_m(self.CENTER, pos) == pytest.approx(25.0, rel=1e-6)

    def test_positions_are_evenly_spaced(self):
        positions = [p for p, _ in ring(self.CENTER, 4, 30.0)]
        gaps = [
            haversine_m(positions[i], positions[(i + 1) % 4]) for i in range(4)
        ]
        assert max(gaps) == pytest.approx(min(gaps), rel=1e-6)

    def test_a_count_of_zero_yields_nothing(self):
        assert list(ring(self.CENTER, 0, 10.0)) == []

    def test_a_negative_radius_is_rejected(self):
        with pytest.raises(DataError, match="must not be negative"):
            list(ring(self.CENTER, 4, -1.0))

    def test_inward_headings_point_at_the_centre(self):
        _, heading = next(iter(ring(self.CENTER, 4, 10.0, start_bearing=0.0)))
        assert heading == pytest.approx(180.0)

    def test_outward_headings_point_away(self):
        _, heading = next(iter(ring(self.CENTER, 4, 10.0, aim="outward")))
        assert heading == pytest.approx(0.0)


class TestResolvePoint:
    def test_it_reads_lat_and_lon(self):
        assert resolve_point({"lat": 41.8, "lon": -72.8}, "test") == Point(41.8, -72.8)

    def test_a_missing_coordinate_is_named(self):
        with pytest.raises(DataError, match="needs both lat and lon"):
            resolve_point({"lat": 41.8}, "test")

    def test_an_out_of_range_latitude_is_rejected(self):
        with pytest.raises(DataError, match="latitude"):
            resolve_point({"lat": 91.0, "lon": 0.0}, "test")

    def test_an_out_of_range_longitude_is_rejected(self):
        with pytest.raises(DataError, match="longitude"):
            resolve_point({"lat": 0.0, "lon": 181.0}, "test")
