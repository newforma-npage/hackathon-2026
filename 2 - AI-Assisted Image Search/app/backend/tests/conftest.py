import sys
import os

# Ensure the backend package is importable when pytest is run from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
