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
import time

import pandas as pd

import config
from breww_client import BrewwClient, BrewwAPIError
from square_client import SquareClient, SquareAPIError
from meta_client import MetaClient, MetaAPIError
from datetime import date, timedelta


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

    print("Fetching Square catalog (for item categories) ...")
    try:
        catalog_objects = client.list_catalog()
        catalog_df = flatten(catalog_objects)
        catalog_path = os.path.join(config.DATA_DIR, "square_catalog.csv")
        catalog_df.to_csv(catalog_path, index=False)
        print(f"  {len(catalog_df)} catalog objects cached in {catalog_path}")
        results.append(("square_catalog", "ok", f"{len(catalog_df)} rows cached"))
    except SquareAPIError as e:
        # Not fatal - the Square tab just shows "Uncategorized" for
        # everything if this is missing, it doesn't need the catalog
        # to show orders/sales at all.
        print(f"  Skipped Square catalog (categories will show as Uncategorized): {e}")
        results.append(("square_catalog", "skipped", str(e)))

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


def _since_date(existing_df, buffer_days, backfill_days):
    """Where a date-keyed pull should start: the day after nothing (a full
    backfill) if there's no cache yet, otherwise buffer_days before the
    newest cached date, so recent days Meta is still finalizing get
    re-checked and replaced."""
    today = date.today()
    if existing_df is not None and "date" in existing_df.columns:
        newest = pd.to_datetime(existing_df["date"], errors="coerce").max()
        if pd.notna(newest):
            return max(newest.date() - timedelta(days=buffer_days), today - timedelta(days=backfill_days))
    return today - timedelta(days=backfill_days)


def _save_date_keyed(path, new_rows, existing_df):
    new_df = pd.DataFrame(new_rows)
    merged = merge_cache(existing_df, new_df, id_col="date")
    if "date" in merged.columns:
        merged = merged.sort_values("date")
    merged.to_csv(path, index=False)
    return new_df, merged


def fetch_meta_data(results):
    """Pull Facebook Page and Instagram data for the Social tab. Each
    piece (Facebook daily, Instagram daily, Instagram follower snapshot,
    Instagram posts) is fetched and cached independently, so one failing
    - e.g. a metric Meta retires - never costs the others.

    Not configured (no META_PAGE_TOKEN) is a skip, not a failure."""
    if not config.META_PAGE_TOKEN:
        print("No META_PAGE_TOKEN set - skipping Facebook/Instagram data (see README, Social tab).")
        return

    try:
        client = MetaClient()
        acct = client.get_account()
    except MetaAPIError as e:
        print(f"Meta setup problem: {e}")
        results.append(("meta_account", "skipped", str(e)))
        return
    print(f"Meta: Page '{acct['page_name']}'" + (f", Instagram @{acct['ig_username']}" if acct["ig_id"] else ", no Instagram account linked"))

    # --- Facebook daily ---
    fb_path = os.path.join(config.DATA_DIR, "social_fb_daily.csv")
    try:
        existing = load_cache(fb_path)
        since = _since_date(existing, config.META_INCREMENTAL_BUFFER_DAYS, config.META_FB_BACKFILL_DAYS)
        print(f"Fetching Facebook daily metrics from {since} ...")
        rows = client.fb_daily(acct["page_id"], since, date.today())
        new_df, merged = _save_date_keyed(fb_path, rows, existing)
        print(f"  {len(new_df)} days fetched -> {len(merged)} total cached in {fb_path}")
        results.append(("meta_fb_daily", "ok", f"{len(merged)} rows cached"))
    except MetaAPIError as e:
        print(f"  Skipped Facebook daily: {e}")
        results.append(("meta_fb_daily", "skipped", str(e)))

    if not acct["ig_id"]:
        return

    # --- Instagram follower snapshot (Instagram only reports today's count) ---
    snap_path = os.path.join(config.DATA_DIR, "social_ig_followers.csv")
    try:
        snap = client.ig_snapshot(acct["ig_id"])
        today_et = pd.Timestamp.now(tz="UTC").tz_convert("America/New_York").strftime("%Y-%m-%d")
        existing = load_cache(snap_path)
        _, merged = _save_date_keyed(
            snap_path, [{"date": today_et, **snap}], existing)
        print(f"  Instagram followers today: {snap['followers_count']} ({len(merged)} daily snapshots cached)")
        results.append(("meta_ig_followers", "ok", f"{len(merged)} snapshots cached"))
    except MetaAPIError as e:
        print(f"  Skipped Instagram follower snapshot: {e}")
        results.append(("meta_ig_followers", "skipped", str(e)))

    # --- Instagram daily ---
    ig_path = os.path.join(config.DATA_DIR, "social_ig_daily.csv")
    try:
        existing = load_cache(ig_path)
        since = _since_date(existing, config.META_INCREMENTAL_BUFFER_DAYS, config.META_IG_BACKFILL_DAYS)
        yesterday = date.today() - timedelta(days=1)  # today is still incomplete
        print(f"Fetching Instagram daily metrics from {since} ...")
        rows = client.ig_daily(acct["ig_id"], since, yesterday)
        gains = client.ig_follower_gain(acct["ig_id"])
        for r in rows:
            if r["date"] in gains:
                r["follower_gain"] = gains[r["date"]]
        new_df, merged = _save_date_keyed(ig_path, rows, existing)
        print(f"  {len(new_df)} days fetched -> {len(merged)} total cached in {ig_path}")
        results.append(("meta_ig_daily", "ok", f"{len(merged)} rows cached"))
    except MetaAPIError as e:
        print(f"  Skipped Instagram daily: {e}")
        results.append(("meta_ig_daily", "skipped", str(e)))

    # --- Instagram posts ---
    posts_path = os.path.join(config.DATA_DIR, "social_ig_posts.csv")
    try:
        existing = load_cache(posts_path)
        refresh_cutoff = (date.today() - timedelta(days=config.META_POST_REFRESH_DAYS)).isoformat()
        print("Fetching Instagram posts" + (f" (refreshing numbers for posts since {refresh_cutoff})" if existing is not None else " (full history - first run)") + " ...")
        posts = client.ig_media(acct["ig_id"], stop_before=refresh_cutoff if existing is not None else None)
        have_insights = set()
        if existing is not None and "reach" in existing.columns:
            have_insights = set(existing.loc[existing["reach"].notna(), "id"].astype(str))
        rows = []
        for p in posts:
            ts = (p.get("timestamp") or "")[:10]
            row = {
                "id": str(p["id"]), "timestamp": p.get("timestamp"),
                "media_type": p.get("media_type"), "product_type": p.get("media_product_type"),
                "permalink": p.get("permalink"),
                "caption": (p.get("caption") or "")[:140].replace("\n", " "),
                "like_count": p.get("like_count"), "comments_count": p.get("comments_count"),
            }
            if ts >= refresh_cutoff or str(p["id"]) not in have_insights:
                try:
                    row.update(client.ig_post_insights(p["id"]))
                except MetaAPIError as e:
                    if "rejected the token" in str(e):
                        raise
                time.sleep(0.15)
            else:
                prev = existing[existing["id"].astype(str) == str(p["id"])]
                if not prev.empty:
                    for k in ("reach", "views", "saved", "shares", "total_interactions"):
                        if k in prev.columns:
                            row[k] = prev.iloc[0][k]
            rows.append(row)
        new_df = pd.DataFrame(rows)
        merged = merge_cache(existing, new_df, id_col="id")
        if "timestamp" in merged.columns:
            merged = merged.sort_values("timestamp")
        merged.to_csv(posts_path, index=False)
        print(f"  {len(new_df)} posts fetched/refreshed -> {len(merged)} total cached in {posts_path}")
        results.append(("meta_ig_posts", "ok", f"{len(merged)} rows cached"))
    except MetaAPIError as e:
        print(f"  Skipped Instagram posts: {e}")
        results.append(("meta_ig_posts", "skipped", str(e)))


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
    fetch_meta_data(results)

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
