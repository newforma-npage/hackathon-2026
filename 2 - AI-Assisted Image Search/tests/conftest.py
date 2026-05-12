"""
Shared pytest configuration for the top-level tests/ directory.

Adds the project root and app/ directory to sys.path so that both
  - the root-level vector_store.py (used by test_vector_store*.py)
  - app/backend/* (used by test_ingest_e2e.py)
are importable without installing the project as a package.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")

for p in [PROJECT_ROOT, APP_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
