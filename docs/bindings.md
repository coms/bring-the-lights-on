# Fixture bindings

This package decides where every light goes. It does not ship the models and
effects that decide what each one looks like. `config/library_bindings.json`
is where you connect the two.

There are three fixtures. One ships bound; two do not.

| Fixture | Kind | What it is | State |
|---|---|---|---|
| `obstruction_red_beacon` | effect | Flashing red beacon for the top of a structure. FAA L-864: red, 20–40 flashes per minute. | **unbound** |
| `obstruction_red_steady` | effect | Steady red side light, ringed at intermediate levels. FAA L-810: steady-burning, not flashing. | **unbound** |
| `obstruction_white_strobe` | library object | Medium-intensity white strobe, FAA L-865. | bound |

Bind the red beacon first. It is one object per structure and it is what makes a
mast readable at night; the side lights are detail on top of it.

## Why nothing is invented

A fabricated GUID produces a package that compiles without complaint and then
draws nothing at all, with no error to tell you why. An empty field and a
message saying it is empty is a much better afternoon.

```
$ python -m tools.tasks bindings
1/3 fixture bindings resolved

  --  obstruction_red_beacon     (effect, not set)
  --  obstruction_red_steady     (effect, not set)
  ok  obstruction_white_strobe   {32b6e309-c93f-43b8-af78-109b96126fff}
```

Unresolved fixtures are skipped, not faked. A build with unresolved fixtures is
a valid partial build — everything already bound still renders. Once you believe
they are all filled in, set `bindings.on_unresolved` to `"error"` in
`config/build_profile.json` so a regression cannot slip through silently.

## Finding the values

**Library objects** need a GUID from a model library the sim has loaded. Sources,
in the order most people find them:

1. **The MSFS SDK sample libraries.** With the SDK installed, open the DevMode
   Object Inspector, filter for `obstruction`, `beacon`, `hazard` or `strobe`,
   and copy the GUID of anything that looks right. The keywords in each fixture's
   `keywords` field are there to search with.
2. **A third-party library you already have.** Many freeware lighting packs ship
   a ModelLib full of exactly these fixtures. The GUIDs are in its `.xml`.
3. **Your own ModelLib.** If you are building models anyway, this is the tidiest
   answer — you control the LOD and the light cone.

**Effects** need the name of an effect in an EffectLibrary the sim has loaded,
not a GUID. Red obstruction lighting is usually better as an effect than as a
model: a flashing light is a behaviour, and an effect can carry the flash rate
without you animating anything.

## Setting one

Either edit the JSON directly, or use the CLI, which validates as it goes and
cannot leave the file in the "marked resolved but empty" state:

```
python -m tools.bind obstruction_red_beacon --effect "MyLib_ObstructionBeacon_Red"
python -m tools.bind obstruction_white_strobe --guid "{32b6e309-...}"
python -m tools.bind obstruction_red_steady --clear
python -m tools.bind --list
```

Braces on a GUID are optional — the SDK's object browser copies them without, so
they are added for you.

## Checking it worked

Build, install, and fly a night circuit past something you know is marked. What
you are looking for:

- The beacon is **on top of** the structure, not at its base. If every light in
  the package is lying on the terrain, `snapToGround` is being applied to
  objects with an AGL height — the validator has a check for exactly this.
- The flash rate reads as a beacon rather than a strobe.
- Side lights ring the structure rather than clustering on one face.
