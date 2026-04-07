"""Configure sys.path so update_readme can be imported from scripts/."""

import sys
from pathlib import Path

# Insert scripts/ directory at front of sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
