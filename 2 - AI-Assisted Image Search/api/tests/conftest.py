"""
Pytest configuration for api/tests/.

Ensures the api/ directory is on sys.path so `from app.xxx import yyy`
works regardless of where pytest is invoked from.
"""

import sys
import os

# api/ directory — contains the app package
_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# Project root — needed by search_core.py to import root-level vector_store.py
_PROJECT_ROOT = os.path.abspath(os.path.join(_API_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
