"""
Settings for the Breww dashboard.

Put your API key in a .env file in this same folder (see .env.example),
so it never ends up in a file you might commit or share:

    BREWW_API_KEY=BRW.xxxxxxxx

Generate the key in Breww: Settings -> Breww Apps & API -> create a
Private app -> create an API key. Read only access is all this needs.

Requires python-dotenv: pip install python-dotenv --break-system-packages
"""

import os

from dotenv import load_dotenv

load_dotenv()  # reads .env in the current directory, if present

# --- Auth -------------------------------------------------------------
BREWW_API_KEY = os.environ.get("BREWW_API_KEY", "")

# Per the Breww public API spec, keys are sent as a Bearer token:
#   Authorization: Bearer BRW.xxxxxxxx
AUTH_HEADER_PREFIX = "Bearer"

BASE_URL = "https://breww.com/api"

# --- Which data to pull -------------------------------------------------
# Endpoint paths are taken directly from Breww's published OpenAPI spec
# (orders_list, drink_batches_list, stock_received_list operations).
#
# "incremental_field" is the field fetch_data.py filters on with a
# "__gte" lookup once a cache already exists, so re-runs only pull
# new/changed rows instead of the whole history again:
#   - orders uses last_modified_at, which Breww bumps on ANY change to
#     the order (status, payment, totals, etc.) - not just creation -
#     so this reliably catches updates to previously-cached orders too.
#   - batches has no equivalent "last modified" field in the API, only
#     creation/start timestamps, so an update to an already-cached
#     batch (e.g. it completes, or its volume changes) won't be picked
#     up unless that batch is re-fetched. "buffer_days" re-pulls that
#     many days of recent history each run (in addition to anything
#     newer) as a partial workaround - it won't catch a very old batch
#     being edited, but covers the common case of a recently-started
#     batch finishing.
#   - stock_received has no usable date field at all (it's a snapshot
#     of current stock lots, not a log of events), so it's always
#     pulled in full.
ENDPOINTS = {
    "orders": {
        "enabled": True,
        "path": "/orders/",
        "incremental_field": "last_modified_at",
        "buffer_days": 0,
    },
    "batches": {
        "enabled": True,
        "path": "/drink-batches/",
        "incremental_field": "datetime_started",
        "buffer_days": 14,
    },
    "stock_received": {
        "enabled": True,
        "path": "/stock-received/",
        "incremental_field": None,
        "buffer_days": 0,
    },
    "customer_types": {
        "enabled": True,
        "path": "/customer-types/",
        "incremental_field": None,  # small reference list (your account's own
        "buffer_days": 0,           # customer categories) - cheap to fully refresh every run
    },
    "order_lines": {
        "enabled": True,
        "path": "/order-lines/",
        # This endpoint has no date/modified-at field to filter on at
        # all (only id, invoice, order, product), so there's no way to
        # do an incremental pull here - it's always a full refresh.
        # That can mean a genuinely large pull once you have years of
        # order history, since it's one row per line item, not per
        # order.
        "incremental_field": None,
        "buffer_days": 0,
    },
    "products": {
        "enabled": True,
        "path": "/products/",
        # Your finished/packaged products (kegs, cans, casks - not the
        # raw stock items in stock_received), used for the Inventory
        # tab's "Products" section. quantity_in_stock_in_format_by_site
        # is a "conditionally included field" per Breww's docs - it's
        # not returned unless explicitly asked for via include_fields,
        # which is what gives us the per-location breakdown.
        "incremental_field": None,  # product catalogs are small and slow-changing
        "buffer_days": 0,           # - cheap to fully refresh every run
        "extra_params": {
            "include_fields": "quantity_in_stock_in_format,quantity_in_stock_in_format_by_site",
        },
    },
    "fulfillments": {
        "enabled": True,
        "path": "/fulfillments/",
        # Used by the Forecast tab as "existing unfulfilled orders" -
        # each fulfillment has a dispatched flag, a scheduled date, and
        # the specific products/quantities inside it. last_modified_at
        # correctly catches a fulfillment flipping from not-dispatched
        # to dispatched, not just newly-created ones.
        "incremental_field": "last_modified_at",
        "buffer_days": 0,
    },
    "planned_packagings": {
        "enabled": True,
        "path": "/planned-packagings/",
        # Used by the Forecast tab as "planned production" of a
        # specific packaged product (distinct from /drink-batches/,
        # which is at the liquid/recipe level, not the packaged-product
        # level). No last-modified field exists here, only created_at -
        # so a re-check buffer is needed to catch quantity_packaged_so_far
        # changing on an already-cached plan as packaging progresses,
        # the same limitation batches has.
        "incremental_field": "created_at",
        "buffer_days": 30,
    },
    "customers_suppliers": {
        "enabled": True,
        "path": "/customers-suppliers/",
        # Used by the Growth & Efficiency tab's Dormant Customers table
        # for contact info (name/email/phone) - not something orders
        # data carries. No last-modified/updated field exists on this
        # endpoint at all (only created_at, which doesn't change), so
        # there's no reliable way to do an incremental pull here -
        # always a full refresh. Note this endpoint has no Hotel/Shop/
        # Club-style customer type field either - that classification
        # only exists on individual orders (customer.type), so a
        # customer with zero orders ever can't be typed at all.
        "incremental_field": None,
        "buffer_days": 0,
    },
}

# --- Output -------------------------------------------------------------
DATA_DIR = "data"
OUTPUT_HTML = "dashboard.html"

# How far back the dashboard's trend charts look. This no longer
# limits what fetch_data.py pulls - that always builds up full
# history in the local cache - it only controls the chart window in
# build_dashboard.py.
TREND_DAYS = 90

# Breww order_status enum (from the OpenAPI spec)
ORDER_STATUS_LABELS = {
    1: "Draft",
    2: "Confirmed",
    3: "Invoiced",
    4: "Cancelled",
    5: "Completed (no invoice)",
}

# Breww payment_status enum
PAYMENT_STATUS_LABELS = {
    1: "Unpaid",
    2: "Part paid",
    3: "Paid",
    4: "Overpaid",
}

# --- Orders charts -------------------------------------------------------
# Default customer types checked when any of the three Orders charts'
# Customer Type filters first load (or after Reset) - all three charts
# share this same default. These are NOT a fixed API enum - they're
# your account's own custom customer categories (Settings in Breww),
# pulled from /customer-types/. The match is case-insensitive and
# ignores leading/trailing spaces, but the spelling otherwise has to
# match what's actually in your Breww account (e.g. if yours is "Bar
# & Restaurant" rather than "Bar / Restaurant", update the list below
# to match).
DEFAULT_CUSTOMER_TYPES = ["Hotel", "Shop", "Club", "Bar / Restaurant"]

# --- Growth & Efficiency tab ---------------------------------------------
# Default window sizes for the two configurable-window charts/tables -
# both are also adjustable live on the page itself; these just set
# what they start at.
NEW_ACCOUNT_WINDOW_DEFAULT_DAYS = 90
DORMANT_CUSTOMER_WINDOW_DEFAULT_DAYS = 60

# Tags used to pick which of a dormant customer's contacts to show, in
# priority order (first match wins) - see the Dormant Customers table.
# These are your account's own free-text contact tags (Breww has no
# structured "primary contact" flag), so the exact wording has to
# match what's actually used in your Breww account.
CONTACT_TAG_MARKETING = "Receives B2B marketing emails"
CONTACT_TAG_INVOICES = "Receives invoice emails"

# --- Orders tab: "All Products Sold" histogram ---------------------------
# A product needs to clear BOTH of these thresholds (not just one) to
# appear on the histogram - computed over whatever's currently
# filtered/date-ranged, not all-time, so narrowing the view can drop a
# product below the bar even if it clears it over the full history.
HISTOGRAM_MIN_SALES_VALUE = 1000
HISTOGRAM_MIN_SALES_UNITS = 10

# Per-product bar/marker colors for the "All Products Sold" histogram
# (and anywhere else products are individually colored). Breww's API
# has no display-color field for products, so colors are normally
# auto-assigned from a fixed palette based on each product's position
# in your full, alphabetized product list - stable across filters, but
# not something you control directly. Add entries here (product name
# -> hex color, matching the name exactly as it appears in Breww) to
# override that for specific products; anything not listed here still
# falls back to the automatic assignment. For example:
#
#   PRODUCT_COLORS = {
#       "Spy-P-A - Regular": "#4CAF6B",
#       "Trafford Ale - Regular": "#3F4B8C",
#   }
PRODUCT_COLORS = {
    # "Spy-P-A - Regular": "#4CAF6B",
    # "Trafford Ale - Regular": "#3F4B8C",
}

# Breww drink batch status enum
BATCH_STATUS_LABELS = {
    1: "Planned",
    2: "In-progress",
    3: "Complete",
}

# Breww drink batch brew_type enum
BREW_TYPE_LABELS = {
    1: "Standard",
    2: "Contract brewed in-house",
    3: "Collaboration in-house",
    4: "Contract brewed by 3rd party",
    5: "Collaboration at 3rd party",
    6: "Guest beer receipted",
}

# Breww product "type" enum
PRODUCT_TYPE_LABELS = {
    1: "Stock item",
    2: "Cask",
    3: "Keg",
    4: "Smallpack",
    5: "Multi-pack",
    6: "Mixed-pack",
    8: "Service",
}

# Which product types count as physical, sellable, packaged inventory
# for the Inventory tab's "Products" section - excludes type 1 ("Stock
# item", which is what /stock-received/ already covers separately) and
# type 8 ("Service", not a physical thing you hold stock of).
PACKAGED_PRODUCT_TYPES = {2, 3, 4, 5, 6}
