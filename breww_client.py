"""
Minimal client for the Breww public API.

Matches the real API behaviour documented in Breww's OpenAPI spec:
  - Auth: "Authorization: Bearer <api_key>"
  - Pagination: {"count": int, "next": url|null, "previous": url|null,
    "results": [...]}, 50 results per page by default, up to 200 via
    page_size.
  - Rate limits: 60 requests/minute, 5000/day. A 429 comes back with a
    Retry-After header/message if you hit them - get_all() waits that
    long and retries automatically rather than giving up, since giving
    up would discard every page already fetched. See get_all()'s
    docstring for the details.
"""

import time
import requests

import config


class BrewwAPIError(Exception):
    pass


class BrewwClient:
    def __init__(self, api_key=None, base_url=None, auth_prefix=None):
        self.api_key = api_key or config.BREWW_API_KEY
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.auth_prefix = auth_prefix or config.AUTH_HEADER_PREFIX

        if not self.api_key:
            raise BrewwAPIError(
                "No Breww API key found. Set the BREWW_API_KEY environment "
                "variable to a key generated in Settings -> Breww Apps & API."
            )

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"{self.auth_prefix} {self.api_key}",
            "Accept": "application/json",
        })

    def get_all(self, path, params=None, max_pages=500, sleep_between=1.1, max_retries=6):
        """
        GET every page of a list endpoint and return the combined list of
        records from the "results" key.

        sleep_between defaults to 1.1s - Breww allows 60 requests/minute
        (1/sec average), so this stays safely under that even on an
        endpoint with hundreds of pages (e.g. order-lines, which has no
        date filter and can mean a very large full pull).

        If a 429 does happen anyway, this waits for the time Breww asks
        for (via the Retry-After header) and retries the SAME page,
        rather than giving up and discarding every page already
        fetched. After max_retries consecutive 429s, it stops and
        returns whatever was collected so far (still useful - it'll
        merge with the existing cache on the next run) instead of
        raising and losing that progress.
        """
        url = f"{self.base_url}{path}"
        params = dict(params or {})
        params.setdefault("page_size", 200)  # Breww's documented max
        records = []
        pages_fetched = 0
        consecutive_429s = 0

        while url and pages_fetched < max_pages:
            request_params = params if pages_fetched == 0 else None
            resp = self.session.get(url, params=request_params)

            if resp.status_code in (401, 403):
                raise BrewwAPIError(
                    f"Auth failed on {path} (HTTP {resp.status_code}). Check that "
                    f"BREWW_API_KEY is set and hasn't been rejected/revoked in "
                    f"Settings -> Breww Apps & API."
                )
            if resp.status_code == 404:
                raise BrewwAPIError(f"Endpoint not found: {path}.")

            if resp.status_code == 429:
                consecutive_429s += 1
                if consecutive_429s > max_retries:
                    print(
                        f"  Still rate limited on {path} after {max_retries} retries - "
                        f"stopping here with {len(records)} rows collected so far. "
                        f"They'll be kept; re-run fetch_data.py later to pick up the rest."
                    )
                    return records

                retry_after_header = resp.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after_header) + 1  # small safety buffer
                except (TypeError, ValueError):
                    wait_seconds = 60  # no usable header - guess conservatively
                print(f"  Rate limited on {path} - waiting {wait_seconds:.0f}s before retrying ...")
                time.sleep(wait_seconds)
                continue  # retry the same page, same params, url unchanged

            consecutive_429s = 0
            resp.raise_for_status()

            payload = resp.json()
            records.extend(payload.get("results", []))
            url = payload.get("next")
            params = None  # "next" already has the query string baked in

            pages_fetched += 1
            if url:
                time.sleep(sleep_between)

        return records
