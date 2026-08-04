"""Shared fixtures.

The repo root goes on sys.path so `import tools` works when pytest is run from
anywhere, which is what `python -m tools.tasks test` does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.generators.common import Context  # noqa: E402
from tools.geo import Point  # noqa: E402
from tools.model import load_all  # noqa: E402

STUB_GUID = "{11111111-2222-3333-4444-555555555555}"


@pytest.fixture
def bound_context():
    """A build context with every fixture bound, so nothing is skipped.

    Most placement tests want to count objects, and an unresolved binding
    silently produces zero of them - which would make every such test pass for
    the wrong reason.
    """
    data = load_all()
    for spec in data["bindings"].fixtures.values():
        spec["resolved"] = True
        if spec["kind"] == "library_object":
            spec["guid"] = STUB_GUID
        else:
            spec["effect_name"] = "Stub_Effect"
    return Context(
        region=data["region"], bindings=data["bindings"],
        profile=data["profile"], data=data,
    )


@pytest.fixture
def marking_schemes():
    """The shipped marking schemes, as the generator sees them."""
    return load_all()["obstructions"]
