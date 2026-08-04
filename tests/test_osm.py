"""Tests for the Overpass client.

Every test here is offline. The network calls go through a stub, because a test
suite that needs Overpass to be up is a test suite that fails for reasons that
have nothing to do with the code.
"""

from __future__ import annotations

import io
import urllib.error

import pytest

from tools.model import DataError
from tools.osm import (
    MIRRORS,
    OverpassError,
    Pacer,
    _bbox_clause,
    _selector_clause,
    fetch_structures,
    parse_height_m,
    query_overpass,
    resolve_endpoint,
)

BOX = {"south": 41.75, "west": -72.83, "north": 41.87, "east": -72.76}


class TestParseHeight:
    def test_a_bare_number_is_metres(self):
        assert parse_height_m("120") == pytest.approx(120.0)

    def test_metres_with_a_unit(self):
        assert parse_height_m("120 m") == pytest.approx(120.0)

    def test_metres_with_no_space(self):
        assert parse_height_m("120m") == pytest.approx(120.0)

    def test_feet_with_a_prime(self):
        assert parse_height_m("393'") == pytest.approx(119.8, rel=0.01)

    def test_feet_spelled_out(self):
        assert parse_height_m("393 feet") == pytest.approx(119.8, rel=0.01)

    def test_feet_abbreviated(self):
        assert parse_height_m("393 ft") == pytest.approx(119.8, rel=0.01)

    def test_a_comma_decimal_separator(self):
        assert parse_height_m("120,5") == pytest.approx(120.5)

    def test_none_stays_none(self):
        assert parse_height_m(None) is None

    def test_empty_is_none(self):
        assert parse_height_m("") is None
        assert parse_height_m("   ") is None

    def test_junk_is_none_rather_than_zero(self):
        # None means "OSM does not say" and makes the sweep skip the
        # structure. Zero would look like a real height of zero.
        assert parse_height_m("about 400ish") is None

    def test_zero_is_none(self):
        assert parse_height_m("0") is None

    def test_negative_is_none(self):
        assert parse_height_m("-50") is None

    def test_a_float(self):
        assert parse_height_m("120.75") == pytest.approx(120.75)


class TestSelectorClause:
    def test_a_single_tag(self):
        clause = _selector_clause({"man_made": "chimney"}, BOX)
        assert '["man_made"="chimney"]' in clause
        assert clause.count('["man_made"="chimney"]') == 2  # node and way

    def test_both_node_and_way_are_queried(self):
        clause = _selector_clause({"man_made": "mast"}, BOX)
        assert "node[" in clause
        assert "way[" in clause

    def test_multiple_tags_must_all_match(self):
        clause = _selector_clause({"man_made": "tower", "tower:type": "communication"}, BOX)
        assert '["man_made"="tower"]["tower:type"="communication"]' in clause

    def test_the_bbox_is_included(self):
        clause = _selector_clause({"man_made": "mast"}, BOX)
        assert "41.75,-72.83,41.87,-72.76" in clause

    def test_an_empty_selector_is_rejected(self):
        with pytest.raises(DataError, match="must not be empty"):
            _selector_clause({}, BOX)

    @pytest.mark.parametrize("bad", ['man"made', "man]made", "man;made", "man\\made"])
    def test_a_key_that_could_escape_the_query_is_rejected(self, bad):
        with pytest.raises(DataError, match="not valid in an OSM tag"):
            _selector_clause({bad: "mast"}, BOX)

    def test_a_value_that_could_escape_the_query_is_rejected(self):
        with pytest.raises(DataError, match="not valid in an OSM tag"):
            _selector_clause({"man_made": 'mast"];out;//'}, BOX)

    def test_a_newline_in_a_value_is_rejected(self):
        with pytest.raises(DataError, match="not valid in an OSM tag"):
            _selector_clause({"man_made": "mast\nout;"}, BOX)


class TestBboxClause:
    def test_order_is_south_west_north_east(self):
        assert _bbox_clause(BOX) == "41.75,-72.83,41.87,-72.76"


class TestResolveEndpoint:
    def test_a_short_mirror_name_expands(self):
        assert resolve_endpoint("kumi") == MIRRORS["kumi"]

    def test_a_full_url_passes_through(self):
        assert resolve_endpoint("https://example.test/api") == "https://example.test/api"


class TestPacer:
    def test_the_first_request_does_not_wait(self):
        slept = []
        pacer = Pacer(3.0, sleep=slept.append, clock=lambda: 0.0)
        pacer.wait()
        assert slept == []

    def test_a_second_request_waits_out_the_gap(self):
        slept = []
        times = iter([0.0, 0.0, 1.0, 1.0])
        pacer = Pacer(3.0, sleep=slept.append, clock=lambda: next(times))
        pacer.wait()
        pacer.wait()
        assert slept == [pytest.approx(2.0)]

    def test_no_wait_once_the_gap_has_already_passed(self):
        slept = []
        times = iter([0.0, 0.0, 10.0, 10.0])
        pacer = Pacer(3.0, sleep=slept.append, clock=lambda: next(times))
        pacer.wait()
        pacer.wait()
        assert slept == []

    def test_being_throttled_doubles_the_gap(self):
        pacer = Pacer(3.0, sleep=lambda _: None, clock=lambda: 0.0)
        pacer.throttled()
        assert pacer.gap == 6.0

    def test_the_gap_is_capped(self):
        pacer = Pacer(40.0, max_gap_s=60.0, sleep=lambda _: None, clock=lambda: 0.0)
        pacer.throttled()
        assert pacer.gap == 60.0

    def test_the_gap_never_shrinks_back(self):
        pacer = Pacer(3.0, sleep=lambda _: None, clock=lambda: 0.0)
        pacer.throttled()
        pacer.wait()
        assert pacer.gap == 6.0

    def test_a_zero_gap_still_becomes_positive_when_throttled(self):
        pacer = Pacer(0.0, sleep=lambda _: None, clock=lambda: 0.0)
        pacer.throttled()
        assert pacer.gap == 1.0

    def test_a_negative_gap_is_rejected(self):
        with pytest.raises(DataError, match="must not be negative"):
            Pacer(-1.0)


def _http_error(code, headers=None):
    return urllib.error.HTTPError(
        "https://example.test", code, "busy", headers or {}, None
    )


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class TestQueryOverpass:
    def test_a_successful_query_returns_parsed_json(self, monkeypatch):
        monkeypatch.setattr(
            "tools.osm.urllib.request.urlopen",
            lambda *a, **k: _Response(b'{"elements": []}'),
        )
        assert query_overpass("[out:json];", "https://example.test") == {"elements": []}

    def test_a_429_is_retried_and_can_succeed(self, monkeypatch):
        calls = []

        def urlopen(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(429)
            return _Response(b'{"elements": [1]}')

        monkeypatch.setattr("tools.osm.urllib.request.urlopen", urlopen)
        monkeypatch.setattr("tools.osm.seconds_until_slot", lambda _: 1)
        result = query_overpass("q", "https://example.test", sleep=lambda _: None)
        assert result == {"elements": [1]}
        assert len(calls) == 2

    def test_a_504_is_retried_too(self, monkeypatch):
        calls = []

        def urlopen(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(504)
            return _Response(b"{}")

        monkeypatch.setattr("tools.osm.urllib.request.urlopen", urlopen)
        monkeypatch.setattr("tools.osm.seconds_until_slot", lambda _: 1)
        query_overpass("q", "https://example.test", sleep=lambda _: None)
        assert len(calls) == 2

    def test_it_gives_up_after_the_attempt_limit(self, monkeypatch):
        monkeypatch.setattr(
            "tools.osm.urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(_http_error(429)),
        )
        monkeypatch.setattr("tools.osm.seconds_until_slot", lambda _: 1)
        with pytest.raises(OverpassError, match="Gave up after 2 attempts"):
            query_overpass("q", "https://example.test", attempts=2, sleep=lambda _: None)

    def test_a_404_is_not_retried(self, monkeypatch):
        calls = []

        def urlopen(*a, **k):
            calls.append(1)
            raise _http_error(404)

        monkeypatch.setattr("tools.osm.urllib.request.urlopen", urlopen)
        with pytest.raises(OverpassError, match="HTTP 404"):
            query_overpass("q", "https://example.test", sleep=lambda _: None)
        assert len(calls) == 1

    def test_a_throttle_tells_the_pacer(self, monkeypatch):
        monkeypatch.setattr(
            "tools.osm.urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(_http_error(429)),
        )
        monkeypatch.setattr("tools.osm.seconds_until_slot", lambda _: 1)
        pacer = Pacer(3.0, sleep=lambda _: None, clock=lambda: 0.0)
        with pytest.raises(OverpassError):
            query_overpass(
                "q", "https://example.test", attempts=2, sleep=lambda _: None, pacer=pacer
            )
        assert pacer.gap > 3.0

    def test_a_retry_after_header_sets_the_wait(self, monkeypatch):
        waits = []
        calls = []

        def urlopen(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(429, {"Retry-After": "7"})
            return _Response(b"{}")

        monkeypatch.setattr("tools.osm.urllib.request.urlopen", urlopen)
        query_overpass("q", "https://example.test", sleep=waits.append)
        assert waits == [8]  # the header value, plus one second of slack

    def test_an_unreachable_host_is_flagged_as_a_connection_failure(self, monkeypatch):
        monkeypatch.setattr(
            "tools.osm.urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("no route")),
        )
        with pytest.raises(OverpassError) as excinfo:
            query_overpass("q", "https://example.test")
        assert excinfo.value.connection is True
        assert "needs outbound internet access" in str(excinfo.value)


class TestFetchStructures:
    def _reply(self, monkeypatch, payload):
        monkeypatch.setattr("tools.osm.query_overpass", lambda *a, **k: payload)

    def test_a_node_becomes_a_structure(self, monkeypatch):
        self._reply(monkeypatch, {"elements": [
            {"type": "node", "id": 1, "lat": 41.8, "lon": -72.8,
             "tags": {"man_made": "mast", "name": "WFSB", "height": "300"}},
        ]})
        found = fetch_structures(BOX, [{"man_made": "mast"}], "https://example.test")
        assert len(found) == 1
        assert found[0]["name"] == "WFSB"
        assert found[0]["height_m"] == pytest.approx(300.0)
        assert found[0]["osm_id"] == "node/1"

    def test_a_way_uses_its_centre(self, monkeypatch):
        self._reply(monkeypatch, {"elements": [
            {"type": "way", "id": 2, "center": {"lat": 41.81, "lon": -72.81},
             "tags": {"man_made": "chimney", "height": "107"}},
        ]})
        found = fetch_structures(BOX, [{"man_made": "chimney"}], "https://example.test")
        assert found[0]["point"].lat == pytest.approx(41.81)
        assert found[0]["osm_id"] == "way/2"

    def test_an_element_with_no_position_is_dropped(self, monkeypatch):
        self._reply(monkeypatch, {"elements": [{"type": "relation", "id": 3, "tags": {}}]})
        assert fetch_structures(BOX, [{"man_made": "mast"}], "https://example.test") == []

    def test_a_missing_height_comes_back_as_none(self, monkeypatch):
        self._reply(monkeypatch, {"elements": [
            {"type": "node", "id": 4, "lat": 41.8, "lon": -72.8, "tags": {"man_made": "mast"}},
        ]})
        found = fetch_structures(BOX, [{"man_made": "mast"}], "https://example.test")
        assert found[0]["height_m"] is None

    def test_tower_height_is_used_when_height_is_absent(self, monkeypatch):
        self._reply(monkeypatch, {"elements": [
            {"type": "node", "id": 5, "lat": 41.8, "lon": -72.8,
             "tags": {"man_made": "mast", "tower:height": "150"}},
        ]})
        found = fetch_structures(BOX, [{"man_made": "mast"}], "https://example.test")
        assert found[0]["height_m"] == pytest.approx(150.0)

    def test_building_height_is_the_last_fallback(self, monkeypatch):
        self._reply(monkeypatch, {"elements": [
            {"type": "node", "id": 6, "lat": 41.8, "lon": -72.8,
             "tags": {"man_made": "chimney", "building:height": "80"}},
        ]})
        found = fetch_structures(BOX, [{"man_made": "chimney"}], "https://example.test")
        assert found[0]["height_m"] == pytest.approx(80.0)

    def test_an_empty_response_is_an_empty_list_not_an_error(self, monkeypatch):
        self._reply(monkeypatch, {"elements": []})
        assert fetch_structures(BOX, [{"man_made": "mast"}], "https://example.test") == []

    def test_no_selectors_is_rejected(self):
        with pytest.raises(DataError, match="at least one entry"):
            fetch_structures(BOX, [], "https://example.test")

    def test_every_selector_ends_up_in_the_query(self, monkeypatch):
        seen = {}

        def capture(query, endpoint, **kwargs):
            seen["query"] = query
            return {"elements": []}

        monkeypatch.setattr("tools.osm.query_overpass", capture)
        fetch_structures(
            BOX, [{"man_made": "mast"}, {"man_made": "chimney"}], "https://example.test"
        )
        assert '["man_made"="mast"]' in seen["query"]
        assert '["man_made"="chimney"]' in seen["query"]
