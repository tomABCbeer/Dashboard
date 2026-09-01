"""Growth & Efficiency tab: New Account Sales and Sales Per Customer.
(The Dormant Customers table that used to live here has moved to the
Customer Report tab, under the Invoice Aging table - both are
customer-specific concerns, so they fit better there.)"""
import json

import config
from shared import filter_dropdown_html, BEER_TOP_N, BEER_COLORS


def build_growth_efficiency_section():
    beer_colors_json = json.dumps(BEER_COLORS)
    default_types_json = json.dumps(config.DEFAULT_CUSTOMER_TYPES)

    new_account_type_html = filter_dropdown_html("growth-new-account-customer-type", "Customer type", "customer types")
    sales_per_customer_type_html = filter_dropdown_html("growth-sales-per-customer-type", "Customer type", "customer types")

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

<script>
(function() {{
  var rawData = JSON.parse(document.getElementById('orders-data').textContent);
  var rawLineData = JSON.parse(document.getElementById('order-line-data').textContent);

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
        type: 'bar', marker: {{color: findConfiguredProductColor(p) || beerColors[i % beerColors.length]}}
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

  applyNewAccountSales();
  applySalesPerCustomer();
}})();
</script>
"""
