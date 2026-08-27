"""
Pull data from the Breww API and cache it to CSV files in DATA_DIR.

The first time an endpoint is fetched (no CSV cached yet), it pulls the
endpoint's FULL history. On every run after that, it only asks Breww
for rows that are new or changed since the cache was last updated (see
"incremental_field" in config.py), and merges those into the existing
cache - old rows are always kept, and a row that comes back again (same
id) simply replaces its older copy rather than duplicating it.

Run this on a schedule (e.g. daily) to keep the cache current without
re-pulling everything each time.

Usage:
    python fetch_data.py
"""

import os
import sys
import json

import pandas as pd

import config
from breww_client import BrewwClient, BrewwAPIError


def flatten(records):
    """Flatten nested objects (e.g. customer.name, drink.name,
    stock_item.name) into dotted columns, and turn any remaining
    list-type fields (e.g. order_lines) into JSON strings so they
    survive a round trip through CSV."""
    if not records:
        return pd.DataFrame()
    df = pd.json_normalize(records)
    for col in df.columns:
        if df[col].apply(lambda v: isinstance(v, (list, dict))).any():
            df[col] = df[col].apply(
                lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v
            )
    return df


def load_cache(path):
    """Load an existing cache CSV. Returns None if there isn't one yet,
    or it's empty - either way that means "do a full pull"."""
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return None
    return df if not df.empty else None


def latest_value(df, field, buffer_days=0):
    """Return the max value of `field` in the cached data, minus a
    buffer (to re-check recent rows for updates), as an ISO string -
    or None if the field isn't usable."""
    if df is None or field not in df.columns:
        return None
    values = pd.to_datetime(df[field], errors="coerce", utc=True).dropna()
    if values.empty:
        return None
    cutoff = values.max() - pd.Timedelta(days=buffer_days)
    return cutoff.isoformat()


def merge_cache(existing_df, new_df, id_col="id"):
    """Combine cached rows with freshly fetched rows. Every existing
    row is kept; if a freshly fetched row has the same id as a cached
    one (it was updated in Breww since we last pulled it), the fresh
    version wins."""
    if existing_df is None or existing_df.empty:
        return new_df
    if new_df.empty:
        return existing_df
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    if id_col in combined.columns:
        combined = combined.drop_duplicates(subset=id_col, keep="last")
    return combined


def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)

    try:
        client = BrewwClient()
    except BrewwAPIError as e:
        print(f"Setup problem: {e}")
        sys.exit(1)

    results = []  # (name, "ok" | "skipped", detail)

    for name, spec in config.ENDPOINTS.items():
        if not spec.get("enabled"):
            continue

        out_path = os.path.join(config.DATA_DIR, f"{name}.csv")
        existing_df = load_cache(out_path)

        incremental_field = spec.get("incremental_field")
        buffer_days = spec.get("buffer_days", 0)

        params = dict(spec.get("extra_params", {}))
        since = latest_value(existing_df, incremental_field, buffer_days) if incremental_field else None
        if since:
            params[f"{incremental_field}__gte"] = since
            print(f"Fetching {name} from {spec['path']} (changed since {since}) ...")
        else:
            if existing_df is None:
                reason = "no cache yet"
            elif not incremental_field:
                reason = "this endpoint has no incremental option, always pulled in full"
            else:
                reason = f"no usable {incremental_field} in cache"
            print(f"Fetching {name} from {spec['path']} (full pull - {reason}) ...")

        try:
            records = client.get_all(spec["path"], params=params)
        except BrewwAPIError as e:
            print(f"  Skipped {name}: {e}")
            results.append((name, "skipped", str(e)))
            continue

        new_df = flatten(records)
        merged_df = merge_cache(existing_df, new_df)

        if "id" in merged_df.columns:
            merged_df = merged_df.sort_values("id")

        merged_df.to_csv(out_path, index=False)
        prev_total = len(existing_df) if existing_df is not None else 0
        print(
            f"  {len(new_df)} new/updated rows fetched -> "
            f"{len(merged_df)} total rows cached (was {prev_total}) in {out_path}"
        )
        results.append((name, "ok", f"{len(merged_df)} rows cached"))

    any_success = any(status == "ok" for _, status, _ in results)

    print("\n--- Summary ---")
    for name, status, detail in results:
        marker = "OK" if status == "ok" else "SKIPPED"
        print(f"  [{marker}] {name}: {detail}")

    if not any_success:
        print(
            "\nNo endpoints returned data. If every endpoint failed the same "
            "way, it's probably auth (check your .env / BREWW_API_KEY) rather "
            "than the endpoint paths, since those are taken directly from "
            "Breww's OpenAPI spec."
        )
        print("\nDone (with errors).")
        sys.exit(1)

    skipped = [name for name, status, _ in results if status == "skipped"]
    if skipped:
        print(f"\nDone, but {len(skipped)} endpoint(s) were skipped: {', '.join(skipped)}. See details above.")
    else:
        print("\nDone. All endpoints fetched successfully.")


if __name__ == "__main__":
    main()
