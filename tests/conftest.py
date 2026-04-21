"""Pytest configuration for x12-parser tests.

This ensures the src module is importable regardless of where tests are run from.
"""
import os
import pathlib
import sys

# Add repo root to path so `python -m src.validate` works from tests
_REPO_ROOT = pathlib.Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Set PYTHONPATH for any subprocess tests that spawn new Python processes
os.environ['PYTHONPATH'] = str(_REPO_ROOT)
