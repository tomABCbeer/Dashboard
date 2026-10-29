"""
Read-only check of why batches are missing from the Batch Packaging table.
Only makes GET requests. Run from the dashboard folder:

    python3 packaging_probe.py

Prints a summary and saves packaging_probe.json - attach that file back.
"""
import json
import time

import pandas as pd

from breww_client import BrewwClient

c = BrewwClient()
out = {}


def count(path, **params):
    time.sleep(1.1)
    r = c.session.get(c.base_url + path, params={"page_size": 1, **params})
    r.raise_for_status()
    return r.json().get("count")


print("Counting batch actions by type in Breww ...")
out["actions_all"] = count("/drink-batch-actions/")
out["actions_by_type"] = {t: count("/drink-batch-actions/", action_type=t) for t in range(1, 15)}
print("  all actions:", out["actions_all"])
print("  by type:", {k: v for k, v in out["actions_by_type"].items() if v})

out["batches_total"] = count("/drink-batches/")
out["batches_by_status"] = {s: count("/drink-batches/", status=s) for s in (1, 2, 3)}
print("  batches:", out["batches_total"], out["batches_by_status"])

cache = pd.read_csv("data/drink_batch_actions.csv")
batches = pd.read_csv("data/batches.csv")
have = set(cache["drink_batch.id"].dropna().astype(int))
missing = batches[~batches["id"].isin(have)].copy()
missing = missing[pd.to_numeric(missing["status"], errors="coerce").isin([2, 3])]
missing = missing.sort_values("datetime_started", ascending=False)
print(f"\nStarted/complete batches with NO packaging row in the table: {len(missing)} of {len(batches)}")
out["missing_count"] = len(missing)
out["missing_sample"] = missing[["id", "batch_code", "drink.name", "datetime_started", "status"]].head(25).to_dict("records")
for r in out["missing_sample"][:8]:
    print("  ", r["batch_code"], "|", r["drink.name"], "|", str(r["datetime_started"])[:10])

print("\nWhat Breww has on the first few missing batches:")
out["missing_detail"] = {}
for r in out["missing_sample"][:4]:
    code = str(r["batch_code"])
    time.sleep(1.1)
    resp = c.session.get(c.base_url + "/drink-batch-actions/", params={"drink_batch_code": code, "page_size": 100})
    resp.raise_for_status()
    rows = resp.json().get("results", [])
    summary = [{"type": a.get("action_type"), "done": a.get("datetime_done"),
                "product": (a.get("initial_product") or {}).get("name"),
                "litres": (a.get("volume_successful") or {}).get("litre")} for a in rows]
    out["missing_detail"][code] = summary
    print(f"  {code}: {[(s['type'], s['product']) for s in summary]}")

with open("packaging_probe.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print("\nSaved packaging_probe.json - attach it here.")
