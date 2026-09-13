"""Inventory tab: Products (finished, packaged goods) and Stock Items
(raw ingredients/packaging), each with their own charts and a table."""
import json

import pandas as pd

import config
from shared import (
    json_safe, has_cols, filter_dropdown_html, kpi_row, table_html,
    BEER_TOP_N, BEER_COLORS, _safe_float,
)

# ---------------------------------------------------------------------
# Stock received (StockReceived schema: stock_item.name, current_quantity,
# price_per_quantity, location.name, batch_code, expiry_date)
# This endpoint has no received-date field, so it's shown as a current
# on-hand snapshot rather than a trend.
# ---------------------------------------------------------------------
def prepare_stock_records(df):
    """Build JSON-serializable stock-lot records for the Inventory
    tab's interactive charts. Includes both quantity and value
    (quantity x price) so the charts can group/sum either dimension."""
    d = df.copy()
    d["current_quantity"] = pd.to_numeric(d.get("current_quantity"), errors="coerce").fillna(0)
    d["price_per_quantity"] = pd.to_numeric(d.get("price_per_quantity"), errors="coerce").fillna(0)
    d["value"] = d["current_quantity"] * d["price_per_quantity"]
    d["item_name"] = d.get("stock_item.name")
    d["location_name"] = d.get("location.name")

    out_cols = ["item_name", "location_name", "current_quantity", "value", "batch_code", "expiry_date"]
    for col in out_cols:
        if col not in d.columns:
            d[col] = None

    raw_records = d[out_cols].to_dict(orient="records")
    return [{k: json_safe(v) for k, v in rec.items()} for rec in raw_records]


def prepare_product_stock_records(products_df):
    """Build JSON-serializable per-product-per-location stock records
    for the Inventory tab's "Products" section, from the /products/
    endpoint - these are finished, packaged, sellable products (kegs,
    cans, casks), not the raw stock items covered separately by
    prepare_stock_records().

    quantity_in_stock_in_format_by_site is a "conditionally included"
    list field (requested via include_fields in config.py) - each
    entry is one product's stock at one site, which fetch_data.py's
    flatten() will have JSON-stringified to survive the CSV round
    trip, so it needs parsing back out here. Only products with actual
    stock (quantity > 0) are included; only physical, sellable product
    types are considered (see config.PACKAGED_PRODUCT_TYPES) - stock
    items and services are excluded since they aren't "products" and
    stock items are already covered by prepare_stock_records()."""
    if products_df is None:
        return []

    d = products_df.copy()
    d["type"] = pd.to_numeric(d.get("type"), errors="coerce")
    d = d[d["type"].isin(config.PACKAGED_PRODUCT_TYPES)]

    def parse_by_site(raw):
        if raw is None:
            return []
        if isinstance(raw, float) and pd.isna(raw):
            return []
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                return []
        elif isinstance(raw, list):
            parsed = raw
        else:
            return []
        return parsed if isinstance(parsed, list) else []

    records = []
    for _, row in d.iterrows():
        name = row.get("name")
        price = _safe_float(row.get("price"))
        by_site = parse_by_site(row.get("quantity_in_stock_in_format_by_site"))
        if by_site:
            for entry in by_site:
                if not isinstance(entry, dict):
                    continue
                qty = _safe_float(entry.get("quantity"))
                if qty <= 0:
                    continue
                records.append({
                    "product_name": json_safe(name),
                    "location_name": json_safe(entry.get("site_name")),
                    "quantity": qty,
                    "value": qty * price,
                })
        else:
            qty = _safe_float(row.get("quantity_in_stock_in_format"))
            if qty > 0:
                records.append({
                    "product_name": json_safe(name),
                    "location_name": None,
                    "quantity": qty,
                    "value": qty * price,
                })
    return records


def build_stock_items_subsection(df):
    """The original Inventory content: raw stock items (ingredients,
    packaging) from /stock-received/. Returns '' if there's nothing to
    show, so the caller can render just a note instead of a mostly-empty
    sub-section."""
    if df is None:
        return "<h3>Stock Items</h3><p class='missing'>No cached data yet - run fetch_data.py first.</p>"

    records = prepare_stock_records(df)
    records_json = json.dumps(records, allow_nan=False)
    item_colors_json = json.dumps(BEER_COLORS)

    location_item_html = filter_dropdown_html("inventory-location-item", "Item", "items")
    top_items_html = filter_dropdown_html("inventory-top-items", "Item", "items")
    location_pie_html = filter_dropdown_html("inventory-location-pie", "Item", "items")

    d = df.copy()
    if "current_quantity" in d.columns:
        d["current_quantity"] = pd.to_numeric(d["current_quantity"], errors="coerce")
    if "price_per_quantity" in d.columns:
        d["price_per_quantity"] = pd.to_numeric(d["price_per_quantity"], errors="coerce")
    if has_cols(d, ["current_quantity", "price_per_quantity"]):
        d["stock_value"] = d["current_quantity"] * d["price_per_quantity"]

    kpis = [(f"{len(d):,}", "Stock lots")]
    if "stock_value" in d.columns:
        kpis.append((f"${d['stock_value'].sum():,.0f}", "Total stock value"))
    kpi_html = kpi_row(kpis)

    display_cols = [c for c in ["stock_item.name", "batch_code", "current_quantity",
                                 "location.name", "expiry_date", "price_per_quantity"] if c in d.columns]
    table = table_html(d, cols=display_cols or None)

    return f"""
<h3>Stock Items</h3>
<p class="section-note">Raw ingredients and packaging received into stock (hops, malt, caps, cans, etc.) - not finished, sellable products. See "Products" below for those.</p>

<h4>Current Stock Items by Location</h4>
<p class="section-note">On-hand quantity per location, stacked by item.</p>
<div class="chart-scoped-filter" id="inventory-location-filters">
{location_item_html}
  <div class="filter-actions">
    <button id="btn-reset-inventory-location-filters">Reset</button>
  </div>
</div>
<div id="chart-inventory-by-location" class="chart-div"></div>

{kpi_html}

<h4>On-Hand Quantity by Item</h4>
<p class="section-note">Your top 10 stock items by quantity currently on hand.</p>
<div class="chart-scoped-filter" id="inventory-top-items-filters">
{top_items_html}
  <div class="filter-actions">
    <button id="btn-reset-inventory-top-items-filters">Reset</button>
  </div>
</div>
<div id="chart-inventory-top-items" class="chart-div"></div>

<h4>Stock Quantity by Location</h4>
<p class="section-note">How your on-hand stock quantity is distributed across locations.</p>
<div class="chart-scoped-filter" id="inventory-location-pie-filters">
{location_pie_html}
  <div class="filter-actions">
    <button id="btn-reset-inventory-location-pie-filters">Reset</button>
  </div>
</div>
<div id="chart-inventory-by-location-pie" class="chart-div"></div>

<h4>Stock Lots</h4>
<p class="section-note">Every individual stock lot currently on hand.</p>
{table}

<script id="stock-data" type="application/json">{records_json}</script>
<script>
(function() {{
  var rawStock = JSON.parse(document.getElementById('stock-data').textContent);
  var itemColors = {item_colors_json};
  var topN = {BEER_TOP_N};

  var allItems = Array.from(new Set(rawStock.map(function(r) {{ return r.item_name; }})
    .filter(function(v) {{ return v; }}))).sort();

  function filterStock(items) {{
    return rawStock.filter(function(r) {{ return items.indexOf(r.item_name) !== -1; }});
  }}

  function updateInventoryByLocation(rows) {{
    var byLocation = {{}};
    rows.forEach(function(r) {{
      var loc = r.location_name || 'Unknown';
      var item = r.item_name || 'Unknown';
      byLocation[loc] = byLocation[loc] || {{}};
      byLocation[loc][item] = (byLocation[loc][item] || 0) + (r.current_quantity || 0);
    }});
    var locations = Object.keys(byLocation).sort();

    var totalsByItem = {{}};
    rows.forEach(function(r) {{
      var item = r.item_name || 'Unknown';
      totalsByItem[item] = (totalsByItem[item] || 0) + (r.current_quantity || 0);
    }});
    var topItems = Object.keys(totalsByItem)
      .sort(function(a, b) {{ return totalsByItem[b] - totalsByItem[a]; }})
      .slice(0, topN);

    var traces = topItems.map(function(item, i) {{
      return {{
        x: locations,
        y: locations.map(function(loc) {{ return (byLocation[loc] && byLocation[loc][item]) || 0; }}),
        name: item, type: 'bar', marker: {{color: itemColors[i % itemColors.length]}}
      }};
    }});

    var otherByLoc = locations.map(function(loc) {{
      var total = 0;
      Object.keys(byLocation[loc] || {{}}).forEach(function(item) {{
        if (topItems.indexOf(item) === -1) total += byLocation[loc][item];
      }});
      return total;
    }});
    if (otherByLoc.some(function(v) {{ return v > 0; }})) {{
      traces.push({{
        x: locations, y: otherByLoc, name: 'Other',
        type: 'bar', marker: {{color: itemColors[itemColors.length - 1]}}
      }});
    }}

    Plotly.react('chart-inventory-by-location', traces, {{
      barmode: 'stack', template: 'plotly_white', title: 'Current Stock Items by Location',
      height: 500, margin: {{r: 30, t: 60, b: 130, l: 70}},
      legend: {{orientation: 'h', x: 0, xanchor: 'left', y: -0.22, yanchor: 'top', title: {{text: ''}}}},
      yaxis: {{title: 'Quantity'}}, xaxis: {{title: ''}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function updateTopItems(rows) {{
    var sums = {{}};
    rows.forEach(function(r) {{
      var item = r.item_name || 'Unknown';
      sums[item] = (sums[item] || 0) + (r.current_quantity || 0);
    }});
    var sorted = Object.entries(sums).sort(function(a, b) {{ return b[1] - a[1]; }}).slice(0, 10).reverse();
    Plotly.react('chart-inventory-top-items', [{{
      x: sorted.map(function(e) {{ return e[1]; }}), y: sorted.map(function(e) {{ return e[0]; }}),
      type: 'bar', orientation: 'h', marker: {{color: '#4CAF6B'}}
    }}], {{
      template: 'plotly_white', title: 'On-hand quantity by item (top 10)',
      xaxis: {{title: "Quantity (kg or litres, per item's tracking type)"}}, yaxis: {{title: ''}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function updateLocationPie(rows) {{
    var sums = {{}};
    rows.forEach(function(r) {{
      var loc = r.location_name || 'Unknown';
      sums[loc] = (sums[loc] || 0) + (r.current_quantity || 0);
    }});
    Plotly.react('chart-inventory-by-location-pie', [{{
      labels: Object.keys(sums), values: Object.values(sums), type: 'pie'
    }}], {{
      template: 'plotly_white', title: 'Stock quantity by location'
    }}, {{displayModeBar: false, responsive: true}});
  }}

  var locationItemFilter = createSearchableFilter({{
    prefix: 'inventory-location-item', allValues: allItems, defaultValues: allItems.slice(),
    presetsKey: 'abco_dashboard_shared_presets_inventory_item_v1',
    onApply: function() {{ applyLocationChart(); }}
  }});
  var topItemsFilter = createSearchableFilter({{
    prefix: 'inventory-top-items', allValues: allItems, defaultValues: allItems.slice(),
    presetsKey: 'abco_dashboard_shared_presets_inventory_item_v1',
    onApply: function() {{ applyTopItemsChart(); }}
  }});
  var locationPieFilter = createSearchableFilter({{
    prefix: 'inventory-location-pie', allValues: allItems, defaultValues: allItems.slice(),
    presetsKey: 'abco_dashboard_shared_presets_inventory_item_v1',
    onApply: function() {{ applyLocationPieChart(); }}
  }});

  function applyLocationChart() {{
    updateInventoryByLocation(filterStock(locationItemFilter.getSelected()));
  }}
  function applyTopItemsChart() {{
    updateTopItems(filterStock(topItemsFilter.getSelected()));
  }}
  function applyLocationPieChart() {{
    updateLocationPie(filterStock(locationPieFilter.getSelected()));
  }}

  document.getElementById('btn-reset-inventory-location-filters').addEventListener('click', function() {{
    locationItemFilter.reset();
    applyLocationChart();
  }});
  document.getElementById('btn-reset-inventory-top-items-filters').addEventListener('click', function() {{
    topItemsFilter.reset();
    applyTopItemsChart();
  }});
  document.getElementById('btn-reset-inventory-location-pie-filters').addEventListener('click', function() {{
    locationPieFilter.reset();
    applyLocationPieChart();
  }});

  applyLocationChart();
  applyTopItemsChart();
  applyLocationPieChart();
}})();
</script>
"""


def build_products_subsection(products_df):
    """Finished, packaged, sellable products (kegs, cans, casks) from
    /products/ - distinct from the raw stock items above. Mirrors that
    section's structure (3 independently-filterable charts, KPIs, a
    table) using the same shared filter component."""
    records = prepare_product_stock_records(products_df)
    if not records:
        return (
            "<h3>Products</h3>"
            "<p class='missing'>No cached product stock data yet - run fetch_data.py first "
            "(needs the products endpoint, added after your last full fetch - it'll pull "
            "automatically next run).</p>"
            '<script id="product-stock-data" type="application/json">[]</script>'
        )

    records_json = json.dumps(records, allow_nan=False)
    item_colors_json = json.dumps(BEER_COLORS)

    location_item_html = filter_dropdown_html("inventory-product-location", "Product", "products")
    top_items_html = filter_dropdown_html("inventory-product-top", "Product", "products")
    location_pie_html = filter_dropdown_html("inventory-product-location-pie", "Product", "products")

    lot_count = len(records)
    total_value = sum(r.get("value") or 0 for r in records)
    kpi_html = kpi_row([(f"{lot_count:,}", "Product/location lines"),
                         (f"${total_value:,.0f}", "Total product stock value")])

    return f"""
<h3>Products</h3>
<p class="section-note">Finished, packaged, sellable products (kegs, cans, casks) - not raw ingredients or packaging materials. See "Stock Items" above for those.</p>

<h4>Current Inventory of Products by Location</h4>
<p class="section-note">On-hand product quantity per location, stacked by product.</p>
<div class="chart-scoped-filter" id="inventory-product-location-filters">
{location_item_html}
  <div class="filter-actions">
    <button id="btn-reset-inventory-product-location-filters">Reset</button>
  </div>
</div>
<div id="chart-inventory-product-by-location" class="chart-div"></div>

{kpi_html}

<h4>On-Hand Quantity by Product</h4>
<p class="section-note">Your top 10 products by quantity currently on hand.</p>
<div class="chart-scoped-filter" id="inventory-product-top-filters">
{top_items_html}
  <div class="filter-actions">
    <button id="btn-reset-inventory-product-top-filters">Reset</button>
  </div>
</div>
<div id="chart-inventory-product-top" class="chart-div"></div>

<h4>Product Stock Quantity by Location</h4>
<p class="section-note">How your on-hand product quantity is distributed across locations.</p>
<div class="chart-scoped-filter" id="inventory-product-location-pie-filters">
{location_pie_html}
  <div class="filter-actions">
    <button id="btn-reset-inventory-product-location-pie-filters">Reset</button>
  </div>
</div>
<div id="chart-inventory-product-by-location-pie" class="chart-div"></div>

<h4>Product Stock by Location</h4>
<p class="section-note">Every product's current quantity, broken out by location - pick a beer to see all its products together, or narrow to one specific product. Click any column header to sort.</p>
<div class="chart-scoped-filter" id="inventory-product-table-filters">
  <div class="filter-group">
    <label>Beer or product</label>
    <div class="customer-dropdown" id="inventory-product-table-dropdown">
      <button type="button" class="customer-dropdown-toggle" id="inventory-product-table-toggle">
        <span id="inventory-product-table-summary">All Products</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="customer-dropdown-panel" id="inventory-product-table-panel" hidden>
        <input type="text" id="inventory-product-table-search" class="customer-search-input"
               placeholder="Search beers and products&hellip;" autocomplete="off">
        <div id="inventory-product-table-list"></div>
        <p id="inventory-product-table-empty" class="product-search-empty" hidden>No beers or products match your search.</p>
      </div>
    </div>
  </div>
</div>
<div class="table-wrap">
  <table class="data-table" id="inventory-product-stock-table"></table>
</div>

<script id="product-stock-data" type="application/json">{records_json}</script>
<script>
(function() {{
  var rawProducts = JSON.parse(document.getElementById('product-stock-data').textContent);
  var itemColors = {item_colors_json};
  var topN = {BEER_TOP_N};

  var allProducts = Array.from(new Set(rawProducts.map(function(r) {{ return r.product_name; }})
    .filter(function(v) {{ return v; }}))).sort();

  function filterProducts(products) {{
    return rawProducts.filter(function(r) {{ return products.indexOf(r.product_name) !== -1; }});
  }}

  function updateProductsByLocation(rows) {{
    var byLocation = {{}};
    rows.forEach(function(r) {{
      var loc = r.location_name || 'Unknown';
      var item = r.product_name || 'Unknown';
      byLocation[loc] = byLocation[loc] || {{}};
      byLocation[loc][item] = (byLocation[loc][item] || 0) + (r.quantity || 0);
    }});
    var locations = Object.keys(byLocation).sort();

    var totalsByProduct = {{}};
    rows.forEach(function(r) {{
      var item = r.product_name || 'Unknown';
      totalsByProduct[item] = (totalsByProduct[item] || 0) + (r.quantity || 0);
    }});
    var topItems = Object.keys(totalsByProduct)
      .sort(function(a, b) {{ return totalsByProduct[b] - totalsByProduct[a]; }})
      .slice(0, topN);

    var traces = topItems.map(function(item, i) {{
      return {{
        x: locations,
        y: locations.map(function(loc) {{ return (byLocation[loc] && byLocation[loc][item]) || 0; }}),
        name: item, type: 'bar', marker: {{color: findConfiguredProductColor(item) || itemColors[i % itemColors.length]}}
      }};
    }});

    var otherByLoc = locations.map(function(loc) {{
      var total = 0;
      Object.keys(byLocation[loc] || {{}}).forEach(function(item) {{
        if (topItems.indexOf(item) === -1) total += byLocation[loc][item];
      }});
      return total;
    }});
    if (otherByLoc.some(function(v) {{ return v > 0; }})) {{
      traces.push({{
        x: locations, y: otherByLoc, name: 'Other',
        type: 'bar', marker: {{color: itemColors[itemColors.length - 1]}}
      }});
    }}

    Plotly.react('chart-inventory-product-by-location', traces, {{
      barmode: 'stack', template: 'plotly_white', title: 'Current Inventory of Products by Location',
      height: 500, margin: {{r: 30, t: 60, b: 130, l: 70}},
      legend: {{orientation: 'h', x: 0, xanchor: 'left', y: -0.22, yanchor: 'top', title: {{text: ''}}}},
      yaxis: {{title: 'Quantity'}}, xaxis: {{title: ''}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function updateTopProducts(rows) {{
    var sums = {{}};
    rows.forEach(function(r) {{
      var item = r.product_name || 'Unknown';
      sums[item] = (sums[item] || 0) + (r.quantity || 0);
    }});
    var sorted = Object.entries(sums).sort(function(a, b) {{ return b[1] - a[1]; }}).slice(0, 10).reverse();
    Plotly.react('chart-inventory-product-top', [{{
      x: sorted.map(function(e) {{ return e[1]; }}), y: sorted.map(function(e) {{ return e[0]; }}),
      type: 'bar', orientation: 'h', marker: {{color: '#4CAF6B'}}
    }}], {{
      template: 'plotly_white', title: 'On-hand quantity by product (top 10)',
      xaxis: {{title: 'Quantity'}}, yaxis: {{title: ''}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function updateProductLocationPie(rows) {{
    var sums = {{}};
    rows.forEach(function(r) {{
      var loc = r.location_name || 'Unknown';
      sums[loc] = (sums[loc] || 0) + (r.quantity || 0);
    }});
    Plotly.react('chart-inventory-product-by-location-pie', [{{
      labels: Object.keys(sums), values: Object.values(sums), type: 'pie'
    }}], {{
      template: 'plotly_white', title: 'Product stock quantity by location'
    }}, {{displayModeBar: false, responsive: true}});
  }}

  var productLocationFilter = createSearchableFilter({{
    prefix: 'inventory-product-location', allValues: allProducts, defaultValues: allProducts.slice(),
    presetsKey: 'abco_dashboard_shared_presets_inventory_product_v1',
    onApply: function() {{ applyProductLocationChart(); }}
  }});
  var productTopFilter = createSearchableFilter({{
    prefix: 'inventory-product-top', allValues: allProducts, defaultValues: allProducts.slice(),
    presetsKey: 'abco_dashboard_shared_presets_inventory_product_v1',
    onApply: function() {{ applyProductTopChart(); }}
  }});
  var productLocationPieFilter = createSearchableFilter({{
    prefix: 'inventory-product-location-pie', allValues: allProducts, defaultValues: allProducts.slice(),
    presetsKey: 'abco_dashboard_shared_presets_inventory_product_v1',
    onApply: function() {{ applyProductLocationPieChart(); }}
  }});

  function applyProductLocationChart() {{
    updateProductsByLocation(filterProducts(productLocationFilter.getSelected()));
  }}
  function applyProductTopChart() {{
    updateTopProducts(filterProducts(productTopFilter.getSelected()));
  }}
  function applyProductLocationPieChart() {{
    updateProductLocationPie(filterProducts(productLocationPieFilter.getSelected()));
  }}

  document.getElementById('btn-reset-inventory-product-location-filters').addEventListener('click', function() {{
    productLocationFilter.reset();
    applyProductLocationChart();
  }});
  document.getElementById('btn-reset-inventory-product-top-filters').addEventListener('click', function() {{
    productTopFilter.reset();
    applyProductTopChart();
  }});
  document.getElementById('btn-reset-inventory-product-location-pie-filters').addEventListener('click', function() {{
    productLocationPieFilter.reset();
    applyProductLocationPieChart();
  }});

  applyProductLocationChart();
  applyProductTopChart();
  applyProductLocationPieChart();

  // ===================== Product Stock by Location table =====================
  // Uses the shared beer-or-product grouping (buildBeerOrProductPickerEntries,
  // in shared.py) - the same picker pattern as the Forecast tab, but
  // with a synthetic "All Products" entry prepended and selected by
  // default, since this table's natural starting point is showing
  // everything rather than requiring an explicit pick first.
  var stockTablePickerEntries = buildBeerOrProductPickerEntries(allProducts, true);
  var stockTableSelectedEntry = stockTablePickerEntries[0];

  var stockTableDropdown = document.getElementById('inventory-product-table-dropdown');
  var stockTablePanel = document.getElementById('inventory-product-table-panel');
  var stockTableToggle = document.getElementById('inventory-product-table-toggle');
  var stockTableSearchInput = document.getElementById('inventory-product-table-search');
  var stockTableListDiv = document.getElementById('inventory-product-table-list');
  var stockTableSummary = document.getElementById('inventory-product-table-summary');
  var stockTableEmptyMsg = document.getElementById('inventory-product-table-empty');

  function buildStockTablePickerList() {{
    stockTableListDiv.innerHTML = stockTablePickerEntries.map(function(entry, i) {{
      var safe = escapeHtml(entry.label);
      return '<label class="customer-row" data-search="' + safe.toLowerCase() + '" data-index="' + i + '">' + safe + '</label>';
    }}).join('') || '<span style="font-size:12px;color:#a39a8c;">No beers or products found</span>';
  }}

  function filterStockTableRows(query) {{
    var q = query.trim().toLowerCase();
    var rows = stockTableListDiv.querySelectorAll('.customer-row');
    var anyVisible = false;
    rows.forEach(function(row) {{
      var matches = !q || row.getAttribute('data-search').indexOf(q) !== -1;
      row.style.display = matches ? '' : 'none';
      if (matches) anyVisible = true;
    }});
    if (stockTableEmptyMsg) stockTableEmptyMsg.hidden = anyVisible || rows.length === 0;
  }}

  function openStockTableDropdown() {{
    stockTablePanel.hidden = false;
    stockTableSearchInput.value = '';
    filterStockTableRows('');
    stockTableSearchInput.focus();
  }}
  function closeStockTableDropdown() {{ stockTablePanel.hidden = true; }}

  stockTableToggle.addEventListener('click', function() {{
    if (stockTablePanel.hidden) {{ openStockTableDropdown(); }} else {{ closeStockTableDropdown(); }}
  }});
  stockTableSearchInput.addEventListener('input', function() {{ filterStockTableRows(stockTableSearchInput.value); }});
  document.addEventListener('click', function(e) {{
    if (!stockTableDropdown.contains(e.target)) closeStockTableDropdown();
  }});
  stockTableDropdown.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ closeStockTableDropdown(); stockTableToggle.focus(); }}
  }});

  stockTableListDiv.addEventListener('click', function(e) {{
    var row = e.target.closest('.customer-row');
    if (!row) return;
    var idx = parseInt(row.getAttribute('data-index'), 10);
    stockTableSelectedEntry = stockTablePickerEntries[idx];
    stockTableSummary.textContent = stockTableSelectedEntry.label;
    closeStockTableDropdown();
    applyStockTable();
  }});

  function fmtQty(n) {{ return (Math.round((n || 0) * 10) / 10).toLocaleString(); }}

  var stockTableSortColumn = 'Product';
  var stockTableSortAscending = true;

  function applyStockTable() {{
    var filteredRows = filterProducts(stockTableSelectedEntry.products);

    var byProduct = {{}};
    var locationsSet = {{}};
    filteredRows.forEach(function(r) {{
      var product = r.product_name || 'Unknown';
      var loc = r.location_name || 'Unspecified';
      locationsSet[loc] = true;
      byProduct[product] = byProduct[product] || {{}};
      byProduct[product][loc] = (byProduct[product][loc] || 0) + (r.quantity || 0);
    }});
    var locations = Object.keys(locationsSet).sort();

    var columns = [{{key: 'Product', label: 'Product', type: 'string'}}];
    locations.forEach(function(loc) {{ columns.push({{key: loc, label: loc, type: 'number'}}); }});
    columns.push({{key: 'Total', label: 'Total', type: 'number'}});

    var pivotRows = Object.keys(byProduct).map(function(product) {{
      var row = {{Product: product}};
      var total = 0;
      locations.forEach(function(loc) {{
        var qty = byProduct[product][loc] || 0;
        row[loc] = qty;
        total += qty;
      }});
      row['Total'] = total;
      return row;
    }});

    var sortColDef = columns.find(function(c) {{ return c.key === stockTableSortColumn; }}) || columns[0];
    var sortedRows = sortGenericRows(pivotRows, stockTableSortColumn, stockTableSortAscending, sortColDef.type);

    var bodyRows = sortedRows.map(function(row) {{
      return '<tr>' + columns.map(function(col) {{
        if (col.key === 'Product') return '<td>' + escapeHtml(row[col.key]) + '</td>';
        return '<td>' + fmtQty(row[col.key]) + '</td>';
      }}).join('') + '</tr>';
    }}).join('');

    document.getElementById('inventory-product-stock-table').innerHTML =
      buildSortableHeaderRow(columns, stockTableSortColumn, stockTableSortAscending) + '<tbody>' + bodyRows + '</tbody>';
  }}

  document.getElementById('inventory-product-stock-table').addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (stockTableSortColumn === key) {{
      stockTableSortAscending = !stockTableSortAscending;
    }} else {{
      stockTableSortColumn = key;
      stockTableSortAscending = (key === 'Product');
    }}
    applyStockTable();
  }});

  buildStockTablePickerList();
  applyStockTable();
}})();
</script>
"""


def build_stock_section(df, products_df=None):
    if df is None and products_df is None:
        return "<h2>Inventory</h2><p class='missing'>No cached data yet - run fetch_data.py first.</p>"

    return (
        "<h2>Inventory</h2>\n"
        + build_products_subsection(products_df)
        + "\n"
        + build_stock_items_subsection(df)
    )


# ---------------------------------------------------------------------
# Customer Report tab: pick a customer, see their sales-by-month
# (stacked by product, with an "average customer of the same type"
# comparison line) and their product mix as a pie, over a chosen date
# range, in either $ or units.
#
# This reuses the SAME order-line data the Orders tab already embeds
# (the <script id="order-line-data"> tag written by
# build_orders_section) rather than embedding a second copy - it reads
# that tag by id at runtime. That JSON already carries customer_id,
# customer_name, product_name, value, and quantity per line.
# ---------------------------------------------------------------------
