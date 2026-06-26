import yaml
import outreach_quality as oq
import database as db

db.init_db()
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)
stats = oq.purge_non_employer_targets(config)
sendable = db.get_sendable_companies(config.get("automation", {}).get("target_cities"))
print("purge", stats)
print("sendable", len(sendable))
print("auto_send", config.get("automation", {}).get("auto_send"))
print("max_per_day", config.get("sending", {}).get("max_per_day"))
