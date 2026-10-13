"""
Minimal client for Meta's Graph API - Facebook Page and Instagram
(Business/Creator) insights, read-only (GET requests only).

Behavior this is built around (all confirmed against the real account
by meta_discovery.py, not guessed):
  - Auth: a Page access token (config.META_PAGE_TOKEN), sent as the
    access_token query parameter. A Page token can read BOTH the Page's
    own insights and its linked Instagram account's insights.
  - Facebook Page insights come back as a daily series. Each value's
    "end_time" is when that day's period ENDS (midnight Pacific, the
    Page's insights timezone), so the value belongs to the day BEFORE
    end_time - _period_date() handles that.
  - Instagram account insights (reach, views, ...) come back as ONE
    total for whatever since/until window is asked for, not a daily
    series - so this asks one day at a time to build a daily series.
  - Meta retired Facebook's older "impressions" and "fans" metrics;
    the replacements used here are page_media_view ("Facebook views")
    and page_follows.
  - Requesting several metrics at once is faster, but one rejected
    metric fails the whole request - so every multi-metric call falls
    back to asking one metric at a time and keeps whatever works.
  - Rate limiting shows up as HTTP 429 or Meta error codes 4/17/32/613
    (and 80004 for Instagram) - retried with exponential backoff.
"""

import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import config


class MetaAPIError(Exception):
    pass


_TOKEN_RE = re.compile(r"EA[A-Za-z0-9]{20,}")
_RATE_CODES = {4, 17, 32, 613, 80004}
_PACIFIC = ZoneInfo("America/Los_Angeles")

FB_METRICS = {
    "page_follows": "page_follows",
    "page_daily_follows_unique": "follows",
    "page_daily_unfollows_unique": "unfollows",
    "page_media_view": "views",
    "page_total_media_view_unique": "unique_viewers",
    "page_views_total": "page_visits",
    "page_post_engagements": "engagements",
}
IG_DAILY_METRICS = [
    "reach", "views", "profile_views", "accounts_engaged", "total_interactions",
    "likes", "comments", "shares", "saves", "replies", "website_clicks",
]
IG_POST_METRICS = ["reach", "views", "saved", "shares", "total_interactions"]


def _redact(text):
    return _TOKEN_RE.sub("[REDACTED]", str(text))


def _period_date(end_time):
    """'2026-09-16T07:00:00+0000' (the END of a Pacific-time day) -> the
    date of the day that period covers, as 'YYYY-MM-DD'."""
    dt = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    return (dt - timedelta(days=1)).astimezone(_PACIFIC).date().isoformat()


def _daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class MetaClient:
    def __init__(self, token=None, version=None):
        self.token = token or config.META_PAGE_TOKEN
        self.version = version or config.META_API_VERSION
        if not self.token:
            raise MetaAPIError(
                "No Meta token found. Set META_PAGE_TOKEN (see the README's "
                "Social tab section / meta_make_permanent_token.py)."
            )
        self.base = f"https://graph.facebook.com/{self.version}"
        self.session = requests.Session()

    # --- low level ---------------------------------------------------
    def _get(self, path, params=None, retries=4):
        p = dict(params or {})
        p["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        last = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=p, timeout=60)
            except requests.RequestException as e:
                last = _redact(e)
                time.sleep(2 ** attempt)
                continue
            try:
                body = r.json()
            except ValueError:
                body = {}
            err = body.get("error") if isinstance(body, dict) else None
            if r.status_code == 200 and not err:
                return body
            code = err.get("code") if err else None
            msg = _redact(err.get("message") if err else r.text[:300])
            if r.status_code == 429 or r.status_code >= 500 or code in _RATE_CODES:
                last = f"HTTP {r.status_code}: {msg}"
                time.sleep(2 ** attempt)
                continue
            if code == 190 or r.status_code in (401, 403):
                raise MetaAPIError(
                    f"Meta rejected the token (HTTP {r.status_code}, code {code}): {msg}. "
                    "It may have been revoked or expired - re-run meta_make_permanent_token.py."
                )
            raise MetaAPIError(f"HTTP {r.status_code} (code {code}): {msg}")
        raise MetaAPIError(f"Gave up after {retries} tries: {last}")

    def _insights(self, node_id, metrics, params):
        """Fetch insights for several metrics; fall back to one-at-a-time if
        the combined request is rejected. Returns {metric_name: data_item}."""
        out = {}
        try:
            body = self._get(f"{node_id}/insights", {"metric": ",".join(metrics), **params})
            for item in body.get("data", []):
                out[item["name"]] = item
            return out
        except MetaAPIError as e:
            if "token" in str(e).lower() and "rejected" in str(e).lower():
                raise
        for m in metrics:
            try:
                body = self._get(f"{node_id}/insights", {"metric": m, **params})
                for item in body.get("data", []):
                    out[item["name"]] = item
            except MetaAPIError as e:
                if "rejected the token" in str(e):
                    raise
        return out

    # --- account discovery ---------------------------------------------
    def get_account(self):
        """With a Page token, 'me' is the Page itself. Returns
        {page_id, page_name, ig_id, ig_username} (ig_* None if not linked)."""
        body = self._get("me", {"fields": "id,name,instagram_business_account{id,username}"})
        ig = body.get("instagram_business_account") or {}
        return {"page_id": body["id"], "page_name": body.get("name"),
                "ig_id": ig.get("id"), "ig_username": ig.get("username")}

    # --- Facebook Page ---------------------------------------------------
    def fb_daily(self, page_id, since, until):
        """Daily Page metrics for since..until (date objects, inclusive).
        Meta limits one request to ~93 days, so this asks in 90-day chunks.
        Returns a list of row dicts, one per day, with the columns in
        FB_METRICS (renamed) plus 'date'."""
        rows = {}
        chunk_start = since
        while chunk_start <= until:
            chunk_end = min(chunk_start + timedelta(days=89), until)
            data = self._insights(page_id, list(FB_METRICS), {
                "period": "day",
                "since": chunk_start.isoformat(),
                "until": (chunk_end + timedelta(days=2)).isoformat(),
            })
            for metric, item in data.items():
                col = FB_METRICS.get(metric)
                for v in item.get("values", []):
                    if "end_time" not in v:
                        continue
                    d = _period_date(v["end_time"])
                    if not (since.isoformat() <= d <= until.isoformat()):
                        continue
                    rows.setdefault(d, {"date": d})[col] = v.get("value")
            chunk_start = chunk_end + timedelta(days=1)
        return [rows[d] for d in sorted(rows)]

    def fb_followers_now(self, page_id):
        body = self._get(page_id, {"fields": "followers_count,fan_count"})
        return body.get("followers_count", body.get("fan_count"))

    # --- Instagram account ---------------------------------------------------
    def ig_snapshot(self, ig_id):
        body = self._get(ig_id, {"fields": "followers_count,media_count"})
        return {"followers_count": body.get("followers_count"),
                "media_count": body.get("media_count")}

    def ig_daily(self, ig_id, since, until, max_consecutive_failures=3):
        """One total_value request per day (newest first, stopping early if
        Meta keeps refusing older days - there's a lookback limit)."""
        rows = []
        failures = 0
        for d in reversed(list(_daterange(since, until))):
            try:
                data = self._insights(ig_id, IG_DAILY_METRICS, {
                    "period": "day", "metric_type": "total_value",
                    "since": d.isoformat(), "until": (d + timedelta(days=1)).isoformat(),
                })
            except MetaAPIError as e:
                if "rejected the token" in str(e):
                    raise
                data = {}
            row = {"date": d.isoformat()}
            for metric, item in data.items():
                tv = item.get("total_value") or {}
                if "value" in tv:
                    row[metric] = tv["value"]
            if len(row) > 1:
                rows.append(row)
                failures = 0
            else:
                failures += 1
                if failures >= max_consecutive_failures:
                    break
            time.sleep(0.1)
        return sorted(rows, key=lambda r: r["date"])

    def ig_follower_gain(self, ig_id, days=29):
        """Best effort: Instagram's daily NET new followers for the last
        ~30 days (the only follower history Instagram offers). Returns
        {date: gain}; empty dict if Meta doesn't return it."""
        today = date.today()
        try:
            data = self._insights(ig_id, ["follower_count"], {
                "period": "day",
                "since": (today - timedelta(days=days)).isoformat(),
                "until": (today + timedelta(days=1)).isoformat(),
            })
        except MetaAPIError as e:
            if "rejected the token" in str(e):
                raise
            return {}
        out = {}
        for v in (data.get("follower_count") or {}).get("values", []):
            if "end_time" in v and v.get("value") is not None:
                out[_period_date(v["end_time"])] = v["value"]
        return out

    # --- Instagram posts ---------------------------------------------------
    def ig_media(self, ig_id, stop_before=None):
        """All posts, newest first. If stop_before ('YYYY-MM-DD') is given,
        stops paging once a whole page is older than that - used for
        incremental runs, where older posts are already cached."""
        posts, after = [], None
        while True:
            params = {
                "fields": "id,caption,media_type,media_product_type,timestamp,"
                          "permalink,like_count,comments_count",
                "limit": 100,
            }
            if after:
                params["after"] = after
            body = self._get(f"{ig_id}/media", params)
            page = body.get("data", [])
            posts.extend(page)
            after = (body.get("paging", {}).get("cursors", {}) or {}).get("after")
            has_next = bool(body.get("paging", {}).get("next"))
            if not page or not has_next or not after:
                break
            if stop_before and all((p.get("timestamp") or "")[:10] < stop_before for p in page):
                break
        return posts

    def ig_post_insights(self, media_id):
        """{reach, views, saved, shares, total_interactions} - whichever
        Meta returns for this particular post (older posts / some media
        types reject certain metrics; those are simply left out)."""
        data = self._insights(media_id, IG_POST_METRICS, {})
        out = {}
        for metric, item in data.items():
            vals = item.get("values") or []
            if vals and "value" in vals[0]:
                out[metric] = vals[0]["value"]
        return out
