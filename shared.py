"""
Shared helpers, constants, and the client-side filter library used by
every tab module. Nothing in here is tab-specific.
"""
import json
import os

import pandas as pd
import plotly.io as pio

import config

PLOTLY_TEMPLATE = "plotly_white"


def load_csv(name):
    path = os.path.join(config.DATA_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    return df


def has_cols(df, cols):
    return all(c in df.columns for c in cols)


def fig_to_html(fig):
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def table_html(df, cols=None, max_rows=25):
    view = df[cols] if cols and has_cols(df, cols) else df
    return view.head(max_rows).to_html(index=False, classes="data-table", border=0)


def kpi_row(items):
    html = "<div class='kpi-row'>"
    for value, label in items:
        html += f"<div class='kpi'><div class='kpi-value'>{value}</div><div class='kpi-label'>{label}</div></div>"
    html += "</div>"
    return html


def filter_dropdown_html(prefix, label, item_noun="options"):
    """HTML for one searchable, savable multi-select dropdown filter.
    `prefix` must be unique on the page - every element id inside is
    "<prefix>-something", and the matching JS (createSearchableFilter,
    see build_orders_section) wires itself up purely from that prefix,
    so this same template covers every filter on the Orders tab."""
    return f"""
  <div class="filter-group">
    <label>{label}</label>
    <div class="filter-dropdown" id="{prefix}-dropdown">
      <button type="button" class="filter-dropdown-toggle" id="{prefix}-toggle">
        <span id="{prefix}-summary">All</span>
        <span class="filter-dropdown-caret">&#9662;</span>
      </button>
      <div class="filter-dropdown-panel" id="{prefix}-panel" hidden>
        <input type="text" id="{prefix}-search" class="filter-search-input"
               placeholder="Search {item_noun}&hellip;" autocomplete="off">
        <div class="filter-dropdown-actions">
          <button type="button" id="{prefix}-select-all">Select all</button>
          <button type="button" id="{prefix}-select-none">Select none</button>
        </div>
        <div class="filter-row-list" id="{prefix}-list"></div>
        <p id="{prefix}-empty" class="filter-search-empty" hidden>No matches.</p>
        <div class="preset-row">
          <select id="{prefix}-preset-select">
            <option value="">Load a saved filter&hellip;</option>
          </select>
          <button type="button" id="{prefix}-save-preset">Save as new&hellip;</button>
          <button type="button" id="{prefix}-delete-preset">Delete</button>
        </div>
        <span id="{prefix}-preset-status" class="preset-status-msg"></span>
      </div>
    </div>
  </div>
"""


# ---------------------------------------------------------------------
# Shared constants for the "Net sales value per month" chart, now
# rendered client-side (see build_orders_section below) so filters can
# be changed live in the browser without rebuilding this file.
# ---------------------------------------------------------------------
# Order here determines trace order, which in turn determines the
# visual stacking order: Plotly stacks the FIRST trace at the base and
# each later trace on top of it. Invoiced first = bottom of the stack,
# Draft last = top.
STACK_STATUSES = ["Invoiced", "Confirmed", "Draft"]
STACK_COLORS = {"Draft": "#7EC8F0", "Confirmed": "#3F4B8C", "Invoiced": "#4CAF6B"}
# Distinct dashed-line colors for prior years, most recent first. Cycles
# if there's more history than colors.
PRIOR_YEAR_COLORS = ["#B0B0B0", "#C9A0DC", "#E0A458", "#7A9E9F", "#D46A6A", "#9AA6B2"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Colors for the "net sales by beer" chart's stacked bars. Only the top
# N beers by value (within whatever's currently filtered) get their own
# color/segment - everything else is grouped into "Other" (last color)
# so the chart and legend stay readable even with a large catalog.
BEER_TOP_N = 7
BEER_COLORS = ["#4CAF6B", "#3F4B8C", "#7EC8F0", "#E0A458", "#D46A6A", "#7A9E9F", "#C9A0DC", "#9AA6B2"]

# Colors for the "all products sold" histogram (one bar per product, no
# top-N grouping). Breww's API has no per-product display-color field
# (checked - the only "colour" field anywhere in the spec is a numeric
# SRM/EBC brewing measurement, not a UI color), so each product gets a
# color assigned from this palette based on its position in the full,
# alphabetically-sorted product list - stable across filter and date
# range changes, cycling if there are more products than colors.
HISTOGRAM_COLORS = [
    "#4CAF6B", "#3F4B8C", "#7EC8F0", "#E0A458", "#D46A6A",
    "#7A9E9F", "#C9A0DC", "#9AA6B2", "#F2D06B", "#8FBF8F",
    "#B0B0B0", "#5B8DBE",
]


# ---------------------------------------------------------------------
# Shared client-side filter library, loaded once at the top of the page
# (see PAGE_TEMPLATE) so every tab's own script can call
# escapeHtml()/createSearchableFilter() without each tab defining its
# own copy. This is plain JS with no Python string formatting inside
# it, so it uses normal single braces - safe to interpolate as-is into
# PAGE_TEMPLATE's .format() call without any doubling.
# ---------------------------------------------------------------------
SHARED_FILTER_LIB_JS = """
function escapeHtml(s) {
  var div = document.createElement('div');
  div.textContent = s == null ? '' : String(s);
  // textContent->innerHTML escapes &, <, > but NOT quote characters,
  // which is fine for text content but not safe to drop straight into
  // an HTML attribute like value="..." - a product/customer/status
  // name containing a " would otherwise break the attribute and
  // corrupt everything rendered after it on the page. Escaping quotes
  // here too keeps this one function safe to use in both contexts.
  return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ---------------------------------------------------------------------
// Generic searchable, savable multi-select dropdown filter. One
// implementation, shared by every filter on every tab (customer type,
// order status, product, and now inventory item) instead of each tab
// defining its own near-duplicate. Every filter this creates supports
// search, select all/none, and named saved presets (its own separate
// localStorage key, so filters don't collide with each other).
// ---------------------------------------------------------------------
function createSearchableFilter(opts) {
  var prefix = opts.prefix;
  var allValues = opts.allValues;
  var defaultValues = opts.defaultValues;
  var presetsKey = opts.presetsKey;
  var onApply = opts.onApply;

  var wrapper = document.getElementById(prefix + '-dropdown');
  var panel = document.getElementById(prefix + '-panel');
  var toggle = document.getElementById(prefix + '-toggle');
  var summary = document.getElementById(prefix + '-summary');
  var searchInput = document.getElementById(prefix + '-search');
  var listDiv = document.getElementById(prefix + '-list');
  var emptyMsg = document.getElementById(prefix + '-empty');
  var selectAllBtn = document.getElementById(prefix + '-select-all');
  var selectNoneBtn = document.getElementById(prefix + '-select-none');
  var presetSelect = document.getElementById(prefix + '-preset-select');
  var savePresetBtn = document.getElementById(prefix + '-save-preset');
  var deletePresetBtn = document.getElementById(prefix + '-delete-preset');
  var presetStatusMsg = document.getElementById(prefix + '-preset-status');

  var currentValues = defaultValues.slice();

  function updateSummary() {
    var total = allValues.length;
    var checked = currentValues.length;
    if (total === 0) {
      summary.textContent = 'None available';
    } else if (checked === total) {
      summary.textContent = 'All (' + total + ')';
    } else if (checked === 0) {
      summary.textContent = 'None selected';
    } else {
      summary.textContent = checked + ' of ' + total + ' selected';
    }
  }

  function buildList() {
    var sorted = allValues.slice().sort(function(a, b) {
      var aChecked = currentValues.indexOf(a) !== -1;
      var bChecked = currentValues.indexOf(b) !== -1;
      if (aChecked !== bChecked) return aChecked ? -1 : 1;  // checked ones float to the top
      return a.localeCompare(b);
    });
    listDiv.innerHTML = sorted.map(function(v) {
      var checked = currentValues.indexOf(v) !== -1 ? 'checked' : '';
      var safe = escapeHtml(v);
      return '<label class="filter-row" data-search="' + safe.toLowerCase() + '">' +
        '<input type="checkbox" value="' + safe + '" ' + checked + '> ' + safe + '</label>';
    }).join('') || '<span style="font-size:12px;color:#a39a8c;">No options found</span>';
    updateSummary();
    filterRows('');
  }

  function filterRows(query) {
    var q = query.trim().toLowerCase();
    var rows = listDiv.querySelectorAll('.filter-row');
    var anyVisible = false;
    rows.forEach(function(row) {
      var matches = !q || row.getAttribute('data-search').indexOf(q) !== -1;
      row.style.display = matches ? '' : 'none';
      if (matches) anyVisible = true;
    });
    if (emptyMsg) emptyMsg.hidden = anyVisible || rows.length === 0;
  }

  function reorderRows() {
    // Re-floats currently-checked rows to the top based on their
    // CURRENT checked state in the DOM - called when the dropdown
    // opens, not on every click, so rows don't jump around under
    // the cursor while checking/unchecking several in a row.
    var rows = Array.from(listDiv.querySelectorAll('.filter-row'));
    rows.sort(function(a, b) {
      var aChecked = a.querySelector('input').checked;
      var bChecked = b.querySelector('input').checked;
      if (aChecked !== bChecked) return aChecked ? -1 : 1;
      return a.getAttribute('data-search').localeCompare(b.getAttribute('data-search'));
    });
    rows.forEach(function(row) { listDiv.appendChild(row); });
  }

  function readChecked() {
    return Array.from(listDiv.querySelectorAll('input:checked')).map(function(el) { return el.value; });
  }

  function open() {
    panel.hidden = false;
    searchInput.value = '';
    reorderRows();
    filterRows('');
    searchInput.focus();
  }
  function close() { panel.hidden = true; }

  toggle.addEventListener('click', function() {
    if (panel.hidden) { open(); } else { close(); }
  });
  searchInput.addEventListener('input', function() { filterRows(searchInput.value); });
  document.addEventListener('click', function(e) {
    if (!wrapper.contains(e.target)) close();
  });
  wrapper.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { close(); toggle.focus(); }
  });

  selectAllBtn.addEventListener('click', function() {
    // Select all/none always means literally all, regardless of the
    // current search text - not just whatever's visible - to match
    // what the button labels actually say.
    listDiv.querySelectorAll('input').forEach(function(el) { el.checked = true; });
    currentValues = readChecked();
    updateSummary();
    onApply();
  });
  selectNoneBtn.addEventListener('click', function() {
    listDiv.querySelectorAll('input').forEach(function(el) { el.checked = false; });
    currentValues = readChecked();
    updateSummary();
    onApply();
  });

  listDiv.addEventListener('change', function() {
    currentValues = readChecked();
    updateSummary();
    onApply();
  });

  function loadPresets() {
    try {
      var raw = localStorage.getItem(presetsKey);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : {};
    } catch (e) {
      return {};
    }
  }
  function savePresetsObj(presets) {
    try {
      localStorage.setItem(presetsKey, JSON.stringify(presets));
      return true;
    } catch (e) {
      return false;
    }
  }
  function refreshPresetDropdown(selectName) {
    var presets = loadPresets();
    var names = Object.keys(presets).sort(function(a, b) { return a.localeCompare(b); });
    presetSelect.innerHTML = '<option value="">Load a saved filter&hellip;</option>' + names.map(function(name) {
      var safe = escapeHtml(name);
      var sel = (name === selectName) ? 'selected' : '';
      return '<option value="' + safe + '" ' + sel + '>' + safe + '</option>';
    }).join('');
  }

  // Presets can be shared across multiple filter instances on
  // completely different tabs (same presetsKey), each built once at
  // page load in its own separate script block with no direct
  // reference to the others. A save/delete in one instance only
  // updates localStorage - it doesn't automatically refresh any
  // sibling dropdown's already-rendered <option> list. A document-level
  // custom event, tagged with the presetsKey, is how those siblings
  // find out something changed and refresh themselves, since a
  // regular JS variable/function reference can't cross script blocks.
  document.addEventListener('abco-presets-changed', function(e) {
    if (e.detail && e.detail.presetsKey === presetsKey) {
      refreshPresetDropdown(presetSelect.value);
    }
  });
  function broadcastPresetsChanged() {
    document.dispatchEvent(new CustomEvent('abco-presets-changed', {detail: {presetsKey: presetsKey}}));
  }

  presetSelect.addEventListener('change', function(e) {
    e.stopPropagation();
    var name = this.value;
    if (!name) return;  // the placeholder option was selected
    var presets = loadPresets();
    var wanted = Array.isArray(presets[name]) ? presets[name] : [];
    wanted = wanted.filter(function(v) { return allValues.indexOf(v) !== -1; });
    currentValues = wanted;
    buildList();
    onApply();
  });

  savePresetBtn.addEventListener('click', function() {
    var name = window.prompt('Name this saved filter:');
    if (name === null) return;  // cancelled
    name = name.trim();
    if (!name) return;
    var presets = loadPresets();
    if (presets[name] && !window.confirm('A saved filter named "' + name + '" already exists. Overwrite it?')) {
      return;
    }
    presets[name] = currentValues.slice();
    if (savePresetsObj(presets)) {
      refreshPresetDropdown(name);
      broadcastPresetsChanged();
      presetStatusMsg.textContent = 'Saved "' + name + '".';
    } else {
      presetStatusMsg.textContent = 'Could not save: your browser is blocking local storage for this page.';
    }
    setTimeout(function() { presetStatusMsg.textContent = ''; }, 4000);
  });

  deletePresetBtn.addEventListener('click', function() {
    var name = presetSelect.value;
    if (!name) {
      presetStatusMsg.textContent = 'Select a saved filter first, then Delete.';
      setTimeout(function() { presetStatusMsg.textContent = ''; }, 4000);
      return;
    }
    if (!window.confirm('Delete saved filter "' + name + '"?')) return;
    var presets = loadPresets();
    delete presets[name];
    savePresetsObj(presets);
    refreshPresetDropdown('');
    broadcastPresetsChanged();
    presetStatusMsg.textContent = 'Deleted "' + name + '".';
    setTimeout(function() { presetStatusMsg.textContent = ''; }, 4000);
  });

  buildList();
  refreshPresetDropdown('');

  return {
    getSelected: function() { return currentValues.slice(); },
    reset: function() {
      currentValues = defaultValues.slice();
      buildList();
    }
  };
}
"""


# ---------------------------------------------------------------------
# Orders (Invoice schema: number, issue_date, order_status, payment_status,
# total, value, customer.name, sales_person.full_name)
#
# This section is interactive: the filter panel (date range, customer
# type, order status) and every chart/table below it are driven by a
# JSON blob of order records embedded in the page and a block of
# plain JavaScript at the end of this section. Nothing here needs a
# server or a rebuild - changing a filter just re-filters that JSON in
# the browser and re-draws the Plotly charts in place.
# ---------------------------------------------------------------------
def json_safe(value):
    """Convert a single cell value to something json.dumps can emit as
    valid JSON. pandas/numpy null markers (NaN, NaT, pd.NA) don't
    become Python None just by being "falsy" - json.dumps happily
    serializes a bare float('nan') as the bare token NaN, which is NOT
    valid JSON and makes a browser's JSON.parse throw immediately."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _safe_float(v, default=0.0):
    try:
        if v is None:
            return default
        f = float(v)
        return default if pd.isna(f) else f
    except (TypeError, ValueError):
        return default


def _parse_bool(v, default=False):
    """Robustly interpret a value that should be a boolean but might
    arrive as a native bool, a stringified 'True'/'False' (common after
    a CSV round trip), or NaN."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return bool(v)
    except (TypeError, ValueError):
        return default


def _parse_json_list(raw):
    """Parse a value that should be a list, handling the case where
    fetch_data.py's flatten() JSON-stringified it to survive the CSV
    round trip."""
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


