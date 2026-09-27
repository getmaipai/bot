"""The profile is the sole source of this body's limits.

Every numeric limit `profile.py` declares is looked up by walking its own
AST for numeric literals; every other source file under `maipai_body` is
then walked the same way, and the test fails if any of those same literals
shows up outside `profile.py`. Small generic numbers (0, 1, 2 and their
negatives) are excluded: they are ordinary code (a duration, an index), not
a copied envelope limit.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "maipai_body"
PROFILE_FILE = PACKAGE_ROOT / "bodies" / "reachy_mini" / "profile.py"

_SAFE_LITERALS = {0.0, 1.0, 2.0, -1.0, -2.0}


def _numeric_literals(path: Path) -> set[float]:
    tree = ast.parse(path.read_text(), filename=str(path))
    literals: set[float] = set()
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operand = node.operand
            if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)):
                if not isinstance(operand.value, bool):
                    value = -float(operand.value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if not isinstance(node.value, bool):
                value = float(node.value)
        if value is not None:
            literals.add(value)
    return literals


def test_profile_is_sole_source_of_limits() -> None:
    limit_literals = _numeric_literals(PROFILE_FILE) - _SAFE_LITERALS
    assert limit_literals, "profile.py declares no numeric limits to check against"

    offenders: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if path == PROFILE_FILE:
            continue
        collision = _numeric_literals(path) & limit_literals
        if collision:
            offenders.append(f"{path.relative_to(PACKAGE_ROOT.parent)}: {sorted(collision)}")

    assert not offenders, "a profile limit is duplicated outside profile.py:\n" + "\n".join(
        offenders
    )
