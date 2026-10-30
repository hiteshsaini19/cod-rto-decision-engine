"""Fill the dashboard with demo data: September's real orders replayed as the last 30 days.

    python scripts/seed_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rto.demo import seed_demo  # noqa: E402

if __name__ == "__main__":
    print(seed_demo())
