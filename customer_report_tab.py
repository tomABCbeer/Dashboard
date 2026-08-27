"""Customer Report tab: pick a customer, see their sales-by-month and
product mix. Reads the Orders tab's already-embedded order-line data
by DOM element id at runtime, rather than embedding its own copy."""
import json

from shared import BEER_TOP_N, BEER_COLORS

def build_customer_report_section():
    beer_colors_json = json.dumps(BEER_COLORS)

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

<script>
(function() {{
  var lineDataEl = document.getElementById('order-line-data');
  var lineData = [];
  try {{ lineData = lineDataEl ? JSON.parse(lineDataEl.textContent) : []; }} catch (e) {{ lineData = []; }}

  var beerColors = {beer_colors_json};
  var beerTopN = {BEER_TOP_N};
  var avgLineColor = '#B0B0B0';

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
    var sParts = startKey.split('-').map(Number), eParts = endKey.split('-').map(Number);
    var y = sParts[0], m = sParts[1];
    var ey = eParts[0], em = eParts[1];
    var guard = 0;
    while ((y < ey || (y === ey && m <= em)) && guard < 1000) {{
      result.push(y + '-' + (m < 10 ? '0' + m : String(m)));
      m++;
      if (m > 12) {{ m = 1; y++; }}
      guard++;
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

    var traces = topProducts.map(function(p, i) {{
      return {{
        x: labels, y: monthlySumForProduct(custLines, p), name: p,
        type: 'bar', marker: {{color: beerColors[i % beerColors.length]}}
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
    var pieColors = topProducts.map(function(p, i) {{ return beerColors[i % beerColors.length]; }});
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
}})();
</script>
"""


# ---------------------------------------------------------------------
# Forecast tab: pick a product, see a projected inventory line over the
# next 4 months, combining:
#   - current stock (from the Products sub-section's data, /products/)
#   - planned production (/planned-packagings/, packaged-product level,
#     not the liquid/recipe level that /drink-batches/ tracks)
#   - existing unfulfilled orders (/fulfillments/ where dispatched is
#     false, each with a scheduled date and specific product/quantity)
#   - a seasonal demand projection: last year's actual quantity for
#     each of the next 4 calendar months, scaled by this year's
#     year-over-year growth rate (this-year-to-date over the same
#     period last year), with already-known unfulfilled orders for
#     that month subtracted out first so a booked order never gets
#     counted twice - once as itself, once as part of the historical
#     pattern.
#
# This reuses the order-line and product-stock data already embedded
# by the Orders and Inventory tabs (read by element id at runtime)
# rather than embedding a third copy.
# ---------------------------------------------------------------------
