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


def build_product_stock_pivot_html(records):
    """Turn the flat per-product-per-location records into a pivot
    table: one row per product, one column per location holding that
    location's quantity, plus a Total column - much easier to scan
    across locations than a long flat list."""
    df = pd.DataFrame(records)
    df["location_name"] = df["location_name"].fillna("Unspecified")
    pivot = df.pivot_table(index="product_name", columns="location_name",
                            values="quantity", aggfunc="sum", fill_value=0)
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False).reset_index()
    pivot = pivot.rename(columns={"product_name": "Product"})
    pivot.columns.name = None  # pivot_table leaves this set to "location_name",
    # which otherwise renders as a stray extra header row/empty column in the HTML table

    numeric_cols = [c for c in pivot.columns if c != "Product"]
    pivot[numeric_cols] = pivot[numeric_cols].round(1)
    return table_html(pivot, max_rows=50)


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

    table = build_product_stock_pivot_html(records)

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
<p class="section-note">Every product's current quantity, broken out by location, in one table.</p>
{table}

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
