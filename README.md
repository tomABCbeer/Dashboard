# ABCo Breww dashboard

A small, no-server dashboard: pull data from the Breww API, cache it as
CSVs, and generate one HTML file with charts and tables you can open in
any browser.

Built against Breww's published OpenAPI spec (the `document.yaml` you
sent over), so the endpoints, field names, and auth scheme below are
confirmed, not guessed.

## Setup

```
pip install requests pandas plotly python-dotenv
```

Generate an API key in Breww: **Settings → Breww Apps & API → create a
Private app → create an API key**. Read only access is all this needs.
Keys start with `BRW.`.

Copy `.env.example` to `.env` and fill in your key:

```
cp .env.example .env
```

Then edit `.env` so it reads:

```
BREWW_API_KEY=BRW.xxxxxxxx
```

`config.py` loads `.env` automatically, so the key is picked up every
time you run the scripts — no need to set it in your terminal each
session. `.env` is already listed in `.gitignore` so it won't get
committed if you put this project in git.

## Run it

```
python fetch_data.py       # pulls data from Breww, saves to data/*.csv
python build_dashboard.py  # builds dashboard.html from those CSVs
open dashboard.html        # (or just double-click it)
```

The first `fetch_data.py` run pulls each endpoint's full history, so
it'll take longer than later runs — expect it to page through
everything Breww has. After that, re-runs are quick: they only pull
what's new or changed and add it to the cache in `data/`, without
losing anything already there.

## Project structure

`build_dashboard.py` is a thin orchestrator — it loads the cached
CSVs, calls one function per tab, and assembles the final HTML. Each
tab's own data prep, HTML, and JavaScript lives in its own file, so
working on one tab doesn't mean reading through the others to find
the right spot:

```
build_dashboard.py        — main(), the page template, wires the tabs together
shared.py                 — helpers and constants every tab uses (table
                             rendering, the searchable-filter component,
                             color palettes, json_safe, load_csv, ...)
orders_tab.py              — Sales by Month, Sales by Month by Product,
                             All Products Sold, Top 10 Customers
batches_tab.py             — Production
inventory_tab.py           — Products and Stock Items (both sub-sections)
customer_report_tab.py     — Customer Report
forecast_tab.py            — Forecast
growth_efficiency_tab.py   — Growth & Efficiency
```

`shared.py` includes the full client-side searchable-filter component
(`createSearchableFilter` — search, select all/none, saved presets)
as a single JS string, injected once at the top of the page rather
than duplicated per tab. Every tab's Python module imports whichever
pieces of `shared.py` it actually needs, so `pyflakes shared.py
orders_tab.py batches_tab.py inventory_tab.py customer_report_tab.py
forecast_tab.py growth_efficiency_tab.py build_dashboard.py` is a
quick way to catch an unused or missing import after editing one.

## What's on the dashboard

The page is organized into six tabs: **Orders**, **Production**,
**Inventory**, **Customer Report**, **Forecast**, and **Growth &
Efficiency**. Only one is visible at a time — clicking a tab shows its
content and hides the others. All the data for every tab is embedded
in the same `dashboard.html` file at build time, so switching tabs is
instant and doesn't need Python or an internet connection.

**Orders** (`/orders/`, the `Invoice` object) — all three charts are
**interactive**, each with its own independent filters, see below
- Order count and total value, all-time — not affected by any filter
- **Sales by Month**, current year as stacked bars by
  order status (Draft / Confirmed / Invoiced), with every prior year
  in your order history plotted as its own dashed line, in a different
  color per year, for comparison. Has its own Customer Type and Order
  Status filters, shown directly above it
- **Sales by Month, by Product**, same shape as above but each bar is
  stacked by product/beer instead of order status — the top 7 products
  get their own segment, everything else is grouped into "Other" to
  keep it readable. Has its own Customer Type, Order Status, and
  Product filters, shown directly above it — entirely separate from
  the first chart's filters. A **Sales $ / # of units** toggle above
  the chart switches both the bars and prior-year lines between dollar
  value and quantity sold
- **All Products Sold**, a single bar per product (not grouped or
  stacked), sorted highest to lowest, each one colored consistently —
  see "Product colors" below. Only products clearing **both**
  `config.HISTOGRAM_MIN_SALES_VALUE` ($1,000 by default) and
  `config.HISTOGRAM_MIN_SALES_UNITS` (10 units by default) — over
  whatever's currently filtered/date-ranged, not all-time — appear on
  the chart, so narrowing the filters or date range can drop a product
  below the bar even if it clears the threshold over full history.
  Switching the $ / units toggle doesn't change which products
  qualify, only how their bars are measured. Has its own Customer
  Type, Order Status, and Product filters, plus a **date range** and
  its own **Sales $ / # of units** toggle — all independent from both
  charts above it
- Top 10 customers by order value, all-time — not affected by any filter
- Recent orders table, all-time — not affected by any filter

All three charts' Customer Type filters share the same default —
Hotel / Shop / Club / Bar-Restaurant, excluding Individual and Export
— set once in `config.DEFAULT_CUSTOMER_TYPES`. Change that one list
to change the starting point everywhere at once.

#### Product colors

Breww's API has no per-product display-color field (checked directly
against the spec — the only "colour" field anywhere in it is an
unrelated numeric brewing measurement), so by default every product on
the "All Products Sold" chart gets a color assigned automatically from
a fixed palette, based on its position in your full, alphabetized
product list. That assignment is stable — a product keeps its color
across filter and date range changes — but it isn't something you
control directly.

To pin specific products to specific colors instead, add them to
`config.PRODUCT_COLORS`:

```python
PRODUCT_COLORS = {
    "Spy-P-A - Regular": "#4CAF6B",
    "Trafford Ale - Regular": "#3F4B8C",
}
```

The product name has to match exactly what's in your Breww order-line
data (case-sensitive) — usually the same name you see elsewhere on the
dashboard's product filters. Any product not listed here still falls
back to the automatic assignment, so you only need to add entries for
the ones you actually want to control.

**Production batches** (`/drink-batches/`, the `DrinkBatch` object)
- Batch count, total volume brewed, average ABV — all-time
- Batch volume by day, last 90 days
- Batches by status (Planned / In-progress / Complete)
- Most-brewed beers, top 10 (all-time)
- Recent batches table

**Inventory** is split into two independent sub-sections, since Breww
tracks these as genuinely different things — every chart in both is
**interactive**, each with its own independent, searchable, savable
filter, same component and behavior as the filters on the Orders tab
(see "Filtering the three Orders charts" above; everything there about
search, floating checked items to the top, and saved presets applies
here too):

**Products** (`/products/`, the `Product` object, shown first) —
finished, packaged, sellable products: kegs, cans, casks of a specific
beer. Only product types that are physical and sellable are included
(casks, kegs, smallpack, multi-pack, mixed-pack) — raw "Stock
item"-type products (covered separately below) and "Service"-type
products (not physical stock) are excluded, as are any products with
zero current stock.
- **Current Inventory of Products by Location** — a stacked bar chart,
  one bar per location, broken down by product (top 7 by quantity,
  everything else grouped into "Other"). Shown first, at the top of
  this sub-section.
- Product/location line count, total product stock value — not
  affected by any of the three product filters
- On-hand quantity by product, top 10 — scoped by its own filter
- Product stock quantity by location (pie) — scoped by its own filter
- **Product stock by location table** — one row per product, one
  column per location holding that location's current quantity, plus
  a Total column summing across locations. Not affected by any
  filter, always shows everything cached.

Note on products: the per-location stock breakdown
(`quantity_in_stock_in_format_by_site`) is a "conditionally included"
field in Breww's API — it isn't returned unless explicitly requested,
which `config.py`'s `products` endpoint entry does via
`include_fields`. If a product's per-site breakdown comes back empty
but it has stock overall, that total is shown under an "Unspecified"
location column instead of being dropped.

**Stock Items** (`/stock-received/`, the `StockReceived` object) —
raw ingredients and packaging received into stock: hops, malt, caps,
cans, and similar. Not finished, sellable products.
- **Current Stock Items by Location** — a stacked bar chart, one bar
  per location, broken down by item (top 7 by quantity, everything
  else grouped into "Other"). Shown first, at the top of this
  sub-section.
- Stock lot count, total stock value (quantity × price) — not affected
  by any of the three item filters, always reflects everything cached
- On-hand quantity by item, top 10 — scoped by its own item filter
- Stock quantity by location (pie) — scoped by its own item filter
- Full stock lots table — not affected by any filter, always shows
  everything cached

Note on stock items: this endpoint returns current stock lots, not a
log of receiving events, so there's no received-date to trend against
— it's shown as a point-in-time snapshot instead. If you want a
*trend* of goods coming in over time, that's the
`/inventory-receipts/` endpoint instead (it has `delivery_date` and
`created_at`), but its data is nested per line item (an `entries`
array), so it'd need its own section — say the word and I'll add it.

Any section with missing data still renders — it'll just show fewer
charts and a note.

**Customer Report** (a new tab, built entirely from the same order and
order-line data as the Orders tab — no new endpoint needed)

Pick a customer from the searchable dropdown and it generates a
two-chart report for just that customer:

- **Sales by Month** — a stacked bar chart, one bar per month across
  whatever date range you've set, with each bar broken down by
  product (top 7 by value/units, everything else grouped into
  "Other"). A dashed comparison line overlays the *average* monthly
  sales among other customers of the same customer type — see "How
  the comparison line is calculated" below. The vertical axis is
  labeled "Net Sales Value ($)" or "Units Sold" depending on the
  toggle below.
- **Product mix** — a pie chart of the same customer's product
  breakdown over the same date range, using the same top-7-plus-Other
  grouping (and matching colors) as the bar chart.

Both charts always render at a fixed size, with the legend explicitly
placed as a horizontal band below the plot rather than off to the
side — since how many legend entries there are (products bought, plus
the comparison line) varies by customer, a side legend competing for
horizontal space was liable to shrink the plot or jump position
depending on who was selected. A horizontal legend below just wraps
across the chart's full width instead, so the plot area stays the same
size regardless of how many products a given customer has bought.

Controls, all above the two charts:
- **Date range** (begin/end) applies to both charts together. When you
  first pick a customer, it's auto-set to that customer's own full
  order history — narrow it from there. Switching to a different
  customer resets the range to *their* history.
- **Sales $ / # of units** toggles both charts between dollar value
  and quantity sold — whichever you're currently viewing.

#### How the comparison line is calculated

For each month in the range, the dashed line shows: total sales
(in whichever unit you've selected) across **all customers of the
same customer type** who ordered anything in that date range, divided
by the **number of distinct customers of that type** who ordered
anything in that date range. That divisor is calculated once for the
whole range and applied to every month — not recalculated per month —
so the line reflects a typical customer's seasonal pattern rather than
just tracking how many customers of that type happened to place an
order in a given month. If the customer's own type has no other
orders in the range, the line simply won't appear for that report.

**Forecast** (a new tab, combines `/products/`, `/planned-packagings/`,
`/fulfillments/`, and the same order-line data as the other tabs — the
first two are new endpoints, added specifically for this tab)

Pick a product from the searchable dropdown and it projects that
product's inventory level over the next 4 calendar months as a line
chart, starting from current stock. Each month combines:

- **Planned production** — from `/planned-packagings/`, which tracks
  production at the *packaged product* level (a specific keg/can/cask
  of a specific beer), not the liquid/recipe level that
  `/drink-batches/` tracks. Only the quantity not yet packaged
  (`quantity - quantity_packaged_so_far`) counts, and a plan uses its
  `expected_release_date` if set, falling back to its `date` (the
  planned packaging date) otherwise.
- **Known unfulfilled orders** — from `/fulfillments/`, filtered to
  ones where `dispatched` is false, using each one's `date_scheduled`.
  A fulfillment with no scheduled date, or one that's overdue (dated
  before the forecast window even starts), is treated as due as soon
  as possible rather than dropped from the forecast. One scheduled
  further out than the 4-month window is excluded, since it's not
  relevant to this chart.
- **Projected new demand** — demand not yet reflected in an actual
  order. This takes last year's actual quantity sold in the *same*
  calendar month, scales it by this year's year-over-year growth rate
  (this year's total-to-date over the same period last year, for that
  product), and then subtracts whatever's already known/booked for
  that month from step above — so a real order already on the books
  is never counted twice, once as itself and once as part of the
  historical pattern.

This is a heuristic planning aid, not a guaranteed prediction — a
breakdown table under the chart shows exactly how each month's number
was built (production, known orders, projected demand, running total),
so you can sanity-check the pieces rather than trusting an opaque
line. A warning appears above the chart if there's no matching sales
history for that product in the comparison period last year (the
projection then falls back to known orders and planned production
only, with no seasonal component), or if that comparison period had
very little volume (under 20 units), since the growth-rate estimate
gets unreliable at that point. The chart doesn't clamp negative
values to zero — a dip below the line at zero is a genuine projected
stockout worth planning around.

**Growth & Efficiency** (a new tab, built entirely from data already
embedded by the Orders tab, plus a new `/customers-suppliers/`
endpoint for contact info)

All three items below only count **Invoiced** orders — Draft,
Confirmed, Cancelled, and Completed-no-invoice orders are ignored
throughout, both for defining a customer's "first order" and for
counting revenue. All three also default their Customer Type filter
to the same set: `config.DEFAULT_CUSTOMER_TYPES` (Hotel / Shop / Club
/ Bar-Restaurant).

- **New Account Sales** — a monthly dual-axis chart: stacked bars
  (left axis; top 7 products by value, everything else grouped into
  "Other") showing revenue from orders placed within a configurable
  window of each customer's first invoiced order (default 90 days,
  editable directly on the chart), plus a line (right axis) showing
  how many *new* accounts joined that month — distinct from the bars,
  which show revenue from *any* qualifying order in that window, not
  just signup-month revenue. The bars are per-*order*: a customer
  whose new-account window spans more than one calendar month
  contributes to each month their qualifying orders actually landed
  in. The line is per-*customer*: it only counts a customer once, in
  the month their first invoiced order happened. Comparing the two
  tells you whether new-account revenue is climbing because you're
  signing more accounts, or because each new account is spending more
  in their early window than it used to. A customer with no invoiced
  orders contributes to neither.
- **Sales Per Customer** — a monthly dual-axis chart: a bar (left
  axis) showing average net sales per customer, and a line (right
  axis) showing the customer count used as that average's denominator.
  A **Cumulative total / Active this month** toggle (defaults to
  Cumulative) controls what that count means — cumulative is every
  customer acquired on or before that month (a running total that
  only climbs), while active is only customers who placed a qualifying
  order that specific month. Comparing how the bar moves relative to
  the line is the point: if both climb together, growth is coming from
  adding accounts; if the bar climbs while the line doesn't, existing
  accounts are spending more.
- **Dormant Customers table** — customers whose last invoiced order is
  older than a configurable window (default 60 days, editable
  directly on the table), sorted oldest-first by default. **Every
  column header is clickable to sort by that column** — click once to
  sort ascending (or, for the Sales column, descending — numbers start
  high-to-low since that's usually the more useful first view of a
  revenue figure), click the same header again to flip direction; an
  arrow next to the header shows which column is currently active and
  which way. A **Has ordered before / Never ordered** toggle switches
  to an entirely different population: customers who show up in your
  Breww account but have never placed an invoiced order at all
  (defaults back to alphabetical-by-name when you switch into this
  mode, since there's no order date to sort by — switching population
  modes always resets the sort to that mode's own default, so a custom
  sort choice doesn't carry over somewhere it wouldn't make sense).
  **The Customer Type filter doesn't apply in "Never ordered" mode** —
  Breww only tracks customer type on individual orders, so a customer
  with zero orders has no order to derive a type from; a note appears
  above the table explaining this when that toggle is active. Columns:
  customer name, last order date, the specific products on *that*
  order (not their order history in general — matched by order ID, so
  two orders placed the same day never get conflated), total sales in
  the trailing 12 months, and a contact name/phone/email.

  Contact selection follows a priority order, since Breww has no
  structured "primary contact" flag, only free-text tags on each
  contact: `config.CONTACT_TAG_MARKETING` ("Receives B2B marketing
  emails") wins if any contact has it, then `config.CONTACT_TAG_INVOICES`
  ("Receives invoice emails"), then the business's own
  `primary_email`/`primary_phone_number` if no contact matches either
  tag — in that last case the name column shows "[No contact names
  available - business contact displayed]" rather than being left
  blank, so it's clear at a glance that no named person was found.

## Filtering the three Orders charts

Each of the three interactive charts has its **own, completely
independent** set of filters, shown directly above it — changing one
chart's filters never affects the other charts, and none of them
affect the KPIs, Top 10 customers, or the recent orders table, which
always show full, unfiltered history. Nothing here needs Python, a
rebuild, or an internet connection after the page first loads (aside
from the one-time Plotly library fetch from its CDN).

- **"Sales by Month"** has its own Customer Type and Order Status
  filters.
- **"Sales by Month, by Product"** has its own separate Customer Type
  and Order Status filters, plus a Product filter and a Sales $ / #
  of units toggle.
- **"All Products Sold"** has yet another separate set of Customer
  Type, Order Status, and Product filters, plus its own date range and
  Sales $ / # of units toggle — the only one of the three with a date
  range, since the other two always show full history by design.

That's eight filters total across the three charts, and every one of
them works and looks the same way — a single reusable component, not
eight different UIs:

- **Click to open**, type to search — the search only narrows what's
  *visible* in the list, it never changes what's checked.
- The closed button always shows a live summary ("All (14)", "3 of 14
  selected", "None selected") so you can tell the filter's state
  without opening it.
- Checked items float to the top of the list (alphabetized among
  themselves, with unchecked ones below, also alphabetized) each time
  you open the dropdown — this re-sorts on open, not on every click,
  so rows don't jump around under your cursor while you're actively
  checking several in a row.
- **Select all / Select none** always act on every item, not just
  whatever the search currently shows.
- **Save as new…** prompts for a name and saves the current selection
  under it (asks before overwriting a name that already exists). The
  **dropdown** beneath it lists every saved filter, alphabetically —
  picking one applies it immediately. **Delete** removes whichever
  saved filter is currently selected, after confirming.

**Saved filters are shared across every filter of the same kind, on
every tab** — not per-chart. Save a Customer Type preset on "Sales by
Month" and it's immediately available on "Sales by Month, by Product,"
"All Products Sold," and all three Customer Type filters on the Growth
& Efficiency tab too, since all six draw from the exact same
underlying list of customer types. The grouping follows what the
filter actually contains, not just its label — sharing only happens
where two filters genuinely offer the same set of possible values:

- **Customer Type** — shared across all 6 instances (Orders' 3 charts
  + Growth & Efficiency's 3 sections)
- **Order Status** — shared across Orders' 3 charts
- **Product** (order-line based) — shared between "Sales by Month, by
  Product" and "All Products Sold"
- **Item** (raw stock items) — shared across Inventory's 3 Stock Items
  charts
- **Product** (packaged goods) — shared across Inventory's 3 Products
  charts, kept *separate* from Orders' Product presets since it comes
  from a different endpoint (`/products/` vs. order lines) and could
  plausibly use different exact names

Saving or deleting a preset updates every filter sharing that group
immediately, even ones on a tab you're not currently viewing — this
works because the underlying storage is genuinely shared, not because
each filter re-checks on a timer. Applying a saved preset is still
per-chart, though: loading one on "Sales by Month" only changes what's
checked *there* — it never reaches into any other chart's own current
selection, shared list or not. All of it lives in this browser's local
storage, so it's per-browser and per-computer, not synced anywhere.

Each chart's **Reset** button puts that chart's own filters back to
their defaults (Customer Type from `config.DEFAULT_CUSTOMER_TYPES`,
everything else fully selected, and for "All Products Sold," the date
range and unit toggle too) — it doesn't touch any saved presets, and
it doesn't affect the other two charts.

Only "All Products Sold" has a date range filter — the other two
always cover full order history, with the current year broken out as
bars and every prior year shown as its own dashed comparison line. The
customer type, order status, and product options on all three are
populated from whatever's actually in your cached order data, so
they'll always reflect the real values in your Breww account.

Production batches stay static (not filtered) for now — say the word
if you'd like that interactive too, matching Orders and Inventory.

## How data flows

1. **First run**, `fetch_data.py` pulls each endpoint's **full
   history** (no date filter), paginated via `page_size=200` and
   `next` links, and writes it to `data/<name>.csv`.
2. **Every run after that**, it only asks Breww for rows that are new
   or changed since the last pull, then merges them into the existing
   CSV: old rows are always kept, and a row with an id already in the
   cache gets replaced by its newer version rather than duplicated.
   How "changed since" works differs by endpoint (see the comments
   above `ENDPOINTS` in `config.py`):
   - **Orders** filter on `last_modified_at`, which Breww bumps on any
     change to the order — so a status or payment update to an order
     from months ago is picked up correctly, not just brand-new orders.
   - **Batches** have no "last modified" field in the API, only
     creation/start timestamps, so updates to an already-cached batch
     (it completes, its volume changes) are only caught if that batch
     gets re-fetched. To cover the common case, each run also
     re-pulls the last 14 days of batches in addition to anything
     newer.
   - **Stock** has no usable date field at all — it's a snapshot of
     current stock, not an event log — so it's always pulled in full.
   - **Order lines** (`/order-lines/`) also has no date field to filter
     on, so it's always pulled in full too. Unlike stock, this can
     genuinely add up over time since it's one row per product/beer
     per order, not one row per order — expect this pull to take
     noticeably longer than the others once you have a few years of
     order history.
   - **Products** (`/products/`) has no last-modified field either, so
     it's always pulled in full — fine, since a product catalog is
     small and doesn't change often.
   - **Fulfillments** (`/fulfillments/`) filter on `last_modified_at`,
     same as orders — this correctly catches a fulfillment flipping
     from not-dispatched to dispatched, not just newly-created ones.
   - **Planned packagings** (`/planned-packagings/`) has no
     last-modified field, only `created_at`, so like batches, each run
     also re-pulls the last 30 days in addition to anything newer, to
     catch `quantity_packaged_so_far` changing on an already-cached
     plan as packaging progresses.
   - **Customers/suppliers** (`/customers-suppliers/`) has no
     last-modified field at all, only `created_at` (which doesn't
     change once set), so there's no reliable way to do an incremental
     pull here — always a full refresh.
3. Nested objects in the response (e.g. `customer.name`, `drink.name`,
   `total_volume.litre`, `stock_item.name`) get flattened into dotted
   CSV columns.
4. `build_dashboard.py` reads those CSVs and renders the page.
   Production batches render their charts/tables directly in Python,
   same as before. Orders, Inventory, and the histogram-style charts
   instead get their raw records embedded as JSON in the page, plus a
   block of JavaScript that does the actual filtering, aggregation,
   and chart-drawing in the browser — see "Filtering the three Orders
   charts" above.
   `config.DEFAULT_CUSTOMER_TYPES` now just sets the *default*
   pre-checked customer types when the page first loads (or after
   Reset), the same across all three Orders charts; it's no longer a
   hard filter baked into the data.
5. Order lines don't carry their own issue date, status, or customer
   type — only the order they belong to does — so `build_dashboard.py`
   joins each line to its parent order (by order id) at build time to
   copy those fields over. That join happens once in Python; after
   that, the beer chart filters and buckets its (now self-contained)
   records in the browser exactly like the rest of the Orders section.

If you ever want to force a clean full re-pull of everything (e.g. you
suspect the cache drifted), just delete the relevant file in `data/`
and run `fetch_data.py` again.

## Extending it

Want another endpoint (products, purchase orders, vessels, deals,
etc.)? The spec you sent has the full schema for all of them. Add an
entry to `ENDPOINTS` in `config.py` with the real path, then add a
`build_x_section()` function in `build_dashboard.py` modeled on the
existing ones, using the field names from that object's schema.

## Rate limits

Breww allows 60 requests/minute and 5,000/day per key. `fetch_data.py`
paces requests to stay under that automatically. If it does get rate
limited anyway (large pulls like `order_lines`, which has no date
filter and can mean hundreds of pages, are the most likely to hit
this), it waits however long Breww asks for and retries automatically
rather than losing progress - you'll see a line like:

```
  Rate limited on /order-lines/ - waiting 16s before retrying ...
```

If it's still rate limited after several retries in a row, it stops
and keeps whatever it already collected for that endpoint (shown as
`[OK]` in the summary, just with fewer rows than a full pull) rather
than losing everything - re-run `fetch_data.py` later to pick up the
rest.
