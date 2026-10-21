"""Esegue il motore completo contro il server ESPN finto, in una cartella temporanea."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
os.makedirs(tmp, exist_ok=True)
cfg = json.load(open(os.path.join(ROOT, "config.json")))
cfg["soccer"]["leagues"] = {"ita.1": "Serie A", "eng.1": "Premier League"}
cfg["nba"]["backfill_days"] = 150
cfg["soccer"]["backfill_days"] = 200
cfg["request_pause_seconds"] = 0
for k in ("nfl", "mlb", "tennis"):
    if k in cfg:
        cfg[k]["backfill_days"] = 200
cfg["max_summaries_per_run"] = int(os.environ.get("MAXS", "5000"))
json.dump(cfg, open(os.path.join(tmp, "config.json"), "w"))
os.environ["VALORE_CONFIG"] = os.path.join(tmp, "config.json")
os.environ["VALORE_DATA"] = os.path.join(tmp, "data")
os.environ["VALORE_OUT"] = os.environ.get("VALORE_OUT", os.path.join(tmp, "out"))
os.environ.pop("ODDS_API_KEY", None)

from tests import fake_espn  # noqa: E402
from engine import espn, run  # noqa: E402

import datetime as dt  # noqa: E402
idx_path = os.path.join(tmp, "fake_index.json")
if os.path.exists(idx_path):
    for k, (sp, d, h, a) in json.load(open(idx_path)).items():
        fake_espn.EVENT_INDEX[k] = (sp, dt.date.fromisoformat(d), tuple(h), tuple(a))
espn.get_json = fake_espn.fake_get_json
from engine import tennis  # noqa: E402
tennis.get_json = fake_espn.fake_get_json
sys.argv = ["run"]
run.main()
json.dump({k: (sp, d.isoformat(), h, a) for k, (sp, d, h, a) in fake_espn.EVENT_INDEX.items()}, open(idx_path, "w"))
print("output in", tmp)
