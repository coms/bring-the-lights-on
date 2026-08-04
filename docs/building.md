# Building and installing

Two stages, with different requirements:

1. **Generate the scenery XML** — Python 3.11+, any OS, no dependencies.
2. **Compile it into a package** — Windows, plus the MSFS 2024 SDK.

The generated XML is committed, so if someone else has run stage 1 you can go
straight to stage 2.

## Stage 1: generate

```
python -m tools.tasks build
```

Reads `data/` and `config/`, writes `PackageSources/scenery/*.xml`, a build
report to `build/report.json`, and regenerates the project and package
definition XML so a version bump in `config/package.json` cannot be applied to
some files and not others.

```
$ python -m tools.tasks build
Bring The Lights On 0.1.0 - Greater Hartford, CT

  9 structure(s) marked
  Objects by feature
    obstructions               117
    TOTAL                      117
```

Useful variations:

| Command | What it does |
|---|---|
| `python -m tools.tasks dry-run` | Generate and report, write nothing |
| `python -m tools.tasks check` | Validate, test, dry run — the pre-commit gate |
| `python -m tools.tasks preview` | Build, plus `build/preview/plan.svg` |
| `python -m tools.tasks clean` | Remove everything generated |

`make build` and friends work identically. On Windows the bundled `make.cmd`
means `make` works with nothing installed, because cmd.exe resolves `make` to it
from the repository root. If you have moved the repo or are calling from another
directory, use the `python -m tools.tasks` form.

### Installing pytest

`check` runs the test suite, which needs pytest:

```
python -m pip install pytest
```

Nothing else in the toolchain has a dependency.

## Stage 2: compile

You need MSFS 2024 and its SDK. The SDK is installed from inside the sim:
**Options → General → Developers → DevMode on**, then **DevMode → Help → SDK
Installer**.

`fspackagetool.exe` lives in the SDK's `Tools` directory, usually:

```
C:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe
```

From the repository root:

```
"C:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe" bring-the-lights-on.xml
```

That produces `Packages\coms-bring-the-lights-on\`. Copy the whole folder into
your Community folder:

| Store | Path |
|---|---|
| Steam | `%APPDATA%\Microsoft Flight Simulator 2024\Packages\Community` |
| MS Store | `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community` |
| Boxed/other | Check `UserCfg.opt` for `InstalledPackagesPath` |

Restart the sim.

## Troubleshooting

**`fspackagetool` rejects the project or package XML.** The SDK has revised these
formats between releases. Generate a project with the SDK's own template tool on
your install, diff it against `bring-the-lights-on.xml` and
`PackageDefinitions/coms-bring-the-lights-on.xml`, and adjust
`tools/packaging.py` — the `Version` attributes are the usual culprit.

**It compiles but nothing appears.** Almost always unresolved fixture bindings.
Run `python -m tools.tasks bindings`; anything unbound is skipped silently by
design. See [bindings.md](bindings.md).

**Every light is lying on the ground.** `snapToGround` is being applied to
objects that have an AGL height. `tools/validate.py` checks for this — run
`python -m tools.tasks validate` and it will name the objects.

**Lights appear in the wrong place, or doubled.** If doubled, the sim is
probably lighting the structure itself; see the duplicate-lighting section of
[data-sources.md](data-sources.md). If simply wrong, check the entry's `source`
field and look the OSM object up.

**The build fails with "fell outside the declared region".** An entry's
coordinates are outside `region` in `data/region.json` — usually a dropped minus
sign on the longitude. The error names the entry.
