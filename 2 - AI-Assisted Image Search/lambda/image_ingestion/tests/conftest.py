import sys
import os

# Add the lambda handler directory to sys.path so `import handler` works
# regardless of where pytest is invoked from.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
