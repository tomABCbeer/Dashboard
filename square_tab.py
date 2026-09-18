"""Square tab: a report of what sold at Square (taproom/event pours,
farmers markets, etc.) over a chosen date range and location(s), for
manually reconciling into Breww as one consolidated transaction -
Breww's own Square integration maps every line item to a Breww
product individually and drops the WHOLE order if even one item isn't
mapped, and creates one Breww order per Square order (which can mean
hundreds in a single busy afternoon) - this is a simpler alternative:
one table of "what we sold," not an attempt to replicate that
integration."""
import json

import pandas as pd

from shared import json_safe, _safe_float, _parse_json_list


def build_catalog_category_map(catalog_df):
    """Resolves an order line item's catalog_object_id (an
    ITEM_VARIATION id) all the way to its category NAME, by walking
    the chain Square actually uses: variation -> parent item
    (item_variation_data.item_id) -> the item's category reference
    (item_data.reporting_category.id, falling back to the first of
    item_data.categories if that's not set - Square added both in the
    same API update, with reporting_category specifically meant for
    "reporting or displaying purposes," which is exactly this use
    case) -> category NAME (category_data.name). None of this is in
    the order data itself - it's a separate concern of Square's
    Catalog API, which is why /v2/catalog/list gets pulled at all.

    Returns a flat variation_id -> category_name map, so callers only
    ever need one lookup, never the three-hop chain. Every hop here
    can fail to resolve for ordinary reasons (an item removed from the
    catalog since, one with no category assigned, a name that just
    isn't in the cached catalog) - this returns whatever DOES resolve;
    the caller decides what a missing category should display as."""
    if catalog_df is None or catalog_df.empty:
        return {}

    category_name_by_id = {}
    item_to_category_id = {}
    variation_to_item_id = {}

    for _, row in catalog_df.iterrows():
        obj_type = row.get("type")
        obj_id = row.get("id")
        if not obj_id or (isinstance(obj_id, float) and pd.isna(obj_id)):
            continue

        if obj_type == "CATEGORY":
            name = row.get("category_data.name")
            if name and not (isinstance(name, float) and pd.isna(name)):
                category_name_by_id[obj_id] = name

        elif obj_type == "ITEM":
            category_id = row.get("item_data.reporting_category.id")
            if category_id is None or (isinstance(category_id, float) and pd.isna(category_id)):
                categories_list = _parse_json_list(row.get("item_data.categories"))
                if categories_list and isinstance(categories_list[0], dict):
                    category_id = categories_list[0].get("id")
            if category_id and not (isinstance(category_id, float) and pd.isna(category_id)):
                item_to_category_id[obj_id] = category_id

        elif obj_type == "ITEM_VARIATION":
            item_id = row.get("item_variation_data.item_id")
            if item_id and not (isinstance(item_id, float) and pd.isna(item_id)):
                variation_to_item_id[obj_id] = item_id

    variation_to_category_name = {}
    for variation_id, item_id in variation_to_item_id.items():
        category_id = item_to_category_id.get(item_id)
        category_name = category_name_by_id.get(category_id) if category_id else None
        if category_name:
            variation_to_category_name[variation_id] = category_name
    return variation_to_category_name


def prepare_square_line_item_records(orders_df, locations_df, catalog_category_map=None):
    """Explode each cached Square order's line_items into one record
    per item sold, joined with that order's location name. Quantity
    and money amounts come back from Square as strings/cents
    respectively - both are converted here (money from cents to
    dollars) so nothing downstream has to think about it again.
    Category comes from catalog_category_map (see
    build_catalog_category_map) via each line item's own
    catalog_object_id - "Uncategorized" for anything that doesn't
    resolve (no catalog cached, no category assigned, item since
    removed from the catalog, etc.)."""
    if orders_df is None or orders_df.empty:
        return []
    catalog_category_map = catalog_category_map or {}

    location_name_by_id = {}
    if locations_df is not None:
        for _, row in locations_df.iterrows():
            loc_id = row.get("id")
            if loc_id:
                location_name_by_id[loc_id] = row.get("name") or loc_id

    records = []
    for _, row in orders_df.iterrows():
        raw_items = row.get("line_items")
        if raw_items is None or (isinstance(raw_items, float) and pd.isna(raw_items)):
            continue
        if isinstance(raw_items, str):
            try:
                items = json.loads(raw_items)
            except (ValueError, TypeError):
                continue
        elif isinstance(raw_items, list):
            items = raw_items
        else:
            continue

        location_id = row.get("location_id")
        created_at = row.get("created_at")
        created_date = None if pd.isna(created_at) else str(created_at)[:10]

        for item in items:
            if not isinstance(item, dict):
                continue
            quantity = _safe_float(item.get("quantity"), default=0.0)
            if quantity <= 0:
                continue
            money = item.get("gross_sales_money") or {}
            revenue_cents = _safe_float(money.get("amount"), default=0.0)
            category = catalog_category_map.get(item.get("catalog_object_id")) or "Uncategorized"

            records.append({
                "order_id": json_safe(row.get("id")),
                "location_id": json_safe(location_id),
                "location_name": json_safe(location_name_by_id.get(location_id, location_id)),
                "date": created_date,
                "item_name": json_safe(item.get("name") or "Unknown item"),
                "variation_name": json_safe(item.get("variation_name")),
                "category": json_safe(category),
                "quantity": quantity,
                "revenue": revenue_cents / 100.0,
            })
    return records


def build_square_section(orders_df, locations_df, catalog_df=None):
    if orders_df is None:
        return (
            "<h2>Square</h2>"
            "<p class='missing'>No cached Square order data yet - if you haven't "
            "set up Square yet, set SQUARE_ACCESS_TOKEN in your .env file (see the "
            "README for how to generate a token), then run fetch_data.py. If you "
            "have set it up already, check that fetch_data.py ran successfully and "
            "actually had the token available when it ran.</p>"
        )

    catalog_category_map = build_catalog_category_map(catalog_df)
    line_items = prepare_square_line_item_records(orders_df, locations_df, catalog_category_map)
    if not line_items:
        return (
            "<h2>Square</h2>"
            "<p class='missing'>Square order data is cached, but no line items "
            "came out of it - double check the cached data in "
            "data/square_orders.csv looks right.</p>"
        )

    line_items_json = json.dumps(line_items, allow_nan=False)

    locations_list = []
    if locations_df is not None:
        for _, row in locations_df.iterrows():
            locations_list.append({
                "id": json_safe(row.get("id")),
                "name": json_safe(row.get("name") or row.get("id")),
                "status": json_safe(row.get("status")),
            })
    locations_json = json.dumps(locations_list, allow_nan=False)

    return f"""
<h2>Square</h2>
<p class="section-note">What sold at Square over a chosen date range and location(s) - not a replacement for Breww's own Square integration, just a simpler report to read from when manually keying in one consolidated Breww transaction (e.g. "sold to Internal Event") for sales that integration would otherwise mis-handle or split across hundreds of individual orders. Only COMPLETED orders are counted here.</p>

<div class="customer-report-controls" id="square-controls">
  <div class="filter-group">
    <label>Date range</label>
    <div style="display:flex; gap:8px; align-items:center;">
      <input type="date" id="square-date-begin">
      <span>to</span>
      <input type="date" id="square-date-end">
    </div>
  </div>
  <div class="filter-group">
    <label>Locations</label>
    <div class="customer-dropdown" id="square-location-dropdown">
      <button type="button" class="customer-dropdown-toggle" id="square-location-toggle">
        <span id="square-location-summary">All locations</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="customer-dropdown-panel" id="square-location-panel" hidden>
        <input type="text" id="square-location-search" class="customer-search-input"
               placeholder="Search locations&hellip;" autocomplete="off">
        <div id="square-location-list"></div>
        <p id="square-location-empty" class="product-search-empty" hidden>No locations match your search.</p>
        <div class="filter-actions" style="padding:8px;">
          <button type="button" id="square-location-select-all">Select all</button>
          <button type="button" id="square-location-select-none">Select none</button>
        </div>
      </div>
    </div>
  </div>
  <div class="filter-group">
    <label>Categories</label>
    <div class="customer-dropdown" id="square-category-dropdown">
      <button type="button" class="customer-dropdown-toggle" id="square-category-toggle">
        <span id="square-category-summary">All categories</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="customer-dropdown-panel" id="square-category-panel" hidden>
        <input type="text" id="square-category-search" class="customer-search-input"
               placeholder="Search categories&hellip;" autocomplete="off">
        <div id="square-category-list"></div>
        <p id="square-category-empty" class="product-search-empty" hidden>No categories match your search.</p>
        <div class="filter-actions" style="padding:8px;">
          <button type="button" id="square-category-select-all">Select all</button>
          <button type="button" id="square-category-select-none">Select none</button>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="square-kpi-row"></div>

<h4>Sales by Item</h4>
<p class="section-note">Quantity and revenue per item over the selected range and location(s), sorted by quantity - use this as your source list for a manual Breww transaction. Click any column header to sort.</p>
<div class="table-wrap">
  <table class="data-table" id="square-sales-table"></table>
</div>

<script id="square-line-item-data" type="application/json">{line_items_json}</script>
<script id="square-locations-data" type="application/json">{locations_json}</script>
<script>
(function() {{
  var lineItems = JSON.parse(document.getElementById('square-line-item-data').textContent);
  var locations = JSON.parse(document.getElementById('square-locations-data').textContent);

  var allDates = lineItems.map(function(r) {{ return r.date; }}).filter(function(v) {{ return v; }}).sort();
  var latestDate = allDates.length ? allDates[allDates.length - 1] : new Date().toISOString().slice(0, 10);
  var latestDateObj = new Date(latestDate + 'T00:00:00Z');
  var defaultBegin = new Date(latestDateObj.getTime() - 6 * 86400000).toISOString().slice(0, 10);

  var beginInput = document.getElementById('square-date-begin');
  var endInput = document.getElementById('square-date-end');
  beginInput.value = defaultBegin;
  endInput.value = latestDate;

  // --- Location multi-select dropdown (checkboxes, not radio - several can be picked) ---
  var selectedLocationIds = {{}};
  locations.forEach(function(loc) {{ selectedLocationIds[loc.id] = true; }});  // all selected by default

  var locDropdown = document.getElementById('square-location-dropdown');
  var locPanel = document.getElementById('square-location-panel');
  var locToggle = document.getElementById('square-location-toggle');
  var locSearchInput = document.getElementById('square-location-search');
  var locListDiv = document.getElementById('square-location-list');
  var locSummary = document.getElementById('square-location-summary');
  var locEmptyMsg = document.getElementById('square-location-empty');

  function updateLocationSummary() {{
    var selectedCount = Object.keys(selectedLocationIds).filter(function(id) {{ return selectedLocationIds[id]; }}).length;
    if (selectedCount === locations.length) {{
      locSummary.textContent = 'All locations';
    }} else if (selectedCount === 0) {{
      locSummary.textContent = 'No locations selected';
    }} else {{
      locSummary.textContent = selectedCount + ' location' + (selectedCount === 1 ? '' : 's') + ' selected';
    }}
  }}

  function buildLocationList() {{
    locListDiv.innerHTML = locations.map(function(loc) {{
      var safe = escapeHtml(loc.name);
      var inactiveTag = loc.status && loc.status !== 'ACTIVE' ? ' <span class="customer-type-tag">' + escapeHtml(loc.status) + '</span>' : '';
      var checked = selectedLocationIds[loc.id] ? 'checked' : '';
      return '<label class="filter-row" data-search="' + safe.toLowerCase() + '">' +
        '<input type="checkbox" data-loc-id="' + escapeHtml(loc.id) + '" ' + checked + '> ' + safe + inactiveTag +
        '</label>';
    }}).join('') || '<span style="font-size:12px;color:#a39a8c;">No locations found</span>';
  }}

  function filterLocationRows(query) {{
    var q = query.trim().toLowerCase();
    var rows = locListDiv.querySelectorAll('.filter-row');
    var anyVisible = false;
    rows.forEach(function(row) {{
      var matches = !q || row.getAttribute('data-search').indexOf(q) !== -1;
      row.style.display = matches ? '' : 'none';
      if (matches) anyVisible = true;
    }});
    if (locEmptyMsg) locEmptyMsg.hidden = anyVisible || rows.length === 0;
  }}

  function openLocDropdown() {{
    locPanel.hidden = false;
    locSearchInput.value = '';
    filterLocationRows('');
    locSearchInput.focus();
  }}
  function closeLocDropdown() {{ locPanel.hidden = true; }}

  locToggle.addEventListener('click', function() {{
    if (locPanel.hidden) {{ openLocDropdown(); }} else {{ closeLocDropdown(); }}
  }});
  locSearchInput.addEventListener('input', function() {{ filterLocationRows(locSearchInput.value); }});
  document.addEventListener('click', function(e) {{
    if (!locDropdown.contains(e.target)) closeLocDropdown();
  }});
  locDropdown.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ closeLocDropdown(); locToggle.focus(); }}
  }});

  locListDiv.addEventListener('change', function(e) {{
    var checkbox = e.target.closest('[data-loc-id]');
    if (!checkbox) return;
    selectedLocationIds[checkbox.getAttribute('data-loc-id')] = checkbox.checked;
    updateLocationSummary();
    applySquareReport();
  }});

  document.getElementById('square-location-select-all').addEventListener('click', function() {{
    locations.forEach(function(loc) {{ selectedLocationIds[loc.id] = true; }});
    buildLocationList();
    updateLocationSummary();
    applySquareReport();
  }});
  document.getElementById('square-location-select-none').addEventListener('click', function() {{
    locations.forEach(function(loc) {{ selectedLocationIds[loc.id] = false; }});
    buildLocationList();
    updateLocationSummary();
    applySquareReport();
  }});

  // --- Category multi-select dropdown (same pattern as locations above) ---
  var allCategories = Array.from(new Set(lineItems.map(function(r) {{ return r.category; }})
    .filter(function(v) {{ return v; }}))).sort();
  var selectedCategories = {{}};
  allCategories.forEach(function(cat) {{ selectedCategories[cat] = true; }});  // all selected by default

  var catDropdown = document.getElementById('square-category-dropdown');
  var catPanel = document.getElementById('square-category-panel');
  var catToggle = document.getElementById('square-category-toggle');
  var catSearchInput = document.getElementById('square-category-search');
  var catListDiv = document.getElementById('square-category-list');
  var catSummary = document.getElementById('square-category-summary');
  var catEmptyMsg = document.getElementById('square-category-empty');

  function updateCategorySummary() {{
    var selectedCount = Object.keys(selectedCategories).filter(function(c) {{ return selectedCategories[c]; }}).length;
    if (selectedCount === allCategories.length) {{
      catSummary.textContent = 'All categories';
    }} else if (selectedCount === 0) {{
      catSummary.textContent = 'No categories selected';
    }} else {{
      catSummary.textContent = selectedCount + ' categor' + (selectedCount === 1 ? 'y' : 'ies') + ' selected';
    }}
  }}

  function buildCategoryList() {{
    catListDiv.innerHTML = allCategories.map(function(cat) {{
      var safe = escapeHtml(cat);
      var checked = selectedCategories[cat] ? 'checked' : '';
      return '<label class="filter-row" data-search="' + safe.toLowerCase() + '">' +
        '<input type="checkbox" data-cat-id="' + safe + '" ' + checked + '> ' + safe +
        '</label>';
    }}).join('') || '<span style="font-size:12px;color:#a39a8c;">No categories found</span>';
  }}

  function filterCategoryRows(query) {{
    var q = query.trim().toLowerCase();
    var rows = catListDiv.querySelectorAll('.filter-row');
    var anyVisible = false;
    rows.forEach(function(row) {{
      var matches = !q || row.getAttribute('data-search').indexOf(q) !== -1;
      row.style.display = matches ? '' : 'none';
      if (matches) anyVisible = true;
    }});
    if (catEmptyMsg) catEmptyMsg.hidden = anyVisible || rows.length === 0;
  }}

  function openCatDropdown() {{
    catPanel.hidden = false;
    catSearchInput.value = '';
    filterCategoryRows('');
    catSearchInput.focus();
  }}
  function closeCatDropdown() {{ catPanel.hidden = true; }}

  catToggle.addEventListener('click', function() {{
    if (catPanel.hidden) {{ openCatDropdown(); }} else {{ closeCatDropdown(); }}
  }});
  catSearchInput.addEventListener('input', function() {{ filterCategoryRows(catSearchInput.value); }});
  document.addEventListener('click', function(e) {{
    if (!catDropdown.contains(e.target)) closeCatDropdown();
  }});
  catDropdown.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ closeCatDropdown(); catToggle.focus(); }}
  }});

  catListDiv.addEventListener('change', function(e) {{
    var checkbox = e.target.closest('[data-cat-id]');
    if (!checkbox) return;
    selectedCategories[checkbox.getAttribute('data-cat-id')] = checkbox.checked;
    updateCategorySummary();
    applySquareReport();
  }});

  document.getElementById('square-category-select-all').addEventListener('click', function() {{
    allCategories.forEach(function(cat) {{ selectedCategories[cat] = true; }});
    buildCategoryList();
    updateCategorySummary();
    applySquareReport();
  }});
  document.getElementById('square-category-select-none').addEventListener('click', function() {{
    allCategories.forEach(function(cat) {{ selectedCategories[cat] = false; }});
    buildCategoryList();
    updateCategorySummary();
    applySquareReport();
  }});

  beginInput.addEventListener('change', applySquareReport);
  endInput.addEventListener('change', applySquareReport);

  // --- Sales by Item table ---
  var SALES_COLUMNS = [
    {{key: 'item_name', label: 'Item', type: 'string'}},
    {{key: 'variation_name', label: 'Variation', type: 'string'}},
    {{key: 'category', label: 'Category', type: 'string'}},
    {{key: 'quantity', label: 'Quantity', type: 'number'}},
    {{key: 'revenue', label: 'Revenue', type: 'number'}}
  ];
  var salesSortColumn = 'quantity';
  var salesSortAscending = false;

  function fmtMoney(n) {{ return '$' + (n || 0).toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}}); }}
  function fmtQty(n) {{ return (Math.round((n || 0) * 100) / 100).toLocaleString(); }}

  function applySquareReport() {{
    var beginVal = beginInput.value;
    var endVal = endInput.value;

    var filtered = lineItems.filter(function(r) {{
      if (!selectedLocationIds[r.location_id]) return false;
      if (!selectedCategories[r.category]) return false;
      if (beginVal && (!r.date || r.date < beginVal)) return false;
      if (endVal && (!r.date || r.date > endVal)) return false;
      return true;
    }});

    var byItem = {{}};
    filtered.forEach(function(r) {{
      var key = r.item_name + '|||' + (r.variation_name || '') + '|||' + r.category;
      if (!byItem[key]) {{
        byItem[key] = {{item_name: r.item_name, variation_name: r.variation_name || '', category: r.category, quantity: 0, revenue: 0}};
      }}
      byItem[key].quantity += r.quantity;
      byItem[key].revenue += r.revenue;
    }});
    var rows = Object.keys(byItem).map(function(k) {{ return byItem[k]; }});

    var totalQty = rows.reduce(function(s, r) {{ return s + r.quantity; }}, 0);
    var totalRevenue = rows.reduce(function(s, r) {{ return s + r.revenue; }}, 0);
    document.getElementById('square-kpi-row').innerHTML =
      '<div class="kpi-row"><div class="kpi"><div class="kpi-value">' + fmtQty(totalQty) + '</div><div class="kpi-label">Total items sold</div></div>' +
      '<div class="kpi"><div class="kpi-value">' + fmtMoney(totalRevenue) + '</div><div class="kpi-label">Total revenue</div></div></div>';

    var sortColDef = SALES_COLUMNS.find(function(c) {{ return c.key === salesSortColumn; }}) || SALES_COLUMNS[3];
    var sortedRows = sortGenericRows(rows, salesSortColumn, salesSortAscending, sortColDef.type);

    var bodyRows = sortedRows.map(function(r) {{
      return '<tr>' +
        '<td>' + escapeHtml(r.item_name) + '</td>' +
        '<td>' + escapeHtml(r.variation_name || '\\u2014') + '</td>' +
        '<td>' + escapeHtml(r.category) + '</td>' +
        '<td>' + fmtQty(r.quantity) + '</td>' +
        '<td>' + fmtMoney(r.revenue) + '</td>' +
        '</tr>';
    }}).join('');

    var totalRow = '<tr style="font-weight:600; border-top:2px solid #e4dcc9;">' +
      '<td>Total</td><td></td><td></td><td>' + fmtQty(totalQty) + '</td><td>' + fmtMoney(totalRevenue) + '</td></tr>';

    document.getElementById('square-sales-table').innerHTML =
      buildSortableHeaderRow(SALES_COLUMNS, salesSortColumn, salesSortAscending) +
      '<tbody>' + bodyRows + '</tbody><tfoot>' + totalRow + '</tfoot>';
  }}

  document.getElementById('square-sales-table').addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (salesSortColumn === key) {{
      salesSortAscending = !salesSortAscending;
    }} else {{
      salesSortColumn = key;
      var colDef = SALES_COLUMNS.find(function(c) {{ return c.key === key; }});
      salesSortAscending = colDef.type !== 'number';
    }}
    applySquareReport();
  }});

  buildLocationList();
  updateLocationSummary();
  buildCategoryList();
  updateCategorySummary();
  applySquareReport();
}})();
</script>
"""
