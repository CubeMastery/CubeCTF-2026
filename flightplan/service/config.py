import os
from pathlib import Path


DB_PATH = Path(os.environ.get("FLIGHTPLAN_DB", "/data/flightplan.db"))
AIRAC_SECRET = os.environ.get("AIRAC_SECRET", "north-atlantic-track-briefing-2026").encode()
PORTAL_NAME = "Cairn Flight Plan Exchange"
