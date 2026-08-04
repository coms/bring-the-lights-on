"""Scenery generators.

There is only one, and it is the point of the package: obstruction marking on
tall structures. Generators never touch disk and never touch the network, so
the whole placement pipeline is directly testable.
"""

from . import obstructions

__all__ = ["obstructions"]
