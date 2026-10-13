"""
Read-only discovery of Breww's Data Explorer API.

Makes GET requests ONLY (no /run/ calls, no exports), so nothing in Breww
is changed and nothing is queried at volume. Saves everything to
data_explorer_discovery.json in this folder; paste that file back to Claude.

Run from the dashboard folder (same place you run fetch_data.py):

    python data_explorer_discovery.py

Uses BREWW_API_KEY from your .env, same as fetch_data.py. The key never
leaves your machine and is not written to the output file.
"""

import json
import sys
import time

import requests

import config

OUTPUT_FILE = "data_explorer_discovery_2.json"
# Round 2: only the datasets the first pass missed (it hit its 15-dataset cap).
PRIORITY = ["products_sold", "sales", "delivery_collection", "racking", "beer",
            "entities", "contacts", "payment_refund", "credit_notes_lines"]
# Datasets whose names contain these words get their full field list pulled
# (plus their relations). Everything is listed regardless.
INTEREST_WORDS = ("order", "sale", "line", "invoice", "fulfil", "product",
                  "batch", "packag", "stock", "customer")
MAX_DATASETS_DETAILED = 15
MAX_RELATIONS_PER_DATASET = 12


def get(path, params=None):
    """GET with simple 429 backoff. Returns (status, json_or_text)."""
    url = config.BASE_URL.rstrip("/") + path
    headers = {
        "Authorization": f"{config.AUTH_HEADER_PREFIX} {config.BREWW_API_KEY}",
        "Accept": "application/json",
    }
    for attempt in range(4):
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:2000]
        return resp.status_code, body
    return 429, "rate limited after retries"


def dataset_names(listing):
    """Be tolerant of the listing shape: list of strings/dicts, or dict wrapper."""
    items = listing
    if isinstance(listing, dict):
        for key in ("results", "datasets", "data"):
            if isinstance(listing.get(key), list):
                items = listing[key]
                break
        else:
            items = list(listing.keys())
    names = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, str):
            names.append(it)
        elif isinstance(it, dict):
            n = it.get("dataset") or it.get("name") or it.get("slug") or it.get("id")
            if n:
                names.append(str(n))
    return names


def relation_names(detail):
    rels = []
    if isinstance(detail, dict):
        r = detail.get("relations")
        if isinstance(r, list):
            for it in r:
                if isinstance(it, str):
                    rels.append(it)
                elif isinstance(it, dict):
                    n = it.get("path") or it.get("relation") or it.get("name") or it.get("field")
                    if n:
                        rels.append(str(n))
        elif isinstance(r, dict):
            rels = list(r.keys())
    return rels


def main():
    if not config.BREWW_API_KEY:
        sys.exit("BREWW_API_KEY is not set - check your .env file.")

    out = {}

    print("Listing datasets...")
    status, listing = get("/data-explorer/")
    out["datasets_listing"] = {"status": status, "body": listing}
    if status != 200:
        print(f"  HTTP {status}: {str(listing)[:300]}")
        save(out)
        sys.exit("Could not list datasets - see the output file.")

    names = dataset_names(listing)
    print(f"  Found {len(names)} datasets: {', '.join(names)}")

    chosen = [n for n in PRIORITY if n in names]
    out["datasets_detailed"] = {}
    for n in chosen:
        print(f"Fetching fields for {n}...")
        status, detail = get(f"/data-explorer/{n}/")
        entry = {"status": status, "body": detail, "relations": {}}
        if status == 200:
            for rel in relation_names(detail)[:MAX_RELATIONS_PER_DATASET]:
                s, d = get(f"/data-explorer/{n}/", params={"relation": rel})
                entry["relations"][rel] = {"status": s, "body": d}
        out["datasets_detailed"][n] = entry

    print("Listing saved reports...")
    status, reports = get("/data-explorer/saved-reports/")
    out["saved_reports"] = {"status": status, "body": reports}

    save(out)
    print(f"\nDone. Paste the contents of {OUTPUT_FILE} back to Claude.")


def save(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    main()
