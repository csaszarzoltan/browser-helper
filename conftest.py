"""Pytest conftest.py — src/ layout path fix.

Ensures that tests can import from the src/ package directory.
This is MANDATORY for all src/ layout projects.
"""
import sys
from pathlib import Path

# Add src/ to Python path so tests can import the package
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))
