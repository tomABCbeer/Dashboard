"""Production tab: just the Recent Batches table, sortable by every
column. (This tab used to also have a batch volume trend chart, a
batches-by-status pie, and a most-brewed-beers chart - removed at the
user's request, keeping only the table.)"""
import json

import pandas as pd

import config
from shared import json_safe


def build_batches_section(df):
    if df is None:
        return "<h2>Production</h2><p class='missing'>No cached data yet - run fetch_data.py first.</p>"

    d = df.copy()
    if "datetime_started" in d.columns:
        d["datetime_started"] = pd.to_datetime(d["datetime_started"], errors="coerce", utc=True)
        d["datetime_started"] = d["datetime_started"].dt.strftime("%Y-%m-%d")
    vol_col = "total_volume.litre" if "total_volume.litre" in d.columns else None
    if vol_col:
        d[vol_col] = pd.to_numeric(d[vol_col], errors="coerce")
    if "status" in d.columns:
        d["status_label"] = pd.to_numeric(d["status"], errors="coerce").map(config.BATCH_STATUS_LABELS).fillna("Unknown")
    if "brew_type" in d.columns:
        d["brew_type_label"] = pd.to_numeric(d["brew_type"], errors="coerce").map(config.BREW_TYPE_LABELS).fillna("Unknown")
    if "abv" in d.columns:
        d["abv"] = pd.to_numeric(d["abv"], errors="coerce")

    records = []
    for _, row in d.iterrows():
        records.append({
            "batch_code": json_safe(row.get("batch_code")),
            "drink_name": json_safe(row.get("drink.name")),
            "status_label": json_safe(row.get("status_label")),
            "datetime_started": json_safe(row.get("datetime_started")),
            "volume": json_safe(row.get(vol_col)) if vol_col else None,
            "abv": json_safe(row.get("abv")),
            "brew_type_label": json_safe(row.get("brew_type_label")),
        })
    records_json = json.dumps(records, allow_nan=False)

    return f"""
<h2>Production</h2>

<h3>Recent Batches</h3>
<p class="section-note">Every batch, all-time. Click any column header to sort.</p>
<div class="table-wrap">
  <table class="data-table" id="batches-table"></table>
</div>

<script id="batches-data" type="application/json">{records_json}</script>
<script>
(function() {{
  var batches = JSON.parse(document.getElementById('batches-data').textContent);

  var BATCH_COLUMNS = [
    {{key: 'batch_code', label: 'Batch Code', type: 'string'}},
    {{key: 'drink_name', label: 'Beer', type: 'string'}},
    {{key: 'status_label', label: 'Status', type: 'string'}},
    {{key: 'datetime_started', label: 'Started', type: 'string'}},
    {{key: 'volume', label: 'Volume (L)', type: 'number'}},
    {{key: 'abv', label: 'ABV (%)', type: 'number'}},
    {{key: 'brew_type_label', label: 'Brew Type', type: 'string'}}
  ];
  var sortColumn = 'datetime_started';
  var sortAscending = false;

  function fmtNum(n) {{ return n === null || n === undefined ? '\\u2014' : Number(n).toLocaleString(undefined, {{maximumFractionDigits: 1}}); }}

  function renderBatchesTable() {{
    var colDef = BATCH_COLUMNS.find(function(c) {{ return c.key === sortColumn; }}) || BATCH_COLUMNS[3];
    var sorted = sortGenericRows(batches, sortColumn, sortAscending, colDef.type);

    var bodyRows = sorted.map(function(r) {{
      return '<tr>' +
        '<td>' + escapeHtml(r.batch_code || '\\u2014') + '</td>' +
        '<td>' + escapeHtml(r.drink_name || '\\u2014') + '</td>' +
        '<td>' + escapeHtml(r.status_label || '\\u2014') + '</td>' +
        '<td>' + escapeHtml(r.datetime_started || '\\u2014') + '</td>' +
        '<td>' + fmtNum(r.volume) + '</td>' +
        '<td>' + fmtNum(r.abv) + '</td>' +
        '<td>' + escapeHtml(r.brew_type_label || '\\u2014') + '</td>' +
        '</tr>';
    }}).join('');

    document.getElementById('batches-table').innerHTML =
      buildSortableHeaderRow(BATCH_COLUMNS, sortColumn, sortAscending) + '<tbody>' + bodyRows + '</tbody>';
  }}

  document.getElementById('batches-table').addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (sortColumn === key) {{
      sortAscending = !sortAscending;
    }} else {{
      sortColumn = key;
      var colDef = BATCH_COLUMNS.find(function(c) {{ return c.key === key; }});
      sortAscending = colDef.type !== 'number';
    }}
    renderBatchesTable();
  }});

  renderBatchesTable();
}})();
</script>
"""
