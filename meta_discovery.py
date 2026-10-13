"""
Read-only discovery of your Meta (Facebook + Instagram) Graph API access.

GET requests only. Finds your Pages and linked Instagram accounts, then tries
a list of insight metrics ONE AT A TIME so we learn which ones your accounts
actually return. Saves meta_discovery.json - paste its contents back to Claude.

Setup: put your System User token in .env next to this file:

    META_ACCESS_TOKEN=EAAB...

Run:   python meta_discovery.py

Page access tokens that Meta returns are used in memory only and are never
written to the output file. Anything that looks like a token is redacted.
"""

import json
import os
import re
import sys
import time
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
VERSION = os.environ.get("META_API_VERSION", "v23.0")
BASE = f"https://graph.facebook.com/{VERSION}"
OUTPUT_FILE = "meta_discovery.json"

IG_ACCOUNT_METRICS = [  # account-level, daily totals
    "reach", "views", "profile_views", "accounts_engaged", "total_interactions",
    "likes", "comments", "shares", "saves", "replies", "follows_and_unfollows",
    "website_clicks",
]
IG_MEDIA_METRICS = ["reach", "views", "likes", "comments", "shares", "saved",
                    "total_interactions"]
PAGE_METRICS = [
    "page_follows", "page_daily_follows_unique", "page_daily_unfollows_unique",
    "page_media_view", "page_total_media_view_unique", "page_views_total",
    "page_post_engagements", "page_impressions", "page_impressions_unique",
    "page_fans", "page_fan_adds",
]

SECRET_RE = re.compile(r"EA[A-Za-z0-9]{20,}")


def redact(obj):
    s = json.dumps(obj)
    s = SECRET_RE.sub("[REDACTED]", s)
    return json.loads(s)


def get(path, params=None, token=None):
    p = dict(params or {})
    p["access_token"] = token or TOKEN
    for attempt in range(4):
        r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=60)
        if r.status_code == 429 or (r.status_code == 400 and
                                    '"code":4' in r.text.replace(" ", "")):
            time.sleep(2 ** attempt)
            continue
        try:
            body = r.json()
        except ValueError:
            body = r.text[:1000]
        return r.status_code, body
    return 429, "rate limited after retries"


def window():
    until = date.today()
    since = until - timedelta(days=28)
    return {"since": since.isoformat(), "until": until.isoformat()}


def try_metrics(node_id, metrics, extra, token):
    out = {}
    for m in metrics:
        status, body = get(f"{node_id}/insights", {"metric": m, **extra}, token)
        if status == 200 and isinstance(body, dict):
            data = body.get("data", [])
            sample = data[0] if data else None
            out[m] = {"ok": True, "sample": sample}
        else:
            err = body.get("error", body) if isinstance(body, dict) else body
            out[m] = {"ok": False, "error": err}
    return out


def main():
    if not TOKEN:
        sys.exit("META_ACCESS_TOKEN is not set - add it to your .env file.")
    out = {"api_version": VERSION, "window": window()}

    status, me = get("me", {"fields": "id,name"})
    out["me"] = {"status": status, "body": me}

    status, perms = get("me/permissions")
    out["permissions"] = {"status": status, "body": perms}

    status, pages = get("me/accounts", {
        "fields": ("id,name,access_token,fan_count,followers_count,"
                   "instagram_business_account{id,username,followers_count,"
                   "media_count}"),
        "limit": 25,
    })
    out["pages_status"] = status
    out["pages"] = []
    if status == 200 and not pages.get("data"):
        # Diagnostics for the "no Pages returned" case
        s1, biz = get("me/businesses", {"fields": "id,name"})
        out["diag_me_businesses"] = {"status": s1, "body": biz}
        out["diag_owned_pages"] = {}
        if s1 == 200 and isinstance(biz, dict):
            for b in biz.get("data", []):
                for edge in ("owned_pages", "client_pages"):
                    s2, d2 = get(f"{b['id']}/{edge}", {"fields": "id,name", "limit": 25})
                    out["diag_owned_pages"][f"{b.get('name')}/{edge}"] = {"status": s2, "body": d2}
        s3, dbg = get("debug_token", {"input_token": TOKEN})
        if s3 == 200 and isinstance(dbg, dict):
            d = dbg.get("data", {})
            out["diag_token_scopes"] = {"granular_scopes": d.get("granular_scopes"),
                                        "type": d.get("type")}
    if status != 200:
        out["pages_error"] = pages
        save(out)
        sys.exit("Could not list Pages - see the output file.")

    for pg in pages.get("data", []):
        page_token = pg.get("access_token") or TOKEN
        entry = {k: v for k, v in pg.items() if k != "access_token"}
        print(f"Page: {pg.get('name')}")
        entry["page_insights"] = try_metrics(
            pg["id"], PAGE_METRICS, {"period": "day", **window()}, page_token)
        ig = pg.get("instagram_business_account")
        if ig:
            print(f"  Instagram: {ig.get('username')}")
            ig_id = ig["id"]
            entry["ig_account_insights"] = try_metrics(
                ig_id, IG_ACCOUNT_METRICS,
                {"period": "day", "metric_type": "total_value", **window()},
                page_token)
            s, media = get(f"{ig_id}/media", {
                "fields": "id,media_type,media_product_type,timestamp,"
                          "like_count,comments_count,permalink",
                "limit": 5}, page_token)
            entry["ig_recent_media"] = {"status": s, "body": media}
            if s == 200 and media.get("data"):
                mid = media["data"][0]["id"]
                entry["ig_media_insights_for_latest"] = try_metrics(
                    mid, IG_MEDIA_METRICS, {}, page_token)
        out["pages"].append(entry)

    save(out)
    print(f"\nDone. Paste the contents of {OUTPUT_FILE} back to Claude.")


def save(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(redact(data), f, indent=2)


if __name__ == "__main__":
    main()
