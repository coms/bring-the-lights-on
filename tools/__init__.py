"""Build toolchain for the Bring The Lights On MSFS 2024 package.

Nothing here talks to the simulator. The tools sweep OpenStreetMap for tall
structures, emit MSFS scenery XML into PackageSources/, and check their own
output. Compiling that into a .bgl and a distributable package is
`fspackagetool`'s job, and it needs Windows and the MSFS SDK - see
docs/building.md.
"""

__version__ = "0.1.0"
