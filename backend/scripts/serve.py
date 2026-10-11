"""Local launcher: python backend/scripts/serve.py [--demo real|synthetic] [--port 8000]

--demo real       replay of REAL captured Open-Meteo responses (fixtures/replay_delhi.json)
--demo synthetic  replay of the SYNTHETIC adverse-air scenario (fixtures/scenario_delhi_synthetic.json)
(no --demo)       live provider data
Local mode only: SQLite store, local dev sign-in, notifications prepared but not sent.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--demo", choices=["real", "synthetic"])
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--data-dir", default=None, help="separate SQLite/data dir (default: backend/.data or backend/.data-demo-*)")
a = ap.parse_args()
if a.demo:
    os.environ["DATA_MODE"] = "replay"
    os.environ["REPLAY_FILE"] = str(BACKEND / "fixtures" / ("replay_delhi.json" if a.demo == "real" else "scenario_delhi_synthetic.json"))
    os.environ.setdefault("DATA_DIR", str(BACKEND / f".data-demo-{a.demo}"))
if a.data_dir:
    os.environ["DATA_DIR"] = a.data_dir
sys.path.insert(0, str(BACKEND))

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=a.port)
