"""Forecast tab: projected inventory for a chosen beer (every one of
its products/package-formats together) or a single standalone
product, over the next 4 months - combining current stock, planned
production, existing unfulfilled orders, and a seasonal demand
projection weighted toward recent sales."""
import json

import pandas as pd

from shared import json_safe, _safe_float, _parse_bool, _parse_json_list, HISTOGRAM_COLORS, build_product_id_name_map, _safe_int, build_batch_completion_map


def prepare_fulfillment_records(fulfillments_df, product_id_name_map=None):
    """Explode each fulfillment's order_lines into per-product-quantity
    records for the Forecast tab's "existing unfulfilled orders" input.
    Each fulfillment carries a dispatched flag and a scheduled date at
    the fulfillment level, which every line item inside it inherits.

    Each line item is the exact same Sale schema used by
    /order-lines/ - meaning it carries the same frozen product-name
    snapshot and the same risk of a renamed product's name going
    stale (see prepare_order_line_records in orders_tab.py for the
    full explanation). Resolved the same way, via the product's
    stable ID."""
    if fulfillments_df is None:
        return []
    product_id_name_map = product_id_name_map or {}

    d = fulfillments_df.copy()
    records = []
    for _, row in d.iterrows():
        dispatched = _parse_bool(row.get("dispatched"))
        date_scheduled = row.get("date_scheduled")
        date_scheduled = None if pd.isna(date_scheduled) else str(date_scheduled)[:10]
        for line in _parse_json_list(row.get("order_lines")):
            if not isinstance(line, dict):
                continue
            qty = _safe_float(line.get("quantity"))
            if qty <= 0:
                continue

            resolved_name = line.get("product_name")
            product_id = _safe_int(line.get("product"))
            if product_id is not None and product_id in product_id_name_map:
                resolved_name = product_id_name_map[product_id]

            records.append({
                "product_name": json_safe(resolved_name),
                "quantity": qty,
                "date_scheduled": date_scheduled,
                "dispatched": dispatched,
            })
    return records


def prepare_planned_packaging_records(packagings_df, product_id_name_map=None, batch_completion_map=None):
    """Flatten planned packagings into product_name, planned date, and
    quantity still remaining to be packaged - the Forecast tab's
    "planned production" input. This is at the packaged-PRODUCT level
    (distinct from /drink-batches/, which is at the liquid/recipe
    level), matching what the forecast needs to track.

    product.name here is a nested product reference, not a bare
    snapshot string field the way order-lines' product_name is - so it
    likely already reflects the product's current name even without
    this. Resolved via product ID anyway, purely defensively, since
    it costs nothing and removes any doubt.

    A line whose batch is marked Complete is EXCLUDED here entirely,
    regardless of its own quantity_remaining - once a batch is done,
    nothing more gets packaged from it, whether a specific line was
    never started or mostly finished (Breww doesn't retroactively zero
    out a line's remaining quantity just because the batch concluded
    without fully using it, e.g. because the brewery packaged into a
    different format instead of what was originally planned). Complete
    is the ONLY exclusion signal - a batch id that doesn't resolve
    (deleted batch, no batches_df available), and a batch that's
    merely running behind schedule (Planned or In-progress, however
    overdue its plan_date), are both left in. There's deliberately no
    date-based staleness check here at all - a batch can legitimately
    run well behind its original plan for all sorts of reasons, and
    that alone doesn't mean the plan's been abandoned."""
    if packagings_df is None:
        return []
    product_id_name_map = product_id_name_map or {}
    batch_completion_map = batch_completion_map or {}

    d = packagings_df.copy()
    d["quantity"] = pd.to_numeric(d.get("quantity"), errors="coerce").fillna(0)
    d["quantity_packaged_so_far"] = pd.to_numeric(d.get("quantity_packaged_so_far"), errors="coerce").fillna(0)
    d["quantity_remaining"] = (d["quantity"] - d["quantity_packaged_so_far"]).clip(lower=0)
    d["product_name"] = d.get("product.name")
    d["product_id"] = d.get("product.id")
    d["batch_id"] = d.get("drink_batch.id")

    # Prefer expected_release_date (when it becomes available) over
    # date (when it's planned to be packaged), falling back to
    # whichever one is actually set on a given row.
    release = d.get("expected_release_date")
    planned = d.get("date")
    if release is not None and planned is not None:
        d["plan_date"] = release.where(release.notna(), planned)
    else:
        d["plan_date"] = release if release is not None else planned

    out_cols = ["product_name", "product_id", "batch_id", "plan_date", "quantity_remaining"]
    for col in out_cols:
        if col not in d.columns:
            d[col] = None
    raw_records = d[out_cols].to_dict(orient="records")
    records = []
    for rec in raw_records:
        batch_id = _safe_int(rec.get("batch_id"))
        if batch_id is not None and batch_completion_map.get(batch_id):
            continue  # batch is Complete - nothing more will be packaged from it

        resolved_name = rec.get("product_name")
        product_id = _safe_int(rec.get("product_id"))
        if product_id is not None and product_id in product_id_name_map:
            resolved_name = product_id_name_map[product_id]
        records.append({
            "product_name": json_safe(resolved_name),
            "plan_date": json_safe(rec.get("plan_date")),
            "quantity_remaining": json_safe(rec.get("quantity_remaining")),
        })
    return [r for r in records if r.get("quantity_remaining") and r["quantity_remaining"] > 0]


def build_forecast_section(fulfillments_df, packagings_df, products_df=None, batches_df=None):
    product_id_name_map = build_product_id_name_map(products_df)
    batch_completion_map = build_batch_completion_map(batches_df)
    fulfillment_records = prepare_fulfillment_records(fulfillments_df, product_id_name_map)
    packaging_records = prepare_planned_packaging_records(packagings_df, product_id_name_map, batch_completion_map)
    fulfillment_json = json.dumps(fulfillment_records, allow_nan=False)
    packaging_json = json.dumps(packaging_records, allow_nan=False)
    line_colors_json = json.dumps(HISTOGRAM_COLORS)

    return f"""
<h2>Forecast</h2>
<p class="section-note">Predicts inventory over the next 4 months, combining current stock, planned production, orders already on the books, and a demand projection that leans on recent sales, adjusted for typical seasonal pattern. This is a heuristic estimate based on the assumptions below, not a guarantee - treat it as a planning aid.</p>

<div class="customer-report-controls" id="forecast-controls">
  <div class="filter-group">
    <label>Beer or product</label>
    <div class="customer-dropdown" id="forecast-product-dropdown">
      <button type="button" class="customer-dropdown-toggle" id="forecast-product-toggle">
        <span id="forecast-product-summary">Select a beer or product&hellip;</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="customer-dropdown-panel" id="forecast-product-panel" hidden>
        <input type="text" id="forecast-product-search" class="customer-search-input"
               placeholder="Search beers and products&hellip;" autocomplete="off">
        <div id="forecast-product-list"></div>
        <p id="forecast-product-empty" class="product-search-empty" hidden>No beers or products match your search.</p>
      </div>
    </div>
  </div>
</div>

<p id="forecast-placeholder" class="customer-report-placeholder">Select a beer or product above to generate its forecast. Selecting a beer shows every one of its products (kegs, cans, etc.) together, so you can compare where each is headed at a glance - selecting an individual product shows just that one.</p>

<div id="forecast-content" hidden>
  <h4>Per-Product Summary</h4>
  <p class="section-note">Current stock and where each product is projected to end up, computed fully independently per product - nothing here is summed across products, since different package formats aren't really comparable quantities.</p>
  <div class="table-wrap">
    <table class="data-table" id="forecast-summary-table"></table>
  </div>

  <h4>Projected Inventory</h4>
  <p class="section-note">Starting from current stock, projected forward month by month - one line per product.</p>
  <div id="forecast-chart" class="chart-div"></div>

  <h4>How this forecast is built</h4>
  <p class="section-note">The month-by-month breakdown behind the chart above, so you can sanity-check the assumptions rather than trust an opaque line. Click any column header to sort.</p>
  <div class="table-wrap">
    <table class="data-table" id="forecast-breakdown-table"></table>
  </div>
</div>

<script id="fulfillment-data" type="application/json">{fulfillment_json}</script>
<script id="planned-packaging-data" type="application/json">{packaging_json}</script>
<script>
(function() {{
  var lineDataEl = document.getElementById('order-line-data');
  var lineData = [];
  try {{ lineData = lineDataEl ? JSON.parse(lineDataEl.textContent) : []; }} catch (e) {{ lineData = []; }}

  var stockDataEl = document.getElementById('product-stock-data');
  var stockData = [];
  try {{ stockData = stockDataEl ? JSON.parse(stockDataEl.textContent) : []; }} catch (e) {{ stockData = []; }}

  var fulfillmentData = JSON.parse(document.getElementById('fulfillment-data').textContent);
  var packagingData = JSON.parse(document.getElementById('planned-packaging-data').textContent);
  var lineColors = {line_colors_json};

  var productSet = {{}};
  stockData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  lineData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  fulfillmentData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  packagingData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  var allProducts = Object.keys(productSet).sort();

  // --- Group products by beer, using Breww's own component_drinks
  // link (productDrinkMap, global - see shared.py) rather than
  // guessing from product name text. config.PRODUCT_COLORS' keys are
  // reused as "which beers are groupable" - a product whose linked
  // drink(s) don't match any configured beer name shows up standalone
  // instead of disappearing. A mixed-pack (more than one linked
  // drink) appears under every beer it contains.
  function matchedBeerNamesForProduct(productName) {{
    var drinkNames = productDrinkMap[productName] || [];
    var matched = [];
    drinkNames.forEach(function(dn) {{
      var m = matchConfiguredBeerName(dn);
      if (m && matched.indexOf(m) === -1) matched.push(m);
    }});
    return matched;
  }}

  var beerGroups = {{}};
  var standaloneProducts = [];
  allProducts.forEach(function(p) {{
    var matched = matchedBeerNamesForProduct(p);
    if (matched.length === 0) {{
      standaloneProducts.push(p);
    }} else {{
      matched.forEach(function(beerName) {{
        if (!beerGroups[beerName]) beerGroups[beerName] = [];
        beerGroups[beerName].push(p);
      }});
    }}
  }});

  var pickerEntries = [];
  Object.keys(beerGroups).sort().forEach(function(beerName) {{
    pickerEntries.push({{type: 'beer', label: beerName + ' (all formats)', products: beerGroups[beerName].slice().sort()}});
  }});
  standaloneProducts.sort().forEach(function(p) {{
    pickerEntries.push({{type: 'product', label: p, products: [p]}});
  }});
  pickerEntries.sort(function(a, b) {{ return a.label.localeCompare(b.label); }});

  var selectedEntry = null;

  if (allProducts.length === 0) {{
    document.getElementById('forecast-placeholder').textContent =
      'No product, order, or production data cached yet - run fetch_data.py to pull it, then rebuild.';
  }}

  // --- Beer/product dropdown (searchable, single-select) -----------------------
  var dropdown = document.getElementById('forecast-product-dropdown');
  var panel = document.getElementById('forecast-product-panel');
  var toggle = document.getElementById('forecast-product-toggle');
  var searchInput = document.getElementById('forecast-product-search');
  var listDiv = document.getElementById('forecast-product-list');
  var summary = document.getElementById('forecast-product-summary');
  var emptyMsg = document.getElementById('forecast-product-empty');

  function buildProductList() {{
    listDiv.innerHTML = pickerEntries.map(function(entry, i) {{
      var safe = escapeHtml(entry.label);
      return '<label class="customer-row" data-search="' + safe.toLowerCase() + '" data-index="' + i + '">' + safe + '</label>';
    }}).join('') || '<span style="font-size:12px;color:#a39a8c;">No beers or products found</span>';
  }}

  function filterProductRows(query) {{
    var q = query.trim().toLowerCase();
    var rows = listDiv.querySelectorAll('.customer-row');
    var anyVisible = false;
    rows.forEach(function(row) {{
      var matches = !q || row.getAttribute('data-search').indexOf(q) !== -1;
      row.style.display = matches ? '' : 'none';
      if (matches) anyVisible = true;
    }});
    if (emptyMsg) emptyMsg.hidden = anyVisible || rows.length === 0;
  }}

  function openDropdown() {{
    panel.hidden = false;
    searchInput.value = '';
    filterProductRows('');
    searchInput.focus();
  }}
  function closeDropdown() {{ panel.hidden = true; }}

  toggle.addEventListener('click', function() {{
    if (panel.hidden) {{ openDropdown(); }} else {{ closeDropdown(); }}
  }});
  searchInput.addEventListener('input', function() {{ filterProductRows(searchInput.value); }});
  document.addEventListener('click', function(e) {{
    if (!dropdown.contains(e.target)) closeDropdown();
  }});
  dropdown.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ closeDropdown(); toggle.focus(); }}
  }});

  listDiv.addEventListener('click', function(e) {{
    var row = e.target.closest('.customer-row');
    if (!row) return;
    var idx = parseInt(row.getAttribute('data-index'), 10);
    selectedEntry = pickerEntries[idx];
    summary.textContent = selectedEntry.label;
    closeDropdown();
    renderForecast();
  }});

  // --- Forecast math ----------------------------------------------------------
  var MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function monthKey(dateStr) {{ return dateStr ? dateStr.slice(0, 7) : null; }}
  function monthLabel(key) {{
    var parts = key.split('-');
    var y = parts[0], m = parseInt(parts[1], 10);
    return MONTH_ABBR[m - 1] + ' ' + y;
  }}
  function fmtNum(n) {{ return Math.round(n).toLocaleString(); }}

  // A trailing-3-month window: the 3 most recently COMPLETED calendar
  // months (not the current, still-in-progress one), and the same 3
  // calendar months exactly one year earlier - shifting by whole
  // months this way (rather than 90 raw days) keeps both windows
  // aligned to the same calendar months, which is what makes the
  // year-over-year comparison meaningful rather than comparing e.g. a
  // summer window against a winter one.
  function shiftMonth(y, m, delta) {{
    var total = (y * 12 + (m - 1)) + delta;
    return {{y: Math.floor(total / 12), m: (total % 12) + 1}};
  }}
  function ymKey(o) {{ return o.y + '-' + (o.m < 10 ? '0' + o.m : o.m); }}

  function computeForecast(productName) {{
    var today = new Date();
    var todayKey = today.toISOString().slice(0, 10);

    var startInventory = stockData
      .filter(function(r) {{ return r.product_name === productName; }})
      .reduce(function(s, r) {{ return s + (r.quantity || 0); }}, 0);

    var months = [];
    var y = today.getUTCFullYear(), m = today.getUTCMonth() + 1;
    for (var i = 0; i < 4; i++) {{
      m++;
      if (m > 12) {{ m = 1; y++; }}
      months.push(y + '-' + (m < 10 ? '0' + m : String(m)));
    }}

    // Known, already-booked orders not yet dispatched.
    var knownUnfulfilled = {{}};
    months.forEach(function(mk) {{ knownUnfulfilled[mk] = 0; }});
    fulfillmentData.forEach(function(r) {{
      if (r.dispatched) return;
      if (r.product_name !== productName) return;
      var mk = monthKey(r.date_scheduled);
      var qty = r.quantity || 0;
      if (mk && knownUnfulfilled.hasOwnProperty(mk)) {{
        knownUnfulfilled[mk] += qty;
      }} else if (!mk || mk < months[0]) {{
        // No scheduled date, or overdue/scheduled before the window
        // starts - treat as due as soon as possible rather than
        // dropping it from the forecast entirely.
        knownUnfulfilled[months[0]] += qty;
      }}
      // Scheduled beyond the 4-month window: not relevant to this chart.
    }});

    // Planned production landing in the window. A plan whose batch is
    // marked Complete never even reaches here - that's filtered out
    // in Python (prepare_planned_packaging_records), since a done
    // batch definitively isn't producing more, regardless of date.
    // Anything that survives that filter is treated as genuinely
    // still active, the same way known unfulfilled orders are below -
    // a plan dated before the forecast window (a batch running
    // behind schedule, for whatever reason) is treated as due as soon
    // as possible rather than dropped, since there's no reason to
    // assume a delayed-but-not-complete batch has been abandoned.
    var plannedProduction = {{}};
    months.forEach(function(mk) {{ plannedProduction[mk] = 0; }});
    packagingData.forEach(function(r) {{
      if (r.product_name !== productName) return;
      var mk = monthKey(r.plan_date);
      var qty = r.quantity_remaining || 0;
      if (mk && plannedProduction.hasOwnProperty(mk)) {{
        plannedProduction[mk] += qty;
      }} else if (!mk || mk < months[0]) {{
        plannedProduction[months[0]] += qty;
      }}
      // Scheduled beyond the 4-month window: not relevant to this chart.
    }});

    // Growth rate, from actual historical order lines, using a
    // trailing window (up to 3 months, see below) rather than
    // year-to-date - weights recent sales much more heavily, while
    // still comparing against the same months a year ago so a
    // genuinely seasonal product doesn't get penalized just because
    // "now" happens to be its off-season.
    function sumQuantityInRange(startDate, endDate) {{
      return lineData.filter(function(r) {{
        return r.product_name === productName &&
          r.order_status_label !== 'Cancelled' &&
          r.issue_date && r.issue_date >= startDate && r.issue_date <= endDate;
      }}).reduce(function(s, r) {{ return s + (r.quantity || 0); }}, 0);
    }}

    // A product's very first sale ever, across all history - used to
    // stop a newly-launched product's pre-launch "zero sales" months
    // from being counted as real down-scaling data. A launch 14
    // months ago and a genuine 0-unit month 14 months ago look
    // identical in the raw numbers otherwise, but mean opposite
    // things for a growth estimate.
    var allSales = lineData.filter(function(r) {{
      return r.product_name === productName && r.order_status_label !== 'Cancelled' && r.issue_date;
    }});
    var firstSaleMonthKey = null;
    allSales.forEach(function(r) {{
      var mk = monthKey(r.issue_date);
      if (!firstSaleMonthKey || mk < firstSaleMonthKey) firstSaleMonthKey = mk;
    }});

    var curY = today.getUTCFullYear(), curM = today.getUTCMonth() + 1;
    var lastCompletedMonth = shiftMonth(curY, curM, -1);
    var lastCompletedMonthKey = ymKey(lastCompletedMonth);

    var growthFactor = 1;
    var hasGrowthHistory = false;
    var lowConfidence = false;
    var trailingThisYear = 0;
    var trailingLastYear = 0;
    var growthWindowMonths = null;

    // Less than one full completed month of history at all (including
    // no sales ever) - no basis for a growth adjustment, use 1x.
    if (firstSaleMonthKey && firstSaleMonthKey <= lastCompletedMonthKey) {{
      // Try the widest window (3 months) first, shrinking to 2 then 1
      // if the product hasn't been around long enough for the wider
      // window's "this year" or "same months last year" side to be
      // real, sold history rather than pre-launch zeros.
      for (var tryN = 3; tryN >= 1; tryN--) {{
        var tryStart = shiftMonth(curY, curM, -tryN);
        var tryStartKey = ymKey(tryStart);
        var tryStartLastYear = shiftMonth(tryStart.y, tryStart.m, -12);
        var tryStartLastYearKey = ymKey(tryStartLastYear);
        if (tryStartKey >= firstSaleMonthKey && tryStartLastYearKey >= firstSaleMonthKey) {{
          growthWindowMonths = tryN;
          break;
        }}
      }}

      if (growthWindowMonths !== null) {{
        var winStart = shiftMonth(curY, curM, -growthWindowMonths);
        var winEnd = lastCompletedMonth;
        var trailingStartKey = ymKey(winStart) + '-01';
        var trailingEndKey = ymKey(winEnd) + '-31';
        trailingThisYear = sumQuantityInRange(trailingStartKey, trailingEndKey);

        var winStartLastYear = shiftMonth(winStart.y, winStart.m, -12);
        var winEndLastYear = shiftMonth(winEnd.y, winEnd.m, -12);
        var trailingStartLastYearKey = ymKey(winStartLastYear) + '-01';
        var trailingEndLastYearKey = ymKey(winEndLastYear) + '-31';
        trailingLastYear = sumQuantityInRange(trailingStartLastYearKey, trailingEndLastYearKey);

        hasGrowthHistory = trailingLastYear > 0;
        growthFactor = hasGrowthHistory ? (trailingThisYear / trailingLastYear) : 1;
        lowConfidence = hasGrowthHistory && trailingLastYear < 20;
      }}
      // growthWindowMonths still null here means the product hasn't
      // been around a full year yet even at a 1-month window - no
      // valid same-period-last-year comparison exists, so it's left
      // at the growthFactor=1 / hasGrowthHistory=false defaults set above.
    }}

    // Projected NEW demand (not yet on the books): last year's actual
    // for that calendar month (the seasonal baseline), scaled by the
    // growth rate above. Deliberately NOT reduced by known unfulfilled
    // orders for that month - those come from a different date field
    // entirely (fulfillments' scheduled delivery date, vs. the order
    // issue dates the baseline and growth rate are built from), so an
    // advance order placed months before its scheduled delivery was
    // never part of the historical baseline to begin with; subtracting
    // it here would silently understate demand rather than avoid
    // double-counting. Known orders and projected demand are added as
    // independent outflows in the running total below instead.
    // "One year before" is computed from EACH forecast month's own
    // year, not from today's year - a forecast month that rolls into
    // next calendar year (e.g. forecasting from October into next
    // January) needs its baseline from THIS January, not from two
    // years back.
    var projectedDemand = {{}};
    var hasSeasonalBaseline = {{}};
    months.forEach(function(mk) {{
      var parts = mk.split('-');
      var thisMonthYear = parseInt(parts[0], 10);
      var lastYearMonthKey = (thisMonthYear - 1) + '-' + parts[1];
      var lastYearMonthActual = sumQuantityInRange(lastYearMonthKey + '-01', lastYearMonthKey + '-31');
      hasSeasonalBaseline[mk] = lastYearMonthActual > 0;
      projectedDemand[mk] = lastYearMonthActual * growthFactor;
    }});

    var points = [{{label: 'Now', key: null, inventory: startInventory}}];
    var running = startInventory;
    months.forEach(function(mk) {{
      running += plannedProduction[mk];
      running -= knownUnfulfilled[mk];
      running -= projectedDemand[mk];
      points.push({{label: monthLabel(mk), key: mk, inventory: running}});
    }});

    return {{
      productName: productName, points: points, months: months, startInventory: startInventory,
      knownUnfulfilled: knownUnfulfilled, plannedProduction: plannedProduction,
      projectedDemand: projectedDemand, growthFactor: growthFactor,
      hasGrowthHistory: hasGrowthHistory, lowConfidence: lowConfidence,
      hasSeasonalBaseline: hasSeasonalBaseline, growthWindowMonths: growthWindowMonths,
      trailingThisYear: trailingThisYear, trailingLastYear: trailingLastYear
    }};
  }}

  // --- Sortable breakdown table -----------------------------------------------
  var BREAKDOWN_COLUMNS = [
    {{key: 'product_name', label: 'Product', type: 'string'}},
    {{key: 'month_label', label: 'Month', type: 'string'}},
    {{key: 'planned_production', label: 'Planned production', type: 'number'}},
    {{key: 'known_orders', label: 'Known orders', type: 'number'}},
    {{key: 'projected_demand', label: 'Projected new demand', type: 'number'}},
    {{key: 'ending_inventory', label: 'Ending inventory', type: 'number'}}
  ];
  var breakdownSortColumn = 'product_name';
  var breakdownSortAscending = true;

  function renderForecast() {{
    var placeholder = document.getElementById('forecast-placeholder');
    var content = document.getElementById('forecast-content');
    if (!selectedEntry) {{
      placeholder.hidden = false;
      content.hidden = true;
      return;
    }}
    placeholder.hidden = true;
    content.hidden = false;

    breakdownSortColumn = 'product_name';
    breakdownSortAscending = true;

    var forecasts = selectedEntry.products.map(function(p) {{ return computeForecast(p); }});

    // --- Per-Product Summary table ---
    var summaryRows = forecasts.map(function(f) {{
      var endInv = f.points[f.points.length - 1].inventory;
      var growthDisplay = f.hasGrowthHistory ? (f.growthFactor * 100).toFixed(0) + '%' : 'N/A';
      if (f.hasGrowthHistory && f.growthWindowMonths && f.growthWindowMonths < 3) {{
        growthDisplay += ' (' + f.growthWindowMonths + 'mo window - new product)';
      }}
      if (f.hasGrowthHistory && f.lowConfidence) growthDisplay += ' (low confidence)';
      return '<tr>' +
        '<td>' + escapeHtml(f.productName) + '</td>' +
        '<td>' + fmtNum(f.startInventory) + '</td>' +
        '<td>' + fmtNum(endInv) + '</td>' +
        '<td>' + growthDisplay + '</td>' +
        '</tr>';
    }}).join('');
    document.getElementById('forecast-summary-table').innerHTML =
      '<thead><tr><th>Product</th><th>Current stock</th><th>Projected in 4 months</th><th>Trailing growth used (up to 3mo)</th></tr></thead>' +
      '<tbody>' + summaryRows + '</tbody>';

    // --- Chart: one line per product ---
    var traces = forecasts.map(function(f, i) {{
      return {{
        x: f.points.map(function(p) {{ return p.label; }}),
        y: f.points.map(function(p) {{ return p.inventory; }}),
        type: 'scatter', mode: 'lines+markers', name: f.productName,
        line: {{color: lineColors[i % lineColors.length]}}, marker: {{color: lineColors[i % lineColors.length]}}
      }};
    }});
    Plotly.react('forecast-chart', traces, {{
      template: 'plotly_white', title: selectedEntry.label + ' - Projected inventory, next 4 months',
      height: 460, margin: {{t: 60, b: 60, l: 70, r: 30}},
      yaxis: {{title: 'Units in stock'}}, xaxis: {{title: ''}},
      legend: {{title: {{text: ''}}}},
      shapes: [{{type: 'line', x0: 0, x1: 1, xref: 'paper', y0: 0, y1: 0, yref: 'y',
                 line: {{color: '#D46A6A', dash: 'dot', width: 1}}}}]
    }}, {{displayModeBar: false, responsive: true}});

    // --- Combined, sortable breakdown table ---
    var allRows = [];
    forecasts.forEach(function(f) {{
      f.months.forEach(function(mk, i) {{
        var note = '';
        if (!f.hasGrowthHistory) {{
          note = ' (no history)';
        }} else if (f.lowConfidence) {{
          note = ' (low confidence)';
        }} else if (!f.hasSeasonalBaseline[mk]) {{
          note = ' (no history for this month)';
        }}
        allRows.push({{
          product_name: f.productName,
          month_label: monthLabel(mk),
          month_key: mk,
          planned_production: f.plannedProduction[mk],
          known_orders: f.knownUnfulfilled[mk],
          projected_demand: f.projectedDemand[mk],
          projected_demand_note: note,
          ending_inventory: f.points[i + 1].inventory
        }});
      }});
    }});

    renderBreakdownTable(allRows);

    document.getElementById('forecast-breakdown-table').onclick = function(e) {{
      var btn = e.target.closest('[data-sort-key]');
      if (!btn) return;
      var key = btn.getAttribute('data-sort-key');
      if (breakdownSortColumn === key) {{
        breakdownSortAscending = !breakdownSortAscending;
      }} else {{
        breakdownSortColumn = key;
        var colDef = BREAKDOWN_COLUMNS.find(function(c) {{ return c.key === key; }});
        breakdownSortAscending = colDef.type !== 'number';
      }}
      renderBreakdownTable(allRows);
    }};
  }}

  function renderBreakdownTable(allRows) {{
    var colDef = BREAKDOWN_COLUMNS.find(function(c) {{ return c.key === breakdownSortColumn; }}) || BREAKDOWN_COLUMNS[0];
    var sorted = sortGenericRows(allRows, breakdownSortColumn, breakdownSortAscending, colDef.type);
    var rows = sorted.map(function(r) {{
      return '<tr>' +
        '<td>' + escapeHtml(r.product_name) + '</td>' +
        '<td>' + escapeHtml(r.month_label) + '</td>' +
        '<td>+' + fmtNum(r.planned_production) + '</td>' +
        '<td>-' + fmtNum(r.known_orders) + '</td>' +
        '<td>-' + fmtNum(r.projected_demand) + escapeHtml(r.projected_demand_note) + '</td>' +
        '<td>' + fmtNum(r.ending_inventory) + '</td>' +
        '</tr>';
    }}).join('');
    document.getElementById('forecast-breakdown-table').innerHTML =
      buildSortableHeaderRow(BREAKDOWN_COLUMNS, breakdownSortColumn, breakdownSortAscending) + '<tbody>' + rows + '</tbody>';
  }}

  buildProductList();
}})();
</script>
"""
