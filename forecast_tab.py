"""Forecast tab: projected inventory for a chosen product over the
next 4 months, combining current stock, planned production, existing
unfulfilled orders, and a seasonal demand projection."""
import json

import pandas as pd

from shared import json_safe, _safe_float, _parse_bool, _parse_json_list

def prepare_fulfillment_records(fulfillments_df):
    """Explode each fulfillment's order_lines into per-product-quantity
    records for the Forecast tab's "existing unfulfilled orders" input.
    Each fulfillment carries a dispatched flag and a scheduled date at
    the fulfillment level, which every line item inside it inherits."""
    if fulfillments_df is None:
        return []

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
            records.append({
                "product_name": json_safe(line.get("product_name")),
                "quantity": qty,
                "date_scheduled": date_scheduled,
                "dispatched": dispatched,
            })
    return records


def prepare_planned_packaging_records(packagings_df):
    """Flatten planned packagings into product_name, planned date, and
    quantity still remaining to be packaged - the Forecast tab's
    "planned production" input. This is at the packaged-PRODUCT level
    (distinct from /drink-batches/, which is at the liquid/recipe
    level), matching what the forecast needs to track."""
    if packagings_df is None:
        return []

    d = packagings_df.copy()
    d["quantity"] = pd.to_numeric(d.get("quantity"), errors="coerce").fillna(0)
    d["quantity_packaged_so_far"] = pd.to_numeric(d.get("quantity_packaged_so_far"), errors="coerce").fillna(0)
    d["quantity_remaining"] = (d["quantity"] - d["quantity_packaged_so_far"]).clip(lower=0)
    d["product_name"] = d.get("product.name")

    # Prefer expected_release_date (when it becomes available) over
    # date (when it's planned to be packaged), falling back to
    # whichever one is actually set on a given row.
    release = d.get("expected_release_date")
    planned = d.get("date")
    if release is not None and planned is not None:
        d["plan_date"] = release.where(release.notna(), planned)
    else:
        d["plan_date"] = release if release is not None else planned

    out_cols = ["product_name", "plan_date", "quantity_remaining"]
    for col in out_cols:
        if col not in d.columns:
            d[col] = None
    raw_records = d[out_cols].to_dict(orient="records")
    records = [{k: json_safe(v) for k, v in rec.items()} for rec in raw_records]
    return [r for r in records if r.get("quantity_remaining") and r["quantity_remaining"] > 0]


def build_forecast_section(fulfillments_df, packagings_df):
    fulfillment_records = prepare_fulfillment_records(fulfillments_df)
    packaging_records = prepare_planned_packaging_records(packagings_df)
    fulfillment_json = json.dumps(fulfillment_records, allow_nan=False)
    packaging_json = json.dumps(packaging_records, allow_nan=False)

    return f"""
<h2>Forecast</h2>
<p class="section-note">Predicts a product's inventory level over the next 4 months, combining current stock, planned production, orders already on the books, and a seasonal demand projection scaled for year-over-year growth. This is a heuristic estimate based on the assumptions below, not a guarantee - treat it as a planning aid.</p>

<div class="customer-report-controls" id="forecast-controls">
  <div class="filter-group">
    <label>Product</label>
    <div class="customer-dropdown" id="forecast-product-dropdown">
      <button type="button" class="customer-dropdown-toggle" id="forecast-product-toggle">
        <span id="forecast-product-summary">Select a product&hellip;</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="customer-dropdown-panel" id="forecast-product-panel" hidden>
        <input type="text" id="forecast-product-search" class="customer-search-input"
               placeholder="Search products&hellip;" autocomplete="off">
        <div id="forecast-product-list"></div>
        <p id="forecast-product-empty" class="product-search-empty" hidden>No products match your search.</p>
      </div>
    </div>
  </div>
</div>

<p id="forecast-placeholder" class="customer-report-placeholder">Select a product above to generate its forecast.</p>

<div id="forecast-content" hidden>
  <div class="kpi-row" id="forecast-kpi-row"></div>
  <h4>Projected Inventory</h4>
  <p class="section-note">Starting from current stock, projected forward month by month using the inputs described below.</p>
  <div id="forecast-chart" class="chart-div"></div>
  <p id="forecast-warning" class="section-note" style="display:none; color:#a35;"></p>
  <h4>How this forecast is built</h4>
  <p class="section-note">The month-by-month breakdown behind the chart above, so you can sanity-check the assumptions rather than trust an opaque line.</p>
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

  var productSet = {{}};
  stockData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  lineData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  fulfillmentData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  packagingData.forEach(function(r) {{ if (r.product_name) productSet[r.product_name] = true; }});
  var allProducts = Object.keys(productSet).sort();

  var selectedProduct = null;

  if (allProducts.length === 0) {{
    document.getElementById('forecast-placeholder').textContent =
      'No product, order, or production data cached yet - run fetch_data.py to pull it, then rebuild.';
  }}

  // --- Product dropdown (searchable, single-select) -----------------------
  var dropdown = document.getElementById('forecast-product-dropdown');
  var panel = document.getElementById('forecast-product-panel');
  var toggle = document.getElementById('forecast-product-toggle');
  var searchInput = document.getElementById('forecast-product-search');
  var listDiv = document.getElementById('forecast-product-list');
  var summary = document.getElementById('forecast-product-summary');
  var emptyMsg = document.getElementById('forecast-product-empty');

  function buildProductList() {{
    listDiv.innerHTML = allProducts.map(function(p) {{
      var safe = escapeHtml(p);
      return '<label class="customer-row" data-search="' + safe.toLowerCase() + '" data-name="' + safe + '">' + safe + '</label>';
    }}).join('') || '<span style="font-size:12px;color:#a39a8c;">No products found</span>';
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
    selectedProduct = row.getAttribute('data-name');
    summary.textContent = selectedProduct;
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

    // Planned production landing in the window.
    var plannedProduction = {{}};
    months.forEach(function(mk) {{ plannedProduction[mk] = 0; }});
    packagingData.forEach(function(r) {{
      if (r.product_name !== productName) return;
      var mk = monthKey(r.plan_date);
      var qty = r.quantity_remaining || 0;
      if (mk && plannedProduction.hasOwnProperty(mk)) {{
        plannedProduction[mk] += qty;
      }} else if (mk && mk < months[0]) {{
        plannedProduction[months[0]] += qty;
      }}
    }});

    // Year-over-year growth rate, from actual historical order lines.
    function sumQuantityInRange(startDate, endDate) {{
      return lineData.filter(function(r) {{
        return r.product_name === productName &&
          r.order_status_label !== 'Cancelled' &&
          r.issue_date && r.issue_date >= startDate && r.issue_date <= endDate;
      }}).reduce(function(s, r) {{ return s + (r.quantity || 0); }}, 0);
    }}

    var thisYear = today.getUTCFullYear();
    var lastYear = thisYear - 1;
    var thisYearToDate = sumQuantityInRange(thisYear + '-01-01', todayKey);
    var lastYearSamePeriod = sumQuantityInRange(lastYear + '-01-01', lastYear + todayKey.slice(4));

    var hasGrowthHistory = lastYearSamePeriod > 0;
    var growthFactor = hasGrowthHistory ? (thisYearToDate / lastYearSamePeriod) : 1;
    var lowConfidence = hasGrowthHistory && lastYearSamePeriod < 20;

    // Projected NEW demand (not yet on the books): last year's actual
    // for that calendar month, scaled by the growth rate, minus
    // whatever's already known/booked for that month - so a booked
    // order is never counted twice.
    var projectedDemand = {{}};
    months.forEach(function(mk) {{
      var parts = mk.split('-');
      var lastYearMonthKey = lastYear + '-' + parts[1];
      var lastYearMonthActual = sumQuantityInRange(lastYearMonthKey + '-01', lastYearMonthKey + '-31');
      var projectedTotal = lastYearMonthActual * growthFactor;
      var alreadyKnown = knownUnfulfilled[mk] || 0;
      projectedDemand[mk] = Math.max(0, projectedTotal - alreadyKnown);
    }});

    var points = [{{ label: 'Now', key: null, inventory: startInventory }}];
    var running = startInventory;
    months.forEach(function(mk) {{
      running += plannedProduction[mk];
      running -= knownUnfulfilled[mk];
      running -= projectedDemand[mk];
      points.push({{ label: monthLabel(mk), key: mk, inventory: running }});
    }});

    return {{
      points: points, months: months, startInventory: startInventory,
      knownUnfulfilled: knownUnfulfilled, plannedProduction: plannedProduction,
      projectedDemand: projectedDemand, growthFactor: growthFactor,
      hasGrowthHistory: hasGrowthHistory, lowConfidence: lowConfidence,
      thisYearToDate: thisYearToDate, lastYearSamePeriod: lastYearSamePeriod
    }};
  }}

  function renderForecast() {{
    var placeholder = document.getElementById('forecast-placeholder');
    var content = document.getElementById('forecast-content');
    if (!selectedProduct) {{
      placeholder.hidden = false;
      content.hidden = true;
      return;
    }}
    placeholder.hidden = true;
    content.hidden = false;

    var f = computeForecast(selectedProduct);
    var endInventory = f.points[f.points.length - 1].inventory;

    document.getElementById('forecast-kpi-row').innerHTML =
      '<div class="kpi"><div class="kpi-value">' + fmtNum(f.startInventory) + '</div><div class="kpi-label">Current stock</div></div>' +
      '<div class="kpi"><div class="kpi-value">' + fmtNum(endInventory) + '</div><div class="kpi-label">Projected in 4 months</div></div>' +
      '<div class="kpi"><div class="kpi-value">' + (f.hasGrowthHistory ? (f.growthFactor * 100).toFixed(0) + '%' : 'N/A') + '</div><div class="kpi-label">YoY demand growth used</div></div>';

    var warningEl = document.getElementById('forecast-warning');
    if (!f.hasGrowthHistory) {{
      warningEl.style.display = '';
      warningEl.textContent = 'No matching sales in the same period last year for this product - the demand projection is based only on known orders and planned production, not a seasonal estimate.';
    }} else if (f.lowConfidence) {{
      warningEl.style.display = '';
      warningEl.textContent = 'Limited historical sales for this product in the comparison period (' + fmtNum(f.lastYearSamePeriod) + ' units last year) - the growth-rate estimate may be unreliable.';
    }} else {{
      warningEl.style.display = 'none';
    }}

    var traces = [{{
      x: f.points.map(function(p) {{ return p.label; }}),
      y: f.points.map(function(p) {{ return p.inventory; }}),
      type: 'scatter', mode: 'lines+markers', name: 'Projected inventory',
      line: {{color: '#4CAF6B'}}, marker: {{color: '#4CAF6B'}}
    }}];
    Plotly.react('forecast-chart', traces, {{
      template: 'plotly_white', title: selectedProduct + ' - Projected inventory, next 4 months',
      height: 460, margin: {{t: 60, b: 60, l: 70, r: 30}},
      yaxis: {{title: 'Units in stock'}}, xaxis: {{title: ''}},
      shapes: [{{type: 'line', x0: 0, x1: 1, xref: 'paper', y0: 0, y1: 0, yref: 'y',
                 line: {{color: '#D46A6A', dash: 'dot', width: 1}}}}]
    }}, {{displayModeBar: false, responsive: true}});

    var rows = f.months.map(function(mk, i) {{
      return '<tr>' +
        '<td>' + escapeHtml(monthLabel(mk)) + '</td>' +
        '<td>+' + fmtNum(f.plannedProduction[mk]) + '</td>' +
        '<td>-' + fmtNum(f.knownUnfulfilled[mk]) + '</td>' +
        '<td>-' + fmtNum(f.projectedDemand[mk]) + '</td>' +
        '<td>' + fmtNum(f.points[i + 1].inventory) + '</td>' +
        '</tr>';
    }}).join('');
    document.getElementById('forecast-breakdown-table').innerHTML =
      '<thead><tr><th>Month</th><th>Planned production</th><th>Known orders</th>' +
      '<th>Projected new demand</th><th>Ending inventory</th></tr></thead><tbody>' + rows + '</tbody>';
  }}

  buildProductList();
}})();
</script>
"""


# ---------------------------------------------------------------------
# Growth & Efficiency tab: New Account Sales, Sales Per Customer, and
# a Dormant Customers table. Reuses the order/order-line data already
# embedded by the Orders tab (read by element id at runtime) plus a
# new customer-contact dataset from /customers-suppliers/, embedded
# here for the Dormant Customers table.
# ---------------------------------------------------------------------
