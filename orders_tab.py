"""Orders tab: Sales by Month, Sales by Month by Product, All Products
Sold, Top 10 Customers, and the recent orders table."""
import json

import pandas as pd

import config
from shared import (
    json_safe, filter_dropdown_html, has_cols, STACK_STATUSES, STACK_COLORS,
    PRIOR_YEAR_COLORS, MONTH_NAMES, BEER_TOP_N, BEER_COLORS, HISTOGRAM_COLORS,
)

def prepare_orders_records(df, customer_types_df):
    """Build a lightweight list of dicts (JSON-serializable) with just
    the fields the browser-side filtering/charting code needs."""
    d = df.copy()

    if customer_types_df is not None and has_cols(customer_types_df, ["id", "type_name"]):
        type_map = dict(zip(customer_types_df["id"], customer_types_df["type_name"]))
        d["customer_type_name"] = d.get("customer.type", pd.Series(dtype=float)).map(type_map)
    else:
        d["customer_type_name"] = None

    if "issue_date" in d.columns:
        parsed = pd.to_datetime(d["issue_date"], errors="coerce", utc=True)
        d["issue_date"] = parsed.dt.strftime("%Y-%m-%d")
    else:
        d["issue_date"] = None

    d["order_status_label"] = d.get("order_status", pd.Series(dtype=float)).map(config.ORDER_STATUS_LABELS)
    d["payment_status_label"] = d.get("payment_status", pd.Series(dtype=float)).map(config.PAYMENT_STATUS_LABELS)
    d["customer_id"] = d.get("customer.id")
    d["customer_name"] = d.get("customer.name")

    for col in ("total", "value", "amount_due"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0)
        else:
            d[col] = 0

    out_cols = ["number", "issue_date", "customer_id", "customer_name", "customer_type_name",
                "order_status_label", "payment_status_label", "total", "value", "amount_due"]
    for col in out_cols:
        if col not in d.columns:
            d[col] = None

    raw_records = d[out_cols].to_dict(orient="records")
    records = [{k: json_safe(v) for k, v in rec.items()} for rec in raw_records]
    return records


def _order_lookup(orders_df, customer_types_df):
    """Map order id -> {issue_date, order_status_label, customer_type_name,
    customer_id, customer_name}. Used to enrich order-line records with
    fields that only live on the parent order (order lines don't carry
    issue_date or customer info themselves)."""
    if orders_df is None or "id" not in orders_df.columns:
        return {}
    d = orders_df.copy()

    if customer_types_df is not None and has_cols(customer_types_df, ["id", "type_name"]):
        type_map = dict(zip(customer_types_df["id"], customer_types_df["type_name"]))
        d["customer_type_name"] = d.get("customer.type", pd.Series(dtype=float)).map(type_map)
    else:
        d["customer_type_name"] = None

    if "issue_date" in d.columns:
        d["issue_date"] = pd.to_datetime(d["issue_date"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
    else:
        d["issue_date"] = None

    d["order_status_label"] = d.get("order_status", pd.Series(dtype=float)).map(config.ORDER_STATUS_LABELS)
    d["customer_id"] = d.get("customer.id")
    d["customer_name"] = d.get("customer.name")

    cols = ["id", "issue_date", "order_status_label", "customer_type_name", "customer_id", "customer_name"]
    lookup = {}
    for row in d[cols].to_dict(orient="records"):
        lookup[row["id"]] = {
            "issue_date": json_safe(row["issue_date"]),
            "order_status_label": json_safe(row["order_status_label"]),
            "customer_type_name": json_safe(row["customer_type_name"]),
            "customer_id": json_safe(row["customer_id"]),
            "customer_name": json_safe(row["customer_name"]),
        }
    return lookup


def prepare_order_line_records(order_lines_df, orders_df, customer_types_df):
    """Build order-line-level records (one per product/beer sold on an
    order), enriched with the parent order's issue_date, status,
    customer type, customer id/name, plus quantity - so the browser can
    filter and bucket these the same way as the order-level records,
    and so the per-customer report can group by customer and toggle
    between $ and units."""
    if order_lines_df is None:
        return []

    order_id_col = "order.id" if "order.id" in order_lines_df.columns else None
    if order_id_col is None:
        return []

    lookup = _order_lookup(orders_df, customer_types_df)

    d = order_lines_df.copy()
    d["value"] = pd.to_numeric(d.get("value"), errors="coerce").fillna(0)
    d["quantity"] = pd.to_numeric(d.get("quantity"), errors="coerce").fillna(0)
    d["product_name"] = d.get("product_name")

    records = []
    for row in d[[order_id_col, "product_name", "value", "quantity"]].to_dict(orient="records"):
        order_info = lookup.get(row[order_id_col])
        if order_info is None:
            continue
        records.append({
            "order_id": json_safe(row[order_id_col]),
            "issue_date": order_info["issue_date"],
            "order_status_label": order_info["order_status_label"],
            "customer_type_name": order_info["customer_type_name"],
            "customer_id": order_info["customer_id"],
            "customer_name": order_info["customer_name"],
            "product_name": json_safe(row["product_name"]),
            "value": json_safe(row["value"]),
            "quantity": json_safe(row["quantity"]),
        })
    return records


def build_orders_section(df, customer_types_df, order_lines_df):
    if df is None:
        return (
            "<h2>Orders</h2><p class='missing'>No cached data yet - run fetch_data.py first.</p>"
            '<script id="order-line-data" type="application/json">[]</script>'
        )

    records = prepare_orders_records(df, customer_types_df)
    records_json = json.dumps(records, allow_nan=False)
    line_records = prepare_order_line_records(order_lines_df, df, customer_types_df)
    line_records_json = json.dumps(line_records, allow_nan=False)
    default_types_json = json.dumps(config.DEFAULT_CUSTOMER_TYPES)
    stack_statuses_json = json.dumps(STACK_STATUSES)
    stack_colors_json = json.dumps(STACK_COLORS)
    beer_colors_json = json.dumps(BEER_COLORS)
    histogram_colors_json = json.dumps(HISTOGRAM_COLORS)

    month_customer_type_html = filter_dropdown_html("month-customer-type", "Customer type", "customer types")
    month_order_status_html = filter_dropdown_html("month-order-status", "Order status", "statuses")
    beer_customer_type_html = filter_dropdown_html("beer-customer-type", "Customer type", "customer types")
    beer_order_status_html = filter_dropdown_html("beer-order-status", "Order status", "statuses")
    beer_product_html = filter_dropdown_html("beer-product", "Product", "products")
    hist_customer_type_html = filter_dropdown_html("hist-customer-type", "Customer type", "customer types")
    hist_order_status_html = filter_dropdown_html("hist-order-status", "Order status", "statuses")
    hist_product_html = filter_dropdown_html("hist-product", "Product", "products")

    return f"""
<h2>Orders</h2>

<h3>Sales by Month</h3>
<p class="section-note">Net sales value by month, stacked by order status, with every prior year plotted as a dashed comparison line.</p>
<div class="filters-panel" id="month-filters">
{month_customer_type_html}
{month_order_status_html}
  <div class="filter-actions">
    <button id="btn-reset-month-filters">Reset</button>
  </div>
</div>

<div class="kpi-row" id="orders-kpi-row"></div>

<div id="chart-sales-by-month" class="chart-div"></div>

<h3>Sales by Month, by Product</h3>
<p class="section-note">Same as above, but each bar is broken down by product instead of order status - the top 7 by value get their own segment, everything else groups into "Other".</p>
<div class="chart-scoped-filter" id="beer-filters">
{beer_customer_type_html}
{beer_order_status_html}
{beer_product_html}
  <div class="filter-group">
    <label>Metric</label>
    <div class="unit-toggle" id="beer-unit-toggle">
      <button type="button" class="active" data-unit="value">Sales $</button>
      <button type="button" data-unit="quantity"># of units</button>
    </div>
  </div>
  <div class="filter-actions">
    <button id="btn-reset-beer-filters">Reset</button>
  </div>
</div>
<div id="chart-sales-by-beer" class="chart-div"></div>

<h3>All Products Sold</h3>
<p class="section-note">Every qualifying product as its own bar, sorted highest to lowest, over whatever date range and filters you set below.</p>
<div class="chart-scoped-filter" id="orders-histogram-filters">
{hist_customer_type_html}
{hist_order_status_html}
{hist_product_html}
  <div class="filter-group">
    <label>Date range</label>
    <div style="display:flex; gap:8px; align-items:center;">
      <input type="date" id="orders-histogram-begin">
      <span>to</span>
      <input type="date" id="orders-histogram-end">
    </div>
  </div>
  <div class="filter-group">
    <label>Metric</label>
    <div class="unit-toggle" id="orders-histogram-unit-toggle">
      <button type="button" class="active" data-unit="value">Sales $</button>
      <button type="button" data-unit="quantity"># of units</button>
    </div>
  </div>
  <div class="filter-actions">
    <button id="btn-reset-orders-histogram-filters">Reset</button>
  </div>
</div>
<div id="chart-orders-histogram" class="chart-div"></div>

<h3>Top 10 Customers</h3>
<p class="section-note">Your top 10 customers by total order value, all-time.</p>
<div id="chart-top-customers" class="chart-div"></div>

<h3>Recent Orders</h3>
<p class="section-note">Your 25 most recent orders, all-time.</p>
<div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Number</th><th>Issue date</th><th>Customer</th><th>Status</th>
      <th>Payment status</th><th>Total</th><th>Amount due</th>
    </tr></thead>
    <tbody id="orders-table-body"></tbody>
  </table>
</div>

<script id="orders-data" type="application/json">{records_json}</script>
<script id="order-line-data" type="application/json">{line_records_json}</script>
<script>
(function() {{
  var rawData = JSON.parse(document.getElementById('orders-data').textContent);
  var rawLineData = JSON.parse(document.getElementById('order-line-data').textContent);
  var defaultCustomerTypes = {default_types_json};
  var stackStatuses = {stack_statuses_json};
  var stackColors = {stack_colors_json};
  var priorYearColors = {json.dumps(PRIOR_YEAR_COLORS)};
  var beerColors = {beer_colors_json};
  var beerTopN = {BEER_TOP_N};
  var histogramColors = {histogram_colors_json};
  var histogramMinSalesValue = {config.HISTOGRAM_MIN_SALES_VALUE};
  var histogramMinSalesUnits = {config.HISTOGRAM_MIN_SALES_UNITS};
  var monthNames = {json.dumps(MONTH_NAMES)};

  var allCustomerTypes = Array.from(new Set(rawData.map(function(r) {{ return r.customer_type_name; }})
    .filter(function(v) {{ return v; }}))).sort();
  var allOrderStatuses = Array.from(new Set(rawData.map(function(r) {{ return r.order_status_label; }})
    .filter(function(v) {{ return v; }}))).sort();
  var allProductNames = Array.from(new Set(rawLineData.map(function(r) {{ return r.product_name; }})
    .filter(function(v) {{ return v; }}))).sort();

  var defaultCustomerTypesFiltered = defaultCustomerTypes.filter(function(t) {{ return allCustomerTypes.indexOf(t) !== -1; }});

  // findConfiguredProductColor()/buildProductColorMap() are global,
  // shared by every chart on every tab that colors individual
  // products - see shared.py. This histogram's per-bar color is
  // stable across filter/date range changes because it's built once
  // here from the FULL product list, not recomputed from whatever's
  // currently visible.
  var productColorMap = buildProductColorMap(allProductNames, histogramColors);


  function filterOrdersForMonth(state) {{
    // Scoped only to "Sales by Month" - unchecking every box means
    // "match none", not "no filter".
    return rawData.filter(function(r) {{
      if (state.customerTypes.indexOf(r.customer_type_name) === -1) return false;
      if (state.orderStatuses.indexOf(r.order_status_label) === -1) return false;
      return true;
    }});
  }}

  function filterLineData(state) {{
    // Scoped only to "Sales by Month, by Product". Order-line records
    // carry a copy of their parent order's customer type and status,
    // so this filter state applies to them too - plus the product
    // filter, which only applies here since orders don't have a
    // single product of their own.
    return rawLineData.filter(function(r) {{
      if (state.customerTypes.indexOf(r.customer_type_name) === -1) return false;
      if (state.orderStatuses.indexOf(r.order_status_label) === -1) return false;
      if (state.products.indexOf(r.product_name) === -1) return false;
      return true;
    }});
  }}

  function filterLineDataForHistogram(state) {{
    // Same as filterLineData, plus an optional date range - scoped
    // only to the "All Products Sold" histogram.
    return rawLineData.filter(function(r) {{
      if (state.customerTypes.indexOf(r.customer_type_name) === -1) return false;
      if (state.orderStatuses.indexOf(r.order_status_label) === -1) return false;
      if (state.products.indexOf(r.product_name) === -1) return false;
      if (state.begin && (!r.issue_date || r.issue_date < state.begin)) return false;
      if (state.end && (!r.issue_date || r.issue_date > state.end)) return false;
      return true;
    }});
  }}

  function fmtMoney(n) {{
    return '$' + Number(n || 0).toLocaleString(undefined, {{maximumFractionDigits: 0}});
  }}

  function updateKPIs(rows) {{
    var count = rows.length;
    var totalValue = rows.reduce(function(s, r) {{ return s + (r.total || 0); }}, 0);
    var amountDue = rows.reduce(function(s, r) {{ return s + (r.amount_due || 0); }}, 0);
    document.getElementById('orders-kpi-row').innerHTML =
      '<div class="kpi"><div class="kpi-value">' + count.toLocaleString() + '</div><div class="kpi-label">Orders (all-time)</div></div>' +
      '<div class="kpi"><div class="kpi-value">' + fmtMoney(totalValue) + '</div><div class="kpi-label">Total order value (all-time)</div></div>' +
      '<div class="kpi"><div class="kpi-value">' + fmtMoney(amountDue) + '</div><div class="kpi-label">Amount still due (all-time)</div></div>';
  }}

  function monthlySum(rows, year, status) {{
    var sums = new Array(12).fill(0);
    rows.forEach(function(r) {{
      if (!r.issue_date) return;
      var d = new Date(r.issue_date + 'T00:00:00Z');
      if (d.getUTCFullYear() !== year) return;
      if (status) {{
        if (r.order_status_label !== status) return;
      }} else {{
        if (stackStatuses.indexOf(r.order_status_label) === -1) return;
      }}
      sums[d.getUTCMonth()] += (r.value || 0);
    }});
    return sums;
  }}

  function updateSalesByMonthChart(rows) {{
    var thisYear = new Date().getUTCFullYear();

    var priorYears = Array.from(new Set(
      rows.map(function(r) {{
        if (!r.issue_date) return null;
        var y = new Date(r.issue_date + 'T00:00:00Z').getUTCFullYear();
        return (y && y !== thisYear) ? y : null;
      }}).filter(function(y) {{ return y !== null; }})
    )).sort(function(a, b) {{ return b - a; }});  // most recent prior year first

    var traces = stackStatuses.map(function(s) {{
      return {{
        x: monthNames, y: monthlySum(rows, thisYear, s), name: s + ' orders (' + thisYear + ')',
        type: 'bar', marker: {{color: stackColors[s]}}
      }};
    }});

    priorYears.forEach(function(year, i) {{
      var color = priorYearColors[i % priorYearColors.length];
      traces.push({{
        x: monthNames, y: monthlySum(rows, year, null), name: String(year),
        mode: 'lines+markers', type: 'scatter',
        line: {{color: color, dash: 'dash'}}, marker: {{color: color}}
      }});
    }});

    Plotly.react('chart-sales-by-month', traces, {{
      barmode: 'stack', template: 'plotly_white',
      title: 'Sales by Month',
      yaxis: {{title: 'Net Sales Value ($)'}}, xaxis: {{title: ''}}, legend: {{title: {{text: ''}}}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  var beerUnitMode = 'value';

  function updateSalesByBeerChart(lineRows) {{
    var thisYear = new Date().getUTCFullYear();
    var metricField = beerUnitMode === 'quantity' ? 'quantity' : 'value';

    var currentYearLines = lineRows.filter(function(r) {{
      if (!r.issue_date) return false;
      return new Date(r.issue_date + 'T00:00:00Z').getUTCFullYear() === thisYear;
    }});

    // Rank beers by total this year (within whatever's currently
    // filtered, in whichever metric is selected) to decide which get
    // their own stacked segment - the rest are grouped into "Other" so
    // the chart stays readable.
    var totalsByBeer = {{}};
    currentYearLines.forEach(function(r) {{
      var name = r.product_name || 'Unknown';
      totalsByBeer[name] = (totalsByBeer[name] || 0) + (r[metricField] || 0);
    }});
    var topBeers = Object.keys(totalsByBeer)
      .sort(function(a, b) {{ return totalsByBeer[b] - totalsByBeer[a]; }})
      .slice(0, beerTopN);

    function monthlySumForBeer(rows, year, beerName) {{
      var sums = new Array(12).fill(0);
      rows.forEach(function(r) {{
        if (!r.issue_date) return;
        var d = new Date(r.issue_date + 'T00:00:00Z');
        if (d.getUTCFullYear() !== year) return;
        var name = r.product_name || 'Unknown';
        if (beerName === null) {{
          if (topBeers.indexOf(name) !== -1) return;  // "Other" = anything not in the top N
        }} else if (name !== beerName) {{
          return;
        }}
        sums[d.getUTCMonth()] += (r[metricField] || 0);
      }});
      return sums;
    }}

    var traces = topBeers.map(function(beerName, i) {{
      return {{
        x: monthNames, y: monthlySumForBeer(lineRows, thisYear, beerName), name: beerName,
        type: 'bar', marker: {{color: findConfiguredProductColor(beerName) || beerColors[i % beerColors.length]}}
      }};
    }});

    var otherTotal = Object.keys(totalsByBeer).reduce(function(sum, name) {{
      return topBeers.indexOf(name) === -1 ? sum + totalsByBeer[name] : sum;
    }}, 0);
    if (otherTotal > 0) {{
      traces.push({{
        x: monthNames, y: monthlySumForBeer(lineRows, thisYear, null), name: 'Other',
        type: 'bar', marker: {{color: beerColors[beerColors.length - 1]}}
      }});
    }}

    var priorYears = Array.from(new Set(
      lineRows.map(function(r) {{
        if (!r.issue_date) return null;
        var y = new Date(r.issue_date + 'T00:00:00Z').getUTCFullYear();
        return (y && y !== thisYear) ? y : null;
      }}).filter(function(y) {{ return y !== null; }})
    )).sort(function(a, b) {{ return b - a; }});

    priorYears.forEach(function(year, i) {{
      var color = priorYearColors[i % priorYearColors.length];
      var sums = new Array(12).fill(0);
      lineRows.forEach(function(r) {{
        if (!r.issue_date) return;
        var d = new Date(r.issue_date + 'T00:00:00Z');
        if (d.getUTCFullYear() !== year) return;
        sums[d.getUTCMonth()] += (r[metricField] || 0);
      }});
      traces.push({{
        x: monthNames, y: sums, name: String(year),
        mode: 'lines+markers', type: 'scatter',
        line: {{color: color, dash: 'dash'}}, marker: {{color: color}}
      }});
    }});

    var beerYTitle = beerUnitMode === 'quantity' ? 'Units Sold' : 'Net Sales Value ($)';
    Plotly.react('chart-sales-by-beer', traces, {{
      barmode: 'stack', template: 'plotly_white',
      title: 'Sales by Month, by Product',
      yaxis: {{title: beerYTitle}}, xaxis: {{title: ''}}, legend: {{title: {{text: ''}}}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  var histUnitMode = 'value';

  function updateHistogramChart(rows) {{
    var totalsByValue = {{}};
    var totalsByUnits = {{}};
    rows.forEach(function(r) {{
      var name = r.product_name || 'Unknown';
      totalsByValue[name] = (totalsByValue[name] || 0) + (r.value || 0);
      totalsByUnits[name] = (totalsByUnits[name] || 0) + (r.quantity || 0);
    }});
    // A product has to clear BOTH thresholds - not just one - to stay
    // on the chart, regardless of which metric is currently displayed,
    // so switching the toggle doesn't change which products qualify,
    // only how their bars are measured.
    var qualifying = Object.keys(totalsByValue).filter(function(name) {{
      return totalsByValue[name] >= histogramMinSalesValue && totalsByUnits[name] >= histogramMinSalesUnits;
    }});
    var totals = histUnitMode === 'quantity' ? totalsByUnits : totalsByValue;
    var sorted = qualifying.sort(function(a, b) {{ return totals[b] - totals[a]; }});
    var colors = sorted.map(function(name) {{ return productColorMap[name] || '#9AA6B2'; }});
    var yTitle = histUnitMode === 'quantity' ? 'Units Sold' : 'Net Sales Value ($)';
    var yAxisConfig = histUnitMode === 'quantity'
      ? {{title: yTitle}}
      : {{title: yTitle, tickprefix: '$', tickformat: ',.2f'}};

    Plotly.react('chart-orders-histogram', [{{
      x: sorted, y: sorted.map(function(name) {{ return totals[name]; }}),
      type: 'bar', marker: {{color: colors}}
    }}], {{
      template: 'plotly_white', title: 'All Products Sold',
      height: 500, margin: {{b: 160}},
      yaxis: yAxisConfig, xaxis: {{title: '', tickangle: -45}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function updateTopCustomers(rows) {{
    var sums = {{}};
    rows.forEach(function(r) {{
      var key = r.customer_name || 'Unknown';
      sums[key] = (sums[key] || 0) + (r.total || 0);
    }});
    var sorted = Object.entries(sums).sort(function(a, b) {{ return b[1] - a[1]; }}).slice(0, 10).reverse();
    Plotly.react('chart-top-customers', [{{
      x: sorted.map(function(e) {{ return e[1]; }}), y: sorted.map(function(e) {{ return e[0]; }}),
      type: 'bar', orientation: 'h', marker: {{color: '#4CAF6B'}}
    }}], {{
      template: 'plotly_white', title: 'Top 10 customers by order value',
      xaxis: {{title: 'Order value ($)'}}, yaxis: {{title: ''}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function updateTable(rows) {{
    var sorted = rows.slice().sort(function(a, b) {{
      return (b.issue_date || '').localeCompare(a.issue_date || '');
    }}).slice(0, 25);
    document.getElementById('orders-table-body').innerHTML = sorted.map(function(r) {{
      return '<tr>' +
        '<td>' + escapeHtml(r.number) + '</td>' +
        '<td>' + escapeHtml(r.issue_date) + '</td>' +
        '<td>' + escapeHtml(r.customer_name) + '</td>' +
        '<td>' + escapeHtml(r.order_status_label) + '</td>' +
        '<td>' + escapeHtml(r.payment_status_label) + '</td>' +
        '<td>' + fmtMoney(r.total) + '</td>' +
        '<td>' + fmtMoney(r.amount_due) + '</td>' +
        '</tr>';
    }}).join('');
  }}

  function applyMonthFilters() {{
    updateSalesByMonthChart(filterOrdersForMonth({{
      customerTypes: monthCustomerTypeFilter.getSelected(),
      orderStatuses: monthOrderStatusFilter.getSelected()
    }}));
  }}

  function applyBeerFilters() {{
    updateSalesByBeerChart(filterLineData({{
      customerTypes: beerCustomerTypeFilter.getSelected(),
      orderStatuses: beerOrderStatusFilter.getSelected(),
      products: beerProductFilter.getSelected()
    }}));
  }}

  function applyHistogramFilters() {{
    updateHistogramChart(filterLineDataForHistogram({{
      customerTypes: histCustomerTypeFilter.getSelected(),
      orderStatuses: histOrderStatusFilter.getSelected(),
      products: histProductFilter.getSelected(),
      begin: document.getElementById('orders-histogram-begin').value,
      end: document.getElementById('orders-histogram-end').value
    }}));
  }}

  var monthCustomerTypeFilter = createSearchableFilter({{
    prefix: 'month-customer-type', allValues: allCustomerTypes, defaultValues: defaultCustomerTypesFiltered,
    presetsKey: 'abco_dashboard_shared_presets_customer_type_v1', onApply: function() {{ applyMonthFilters(); }}
  }});
  var monthOrderStatusFilter = createSearchableFilter({{
    prefix: 'month-order-status', allValues: allOrderStatuses, defaultValues: allOrderStatuses.slice(),
    presetsKey: 'abco_dashboard_shared_presets_order_status_v1', onApply: function() {{ applyMonthFilters(); }}
  }});
  var beerCustomerTypeFilter = createSearchableFilter({{
    prefix: 'beer-customer-type', allValues: allCustomerTypes, defaultValues: defaultCustomerTypesFiltered,
    presetsKey: 'abco_dashboard_shared_presets_customer_type_v1', onApply: function() {{ applyBeerFilters(); }}
  }});
  var beerOrderStatusFilter = createSearchableFilter({{
    prefix: 'beer-order-status', allValues: allOrderStatuses, defaultValues: allOrderStatuses.slice(),
    presetsKey: 'abco_dashboard_shared_presets_order_status_v1', onApply: function() {{ applyBeerFilters(); }}
  }});
  var beerProductFilter = createSearchableFilter({{
    prefix: 'beer-product', allValues: allProductNames, defaultValues: allProductNames.slice(),
    presetsKey: 'abco_dashboard_product_presets_v1', onApply: function() {{ applyBeerFilters(); }}
  }});
  var histCustomerTypeFilter = createSearchableFilter({{
    prefix: 'hist-customer-type', allValues: allCustomerTypes, defaultValues: defaultCustomerTypesFiltered,
    presetsKey: 'abco_dashboard_shared_presets_customer_type_v1', onApply: function() {{ applyHistogramFilters(); }}
  }});
  var histOrderStatusFilter = createSearchableFilter({{
    prefix: 'hist-order-status', allValues: allOrderStatuses, defaultValues: allOrderStatuses.slice(),
    presetsKey: 'abco_dashboard_shared_presets_order_status_v1', onApply: function() {{ applyHistogramFilters(); }}
  }});
  var histProductFilter = createSearchableFilter({{
    prefix: 'hist-product', allValues: allProductNames, defaultValues: allProductNames.slice(),
    presetsKey: 'abco_dashboard_product_presets_v1', onApply: function() {{ applyHistogramFilters(); }}
  }});

  document.getElementById('btn-reset-month-filters').addEventListener('click', function() {{
    monthCustomerTypeFilter.reset();
    monthOrderStatusFilter.reset();
    applyMonthFilters();
  }});

  document.getElementById('btn-reset-beer-filters').addEventListener('click', function() {{
    beerCustomerTypeFilter.reset();
    beerOrderStatusFilter.reset();
    beerProductFilter.reset();
    beerUnitMode = 'value';
    document.querySelectorAll('#beer-unit-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b.getAttribute('data-unit') === 'value');
    }});
    applyBeerFilters();
  }});

  document.getElementById('beer-unit-toggle').addEventListener('click', function(e) {{
    var btn = e.target.closest('button');
    if (!btn) return;
    beerUnitMode = btn.getAttribute('data-unit');
    document.querySelectorAll('#beer-unit-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b === btn);
    }});
    applyBeerFilters();
  }});

  document.getElementById('orders-histogram-begin').addEventListener('change', applyHistogramFilters);
  document.getElementById('orders-histogram-end').addEventListener('change', applyHistogramFilters);

  document.getElementById('orders-histogram-unit-toggle').addEventListener('click', function(e) {{
    var btn = e.target.closest('button');
    if (!btn) return;
    histUnitMode = btn.getAttribute('data-unit');
    document.querySelectorAll('#orders-histogram-unit-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b === btn);
    }});
    applyHistogramFilters();
  }});

  document.getElementById('btn-reset-orders-histogram-filters').addEventListener('click', function() {{
    histCustomerTypeFilter.reset();
    histOrderStatusFilter.reset();
    histProductFilter.reset();
    document.getElementById('orders-histogram-begin').value = '';
    document.getElementById('orders-histogram-end').value = '';
    histUnitMode = 'value';
    document.querySelectorAll('#orders-histogram-unit-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b.getAttribute('data-unit') === 'value');
    }});
    applyHistogramFilters();
  }});

  // KPIs, top customers, and the recent orders table are not scoped
  // to either chart's filters - they always reflect full history.
  updateKPIs(rawData);
  updateTopCustomers(rawData);
  updateTable(rawData);

  applyMonthFilters();
  applyBeerFilters();
  applyHistogramFilters();
}})();
</script>
"""


# ---------------------------------------------------------------------
# Production batches (DrinkBatch schema: batch_code, drink.name, status,
# datetime_started, total_volume.litre, abv, brew_type)
# ---------------------------------------------------------------------
