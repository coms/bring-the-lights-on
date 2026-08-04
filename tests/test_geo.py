"""Tests for the geodesy helpers.

Distances are checked against known values rather than against the code's own
output, so a refactor that quietly changes the earth model fails here.
"""

from __future__ import annotations

import math

import pytest

from tools.geo import (
    EARTH_RADIUS_M,
    Point,
    bbox_contains,
    destination,
    feet_to_metres,
    haversine_m,
    metres_to_feet,
    normalize_heading,
)

HARTFORD = Point(41.766390, -72.673060)


class TestNormalizeHeading:
    def test_leaves_a_heading_in_range_alone(self):
        assert normalize_heading(90.0) == 90.0

    def test_wraps_past_360(self):
        assert normalize_heading(450.0) == 90.0

    def test_wraps_negative(self):
        assert normalize_heading(-90.0) == 270.0

    def test_360_becomes_zero(self):
        assert normalize_heading(360.0) == 0.0


class TestHaversine:
    def test_zero_distance_to_itself(self):
        assert haversine_m(HARTFORD, HARTFORD) == pytest.approx(0.0, abs=1e-9)

    def test_one_degree_of_latitude(self):
        # A degree of latitude is ~111.2 km anywhere on a sphere.
        north = Point(HARTFORD.lat + 1.0, HARTFORD.lon)
        assert haversine_m(HARTFORD, north) == pytest.approx(111195, rel=0.001)

    def test_a_degree_of_longitude_shrinks_with_latitude(self):
        equator = haversine_m(Point(0.0, 0.0), Point(0.0, 1.0))
        up_north = haversine_m(Point(60.0, 0.0), Point(60.0, 1.0))
        # cos(60 deg) = 0.5, so it should be about half.
        assert up_north == pytest.approx(equator * 0.5, rel=0.001)

    def test_is_symmetric(self):
        other = Point(41.8, -72.8)
        assert haversine_m(HARTFORD, other) == pytest.approx(haversine_m(other, HARTFORD))

    def test_antipodal_points_are_half_the_circumference(self):
        antipode = Point(-HARTFORD.lat, HARTFORD.lon + 180.0)
        assert haversine_m(HARTFORD, antipode) == pytest.approx(
            math.pi * EARTH_RADIUS_M, rel=0.001
        )


class TestDestination:
    def test_zero_distance_returns_the_origin(self):
        assert destination(HARTFORD, 45.0, 0.0) == HARTFORD

    def test_travelling_north_increases_latitude_only(self):
        moved = destination(HARTFORD, 0.0, 1000.0)
        assert moved.lat > HARTFORD.lat
        assert moved.lon == pytest.approx(HARTFORD.lon, abs=1e-9)

    def test_travelling_east_increases_longitude_only(self):
        moved = destination(HARTFORD, 90.0, 1000.0)
        assert moved.lon > HARTFORD.lon
        assert moved.lat == pytest.approx(HARTFORD.lat, abs=1e-6)

    def test_round_trips_with_haversine(self):
        moved = destination(HARTFORD, 137.0, 2500.0)
        assert haversine_m(HARTFORD, moved) == pytest.approx(2500.0, rel=1e-6)

    def test_a_full_circle_of_bearings_all_land_the_same_distance_away(self):
        for bearing in range(0, 360, 30):
            moved = destination(HARTFORD, float(bearing), 500.0)
            assert haversine_m(HARTFORD, moved) == pytest.approx(500.0, rel=1e-6)

    def test_longitude_stays_in_range_crossing_the_antimeridian(self):
        near_dateline = Point(0.0, 179.99)
        moved = destination(near_dateline, 90.0, 5000.0)
        assert -180.0 <= moved.lon < 180.0
        # It really did cross, rather than being clamped.
        assert moved.lon < 0


class TestBboxContains:
    BOX = {"south": 41.7, "west": -72.8, "north": 41.9, "east": -72.6}

    def test_a_point_inside(self):
        assert bbox_contains(self.BOX, Point(41.8, -72.7))

    def test_a_point_north_of_the_box(self):
        assert not bbox_contains(self.BOX, Point(42.0, -72.7))

    def test_a_point_west_of_the_box(self):
        assert not bbox_contains(self.BOX, Point(41.8, -72.9))

    def test_the_corners_count_as_inside(self):
        assert bbox_contains(self.BOX, Point(41.7, -72.8))
        assert bbox_contains(self.BOX, Point(41.9, -72.6))

    def test_a_margin_widens_the_box(self):
        outside = Point(41.95, -72.7)
        assert not bbox_contains(self.BOX, outside)
        assert bbox_contains(self.BOX, outside, margin_deg=0.1)

    def test_a_sign_flip_lands_outside(self):
        # The failure this guard exists for: a dropped minus on the longitude.
        assert not bbox_contains(self.BOX, Point(41.8, 72.7))


class TestConversions:
    def test_feet_to_metres(self):
        assert feet_to_metres(1000.0) == pytest.approx(304.8)

    def test_metres_to_feet(self):
        assert metres_to_feet(304.8) == pytest.approx(1000.0)

    def test_they_round_trip(self):
        assert metres_to_feet(feet_to_metres(535.0)) == pytest.approx(535.0)

    def test_zero(self):
        assert feet_to_metres(0.0) == 0.0
        assert metres_to_feet(0.0) == 0.0
