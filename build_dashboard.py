"""
ABCo Breww Dashboard - build script.

Pulls together every tab (each in its own module) into one static,
self-contained dashboard.html. Run fetch_data.py first to populate
the data/ directory, then this script.
"""
import pandas as pd

import config
from shared import SHARED_FILTER_LIB_JS, load_csv
from orders_tab import build_orders_section
from batches_tab import build_batches_section
from inventory_tab import build_stock_section
from customer_report_tab import build_customer_report_section
from forecast_tab import build_forecast_section
from growth_efficiency_tab import build_growth_efficiency_section

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ABCo - Breww Dashboard</title>
<script charset="utf-8" src="https://cdn.plot.ly/plotly-3.7.0.min.js"></script>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 0; padding: 0 24px 48px; background: #faf8f4; color: #2b2420; }}
  header {{ padding: 28px 0 12px; }}
  header h1 {{ margin: 0 0 4px; font-size: 26px; }}
  header p {{ margin: 0; color: #7a7268; font-size: 14px; }}
  h2 {{ margin-top: 48px; border-bottom: 2px solid #e4dcc9; padding-bottom: 8px; }}
  h3 {{ margin-top: 24px; }}
  h4 {{ margin-top: 20px; font-size: 15px; }}
  .section-note {{ color: #7a7268; font-size: 13px; margin: -8px 0 12px; }}
  .kpi-row {{ display: flex; gap: 16px; margin: 16px 0 24px; flex-wrap: wrap; }}
  .kpi {{ background: white; border: 1px solid #e4dcc9; border-radius: 10px; padding: 16px 24px; min-width: 140px; }}
  .kpi-value {{ font-size: 26px; font-weight: 700; }}
  .kpi-label {{ font-size: 13px; color: #7a7268; margin-top: 4px; }}
  .data-table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: white; }}
  .data-table th {{ background: #f1ead9; text-align: left; padding: 8px 10px; position: sticky; top: 0; }}
  .data-table td {{ padding: 6px 10px; border-top: 1px solid #ece6d8; }}
  .sort-header-btn {{ display: block; width: 100%; text-align: left; padding: 0; margin: 0; border: none; background: none; font: inherit; font-weight: 600; cursor: pointer; color: inherit; }}
  .sort-header-btn:hover {{ text-decoration: underline; }}
  .table-wrap {{ overflow-x: auto; max-height: 420px; overflow-y: auto; border: 1px solid #e4dcc9; border-radius: 8px; }}
  .missing {{ color: #a35; font-style: italic; }}
  footer {{ margin-top: 48px; color: #a39a8c; font-size: 12px; }}
  .filters-panel {{ background: white; border: 1px solid #e4dcc9; border-radius: 10px; padding: 16px 20px; margin: 16px 0; display: flex; flex-wrap: wrap; gap: 20px 28px; align-items: flex-start; }}
  .filter-group {{ display: flex; flex-direction: column; gap: 6px; }}
  .filter-group > label:first-child {{ font-size: 12px; font-weight: 700; color: #7a7268; text-transform: uppercase; letter-spacing: 0.03em; }}
  .filter-actions {{ display: flex; gap: 8px; align-items: center; margin-left: auto; }}
  .filter-actions button {{ padding: 7px 14px; border-radius: 6px; border: 1px solid #e4dcc9; background: #faf8f4; font-size: 13px; cursor: pointer; }}
  .filter-actions button:hover {{ background: #f1ead9; }}
  .filter-actions button.primary {{ background: #4CAF6B; color: white; border-color: #4CAF6B; }}
  .filter-actions button.primary:hover {{ background: #3f9a5b; }}
  .preset-row {{ display: flex; gap: 8px; align-items: center; }}
  .preset-row select {{ padding: 6px 8px; border: 1px solid #e4dcc9; border-radius: 6px; font-size: 13px; background: white; max-width: 220px; }}
  .preset-row button {{ padding: 6px 12px; border-radius: 6px; border: 1px solid #e4dcc9; background: #faf8f4; font-size: 13px; cursor: pointer; }}
  .preset-row button:hover {{ background: #f1ead9; }}
  .chart-scoped-filter {{ background: #faf6ec; border: 1px dashed #d8cba8; border-radius: 8px; padding: 16px 20px; margin: 8px 0 4px; display: flex; flex-wrap: wrap; gap: 20px 28px; align-items: flex-start; }}
  .chart-scoped-filter > .filter-group > label:first-child {{ font-size: 11px; font-weight: 700; color: #9a8a5f; text-transform: uppercase; letter-spacing: 0.03em; }}

  .filter-dropdown {{ position: relative; max-width: 420px; }}
  .filter-dropdown-toggle {{ width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border: 1px solid #d8cba8; border-radius: 6px; background: white; font-size: 13px; cursor: pointer; text-align: left; }}
  .filter-dropdown-toggle:hover {{ background: #f1ead9; }}
  .filter-dropdown-caret {{ color: #9a8a5f; margin-left: 8px; }}
  .filter-dropdown-panel {{ position: absolute; top: calc(100% + 4px); left: 0; width: 100%; min-width: 320px; background: white; border: 1px solid #d8cba8; border-radius: 8px; box-shadow: 0 8px 24px rgba(43, 36, 32, 0.15); z-index: 20; padding: 10px; }}
  .filter-search-input {{ width: 100%; box-sizing: border-box; padding: 7px 10px; border: 1px solid #e4dcc9; border-radius: 6px; font-size: 13px; margin-bottom: 8px; }}
  .filter-search-input:focus {{ outline: 2px solid #c9a0dc; outline-offset: -1px; }}
  .filter-dropdown-actions {{ display: flex; gap: 8px; margin-bottom: 8px; }}
  .filter-dropdown-actions button {{ padding: 4px 10px; border-radius: 6px; border: 1px solid #d8cba8; background: #faf6ec; font-size: 12px; cursor: pointer; }}
  .filter-dropdown-actions button:hover {{ background: #f1ead9; }}
  .filter-row-list {{ max-height: 260px; overflow-y: auto; border-top: 1px solid #ece6d8; padding-top: 6px; }}
  .filter-row {{ display: block; padding: 5px 4px; font-size: 13px; cursor: pointer; border-radius: 4px; }}
  .filter-row:hover {{ background: #f1ead9; }}
  .filter-row input {{ margin-right: 8px; }}
  .filter-search-empty {{ font-size: 12px; color: #a39a8c; font-style: italic; margin: 6px 4px 2px; }}
  .preset-status-msg {{ font-size: 12px; color: #7a7268; display: block; margin-top: 4px; }}
  .chart-div {{ min-height: 400px; }}

  .tab-nav {{ display: flex; gap: 4px; border-bottom: 2px solid #e4dcc9; margin-top: 16px; }}
  .tab-btn {{ padding: 10px 20px; border: none; background: none; font-size: 15px; font-weight: 600; color: #7a7268; cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -2px; }}
  .tab-btn:hover {{ color: #2b2420; }}
  .tab-btn.active {{ color: #4CAF6B; border-bottom-color: #4CAF6B; }}
  .tab-panel h2:first-child {{ margin-top: 24px; }}

  .customer-search-input {{ width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid #e4dcc9; border-radius: 6px; font-size: 13px; margin-bottom: 8px; }}
  .customer-search-input:focus {{ outline: 2px solid #c9a0dc; outline-offset: -1px; }}
  .customer-dropdown {{ position: relative; max-width: 420px; }}
  .customer-dropdown-toggle {{ width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border: 1px solid #d8cba8; border-radius: 6px; background: white; font-size: 13px; cursor: pointer; text-align: left; }}
  .customer-dropdown-toggle:hover {{ background: #f1ead9; }}
  .customer-dropdown-panel {{ position: absolute; top: calc(100% + 4px); left: 0; width: 100%; min-width: 320px; background: white; border: 1px solid #d8cba8; border-radius: 8px; box-shadow: 0 8px 24px rgba(43, 36, 32, 0.15); z-index: 20; padding: 10px; max-height: 340px; overflow-y: auto; }}
  .customer-row {{ display: block; padding: 6px 8px; font-size: 13px; cursor: pointer; border-radius: 4px; }}
  .customer-row:hover {{ background: #f1ead9; }}
  .customer-row .customer-type-tag {{ color: #a39a8c; font-size: 11px; margin-left: 6px; }}
  .customer-report-controls {{ background: white; border: 1px solid #e4dcc9; border-radius: 10px; padding: 16px 20px; margin: 16px 0; display: flex; flex-wrap: wrap; gap: 20px 28px; align-items: flex-start; }}
  .unit-toggle {{ display: flex; border: 1px solid #e4dcc9; border-radius: 6px; overflow: hidden; }}
  .unit-toggle button {{ padding: 7px 14px; border: none; background: #faf8f4; font-size: 13px; cursor: pointer; }}
  .unit-toggle button.active {{ background: #4CAF6B; color: white; }}
  .customer-report-placeholder {{ color: #a39a8c; font-style: italic; padding: 40px 0; text-align: center; }}
  .customer-report-charts {{ display: grid; grid-template-columns: 1fr; gap: 24px; }}
</style>
</head>
<body>
<script>
{shared_filter_lib_js}
</script>
<header>
  <h1>ABCo Breww Dashboard</h1>
  <p>Generated {generated_at}</p>
</header>

<div class="tab-nav" id="tab-nav">
  <button class="tab-btn active" type="button" data-tab="orders">Orders</button>
  <button class="tab-btn" type="button" data-tab="production">Production</button>
  <button class="tab-btn" type="button" data-tab="inventory">Inventory</button>
  <button class="tab-btn" type="button" data-tab="customer-report">Customer Report</button>
  <button class="tab-btn" type="button" data-tab="forecast">Forecast</button>
  <button class="tab-btn" type="button" data-tab="growth-efficiency">Growth &amp; Efficiency</button>
</div>

<div class="tab-panel" id="tab-orders" data-tab-panel="orders">{orders_html}</div>
<div class="tab-panel" id="tab-production" data-tab-panel="production" hidden>{batches_html}</div>
<div class="tab-panel" id="tab-inventory" data-tab-panel="inventory" hidden>{stock_html}</div>
<div class="tab-panel" id="tab-customer-report" data-tab-panel="customer-report" hidden>{customer_report_html}</div>
<div class="tab-panel" id="tab-forecast" data-tab-panel="forecast" hidden>{forecast_html}</div>
<div class="tab-panel" id="tab-growth-efficiency" data-tab-panel="growth-efficiency" hidden>{growth_efficiency_html}</div>

<script>
(function() {{
  var tabButtons = document.querySelectorAll('.tab-btn');
  var tabPanels = document.querySelectorAll('.tab-panel');

  function activateTab(name) {{
    tabButtons.forEach(function(b) {{ b.classList.toggle('active', b.getAttribute('data-tab') === name); }});
    tabPanels.forEach(function(p) {{ p.hidden = (p.getAttribute('data-tab-panel') !== name); }});

    // Charts drawn while their tab was hidden (display:none) often end
    // up with broken/zero dimensions, since Plotly measures the
    // container at draw time. Forcing a resize on every Plotly chart
    // in the panel we just revealed fixes that without needing to
    // redraw the chart's data.
    var panel = document.querySelector('[data-tab-panel="' + name + '"]');
    if (panel && window.Plotly && window.Plotly.Plots) {{
      panel.querySelectorAll('.js-plotly-plot').forEach(function(el) {{
        try {{ window.Plotly.Plots.resize(el); }} catch (e) {{}}
      }});
    }}
  }}

  tabButtons.forEach(function(btn) {{
    btn.addEventListener('click', function() {{ activateTab(btn.getAttribute('data-tab')); }});
  }});
}})();
</script>

<footer>Data pulled from the Breww API via fetch_data.py. Re-run fetch_data.py, then this script, to refresh. Order filters above are applied live in your browser and don't require rebuilding this file.</footer>
</body>
</html>
"""




def main():
    orders_df = load_csv("orders")
    batches_df = load_csv("batches")
    stock_df = load_csv("stock_received")
    customer_types_df = load_csv("customer_types")
    order_lines_df = load_csv("order_lines")
    products_df = load_csv("products")
    fulfillments_df = load_csv("fulfillments")
    packagings_df = load_csv("planned_packagings")
    customers_df = load_csv("customers_suppliers")

    html = PAGE_TEMPLATE.format(
        generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        shared_filter_lib_js=SHARED_FILTER_LIB_JS,
        orders_html=build_orders_section(orders_df, customer_types_df, order_lines_df),
        batches_html=build_batches_section(batches_df),
        stock_html=build_stock_section(stock_df, products_df),
        customer_report_html=build_customer_report_section(),
        forecast_html=build_forecast_section(fulfillments_df, packagings_df),
        growth_efficiency_html=build_growth_efficiency_section(customers_df),
    )

    with open(config.OUTPUT_HTML, "w") as f:
        f.write(html)

    print(f"Wrote {config.OUTPUT_HTML}")


if __name__ == "__main__":
    main()
