"""
Minimal client for Square's Locations and Orders APIs.

Matches Square's documented behavior:
  - Auth: "Authorization: Bearer <access_token>", plus a required
    "Square-Version" header (Square's APIs are date-versioned; an
    older version keeps working indefinitely by design, so this
    doesn't need to be bumped often - see config.SQUARE_API_VERSION).
  - Pagination: cursor-based, in the response body (a "cursor" field),
    not query params. ListLocations returns everything in a single
    page for a normal-sized account, but is still handled defensively
    here in case that ever changes. SearchOrders returns up to 1000
    orders per page (this client always asks for the max) and expects
    the cursor to be echoed back in the NEXT request's body to get the
    following page.
  - IMPORTANT Square-specific quirk: if a SearchOrders query filters by
    a timestamp field (e.g. updated_at), the query's sort field MUST be
    set to that exact same field, or Square rejects the request
    outright. There's no documented way around this - it's a hard
    requirement of the API, not a bug in this client.
  - Rate limits: Square doesn't document specific numbers as clearly as
    Breww does, so this retries a 429 with a fixed exponential backoff
    rather than trusting a specific header to be present.
"""

import time
import requests

import config


class SquareAPIError(Exception):
    pass


class SquareClient:
    def __init__(self, access_token=None, base_url=None, api_version=None):
        self.access_token = access_token or config.SQUARE_ACCESS_TOKEN
        self.base_url = (base_url or config.SQUARE_BASE_URL).rstrip("/")
        self.api_version = api_version or config.SQUARE_API_VERSION

        if not self.access_token:
            raise SquareAPIError(
                "No Square access token found. Set the SQUARE_ACCESS_TOKEN "
                "environment variable to a personal access token generated "
                "in the Square Developer Dashboard -> your application -> "
                "Credentials (Production)."
            )

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Square-Version": self.api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def list_locations(self):
        """GET /v2/locations - every location on the account, active or
        not (the caller decides what to do with inactive ones; this
        client doesn't filter anything out). Cursor-pagination is
        checked defensively even though a location list this long
        would be unusual."""
        locations = []
        url = f"{self.base_url}/v2/locations"
        params = {}
        while True:
            resp = self._request("get", url, path="/v2/locations", params=params or None)
            payload = resp.json()
            locations.extend(payload.get("locations", []))
            cursor = payload.get("cursor")
            if not cursor:
                break
            params = {"cursor": cursor}
        return locations

    def search_orders(self, location_ids, updated_since=None, states=None, max_pages=500, sleep_between=0.5):
        """POST /v2/orders/search, across as many location_ids as
        given. Square caps location_ids at 10 per request (a hard
        limit, confirmed by a real 400 error on an account with more
        than that) - this splits into batches of 10 and makes one
        fully-paginated call per batch, combining the results. An
        order belongs to exactly one location, so splitting locations
        into separate queries this way can't produce a duplicate -
        each batch's results are a clean, non-overlapping slice of the
        total.

        Filters to orders in the given states; if updated_since (an
        ISO timestamp) is also given, further filters to orders
        updated on/after it, sorted by UPDATED_AT - Square requires
        the sort field to exactly match the filtered timestamp field,
        which is why both are hardcoded together here rather than
        being independently configurable. Passing updated_since=None
        (the default) omits the date filter entirely - a genuine
        all-time pull, sorted by CREATED_AT instead (Square's own
        default sort field, used explicitly here for clarity rather
        than left implicit) since there's no date filter for
        UPDATED_AT to have to match in that case."""
        MAX_LOCATIONS_PER_REQUEST = 10
        orders = []
        for i in range(0, len(location_ids), MAX_LOCATIONS_PER_REQUEST):
            batch = location_ids[i:i + MAX_LOCATIONS_PER_REQUEST]
            orders.extend(self._search_orders_batch(
                batch, updated_since=updated_since, states=states,
                max_pages=max_pages, sleep_between=sleep_between,
            ))
        return orders

    def _search_orders_batch(self, location_ids, updated_since=None, states=None, max_pages=500, sleep_between=0.5):
        """The actual paginated SearchOrders call for AT MOST 10
        location_ids - see search_orders, which splits a larger list
        into batches of this size and calls this once per batch."""
        url = f"{self.base_url}/v2/orders/search"
        states = states or list(config.SQUARE_ORDER_STATES)

        query = {"filter": {"state_filter": {"states": states}}}
        if updated_since:
            query["filter"]["date_time_filter"] = {"updated_at": {"start_at": updated_since}}
            query["sort"] = {"sort_field": "UPDATED_AT", "sort_order": "ASC"}
        else:
            query["sort"] = {"sort_field": "CREATED_AT", "sort_order": "ASC"}

        body = {
            "location_ids": location_ids,
            "query": query,
            "limit": 1000,  # Square's documented max per page
        }

        orders = []
        pages_fetched = 0
        while pages_fetched < max_pages:
            resp = self._request("post", url, path="/v2/orders/search", json_body=body)
            payload = resp.json()
            orders.extend(payload.get("orders", []))
            cursor = payload.get("cursor")
            pages_fetched += 1

            if not cursor:
                break
            body["cursor"] = cursor
            time.sleep(sleep_between)

        return orders

    def _request(self, method, url, path, params=None, json_body=None, max_retries=5):
        """Shared request/error/retry handling for both endpoints
        above. Square doesn't document a Retry-After-style header as
        explicitly as Breww does, so a 429 here backs off with a fixed
        exponential delay (2s, 4s, 8s, ...) instead of trusting one."""
        attempt = 0
        while True:
            resp = self.session.request(method, url, params=params, json=json_body)

            if resp.status_code in (401, 403):
                raise SquareAPIError(
                    f"Auth failed on {path} (HTTP {resp.status_code}). Check that "
                    f"SQUARE_ACCESS_TOKEN is set and hasn't been revoked in the "
                    f"Square Developer Dashboard's Credentials page."
                )
            if resp.status_code == 429:
                attempt += 1
                if attempt > max_retries:
                    raise SquareAPIError(
                        f"Still rate limited on {path} after {max_retries} retries - giving up for now."
                    )
                wait_seconds = 2 ** attempt
                print(f"  Rate limited on {path} - waiting {wait_seconds}s before retrying ...")
                time.sleep(wait_seconds)
                continue

            if not resp.ok:
                try:
                    detail = resp.json()
                except ValueError:
                    detail = resp.text
                raise SquareAPIError(f"Square API error on {path} (HTTP {resp.status_code}): {detail}")

            return resp
