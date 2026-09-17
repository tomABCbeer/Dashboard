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
from square_client import SquareClient, SquareAPIError


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


def fetch_square_data(results):
    """Pull Square location and order data for the Square tab's "what
    did we sell that needs a manual Breww reconciliation" report.

    Genuinely different shape than the generic Breww endpoint loop
    above, so it's handled separately rather than forced into that
    same loop: it's a two-step process (locations first, since
    SearchOrders needs their IDs), and Square's SearchOrders is a POST
    with a cursor in the response body, not Breww's GET-with-query-
    params pagination. Appends its own entries to the same `results`
    list the Breww loop uses, so both flow through the same summary
    printing and success/failure check at the end of main() without
    needing special-casing there.

    If SQUARE_ACCESS_TOKEN isn't set at all, this is treated as "the
    Square tab isn't configured yet" rather than a failure - most
    people running this dashboard for the first time won't have it
    set, and that's fine; the tab just shows a "not configured" message
    until it is."""
    if not config.SQUARE_ACCESS_TOKEN:
        print("No SQUARE_ACCESS_TOKEN set - skipping Square data (set it in .env to enable the Square tab).")
        return

    try:
        client = SquareClient()
    except SquareAPIError as e:
        print(f"Square setup problem: {e}")
        results.append(("square_orders", "skipped", str(e)))
        return

    print("Fetching Square locations ...")
    try:
        locations = client.list_locations()
    except SquareAPIError as e:
        print(f"  Skipped Square locations: {e}")
        results.append(("square_locations", "skipped", str(e)))
        return

    locations_df = flatten(locations)
    locations_path = os.path.join(config.DATA_DIR, "square_locations.csv")
    locations_df.to_csv(locations_path, index=False)
    print(f"  {len(locations_df)} locations cached in {locations_path}")
    results.append(("square_locations", "ok", f"{len(locations_df)} rows cached"))

    location_ids = [loc["id"] for loc in locations if loc.get("id")]
    if not location_ids:
        print("  No Square locations found - skipping orders (nothing to search).")
        return

    orders_path = os.path.join(config.DATA_DIR, "square_orders.csv")
    existing_df = load_cache(orders_path)
    since = latest_value(existing_df, "updated_at", config.SQUARE_INCREMENTAL_BUFFER_DAYS)
    if since:
        print(f"Fetching Square orders (updated since {since}) ...")
    else:
        print("Fetching Square orders (full pull - ALL history, no cache yet - this only happens once, but may take a while) ...")

    try:
        orders = client.search_orders(location_ids=location_ids, updated_since=since)
    except SquareAPIError as e:
        print(f"  Skipped Square orders: {e}")
        results.append(("square_orders", "skipped", str(e)))
        return

    new_df = flatten(orders)
    merged_df = merge_cache(existing_df, new_df)
    if "id" in merged_df.columns:
        merged_df = merged_df.sort_values("id")
    merged_df.to_csv(orders_path, index=False)
    prev_total = len(existing_df) if existing_df is not None else 0
    print(f"  {len(new_df)} new/updated orders fetched -> {len(merged_df)} total cached (was {prev_total}) in {orders_path}")
    results.append(("square_orders", "ok", f"{len(merged_df)} rows cached"))


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

    fetch_square_data(results)

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
