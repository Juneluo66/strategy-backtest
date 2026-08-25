"""Ensure this track does not import sector_momentum strategy code."""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "us_sector_equal_weight"


def test_no_us_sector_momentum_imports():
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "us_sector_momentum" in alias.name:
                        offenders.append(str(path))
            if isinstance(node, ast.ImportFrom):
                if node.module and "us_sector_momentum" in node.module:
                    offenders.append(str(path))
    assert not offenders


def test_no_topn_or_momentum_signal_modules():
    names = {p.name for p in SRC.glob("*.py")}
    assert "signals.py" not in names
