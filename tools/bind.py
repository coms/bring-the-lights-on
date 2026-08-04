"""Fill in fixture bindings from the command line.

    python -m tools.bind --list
    python -m tools.bind obstruction_white_strobe --guid "{7f8b3c00-1111-2222-3333-444455556666}"
    python -m tools.bind obstruction_red_beacon --effect "MyLib_ObstructionBeacon_Red"
    python -m tools.bind obstruction_red_steady --clear

Editing config/library_bindings.json by hand works too; this just validates as
it goes and cannot leave the file in the "marked resolved but empty" state that
would produce a package which builds cleanly and draws nothing.

Where the values come from: docs/bindings.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .model import REPO_ROOT, DataError, load_json

BINDINGS_PATH = Path("config") / "library_bindings.json"

# MSFS library object GUIDs are canonical-form UUIDs in braces. Accepting a
# bare UUID and adding the braces is a kindness: the SDK's object browser
# copies them without.
GUID_RE = re.compile(r"^\{?[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}?$")


def normalize_guid(value: str) -> str:
    if not GUID_RE.match(value.strip()):
        raise DataError(
            f"{value!r} is not a GUID. Expected the canonical form, with or without braces, "
            f"e.g. {{7f8b3c00-1111-2222-3333-444455556666}}"
        )
    guid = value.strip()
    if not guid.startswith("{"):
        guid = "{" + guid + "}"
    return guid.lower()


def list_bindings(root: Path) -> None:
    raw = load_json(root / BINDINGS_PATH)
    fixtures = raw["fixtures"]
    width = max(len(name) for name in fixtures)

    resolved = [n for n, s in fixtures.items() if s.get("resolved")]
    print(f"{len(resolved)}/{len(fixtures)} fixture bindings resolved\n")

    for name in sorted(fixtures):
        spec = fixtures[name]
        if spec.get("resolved"):
            value = spec.get("guid") or spec.get("effect_name") or "?"
            mark, detail = "ok  ", value
        else:
            mark, detail = "--  ", f"({spec['kind']}, not set)"
        print(f"  {mark}{name:<{width}}  {detail}")

    print()
    for name in sorted(fixtures):
        if not fixtures[name].get("resolved"):
            print(f"  {name}: {fixtures[name]['description']}")


def set_binding(
    root: Path, fixture: str, *, guid: str | None, effect: str | None, clear: bool
) -> None:
    path = root / BINDINGS_PATH
    raw = load_json(path)
    fixtures = raw["fixtures"]

    if fixture not in fixtures:
        known = ", ".join(sorted(fixtures))
        raise DataError(f"unknown fixture {fixture!r}. Known fixtures: {known}")

    spec = fixtures[fixture]
    kind = spec["kind"]

    if clear:
        spec["resolved"] = False
        spec["guid" if kind == "library_object" else "effect_name"] = None
        print(f"  cleared {fixture}")
    elif guid is not None:
        if kind != "library_object":
            raise DataError(
                f"{fixture} is an effect binding, not a library object. Use --effect."
            )
        spec["guid"] = normalize_guid(guid)
        spec["resolved"] = True
        print(f"  {fixture} -> {spec['guid']}")
    elif effect is not None:
        if kind != "effect":
            raise DataError(
                f"{fixture} is a library object binding, not an effect. Use --guid."
            )
        if not effect.strip():
            raise DataError("effect name must not be empty")
        spec["effect_name"] = effect.strip()
        spec["resolved"] = True
        print(f"  {fixture} -> {spec['effect_name']}")
    else:
        raise DataError("pass one of --guid, --effect or --clear")

    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    remaining = [n for n, s in fixtures.items() if not s.get("resolved")]
    if remaining:
        print(f"  {len(remaining)} binding(s) still unresolved")
    else:
        print("  all bindings resolved - consider setting bindings.on_unresolved to 'error'")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("fixture", nargs="?", help="fixture type to bind")
    parser.add_argument("--list", action="store_true", help="show every binding and its state")
    parser.add_argument("--guid", help="library object GUID, for library_object fixtures")
    parser.add_argument("--effect", help="effect name, for effect fixtures")
    parser.add_argument("--clear", action="store_true", help="unset this binding")
    args = parser.parse_args(argv)

    try:
        if args.list or not args.fixture:
            list_bindings(REPO_ROOT)
            return 0
        set_binding(
            REPO_ROOT, args.fixture, guid=args.guid, effect=args.effect, clear=args.clear
        )
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
