"""Overpass client: find tall structures inside a bounding box.

This is the only part of the toolchain that touches the network, and it is
never called by the build. `tools/sweep.py` drives it, writes the result into
data/obstructions.json, and you commit that like any other edit. Someone
cloning the repo builds from checked-in data with no internet access at all.

Overpass is a shared free service, so this module is deliberately polite: one
query at a time, a gap between them, and a backoff that listens to the server's
own Retry-After rather than guessing.

OSM data is ODbL-licensed. See docs/data-sources.md for what that means for
anything you redistribute.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .geo import Point
from .model import DataError

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "bring-the-lights-on/0.1 (MSFS scenery toolchain)"

# Be polite: one query at a time, with a gap between them, and a timeout that
# gives up rather than holding a slot.
REQUEST_GAP_S = 3.0
REQUEST_TIMEOUT_S = 180

# After the server throttles us, the gap doubles for the rest of the run - the
# instance has told us it is busy, and carrying on at the old rate just earns
# another 429. It never shrinks back within a run.
MAX_GAP_S = 60.0

# Rate limiting is normal on the public instances, not exceptional - a whole
# sweep should survive one rather than throwing away the areas that already
# succeeded.
MAX_ATTEMPTS = 4
RETRY_BACKOFF_S = 15
MAX_RETRY_WAIT_S = 180

# Public Overpass instances. Short names may be passed to --endpoint.
MIRRORS = {
    "de": "https://overpass-api.de/api/interpreter",
    "kumi": "https://overpass.kumi.systems/api/interpreter",
    "fr": "https://overpass.openstreetmap.fr/api/interpreter",
    "ru": "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
}


class Pacer:
    """Spaces requests out, and backs further off once throttled.

    Overpass measures load per client. A fixed gap is fine until the instance
    is busy, at which point continuing at the same rate is what turns one 429
    into a run of them - so a throttle permanently doubles the gap for the rest
    of the run.
    """

    def __init__(self, gap_s: float = REQUEST_GAP_S, *, max_gap_s: float = MAX_GAP_S,
                 sleep=time.sleep, clock=time.monotonic) -> None:
        if gap_s < 0:
            raise DataError(f"request gap must not be negative, got {gap_s}")
        self.gap = float(gap_s)
        self.max_gap = float(max_gap_s)
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        """Block until enough time has passed since the previous request."""
        now = self._clock()
        if self._last is not None:
            remaining = self.gap - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

    def throttled(self) -> None:
        self.gap = min(self.gap * 2, self.max_gap) if self.gap else 1.0


class OverpassError(Exception):
    """A request failed in a way the caller should report rather than retry."""

    def __init__(self, message: str, *, retryable: bool = False,
                 connection: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        # True when we never reached the server at all, so the caller can say
        # "the network is down" rather than "there are no masts there".
        self.connection = connection


def resolve_endpoint(value: str) -> str:
    """Accept either a short mirror name or a full URL."""
    return MIRRORS.get(value, value)


def _status_url(endpoint: str) -> str:
    return endpoint.rsplit("/", 1)[0] + "/status"


def seconds_until_slot(endpoint: str) -> int | None:
    """Ask Overpass when our next query slot frees up.

    The status endpoint reports rate-limit state in plain text, including
    lines like "Slot available after: <time>, in 42 seconds." Knowing the
    real number beats guessing at a backoff.
    """
    try:
        request = urllib.request.Request(
            _status_url(endpoint), headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", "replace")
    except Exception:
        # Purely advisory - never let the diagnostic break the caller.
        return None

    waits = [int(m) for m in re.findall(r"in (\d+) seconds", text)]
    return min(waits) if waits else None


def query_overpass(
    query: str,
    endpoint: str = DEFAULT_ENDPOINT,
    *,
    attempts: int = MAX_ATTEMPTS,
    sleep=None,
    pacer: "Pacer | None" = None,
) -> dict:
    """POST an Overpass QL query and return the parsed JSON.

    Retries on the transient failures - rate limiting and gateway timeouts -
    because a single 429 partway through a multi-area sweep otherwise throws
    away every query that already succeeded. Waits are taken from the server's
    own Retry-After header or status endpoint where it offers one, and fall
    back to exponential backoff.
    """
    endpoint = resolve_endpoint(endpoint)
    # Resolved at call time, not captured as a default, so that a test - or a
    # caller wanting to not actually sleep - can substitute it.
    sleep = time.sleep if sleep is None else sleep
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last: OverpassError | None = None

    for attempt in range(1, attempts + 1):
        if pacer is not None:
            pacer.wait()
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            if exc.code in (429, 504):
                last = OverpassError(
                    f"Overpass is rate-limiting or overloaded (HTTP {exc.code}).",
                    retryable=True,
                )
                # The instance has told us it is busy. Slow every later request
                # down, not just the retry of this one.
                if pacer is not None:
                    pacer.throttled()
            else:
                raise OverpassError(
                    f"Overpass returned HTTP {exc.code}: {exc.reason}"
                ) from exc

            if attempt < attempts:
                wait = _retry_after(exc) or seconds_until_slot(endpoint)
                if wait is None:
                    wait = RETRY_BACKOFF_S * (2 ** (attempt - 1))
                wait = min(int(wait) + 1, MAX_RETRY_WAIT_S)
                print(
                    f"\n    HTTP {exc.code} from Overpass; waiting {wait}s "
                    f"(attempt {attempt}/{attempts}) ... ",
                    end="", flush=True,
                )
                sleep(wait)
                continue

        except urllib.error.URLError as exc:
            raise OverpassError(
                f"could not reach {endpoint}: {exc.reason}. This tool needs outbound "
                f"internet access; the build itself does not.",
                connection=True,
            ) from exc

    mirrors = ", ".join(name for name in MIRRORS if resolve_endpoint(name) != endpoint)
    raise OverpassError(
        f"{last} Gave up after {attempts} attempts. Wait a few minutes and re-run just "
        f"this area, or try another mirror: --endpoint {mirrors}"
    )


def _retry_after(exc: urllib.error.HTTPError) -> int | None:
    """Seconds from a Retry-After header, if the server sent a usable one."""
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if not raw:
        return None
    try:
        return max(0, int(str(raw).strip()))
    except ValueError:
        # The HTTP-date form is legal but Overpass does not use it.
        return None


def _bbox_clause(bbox: dict) -> str:
    return f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"


def parse_height_m(raw: str | None) -> float | None:
    """Parse an OSM height tag into metres.

    OSM heights are metres by default but the tag is free text and people write
    `120`, `120 m`, `120m` and `393'` interchangeably. Anything unrecognised
    returns None so the caller can skip the structure rather than silently
    placing a beacon at the wrong altitude.
    """
    if raw is None:
        return None
    text = str(raw).strip().lower().replace(",", ".")
    if not text:
        return None

    unit_m = 1.0
    for suffix, factor in (("'", 0.3048), ("ft", 0.3048), ("feet", 0.3048), ("m", 1.0)):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            unit_m = factor
            break

    try:
        value = float(text)
    except ValueError:
        return None
    return value * unit_m if value > 0 else None


# Characters that would let a selector escape its quoted tag filter and append
# arbitrary Overpass QL. None of them are legal in an OSM tag key or value, so
# their presence means the config file is wrong rather than that we need
# escaping.
_QL_UNSAFE = set('"[]();\\\n\r')


def _selector_clause(selector: dict, bbox: dict) -> str:
    """Turn a `{"man_made": "chimney"}` selector into Overpass node/way lines."""
    if not selector:
        raise DataError("sweep selectors must not be empty")

    parts = []
    for key, value in selector.items():
        for label, text in (("key", str(key)), ("value", str(value))):
            bad = sorted(_QL_UNSAFE & set(text))
            if bad:
                raise DataError(
                    f"sweep.selectors: {label} {text!r} contains {''.join(bad)!r}, which is "
                    f"not valid in an OSM tag and would break the Overpass query."
                )
        parts.append(f'["{key}"="{value}"]')

    tags = "".join(parts)
    area = _bbox_clause(bbox)
    return f"  node{tags}({area});\n  way{tags}({area});"


def fetch_structures(bbox: dict, selectors: list[dict], endpoint: str,
                     *, pacer: "Pacer | None" = None) -> list[dict]:
    """Fetch tall structures matching any selector inside a bounding box.

    Selectors are a union: a broadcast farm is often tagged inconsistently
    between `man_made=mast` and `man_made=tower`, and taking only one of them
    misses masts, so the config declares every tagging it wants to catch.

    Returns dicts with position, name and height where OSM records one. A
    height of None means OSM does not say, which the sweep treats as a reason
    to skip the structure rather than to guess.
    """
    if not selectors:
        raise DataError("a sweep needs at least one entry in sweep.selectors")

    body = "\n".join(_selector_clause(selector, bbox) for selector in selectors)
    query = f"[out:json][timeout:60];\n(\n{body}\n);\nout center tags;\n"
    result = query_overpass(query, endpoint, pacer=pacer)
    structures: list[dict] = []
    for element in result.get("elements", []):
        if "center" in element:
            lat, lon = element["center"]["lat"], element["center"]["lon"]
        elif "lat" in element:
            lat, lon = element["lat"], element["lon"]
        else:
            continue

        tags = element.get("tags", {})
        height_m = (
            parse_height_m(tags.get("height"))
            or parse_height_m(tags.get("tower:height"))
            # Chimneys and older mast entries sometimes carry this instead.
            or parse_height_m(tags.get("building:height"))
        )
        structures.append({
            "point": Point(lat, lon),
            "name": tags.get("name"),
            "operator": tags.get("operator"),
            "height_m": height_m,
            "osm_id": f"{element.get('type', '?')}/{element.get('id', '?')}",
        })
    return structures
