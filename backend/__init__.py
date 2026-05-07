# backend package — adds this directory to sys.path so all intra-package
# imports continue to work as bare names (e.g. "from schema import ...").
import sys
from pathlib import Path

_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
