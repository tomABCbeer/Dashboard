"""Production tab: batch packaging table.

One row per batch + packaged date + package type, built from Breww's
on-site (type 5) and off-site received (type 7) packaging records
from /drink-batch-actions/.
Breww doesn't return a package COUNT on those records, so the count is
derived: litres packaged / litres per package (the product's gross
liquid volume). If the division isn't close to a whole number (part-
filled kegs, odd fills) the count is rounded and shown with a "~".
"""
import json

import pandas as pd

from shared import json_safe

# 5 = packaged on-site, 7 = packaged off-site (contract brews) and received
PACKAGING_ACTION_TYPES = (5, 7)


def _num(v):
    n = pd.to_numeric(v, errors="coerce")
    return None if pd.isna(n) else float(n)


def build_packaging_records(actions_df, batches_df, container_types_df):
    """Return a list of row dicts (one per batch/date/package type)."""
    if actions_df is None or actions_df.empty:
        return []
    a = actions_df.copy()
    if "action_type" in a.columns:
        a = a[pd.to_numeric(a["action_type"], errors="coerce").isin(PACKAGING_ACTION_TYPES)]

    refs = {}
    if batches_df is not None and "id" in batches_df.columns and "batch_ref" in batches_df.columns:
        for _, r in batches_df.iterrows():
            ref = r.get("batch_ref")
            refs[r["id"]] = None if pd.isna(ref) else str(ref)

    ct_names = {}
    if container_types_df is not None and "id" in container_types_df.columns and "name" in container_types_df.columns:
        for _, r in container_types_df.iterrows():
            ct_names[r["id"]] = r["name"]

    groups = {}
    for _, r in a.iterrows():
        done = pd.to_datetime(r.get("datetime_done"), errors="coerce", utc=True)
        if pd.isna(done):
            continue
        day = done.tz_convert("America/New_York").strftime("%Y-%m-%d")
        vol = _num(r.get("volume_successful.litre")) or 0.0
        per = (_num(r.get("initial_product.liquid_volume_gross.litre"))
               or _num(r.get("initial_product.liquid_volume_taxable.litre")))
        beer = json_safe(r.get("drink_batch.drink.name"))
        pid = _num(r.get("initial_product.id"))
        # Package type = the product's own name, minus the leading beer
        # name ("My New GF - 24 x 16oz Can" -> "24 x 16oz Can"). Not the
        # container type: different sizes can share one container type.
        pkg = json_safe(r.get("initial_product.name"))
        if pkg and beer and pkg.startswith(beer + " - "):
            pkg = pkg[len(beer) + 3:]
        if not pkg:
            ct_id = _num(r.get("container_type"))
            pkg = ct_names.get(int(ct_id)) if ct_id is not None else None
        pkg = pkg or "Unknown"
        batch_id = _num(r.get("drink_batch.id"))
        key = (batch_id, day, pid if pid is not None else pkg)
        g = groups.setdefault(key, {
            "batch_code": json_safe(r.get("drink_batch.batch_code")),
            "batch_ref": refs.get(int(batch_id)) if batch_id is not None else None,
            "date": day,
            "beer": beer,
            "package": pkg,
            "volume": 0.0,
            "per": per,
        })
        g["volume"] += vol

    out = []
    for g in groups.values():
        per = g.pop("per")
        count, approx = None, False
        if per and per > 0:
            raw = g["volume"] / per
            count = int(round(raw))
            approx = abs(raw - count) > 0.05 * max(count, 1) if count else True
        g["count"] = count
        g["approx"] = approx
        g["volume"] = round(g["volume"], 2)
        out.append(g)
    return out


TEMPLATE = r"""
<h3>Batch Packaging</h3>
<p class="section-note">Every batch and how it was packaged. Package counts are worked out from litres packaged &divide; litres per package, so a <strong>~</strong> means the volume didn't divide into a whole number (part-filled packages). Click any header to sort.</p>

<div class="customer-report-controls">
  <div class="filter-group">
    <label>Packaged date</label>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <input type="date" id="pkg-date-begin">
      <span>to</span>
      <input type="date" id="pkg-date-end">
      <button type="button" class="sort-header-btn" data-pkg-preset="30">30d</button>
      <button type="button" class="sort-header-btn" data-pkg-preset="90">90d</button>
      <button type="button" class="sort-header-btn" data-pkg-preset="365">1y</button>
      <button type="button" class="sort-header-btn" data-pkg-preset="0">All</button>
    </div>
  </div>
</div>
<p class="section-note" id="pkg-summary"></p>
<div class="table-wrap"><table class="data-table" id="pkg-table"></table></div>

<script id="pkg-data" type="application/json">%%DATA%%</script>
<script>
(function() {
  var rows = JSON.parse(document.getElementById('pkg-data').textContent);
  var COLS = [
    {key: 'batch_code', label: 'Batch #', type: 'string'},
    {key: 'batch_ref', label: 'Batch Ref', type: 'string'},
    {key: 'date', label: 'Packaged', type: 'string'},
    {key: 'beer', label: 'Beer', type: 'string'},
    {key: 'package', label: 'Package Type', type: 'string'},
    {key: 'count', label: 'Qty', type: 'number'},
    {key: 'volume', label: 'Total Volume (L)', type: 'number'}
  ];
  var sortColumn = 'date', sortAscending = false;
  var elBegin = document.getElementById('pkg-date-begin');
  var elEnd = document.getElementById('pkg-date-end');

  function fmt(n) { return n === null || n === undefined ? '—' : Number(n).toLocaleString(undefined, {maximumFractionDigits: 1}); }
  function iso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }

  function render() {
    var b = elBegin.value, e = elEnd.value;
    var filtered = rows.filter(function(r) { return (!b || r.date >= b) && (!e || r.date <= e); });
    var col = COLS.find(function(c) { return c.key === sortColumn; });
    var sorted = sortGenericRows(filtered, sortColumn, sortAscending, col.type);
    var litres = filtered.reduce(function(s, r) { return s + (r.volume || 0); }, 0);
    var batches = {};
    filtered.forEach(function(r) { batches[r.batch_code] = 1; });
    document.getElementById('pkg-summary').textContent =
      filtered.length + ' rows · ' + Object.keys(batches).length + ' batches · ' + fmt(litres) + ' L packaged';
    var body = sorted.map(function(r) {
      return '<tr><td>' + escapeHtml(r.batch_code || '—') + '</td>' +
        '<td>' + escapeHtml(r.batch_ref || '—') + '</td>' +
        '<td>' + escapeHtml(r.date) + '</td>' +
        '<td>' + escapeHtml(r.beer || '—') + '</td>' +
        '<td>' + escapeHtml(r.package) + '</td>' +
        '<td>' + (r.count === null ? '—' : (r.approx ? '~' : '') + fmt(r.count)) + '</td>' +
        '<td>' + fmt(r.volume) + '</td></tr>';
    }).join('');
    document.getElementById('pkg-table').innerHTML =
      buildSortableHeaderRow(COLS, sortColumn, sortAscending) + '<tbody>' + body + '</tbody>';
  }

  document.getElementById('pkg-table').addEventListener('click', function(ev) {
    var btn = ev.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (sortColumn === key) { sortAscending = !sortAscending; }
    else {
      sortColumn = key;
      sortAscending = COLS.find(function(c) { return c.key === key; }).type !== 'number';
    }
    render();
  });
  document.querySelectorAll('[data-pkg-preset]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var n = parseInt(btn.getAttribute('data-pkg-preset'), 10);
      if (!n) { elBegin.value = ''; elEnd.value = ''; }
      else { var d = new Date(); elEnd.value = iso(d); d.setDate(d.getDate() - n); elBegin.value = iso(d); }
      render();
    });
  });
  elBegin.addEventListener('change', render);
  elEnd.addEventListener('change', render);
  render();
})();
</script>
"""


def build_packaging_section(actions_df, batches_df, container_types_df):
    if actions_df is None:
        return ("<h3>Batch Packaging</h3><p class='missing'>No packaging data cached yet - "
                "run fetch_data.py first.</p>")
    records = build_packaging_records(actions_df, batches_df, container_types_df)
    data = json.dumps(records, allow_nan=False).replace("</", "<\\/")
    return TEMPLATE.replace("%%DATA%%", data)
