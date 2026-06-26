import sys
from pathlib import Path

_script = Path(__file__).resolve()
_root = _script.parents[2] if len(_script.parents) > 2 else _script.parent
if not (_root / "outreach_quality.py").exists():
    _root = _script.parent
sys.path.insert(0, str(_root))

import yaml
import outreach_quality as oq
import database as db

db.init_db()
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

before = db.get_stats()
result = oq.purge_all_non_employers(config)
after = db.get_stats()
cities = config.get("automation", {}).get("target_cities")
sendable = db.get_sendable_companies(cities)

print("before_total", before.get("total"))
print("purge", result)
print("after_total", after.get("total"))
print("sendable", len(sendable))
print("email_found", after.get("email_found", 0))
print("no_email", after.get("no_email", 0))
