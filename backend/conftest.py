"""pytest configuration — adds backend root to sys.path."""
import sys
from pathlib import Path

# Ensure the backend root is on sys.path so test imports work
backend_root = Path(__file__).parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))
