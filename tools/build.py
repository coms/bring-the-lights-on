"""Build driver: data + config -> MSFS scenery XML.

    python -m tools.build            # write PackageSources/scenery/*.xml
    python -m tools.build --dry-run  # generate and report, write nothing
    python -m tools.build --quiet    # report only totals

Exit status is non-zero if the build would produce something the sim should not
be asked to load, or if bindings.on_unresolved is "error" and any remain.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .fsxml import SceneryFile
from .generators import obstructions
from .generators.common import Context
from .model import REPO_ROOT, DataError, load_all

GENERATORS = [
    ("obstructions", obstructions),
]


def build(root: Path = REPO_ROOT, *, dry_run: bool = False, quiet: bool = False) -> dict:
    data = load_all(root)
    profile = data["profile"]
    ctx = Context(
        region=data["region"],
        bindings=data["bindings"],
        profile=profile,
        data=data,
    )

    files: list[SceneryFile] = []
    per_feature: dict[str, int] = {}

    for name, module in GENERATORS:
        if not profile.enabled(name):
            per_feature[name] = 0
            continue
        scenery = module.generate(ctx)
        per_feature[name] = len(scenery)
        files.append(scenery)

    total = sum(per_feature.values())
    report = {
        "package": data["package"]["package_name"],
        "version": data["package"]["package_version"],
        "region": data["region"].name,
        "total_objects": total,
        "objects_by_feature": per_feature,
        "structures": len(data["obstructions"].get("obstructions", [])),
        "files": [{"filename": f.filename, "objects": len(f)} for f in files],
        "bindings": {
            "resolved": data["bindings"].resolved_names,
            "unresolved": data["bindings"].unresolved_names,
            "objects_skipped_by_fixture": dict(data["bindings"].unresolved_hits),
            "objects_skipped_total": sum(data["bindings"].unresolved_hits.values()),
        },
        "out_of_region": [
            {"source_id": sid, "lat": p.lat, "lon": p.lon} for sid, p in ctx.out_of_region
        ],
    }

    problems = _check(report, profile)
    if not quiet:
        _print_report(report, profile, problems, dry_run=dry_run)

    if problems:
        raise DataError("; ".join(problems))

    if not dry_run:
        _write(files, report, data, profile, root)

    return report


def _check(report: dict, profile) -> list[str]:
    problems: list[str] = []
    total = report["total_objects"]

    if total > profile.max_total_objects:
        problems.append(
            f"{total} objects exceeds limits.max_total_objects ({profile.max_total_objects}). "
            f"Raise sweep.min_marked_height_ft, or narrow the region."
        )
    if report["out_of_region"]:
        ids = sorted({e["source_id"] for e in report["out_of_region"]})
        problems.append(
            f"{len(report['out_of_region'])} object(s) fell outside the declared region, "
            f"from: {', '.join(ids)}. Check the coordinates in data/obstructions.json."
        )
    if profile.error_on_unresolved and report["bindings"]["unresolved"]:
        problems.append(
            f"unresolved fixture bindings with on_unresolved='error': "
            f"{', '.join(report['bindings']['unresolved'])}"
        )
    return problems


def _print_report(report: dict, profile, problems: list[str], *, dry_run: bool) -> None:
    mode = " (dry run)" if dry_run else ""
    print(f"Bring The Lights On {report['version']} - {report['region']}{mode}")
    print()
    print(f"  {report['structures']} structure(s) marked")
    print("  Objects by feature")
    for name, count in report["objects_by_feature"].items():
        state = "" if count else "  (disabled or fully skipped)"
        print(f"    {name:<16} {count:>7,}{state}")
    print(f"    {'TOTAL':<16} {report['total_objects']:>7,}")

    if report["total_objects"] > profile.warn_total_objects:
        print()
        print(
            f"  ! {report['total_objects']:,} objects is above the "
            f"{profile.warn_total_objects:,} comfort threshold. Expect a frame cost; "
            f"raise sweep.min_marked_height_ft to thin it out."
        )

    unresolved = report["bindings"]["unresolved"]
    if unresolved:
        skipped = report["bindings"]["objects_skipped_total"]
        print()
        print(f"  Unresolved fixture bindings: {len(unresolved)}")
        print(f"  {skipped:,} object(s) were skipped because of them.")
        by_fixture = report["bindings"]["objects_skipped_by_fixture"]
        for name in unresolved:
            count = by_fixture.get(name, 0)
            print(f"    {name:<28} {count:>7,} skipped")
        print()
        print("  Fill these in at config/library_bindings.json - see docs/bindings.md.")

    if problems:
        print()
        for problem in problems:
            print(f"  ERROR: {problem}")


def _write(files, report, data, profile, root: Path) -> None:
    out_dir = profile.scenery_dir
    # Generated files only ever live here, so clearing the directory keeps a
    # renamed or removed feature from leaving a stale .xml behind that
    # fspackagetool would happily compile into the package.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    note = f"Generated by tools/build.py for {report['package']} {report['version']}."
    for scenery in files:
        (out_dir / scenery.filename).write_text(
            scenery.render(generator_note=note), encoding="utf-8"
        )

    build_dir = root / "build"
    build_dir.mkdir(exist_ok=True)
    (build_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if profile.write_preview:
        from .preview import write_preview

        write_preview(files, data, profile.preview_dir)

    # Keep the project and package-definition XML in step with the version in
    # config/package.json, so a bump cannot be applied to some files and not
    # others.
    from .packaging import write as write_packaging

    write_packaging(root)

    print()
    print(f"  Wrote {len(files)} scenery file(s) to {out_dir.relative_to(root)}/")
    print(f"  Build report: {(build_dir / 'report.json').relative_to(root)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build obstruction lighting scenery XML.")
    parser.add_argument("--dry-run", action="store_true", help="generate and report, write nothing")
    parser.add_argument("--quiet", action="store_true", help="suppress the per-feature report")
    args = parser.parse_args(argv)

    try:
        build(dry_run=args.dry_run, quiet=args.quiet)
    except DataError as exc:
        print(f"\nbuild failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
