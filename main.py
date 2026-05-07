# Root entry-point shim — delegates to backend/cli.py.
# Run:  python main.py --demo
# API:  uvicorn backend.api:app --reload
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
