"""Growth & Efficiency tab: New Account Sales, Sales Per Customer, and
the Dormant Customers table."""
import json

import config
from shared import json_safe, _parse_json_list, filter_dropdown_html, BEER_TOP_N, BEER_COLORS

def prepare_customer_records(customers_df):
    """Build JSON-serializable per-customer contact records for the
    Growth & Efficiency tab's Dormant Customers table, from
    /customers-suppliers/. Picks one contact per customer using
    config.CONTACT_TAG_MARKETING then config.CONTACT_TAG_INVOICES (in
    that priority order - Breww has no structured "primary contact"
    flag, only free-text tags), falling back to the business's own
    primary_email/primary_phone_number with no contact name (there's
    no person to name in that case) if neither tag matches, or the
    account has no contacts at all.

    This endpoint has no Hotel/Shop/Club-style customer type field, so
    that's deliberately not resolved here - the Growth & Efficiency
    tab's JS resolves it from order data instead (where available),
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


def build_growth_efficiency_section(customers_df):
    customer_records = prepare_customer_records(customers_df)
    customer_records_json = json.dumps(customer_records, allow_nan=False)
    beer_colors_json = json.dumps(BEER_COLORS)
    default_types_json = json.dumps(config.DEFAULT_CUSTOMER_TYPES)

    new_account_type_html = filter_dropdown_html("growth-new-account-customer-type", "Customer type", "customer types")
    sales_per_customer_type_html = filter_dropdown_html("growth-sales-per-customer-type", "Customer type", "customer types")
    dormant_type_html = filter_dropdown_html("growth-dormant-customer-type", "Customer type", "customer types")

    return f"""
<h2>Growth &amp; Efficiency</h2>

<h3>New Account Sales</h3>
<p class="section-note">Revenue from orders placed within a configurable window of each customer's first invoiced order, stacked by product (left axis) - a rising trend signals new accounts are ramping up faster than they used to. The line shows how many new accounts joined each month (right axis), so you can tell whether revenue growth is from more new accounts or from each one spending more.</p>

<div class="chart-scoped-filter" id="growth-new-account-filters">
{new_account_type_html}
  <div class="filter-group">
    <label>New account window (days)</label>
    <input type="number" id="growth-new-account-window" min="1" value="{config.NEW_ACCOUNT_WINDOW_DEFAULT_DAYS}" style="width:80px;">
  </div>
  <div class="filter-actions">
    <button id="btn-reset-growth-new-account-filters">Reset</button>
  </div>
</div>
<div id="chart-growth-new-account-sales" class="chart-div"></div>

<h3>Sales Per Customer</h3>
<p class="section-note">Average sales per customer (bar, left axis) alongside the customer count behind that average (line, right axis) - compare how they move together to see whether growth is coming from adding accounts or from existing ones spending more.</p>

<div class="chart-scoped-filter" id="growth-sales-per-customer-filters">
{sales_per_customer_type_html}
  <div class="filter-group">
    <label>Customer count basis</label>
    <div class="unit-toggle" id="growth-customer-basis-toggle">
      <button type="button" class="active" data-basis="cumulative">Cumulative total</button>
      <button type="button" data-basis="active">Active this month</button>
    </div>
  </div>
  <div class="filter-actions">
    <button id="btn-reset-growth-sales-per-customer-filters">Reset</button>
  </div>
</div>
<div id="chart-growth-sales-per-customer" class="chart-div"></div>

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
  var rawLineData = JSON.parse(document.getElementById('order-line-data').textContent);
  var contactDataEl = document.getElementById('customer-contact-data');
  var contactData = [];
  try {{ contactData = contactDataEl ? JSON.parse(contactDataEl.textContent) : []; }} catch (e) {{ contactData = []; }}

  var beerColors = {beer_colors_json};
  var beerTopN = {BEER_TOP_N};

  var allCustomerTypes = Array.from(new Set(rawData.map(function(r) {{ return r.customer_type_name; }})
    .filter(function(v) {{ return v; }}))).sort();
  var defaultCustomerTypes = {default_types_json};
  var defaultCustomerTypesFiltered = defaultCustomerTypes.filter(function(t) {{ return allCustomerTypes.indexOf(t) !== -1; }});

  var MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function monthKey(dateStr) {{ return dateStr ? dateStr.slice(0, 7) : null; }}
  function monthLabel(key) {{
    var parts = key.split('-');
    var y = parts[0], m = parseInt(parts[1], 10);
    return MONTH_ABBR[m - 1] + ' ' + y;
  }}

  var contactByCustomerId = {{}};
  contactData.forEach(function(c) {{ contactByCustomerId[c.customer_id] = c; }});

  // First INVOICED order date per customer, among customers present
  // in customerIdSet (or all customers if no set given). Shared logic
  // for both New Account Sales and Sales Per Customer.
  function computeFirstInvoicedDates(customerIdSet) {{
    var map = {{}};
    rawData.forEach(function(r) {{
      if (r.order_status_label !== 'Invoiced') return;
      if (!r.issue_date) return;
      if (customerIdSet && !customerIdSet.has(r.customer_id)) return;
      var existing = map[r.customer_id];
      if (!existing || r.issue_date < existing) {{
        map[r.customer_id] = r.issue_date;
      }}
    }});
    return map;
  }}

  // ===================== New Account Sales =====================
  var newAccountCustomerTypeFilter = createSearchableFilter({{
    prefix: 'growth-new-account-customer-type', allValues: allCustomerTypes, defaultValues: defaultCustomerTypesFiltered,
    presetsKey: 'abco_dashboard_shared_presets_customer_type_v1',
    onApply: function() {{ applyNewAccountSales(); }}
  }});

  function applyNewAccountSales() {{
    var selectedTypes = newAccountCustomerTypeFilter.getSelected();
    var windowInput = document.getElementById('growth-new-account-window');
    var windowDays = parseInt(windowInput.value, 10);
    if (!windowDays || windowDays < 1) windowDays = {config.NEW_ACCOUNT_WINDOW_DEFAULT_DAYS};

    var eligibleCustomerIds = new Set(
      rawData.filter(function(r) {{ return selectedTypes.indexOf(r.customer_type_name) !== -1; }})
        .map(function(r) {{ return r.customer_id; }})
    );
    var firstInvoiced = computeFirstInvoicedDates(eligibleCustomerIds);

    var qualifyingLines = rawLineData.filter(function(r) {{
      if (r.order_status_label !== 'Invoiced') return false;
      if (selectedTypes.indexOf(r.customer_type_name) === -1) return false;
      var first = firstInvoiced[r.customer_id];
      if (!first || !r.issue_date) return false;
      var daysDiff = (new Date(r.issue_date + 'T00:00:00Z') - new Date(first + 'T00:00:00Z')) / 86400000;
      return daysDiff >= 0 && daysDiff < windowDays;
    }});

    var months = Array.from(new Set(qualifyingLines.map(function(r) {{ return monthKey(r.issue_date); }})))
      .filter(function(m) {{ return m; }}).sort();
    var labels = months.map(monthLabel);

    // # of new accounts that month = distinct customers (matching the
    // current type filter) whose FIRST invoiced order fell in that
    // month - not how many qualifying orders landed there (that's
    // what the bars already show). A customer's first invoiced order
    // is always within the window by definition (day 0), so every
    // month with a new account already has a bar - this never adds a
    // month the bars don't already cover.
    var newAccountCountByMonth = {{}};
    months.forEach(function(mk) {{ newAccountCountByMonth[mk] = 0; }});
    Object.keys(firstInvoiced).forEach(function(cid) {{
      var mk = monthKey(firstInvoiced[cid]);
      if (mk in newAccountCountByMonth) newAccountCountByMonth[mk]++;
    }});
    var newAccountCounts = months.map(function(mk) {{ return newAccountCountByMonth[mk]; }});

    var totalsByProduct = {{}};
    qualifyingLines.forEach(function(r) {{
      var name = r.product_name || 'Unknown';
      totalsByProduct[name] = (totalsByProduct[name] || 0) + (r.value || 0);
    }});
    var topProducts = Object.keys(totalsByProduct)
      .sort(function(a, b) {{ return totalsByProduct[b] - totalsByProduct[a]; }})
      .slice(0, beerTopN);

    function monthlySumForProduct(productName) {{
      var map = {{}};
      months.forEach(function(mk) {{ map[mk] = 0; }});
      qualifyingLines.forEach(function(r) {{
        var mk = monthKey(r.issue_date);
        if (!(mk in map)) return;
        var name = r.product_name || 'Unknown';
        if (productName === null) {{
          if (topProducts.indexOf(name) !== -1) return;
        }} else if (name !== productName) {{
          return;
        }}
        map[mk] += (r.value || 0);
      }});
      return months.map(function(mk) {{ return map[mk]; }});
    }}

    var traces = topProducts.map(function(p, i) {{
      return {{
        x: labels, y: monthlySumForProduct(p), name: p,
        type: 'bar', marker: {{color: beerColors[i % beerColors.length]}}
      }};
    }});
    var otherTotal = Object.keys(totalsByProduct).reduce(function(s, n) {{
      return topProducts.indexOf(n) === -1 ? s + totalsByProduct[n] : s;
    }}, 0);
    if (otherTotal > 0) {{
      traces.push({{
        x: labels, y: monthlySumForProduct(null), name: 'Other',
        type: 'bar', marker: {{color: beerColors[beerColors.length - 1]}}
      }});
    }}

    traces.push({{
      x: labels, y: newAccountCounts, name: '# of new accounts',
      type: 'scatter', mode: 'lines+markers',
      line: {{color: '#B0B0B0'}}, marker: {{color: '#B0B0B0'}}, yaxis: 'y2'
    }});

    Plotly.react('chart-growth-new-account-sales', traces, {{
      barmode: 'stack', template: 'plotly_white',
      title: 'New Account Sales (orders within ' + windowDays + ' days of first invoiced order)',
      height: 460,
      yaxis: {{title: 'Net Sales Value ($)'}},
      yaxis2: {{title: '# of New Accounts', overlaying: 'y', side: 'right', rangemode: 'tozero'}},
      xaxis: {{title: ''}}, legend: {{title: {{text: ''}}}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  document.getElementById('growth-new-account-window').addEventListener('change', applyNewAccountSales);
  document.getElementById('btn-reset-growth-new-account-filters').addEventListener('click', function() {{
    newAccountCustomerTypeFilter.reset();
    document.getElementById('growth-new-account-window').value = {config.NEW_ACCOUNT_WINDOW_DEFAULT_DAYS};
    applyNewAccountSales();
  }});

  // ===================== Sales Per Customer =====================
  var salesPerCustomerTypeFilter = createSearchableFilter({{
    prefix: 'growth-sales-per-customer-type', allValues: allCustomerTypes, defaultValues: defaultCustomerTypesFiltered,
    presetsKey: 'abco_dashboard_shared_presets_customer_type_v1',
    onApply: function() {{ applySalesPerCustomer(); }}
  }});
  var customerBasisMode = 'cumulative';

  function applySalesPerCustomer() {{
    var selectedTypes = salesPerCustomerTypeFilter.getSelected();
    var eligibleOrders = rawData.filter(function(r) {{
      return r.order_status_label === 'Invoiced' && selectedTypes.indexOf(r.customer_type_name) !== -1;
    }});
    var eligibleCustomerIds = new Set(eligibleOrders.map(function(r) {{ return r.customer_id; }}));
    var firstInvoiced = computeFirstInvoicedDates(eligibleCustomerIds);

    var months = Array.from(new Set(eligibleOrders.map(function(r) {{ return monthKey(r.issue_date); }})))
      .filter(function(m) {{ return m; }}).sort();
    var labels = months.map(monthLabel);

    var salesByMonth = {{}};
    months.forEach(function(mk) {{ salesByMonth[mk] = 0; }});
    eligibleOrders.forEach(function(r) {{
      var mk = monthKey(r.issue_date);
      if (mk in salesByMonth) salesByMonth[mk] += (r.value || 0);
    }});

    var countByMonth = {{}};
    if (customerBasisMode === 'cumulative') {{
      months.forEach(function(mk) {{
        var monthEnd = mk + '-31';  // safe upper bound for string comparison against real dates
        var count = 0;
        Object.keys(firstInvoiced).forEach(function(cid) {{
          if (firstInvoiced[cid] <= monthEnd) count++;
        }});
        countByMonth[mk] = count;
      }});
    }} else {{
      months.forEach(function(mk) {{
        var activeSet = new Set();
        eligibleOrders.forEach(function(r) {{
          if (monthKey(r.issue_date) === mk) activeSet.add(r.customer_id);
        }});
        countByMonth[mk] = activeSet.size;
      }});
    }}

    var avgSales = months.map(function(mk) {{
      var count = countByMonth[mk];
      return count > 0 ? salesByMonth[mk] / count : 0;
    }});
    var counts = months.map(function(mk) {{ return countByMonth[mk]; }});

    Plotly.react('chart-growth-sales-per-customer', [
      {{
        x: labels, y: avgSales, type: 'bar', name: 'Avg. sales per customer',
        marker: {{color: '#4CAF6B'}}, yaxis: 'y'
      }},
      {{
        x: labels, y: counts, type: 'scatter', mode: 'lines+markers', name: 'Customer count',
        line: {{color: '#3F4B8C'}}, marker: {{color: '#3F4B8C'}}, yaxis: 'y2'
      }}
    ], {{
      template: 'plotly_white', title: 'Sales Per Customer',
      height: 460,
      yaxis: {{title: 'Avg. Sales per Customer ($)', side: 'left'}},
      yaxis2: {{title: 'Customer Count', overlaying: 'y', side: 'right'}},
      xaxis: {{title: ''}}, legend: {{title: {{text: ''}}}}
    }}, {{displayModeBar: false, responsive: true}});
  }}

  document.getElementById('growth-customer-basis-toggle').addEventListener('click', function(e) {{
    var btn = e.target.closest('button');
    if (!btn) return;
    customerBasisMode = btn.getAttribute('data-basis');
    document.querySelectorAll('#growth-customer-basis-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b === btn);
    }});
    applySalesPerCustomer();
  }});
  document.getElementById('btn-reset-growth-sales-per-customer-filters').addEventListener('click', function() {{
    salesPerCustomerTypeFilter.reset();
    customerBasisMode = 'cumulative';
    document.querySelectorAll('#growth-customer-basis-toggle button').forEach(function(b) {{
      b.classList.toggle('active', b.getAttribute('data-basis') === 'cumulative');
    }});
    applySalesPerCustomer();
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
    // Matches this table's original fixed sort order for each
    // population, before per-column sorting existed - oldest-first
    // for has-ordered, alphabetical for never-ordered (which has no
    // order date to sort by).
    return mode === 'has-ordered'
      ? {{column: 'last_order_date', ascending: true}}
      : {{column: 'customer_name', ascending: true}};
  }}

  var dormantInitialSort = dormantDefaultSort(dormantPopulationMode);
  var dormantSortColumn = dormantInitialSort.column;
  var dormantSortAscending = dormantInitialSort.ascending;

  function sortDormantRows(rows, column, ascending, type) {{
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

  function buildDormantHeaderRow() {{
    var cells = DORMANT_COLUMNS.map(function(col) {{
      var indicator = '';
      if (dormantSortColumn === col.key) {{
        indicator = dormantSortAscending ? ' \\u25b2' : ' \\u25bc';
      }}
      return '<th><button type="button" class="sort-header-btn" data-sort-key="' + col.key + '">' +
        escapeHtml(col.label) + indicator + '</button></th>';
    }}).join('');
    return '<thead><tr>' + cells + '</tr></thead>';
  }}

  function applyDormantTable() {{
    var windowInput = document.getElementById('growth-dormant-window');
    var windowDays = parseInt(windowInput.value, 10);
    if (!windowDays || windowDays < 1) windowDays = {config.DORMANT_CUSTOMER_WINDOW_DEFAULT_DAYS};
    var selectedTypes = dormantCustomerTypeFilter.getSelected();
    var typeNote = document.getElementById('growth-dormant-type-note');
    var todayKey = new Date().toISOString().slice(0, 10);
    var cutoffDate = new Date(todayKey + 'T00:00:00Z');
    var yearAgoKey = new Date(cutoffDate.getTime() - 365 * 86400000).toISOString().slice(0, 10);

    // Last INVOICED order per customer, derived from line-level data
    // so we get the specific order_id (for precise product grouping -
    // two same-day orders from one customer stay distinct).
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
    rows = sortDormantRows(rows, dormantSortColumn, dormantSortAscending, sortColDef.type);

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
    document.getElementById('growth-dormant-table').innerHTML = buildDormantHeaderRow() + '<tbody>' + bodyRows + '</tbody>';
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
      // Numeric columns start high-to-low on first click (the more
      // useful initial view for a revenue figure); text/date columns
      // start ascending (A-Z / oldest-first).
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

  applyNewAccountSales();
  applySalesPerCustomer();
  applyDormantTable();
}})();
</script>
"""


