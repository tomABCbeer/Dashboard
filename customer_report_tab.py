"""Customer Report tab: pick a customer and see their sales-by-month
and product mix, an Invoice Aging table, and a Dormant Customers table
(moved here from Growth & Efficiency, since both are customer-specific
concerns). Reads the Orders tab's already-embedded order data by DOM
element id at runtime, rather than embedding a second copy."""
import json

import config
from shared import BEER_TOP_N, BEER_COLORS, json_safe, _parse_json_list, filter_dropdown_html


def prepare_customer_records(customers_df):
    """Build JSON-serializable per-customer contact records, from
    /customers-suppliers/, for the Invoice Aging and Dormant Customers
    tables. Picks one contact per customer using
    config.CONTACT_TAG_MARKETING then config.CONTACT_TAG_INVOICES (in
    that priority order - Breww has no structured "primary contact"
    flag, only free-text tags), falling back to the business's own
    primary_email/primary_phone_number with no contact name (there's
    no person to name in that case) if neither tag matches, or the
    account has no contacts at all.

    This endpoint has no Hotel/Shop/Club-style customer type field, so
    that's deliberately not resolved here - the Dormant Customers
    table's JS resolves it from order data instead (where available),
    since a customer with zero orders ever can't be typed at all
    either way."""
    if customers_df is None:
        return []

    d = customers_df.copy()

    records = []
    for _, row in d.iterrows():
        contacts = _parse_json_list(row.get("contacts"))
        business_email = row.get("primary_email")
        business_phone = row.get("primary_phone_number")

        chosen = None
        for tag_wanted in (config.CONTACT_TAG_MARKETING, config.CONTACT_TAG_INVOICES):
            for c in contacts:
                if not isinstance(c, dict):
                    continue
                tags = c.get("tags")
                if isinstance(tags, list) and tag_wanted in tags:
                    chosen = c
                    break
            if chosen is not None:
                break

        if chosen is not None:
            first = (chosen.get("first_name") or "").strip()
            last = (chosen.get("last_name") or "").strip()
            contact_name = (first + " " + last).strip() or None
            contact_email = chosen.get("primary_email") or business_email
            contact_phone = chosen.get("primary_phone_number") or business_phone
        else:
            contact_name = "[No contact names available - business contact displayed]"
            contact_email = business_email
            contact_phone = business_phone

        records.append({
            "customer_id": json_safe(row.get("id")),
            "customer_name": json_safe(row.get("name")),
            "contact_name": json_safe(contact_name),
            "contact_email": json_safe(contact_email),
            "contact_phone": json_safe(contact_phone),
        })
    return records


def build_customer_report_section(customers_df):
    beer_colors_json = json.dumps(BEER_COLORS)
    customer_records = prepare_customer_records(customers_df)
    customer_records_json = json.dumps(customer_records, allow_nan=False)
    default_types_json = json.dumps(config.DEFAULT_CUSTOMER_TYPES)
    dormant_type_html = filter_dropdown_html("growth-dormant-customer-type", "Customer type", "customer types")

    return f"""
<h2>Customer Report</h2>

<div class="customer-report-controls" id="customer-report-controls">
  <div class="filter-group">
    <label>Customer</label>
    <div class="customer-dropdown" id="customer-dropdown">
      <button type="button" class="customer-dropdown-toggle" id="customer-dropdown-toggle">
        <span id="customer-dropdown-summary">Select a customer&hellip;</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="customer-dropdown-panel" id="customer-dropdown-panel" hidden>
        <input type="text" id="customer-search-input" class="customer-search-input"
               placeholder="Search customers&hellip;" autocomplete="off">
        <div id="customer-list"></div>
        <p id="customer-search-empty" class="product-search-empty" hidden>No customers match your search.</p>
      </div>
    </div>
  </div>
  <div class="filter-group">
    <label>Date range</label>
    <div style="display:flex; gap:8px; align-items:center;">
      <input type="date" id="customer-report-begin">
      <span>to</span>
      <input type="date" id="customer-report-end">
    </div>
  </div>
  <div class="filter-group">
    <label>Metric</label>
    <div class="unit-toggle" id="unit-toggle">
      <button type="button" class="active" data-unit="value">Sales $</button>
      <button type="button" data-unit="quantity"># of units</button>
    </div>
  </div>
</div>

<p id="customer-report-placeholder" class="customer-report-placeholder">Select a customer above to generate their report.</p>

<div id="customer-report-content" hidden>
  <div class="customer-report-charts">
    <div>
      <h4>Sales by Month</h4>
      <p class="section-note">This customer's sales by month, stacked by product, with a dashed line showing the average for other customers of the same type.</p>
      <div id="customer-sales-by-month-chart" class="chart-div"></div>
    </div>
    <div>
      <h4>Product Mix</h4>
      <p class="section-note">This customer's product mix over the same date range as the chart above.</p>
      <div id="customer-product-pie-chart" class="chart-div"></div>
    </div>
  </div>
</div>

<h3>Invoice Aging</h3>
<p class="section-note">Customers with an unpaid invoice more than the configured number of days past its due date - an invoice that isn't due yet never counts, no matter how old. Sorted most-overdue-first by default; click any column header to resort.</p>
<div class="chart-scoped-filter" id="invoice-aging-filters">
  <div class="filter-group">
    <label>Show invoices more than (days) past due</label>
    <input type="number" id="invoice-aging-window" min="0" value="{config.INVOICE_AGING_DEFAULT_DAYS}" style="width:80px;">
  </div>
  <div class="filter-actions">
    <button id="btn-reset-invoice-aging-filters">Reset</button>
  </div>
</div>
<div class="table-wrap">
  <table class="data-table" id="invoice-aging-table"></table>
</div>

<h3>Dormant Customers</h3>
<p class="section-note">Customers whose last invoiced order is older than the configured window, or who've never ordered at all - sorted oldest-first by default; click any column header to resort.</p>
<div class="chart-scoped-filter" id="growth-dormant-filters">
{dormant_type_html}
  <div class="filter-group">
    <label>Dormancy window (days)</label>
    <input type="number" id="growth-dormant-window" min="1" value="{config.DORMANT_CUSTOMER_WINDOW_DEFAULT_DAYS}" style="width:80px;">
  </div>
  <div class="filter-group">
    <label>Population</label>
    <div class="unit-toggle" id="growth-dormant-population-toggle">
      <button type="button" class="active" data-population="has-ordered">Has ordered before</button>
      <button type="button" data-population="never-ordered">Never ordered</button>
    </div>
  </div>
  <div class="filter-actions">
    <button id="btn-reset-growth-dormant-filters">Reset</button>
  </div>
</div>
<p id="growth-dormant-type-note" class="section-note" style="display:none;">Customer Type filter doesn't apply to "Never ordered" - Breww only tracks customer type on individual orders, so a customer with no orders can't be classified.</p>
<div class="table-wrap">
  <table class="data-table" id="growth-dormant-table"></table>
</div>

<script id="customer-contact-data" type="application/json">{customer_records_json}</script>
<script>
(function() {{
  var rawData = JSON.parse(document.getElementById('orders-data').textContent);
  var lineDataEl = document.getElementById('order-line-data');
  var lineData = [];
  try {{ lineData = lineDataEl ? JSON.parse(lineDataEl.textContent) : []; }} catch (e) {{ lineData = []; }}
  var rawLineData = lineData;

  var contactDataEl = document.getElementById('customer-contact-data');
  var contactData = [];
  try {{ contactData = contactDataEl ? JSON.parse(contactDataEl.textContent) : []; }} catch (e) {{ contactData = []; }}
  var contactByCustomerId = {{}};
  contactData.forEach(function(c) {{ contactByCustomerId[c.customer_id] = c; }});

  var beerColors = {beer_colors_json};
  var beerTopN = {BEER_TOP_N};
  var avgLineColor = '#B0B0B0';

  var allCustomerTypes = Array.from(new Set(rawData.map(function(r) {{ return r.customer_type_name; }})
    .filter(function(v) {{ return v; }}))).sort();
  var defaultCustomerTypes = {default_types_json};
  var defaultCustomerTypesFiltered = defaultCustomerTypes.filter(function(t) {{ return allCustomerTypes.indexOf(t) !== -1; }});

  var customersById = {{}};
  lineData.forEach(function(r) {{
    if (r.customer_id == null) return;
    if (!customersById[r.customer_id]) {{
      customersById[r.customer_id] = {{ id: r.customer_id, name: r.customer_name || 'Unknown', type: r.customer_type_name || null }};
    }}
  }});
  var allCustomers = Object.keys(customersById).map(function(k) {{ return customersById[k]; }})
    .sort(function(a, b) {{ return a.name.localeCompare(b.name); }});

  var selectedCustomerId = null;
  var unitMode = 'value';

  if (allCustomers.length === 0) {{
    document.getElementById('customer-report-placeholder').textContent =
      'No customer order data cached yet - run fetch_data.py to pull orders and order lines, then rebuild.';
  }}

  // --- Customer dropdown (searchable, single-select) ---------------------
  var custDropdown = document.getElementById('customer-dropdown');
  var custPanel = document.getElementById('customer-dropdown-panel');
  var custToggle = document.getElementById('customer-dropdown-toggle');
  var custSearchInput = document.getElementById('customer-search-input');
  var custListDiv = document.getElementById('customer-list');
  var custSummary = document.getElementById('customer-dropdown-summary');
  var custEmptyMsg = document.getElementById('customer-search-empty');

  function buildCustomerList() {{
    custListDiv.innerHTML = allCustomers.map(function(c) {{
      var safeName = escapeHtml(c.name);
      var safeType = c.type ? escapeHtml(c.type) : '';
      return '<label class="customer-row" data-search="' + safeName.toLowerCase() + '" data-id="' + escapeHtml(String(c.id)) + '">' +
        safeName + (safeType ? '<span class="customer-type-tag">' + safeType + '</span>' : '') + '</label>';
    }}).join('') || '<span style="font-size:12px;color:#a39a8c;">No customers found</span>';
  }}

  function filterCustomerRows(query) {{
    var q = query.trim().toLowerCase();
    var rows = custListDiv.querySelectorAll('.customer-row');
    var anyVisible = false;
    rows.forEach(function(row) {{
      var matches = !q || row.getAttribute('data-search').indexOf(q) !== -1;
      row.style.display = matches ? '' : 'none';
      if (matches) anyVisible = true;
    }});
    custEmptyMsg.hidden = anyVisible || rows.length === 0;
  }}

  function openCustDropdown() {{
    custPanel.hidden = false;
    custSearchInput.value = '';
    filterCustomerRows('');
    custSearchInput.focus();
  }}
  function closeCustDropdown() {{ custPanel.hidden = true; }}

  custToggle.addEventListener('click', function() {{
    if (custPanel.hidden) {{ openCustDropdown(); }} else {{ closeCustDropdown(); }}
  }});
  custSearchInput.addEventListener('input', function() {{ filterCustomerRows(custSearchInput.value); }});
  document.addEventListener('click', function(e) {{
    if (!custDropdown.contains(e.target)) closeCustDropdown();
  }});
  custDropdown.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ closeCustDropdown(); custToggle.focus(); }}
  }});

  custListDiv.addEventListener('click', function(e) {{
    var row = e.target.closest('.customer-row');
    if (!row) return;
    var clickedId = row.getAttribute('data-id');
    var cust = allCustomers.find(function(c) {{ return String(c.id) === clickedId; }});
    if (!cust) return;
    selectedCustomerId = cust.id;
    custSummary.textContent = cust.name;
    closeCustDropdown();
    setDefaultDateRangeForCustomer(cust.id);
    renderReport();
  }});

  // --- Date range -----------------------------------------------------------
  var beginInput = document.getElementById('customer-report-begin');
  var endInput = document.getElementById('customer-report-end');
  beginInput.addEventListener('change', renderReport);
  endInput.addEventListener('change', renderReport);

  function setDefaultDateRangeForCustomer(customerId) {{
    // A sensible starting point is that customer's own full order
    // history - the user can narrow further from there.
    var dates = lineData.filter(function(r) {{ return r.customer_id === customerId && r.issue_date; }})
      .map(function(r) {{ return r.issue_date; }}).sort();
    if (dates.length) {{
      beginInput.value = dates[0];
      endInput.value = dates[dates.length - 1];
    }}
  }}

  // --- Unit toggle ------------------------------------------------------------
  var unitButtons = document.querySelectorAll('#unit-toggle button');
  unitButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      unitMode = btn.getAttribute('data-unit');
      unitButtons.forEach(function(b) {{ b.classList.toggle('active', b === btn); }});
      renderReport();
    }});
  }});

  // --- Report rendering ---------------------------------------------------------
  function metricOf(r) {{ return unitMode === 'quantity' ? (r.quantity || 0) : (r.value || 0); }}
  function monthKey(dateStr) {{ return dateStr ? dateStr.slice(0, 7) : null; }}

  var MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function monthLabel(key) {{
    var parts = key.split('-');
    var y = parts[0], m = parseInt(parts[1], 10);
    return MONTH_ABBR[m - 1] + ' ' + y;
  }}
  function buildMonthRange(startKey, endKey) {{
    var result = [];
    if (!startKey || !endKey) return result;
    var y = parseInt(startKey.slice(0, 4), 10), m = parseInt(startKey.slice(5, 7), 10);
    var endY = parseInt(endKey.slice(0, 4), 10), endM = parseInt(endKey.slice(5, 7), 10);
    while (y < endY || (y === endY && m <= endM)) {{
      result.push(y + '-' + (m < 10 ? '0' : '') + m);
      m++;
      if (m > 12) {{ m = 1; y++; }}
    }}
    return result;
  }}

  function emptyChartMessage(divId, title) {{
    Plotly.react(divId, [], {{
      template: 'plotly_white', title: title, height: 500,
      xaxis: {{visible: false}}, yaxis: {{visible: false}},
      annotations: [{{text: 'No orders in this date range', showarrow: false, x: 0.5, y: 0.5,
                      xref: 'paper', yref: 'paper', font: {{color: '#a39a8c', size: 13}}}}]
    }}, {{displayModeBar: false, responsive: true}});
  }}

  function renderReport() {{
    var placeholder = document.getElementById('customer-report-placeholder');
    var content = document.getElementById('customer-report-content');

    if (!selectedCustomerId) {{
      placeholder.hidden = false;
      content.hidden = true;
      return;
    }}
    placeholder.hidden = true;
    content.hidden = false;

    var cust = customersById[selectedCustomerId];
    var beginVal = beginInput.value;
    var endVal = endInput.value;

    var custLines = lineData.filter(function(r) {{
      if (r.customer_id !== selectedCustomerId) return false;
      if (!r.issue_date) return false;
      if (beginVal && r.issue_date < beginVal) return false;
      if (endVal && r.issue_date > endVal) return false;
      return true;
    }});

    if (custLines.length === 0 || !beginVal || !endVal) {{
      emptyChartMessage('customer-sales-by-month-chart', cust.name + ' - Sales by Month');
      emptyChartMessage('customer-product-pie-chart', cust.name + ' - Product mix');
      return;
    }}

    var months = buildMonthRange(monthKey(beginVal), monthKey(endVal));
    var labels = months.map(monthLabel);

    var totalsByProduct = {{}};
    custLines.forEach(function(r) {{
      var name = r.product_name || 'Unknown';
      totalsByProduct[name] = (totalsByProduct[name] || 0) + metricOf(r);
    }});
    var topProducts = Object.keys(totalsByProduct)
      .sort(function(a, b) {{ return totalsByProduct[b] - totalsByProduct[a]; }})
      .slice(0, beerTopN);
    var otherTotal = Object.keys(totalsByProduct).reduce(function(s, n) {{
      return topProducts.indexOf(n) === -1 ? s + totalsByProduct[n] : s;
    }}, 0);

    function monthlySumForProduct(rows, productName) {{
      var map = {{}};
      months.forEach(function(mk) {{ map[mk] = 0; }});
      rows.forEach(function(r) {{
        var mk = monthKey(r.issue_date);
        if (!(mk in map)) return;
        var name = r.product_name || 'Unknown';
        if (productName === null) {{
          if (topProducts.indexOf(name) !== -1) return;
        }} else if (name !== productName) {{
          return;
        }}
        map[mk] += metricOf(r);
      }});
      return months.map(function(mk) {{ return map[mk]; }});
    }}

    // Computed once, shared between the bar chart below and the pie
    // chart further down, so the same beer gets the same color in
    // both places on this customer's page - not just matching the
    // histogram on the Orders tab.
    var topProductColors = topProducts.map(function(p, i) {{
      return findConfiguredProductColor(p) || beerColors[i % beerColors.length];
    }});

    var traces = topProducts.map(function(p, i) {{
      return {{
        x: labels, y: monthlySumForProduct(custLines, p), name: p,
        type: 'bar', marker: {{color: topProductColors[i]}}
      }};
    }});
    if (otherTotal > 0) {{
      traces.push({{
        x: labels, y: monthlySumForProduct(custLines, null), name: 'Other',
        type: 'bar', marker: {{color: beerColors[beerColors.length - 1]}}
      }});
    }}

    // Comparison line: average monthly sales among OTHER customers of
    // the same customer type, over the same date range. The
    // denominator is the count of distinct customers of that type who
    // had at least one order in this range (fixed across all months),
    // not a month-by-month headcount - so the line reflects typical
    // seasonal pattern per customer, rather than just tracking how
    // many customers of that type happened to order in a given month.
    if (cust.type) {{
      var typeLines = lineData.filter(function(r) {{
        return r.customer_type_name === cust.type && r.issue_date &&
          r.issue_date >= beginVal && r.issue_date <= endVal;
      }});
      var distinctTypeCustomers = new Set(typeLines.map(function(r) {{ return r.customer_id; }})).size || 1;
      var typeMonthlyTotals = {{}};
      months.forEach(function(mk) {{ typeMonthlyTotals[mk] = 0; }});
      typeLines.forEach(function(r) {{
        var mk = monthKey(r.issue_date);
        if (mk in typeMonthlyTotals) typeMonthlyTotals[mk] += metricOf(r);
      }});
      var avgLine = months.map(function(mk) {{ return typeMonthlyTotals[mk] / distinctTypeCustomers; }});
      traces.push({{
        x: labels, y: avgLine, name: 'Avg. ' + cust.type + ' customer',
        type: 'scatter', mode: 'lines+markers',
        line: {{color: avgLineColor, dash: 'dash'}}, marker: {{color: avgLineColor}}
      }});
    }}

    var yTitle = unitMode === 'quantity' ? 'Units Sold' : 'Net Sales Value ($)';
    Plotly.react('customer-sales-by-month-chart', traces, {{
      barmode: 'stack', template: 'plotly_white', title: cust.name + ' - Sales by Month',
      height: 500,
      // A vertical legend pinned to the side still needs guaranteed
      // horizontal room, which a narrow container doesn't always have -
      // and how many legend entries there are (products + "Other" +
      // the average line) varies by customer, so that risk isn't
      // predictable. A horizontal legend below the plot sidesteps this
      // entirely: it just wraps across the full chart width instead of
      // competing with the plot for side space, so the chart looks the
      // same size no matter how many products someone bought.
      margin: {{r: 30, t: 60, b: 130, l: 70}},
      legend: {{orientation: 'h', x: 0, xanchor: 'left', y: -0.22, yanchor: 'top', title: {{text: ''}}}},
      yaxis: {{title: yTitle}}, xaxis: {{title: ''}}
    }}, {{displayModeBar: false, responsive: true}});

    var pieLabels = topProducts.slice();
    var pieValues = topProducts.map(function(p) {{ return totalsByProduct[p]; }});
    var pieColors = topProductColors.slice();
    if (otherTotal > 0) {{
      pieLabels.push('Other');
      pieValues.push(otherTotal);
      pieColors.push(beerColors[beerColors.length - 1]);
    }}
    var unitLabel = unitMode === 'quantity' ? 'units' : '$';
    Plotly.react('customer-product-pie-chart', [{{
      labels: pieLabels, values: pieValues, type: 'pie', marker: {{colors: pieColors}}
    }}], {{
      template: 'plotly_white', title: cust.name + ' - Product mix (' + unitLabel + ')',
      height: 500,
      margin: {{r: 30, t: 60, b: 130, l: 20}},
      legend: {{orientation: 'h', x: 0, xanchor: 'left', y: -0.15, yanchor: 'top', title: {{text: ''}}}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  buildCustomerList();

  // ===================== Invoice Aging table =====================
  var INVOICE_AGING_COLUMNS = [
    {{key: 'customer_name', label: 'Customer', type: 'string'}},
    {{key: 'invoice_number', label: 'Invoice Number', type: 'string'}},
    {{key: 'due_date', label: 'Due Date', type: 'string'}},
    {{key: 'contact_name', label: 'Contact Name', type: 'string'}},
    {{key: 'contact_phone', label: 'Phone', type: 'string'}},
    {{key: 'contact_email', label: 'Email', type: 'string'}}
  ];

  function invoiceAgingDefaultSort() {{
    return {{column: 'due_date', ascending: true}};  // earliest due date = most overdue, first
  }}

  var invoiceAgingSortInit = invoiceAgingDefaultSort();
  var invoiceAgingSortColumn = invoiceAgingSortInit.column;
  var invoiceAgingSortAscending = invoiceAgingSortInit.ascending;

  function sortGenericRows(rows, column, ascending, type) {{
    return rows.slice().sort(function(a, b) {{
      if (type === 'number') {{
        var an = a[column] || 0, bn = b[column] || 0;
        return ascending ? an - bn : bn - an;
      }}
      var as = (a[column] || '').toString().toLowerCase();
      var bs = (b[column] || '').toString().toLowerCase();
      if (as < bs) return ascending ? -1 : 1;
      if (as > bs) return ascending ? 1 : -1;
      return 0;
    }});
  }}

  function buildSortableHeaderRow(columns, sortColumn, sortAscending) {{
    var cells = columns.map(function(col) {{
      var indicator = '';
      if (sortColumn === col.key) {{
        indicator = sortAscending ? ' \\u25b2' : ' \\u25bc';
      }}
      return '<th><button type="button" class="sort-header-btn" data-sort-key="' + col.key + '">' +
        escapeHtml(col.label) + indicator + '</button></th>';
    }}).join('');
    return '<thead><tr>' + cells + '</tr></thead>';
  }}

  function applyInvoiceAging() {{
    var windowInput = document.getElementById('invoice-aging-window');
    var windowDays = parseInt(windowInput.value, 10);
    if (isNaN(windowDays) || windowDays < 0) windowDays = {config.INVOICE_AGING_DEFAULT_DAYS};
    var todayKey = new Date().toISOString().slice(0, 10);
    var todayDate = new Date(todayKey + 'T00:00:00Z');

    var rows = [];
    rawData.forEach(function(r) {{
      if (r.order_status_label !== 'Invoiced') return;
      if (!(r.amount_due > 0)) return;
      if (!r.due_date) return;
      var dueDate = new Date(r.due_date + 'T00:00:00Z');
      var daysPastDue = Math.floor((todayDate - dueDate) / 86400000);
      if (daysPastDue < windowDays) return;  // not overdue by at least X days (includes not-yet-due, which is negative)

      var contact = contactByCustomerId[r.customer_id];
      rows.push({{
        customer_name: r.customer_name,
        invoice_number: r.number,
        due_date: r.due_date,
        contact_name: contact ? contact.contact_name : '',
        contact_phone: contact ? contact.contact_phone : '',
        contact_email: contact ? contact.contact_email : ''
      }});
    }});

    var sortColDef = INVOICE_AGING_COLUMNS.find(function(c) {{ return c.key === invoiceAgingSortColumn; }}) || INVOICE_AGING_COLUMNS[2];
    rows = sortGenericRows(rows, invoiceAgingSortColumn, invoiceAgingSortAscending, sortColDef.type);

    var bodyRows = rows.map(function(r) {{
      return '<tr>' +
        '<td>' + escapeHtml(r.customer_name) + '</td>' +
        '<td>' + escapeHtml(r.invoice_number) + '</td>' +
        '<td>' + escapeHtml(r.due_date) + '</td>' +
        '<td>' + escapeHtml(r.contact_name || '') + '</td>' +
        '<td>' + escapeHtml(r.contact_phone || '') + '</td>' +
        '<td>' + escapeHtml(r.contact_email || '') + '</td>' +
        '</tr>';
    }}).join('');
    document.getElementById('invoice-aging-table').innerHTML =
      buildSortableHeaderRow(INVOICE_AGING_COLUMNS, invoiceAgingSortColumn, invoiceAgingSortAscending) + '<tbody>' + bodyRows + '</tbody>';
  }}

  document.getElementById('invoice-aging-table').addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (invoiceAgingSortColumn === key) {{
      invoiceAgingSortAscending = !invoiceAgingSortAscending;
    }} else {{
      invoiceAgingSortColumn = key;
      invoiceAgingSortAscending = true;
    }}
    applyInvoiceAging();
  }});
  document.getElementById('invoice-aging-window').addEventListener('change', applyInvoiceAging);
  document.getElementById('btn-reset-invoice-aging-filters').addEventListener('click', function() {{
    document.getElementById('invoice-aging-window').value = {config.INVOICE_AGING_DEFAULT_DAYS};
    var resetSort = invoiceAgingDefaultSort();
    invoiceAgingSortColumn = resetSort.column;
    invoiceAgingSortAscending = resetSort.ascending;
    applyInvoiceAging();
  }});

  // ===================== Dormant Customers table =====================
  var dormantCustomerTypeFilter = createSearchableFilter({{
    prefix: 'growth-dormant-customer-type', allValues: allCustomerTypes, defaultValues: defaultCustomerTypesFiltered,
    presetsKey: 'abco_dashboard_shared_presets_customer_type_v1',
    onApply: function() {{ applyDormantTable(); }}
  }});
  var dormantPopulationMode = 'has-ordered';

  var DORMANT_COLUMNS = [
    {{key: 'customer_name', label: 'Customer', type: 'string'}},
    {{key: 'last_order_date', label: 'Last Order Date', type: 'string'}},
    {{key: 'last_order_products', label: 'Last Order Products', type: 'string'}},
    {{key: 'sales_last_12mo', label: 'Sales (Last 12mo)', type: 'number'}},
    {{key: 'contact_name', label: 'Contact Name', type: 'string'}},
    {{key: 'contact_phone', label: 'Phone', type: 'string'}},
    {{key: 'contact_email', label: 'Email', type: 'string'}}
  ];

  function dormantDefaultSort(mode) {{
    return mode === 'has-ordered'
      ? {{column: 'last_order_date', ascending: true}}
      : {{column: 'customer_name', ascending: true}};
  }}

  var dormantInitialSort = dormantDefaultSort(dormantPopulationMode);
  var dormantSortColumn = dormantInitialSort.column;
  var dormantSortAscending = dormantInitialSort.ascending;

  function applyDormantTable() {{
    var windowInput = document.getElementById('growth-dormant-window');
    var windowDays = parseInt(windowInput.value, 10);
    if (!windowDays || windowDays < 1) windowDays = {config.DORMANT_CUSTOMER_WINDOW_DEFAULT_DAYS};
    var selectedTypes = dormantCustomerTypeFilter.getSelected();
    var typeNote = document.getElementById('growth-dormant-type-note');
    var todayKey = new Date().toISOString().slice(0, 10);
    var cutoffDate = new Date(todayKey + 'T00:00:00Z');
    var yearAgoKey = new Date(cutoffDate.getTime() - 365 * 86400000).toISOString().slice(0, 10);

    var lastInvoicedByCustomer = {{}};
    rawLineData.forEach(function(r) {{
      if (r.order_status_label !== 'Invoiced') return;
      if (!r.issue_date) return;
      var existing = lastInvoicedByCustomer[r.customer_id];
      if (!existing || r.issue_date > existing.issue_date ||
          (r.issue_date === existing.issue_date && r.order_id > existing.order_id)) {{
        lastInvoicedByCustomer[r.customer_id] = {{
          issue_date: r.issue_date, order_id: r.order_id,
          customer_name: r.customer_name, customer_type_name: r.customer_type_name
        }};
      }}
    }});

    var salesLast12moByCustomer = {{}};
    rawData.forEach(function(r) {{
      if (r.order_status_label !== 'Invoiced') return;
      if (!r.issue_date) return;
      if (r.issue_date < yearAgoKey || r.issue_date > todayKey) return;
      salesLast12moByCustomer[r.customer_id] = (salesLast12moByCustomer[r.customer_id] || 0) + (r.value || 0);
    }});

    var rows = [];

    if (dormantPopulationMode === 'has-ordered') {{
      typeNote.style.display = 'none';
      Object.keys(lastInvoicedByCustomer).forEach(function(cid) {{
        var info = lastInvoicedByCustomer[cid];
        if (selectedTypes.indexOf(info.customer_type_name) === -1) return;
        var lastDate = new Date(info.issue_date + 'T00:00:00Z');
        var daysSince = Math.floor((cutoffDate - lastDate) / 86400000);
        if (daysSince < windowDays) return;

        var products = Array.from(new Set(rawLineData
          .filter(function(r) {{ return r.order_id === info.order_id; }})
          .map(function(r) {{ return r.product_name; }})
          .filter(function(v) {{ return v; }})));
        var contact = contactByCustomerId[cid];

        rows.push({{
          customer_name: info.customer_name,
          last_order_date: info.issue_date,
          last_order_products: products.join(', '),
          sales_last_12mo: salesLast12moByCustomer[cid] || 0,
          contact_name: contact ? contact.contact_name : '',
          contact_phone: contact ? contact.contact_phone : '',
          contact_email: contact ? contact.contact_email : ''
        }});
      }});
    }} else {{
      typeNote.style.display = '';
      var everOrderedIds = new Set(
        rawData.filter(function(r) {{ return r.order_status_label === 'Invoiced'; }})
          .map(function(r) {{ return r.customer_id; }})
      );
      contactData.forEach(function(c) {{
        if (everOrderedIds.has(c.customer_id)) return;
        rows.push({{
          customer_name: c.customer_name,
          last_order_date: '',
          last_order_products: '',
          sales_last_12mo: 0,
          contact_name: c.contact_name,
          contact_phone: c.contact_phone,
          contact_email: c.contact_email
        }});
      }});
    }}

    var sortColDef = DORMANT_COLUMNS.find(function(c) {{ return c.key === dormantSortColumn; }}) || DORMANT_COLUMNS[1];
    rows = sortGenericRows(rows, dormantSortColumn, dormantSortAscending, sortColDef.type);

    var bodyRows = rows.map(function(r) {{
      return '<tr>' +
        '<td>' + escapeHtml(r.customer_name) + '</td>' +
        '<td>' + escapeHtml(r.last_order_date || '\\u2014') + '</td>' +
        '<td>' + escapeHtml(r.last_order_products || '\\u2014') + '</td>' +
        '<td>$' + Math.round(r.sales_last_12mo).toLocaleString() + '</td>' +
        '<td>' + escapeHtml(r.contact_name || '') + '</td>' +
        '<td>' + escapeHtml(r.contact_phone || '') + '</td>' +
        '<td>' + escapeHtml(r.contact_email || '') + '</td>' +
        '</tr>';
    }}).join('');
    document.getElementById('growth-dormant-table').innerHTML =
      buildSortableHeaderRow(DORMANT_COLUMNS, dormantSortColumn, dormantSortAscending) + '<tbody>' + bodyRows + '</tbody>';
  }}

  document.getElementById('growth-dormant-table').addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (dormantSortColumn === key) {{
      dormantSortAscending = !dormantSortAscending;
    }} else {{
      dormantSortColumn = key;
      var colDef = DORMANT_COLUMNS.find(function(c) {{ return c.key === key; }});
      dormantSortAscending = colDef.type !== 'number';
    }}
    applyDormantTable();
  }});

  document.getElementById('growth-dormant-window').addEventListener('change', applyDormantTable);
  document.getElementById('growth-dormant-population-toggle').addEventListener('click', function(e) {{
    var btn = e.target.closest('button');
    if (!btn) return;
    dormantPopulationMode = btn.getAttribute('data-population');
    document.querySelectorAll('#growth-dormant-population-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b === btn);
    }});
    var def = dormantDefaultSort(dormantPopulationMode);
    dormantSortColumn = def.column;
    dormantSortAscending = def.ascending;
    applyDormantTable();
  }});
  document.getElementById('btn-reset-growth-dormant-filters').addEventListener('click', function() {{
    dormantCustomerTypeFilter.reset();
    document.getElementById('growth-dormant-window').value = {config.DORMANT_CUSTOMER_WINDOW_DEFAULT_DAYS};
    dormantPopulationMode = 'has-ordered';
    document.querySelectorAll('#growth-dormant-population-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b.getAttribute('data-population') === 'has-ordered');
    }});
    var resetDef = dormantDefaultSort(dormantPopulationMode);
    dormantSortColumn = resetDef.column;
    dormantSortAscending = resetDef.ascending;
    applyDormantTable();
  }});

  applyInvoiceAging();
  applyDormantTable();
}})();
</script>
"""
