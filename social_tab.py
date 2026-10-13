"""Social tab: Facebook Page and Instagram performance over time, from
Meta's Graph API (see meta_client.py / fetch_data.fetch_meta_data).

Four cached CSVs feed it (any can be missing - the tab shows whatever it
has):
  social_fb_daily.csv      one row per day of Facebook Page metrics
  social_ig_daily.csv      one row per day of Instagram account metrics
  social_ig_followers.csv  one follower-count snapshot per refresh
  social_ig_posts.csv      one row per Instagram post, with its numbers

The page template below is a plain string (not an f-string) with
%%TOKEN%% placeholders swapped in afterward - the JavaScript is long
enough that doubling every brace for an f-string was a bug magnet."""
import json
from datetime import date, timedelta

import pandas as pd

from shared import json_safe


def _num(v):
    """Cell -> int/float, or None for blank/NaN (never NaN, which isn't
    valid JSON)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else f


def _daily_records(df, columns):
    if df is None or df.empty or "date" not in df.columns:
        return []
    out = []
    for _, row in df.sort_values("date").iterrows():
        rec = {"date": str(row["date"])[:10]}
        for c in columns:
            rec[c] = _num(row.get(c)) if c in df.columns else None
        out.append(rec)
    return out


def build_follower_series(followers_df, ig_daily_df):
    """Instagram only ever reports TODAY's follower count, so history is
    built two ways: real daily snapshots saved by every refresh, plus
    - for days before the first snapshot - an estimate worked backwards
    from Instagram's daily net-new-followers numbers (available for
    roughly the last 30 days). Real snapshots always win over estimates.
    Returns [{date, followers, estimated}] sorted by date."""
    snaps = {}
    if followers_df is not None and not followers_df.empty and "date" in followers_df.columns:
        for _, row in followers_df.iterrows():
            v = _num(row.get("followers_count"))
            if v is not None:
                snaps[str(row["date"])[:10]] = v
    if not snaps:
        return []

    gains = {}
    if ig_daily_df is not None and not ig_daily_df.empty and "follower_gain" in ig_daily_df.columns:
        for _, row in ig_daily_df.iterrows():
            g = _num(row.get("follower_gain"))
            if g is not None:
                gains[str(row["date"])[:10]] = g

    series = {d: {"date": d, "followers": v, "estimated": False} for d, v in snaps.items()}
    # A snapshot is saved early each morning, so it is a close stand-in
    # for the END of the previous day; work backwards from there using
    # each day's net new followers (end of day D-1 = end of day D minus
    # D's gain). Stops at the first day Instagram gave no gain for.
    earliest = min(snaps)
    d = date.fromisoformat(earliest) - timedelta(days=1)
    value = snaps[earliest]
    while True:
        key = d.isoformat()
        if key in series:
            value = series[key]["followers"]
        else:
            series[key] = {"date": key, "followers": value, "estimated": True}
        gain = gains.get(key)
        if gain is None:
            break
        value -= gain
        d -= timedelta(days=1)
    return [series[k] for k in sorted(series)]


def _post_type(product_type, media_type):
    pt = (product_type or "").upper()
    mt = (media_type or "").upper()
    if pt == "REELS":
        return "Reel"
    if pt == "STORY":
        return "Story"
    if mt == "CAROUSEL_ALBUM":
        return "Carousel"
    if mt == "VIDEO":
        return "Video"
    if mt == "IMAGE":
        return "Photo"
    return (media_type or "Post").title()


def _post_records(posts_df):
    if posts_df is None or posts_df.empty:
        return []
    ts = pd.to_datetime(posts_df.get("timestamp"), errors="coerce", utc=True)
    out = []
    for i, (_, row) in enumerate(posts_df.iterrows()):
        t = ts.iloc[i]
        if pd.isna(t):
            continue
        out.append({
            "date": t.tz_convert("America/New_York").strftime("%Y-%m-%d"),
            "type": _post_type(row.get("product_type"), row.get("media_type")),
            "caption": json_safe(row.get("caption")) if isinstance(row.get("caption"), str) else "",
            "permalink": json_safe(row.get("permalink")) if isinstance(row.get("permalink"), str) else "",
            "reach": _num(row.get("reach")),
            "views": _num(row.get("views")),
            "likes": _num(row.get("like_count")),
            "comments": _num(row.get("comments_count")),
            "shares": _num(row.get("shares")),
            "saves": _num(row.get("saved")),
            "interactions": _num(row.get("total_interactions")),
        })
    return out


SOCIAL_TEMPLATE = r"""
<h2>Social</h2>
<p class="section-note">Facebook Page and Instagram performance from Meta's own reporting. <strong>Data through %%LATEST%%.</strong> Meta finalizes the most recent day or two after the fact, so the newest bars can creep up slightly on the next refresh. Facebook history goes back about a year; Instagram's daily account numbers only reach back about 30 days from the first refresh, so Instagram charts build up over time from there. The post table is Instagram only.</p>

<div class="customer-report-controls" id="social-controls">
  <div class="filter-group">
    <label>Date range</label>
    <div style="display:flex; gap:8px; align-items:center;">
      <input type="date" id="social-date-begin">
      <span>to</span>
      <input type="date" id="social-date-end">
    </div>
  </div>
  <div class="filter-group">
    <label>Platforms</label>
    <div style="display:flex; gap:16px; align-items:center; font-size:13px;">
      <label><input type="checkbox" id="social-plat-fb" checked> Facebook</label>
      <label><input type="checkbox" id="social-plat-ig" checked> Instagram</label>
    </div>
  </div>
</div>

<div id="social-kpi-row"></div>

<h4>Followers Over Time</h4>
<p class="section-note" id="social-followers-note"></p>
<div id="social-followers-chart" class="chart-div"></div>

<h4>Daily Views &amp; Reach</h4>
<p class="section-note">Views count every time content was shown (including repeats to the same person). Reach counts each person once per day. Facebook "reach" here is unique viewers.</p>
<div class="unit-toggle" id="social-metric-toggle" style="display:inline-flex; margin-bottom:8px;">
  <button type="button" data-metric="views" class="active">Views</button>
  <button type="button" data-metric="reach">Reach</button>
</div>
<div id="social-views-chart" class="chart-div"></div>

<h4>Daily Engagement</h4>
<p class="section-note">Instagram likes, comments, shares and saves across all content, plus Facebook post engagements (reactions, comments, shares and clicks on posts).</p>
<div id="social-engagement-chart" class="chart-div"></div>

<h4>Instagram Posts</h4>
<p class="section-note" id="social-posts-note">Posts published in the selected date range. Numbers are lifetime totals so far for each post. Click any column header to sort; click a caption to open the post.</p>
<div class="table-wrap">
  <table class="data-table" id="social-posts-table"></table>
</div>

<script id="social-fb-data" type="application/json">%%FB_JSON%%</script>
<script id="social-ig-data" type="application/json">%%IG_JSON%%</script>
<script id="social-ig-followers-data" type="application/json">%%FOLLOWERS_JSON%%</script>
<script id="social-posts-data" type="application/json">%%POSTS_JSON%%</script>
<script>
(function() {
  var fb = JSON.parse(document.getElementById('social-fb-data').textContent);
  var ig = JSON.parse(document.getElementById('social-ig-data').textContent);
  var igFollowers = JSON.parse(document.getElementById('social-ig-followers-data').textContent);
  var posts = JSON.parse(document.getElementById('social-posts-data').textContent);

  var FB_COLOR = '#3F4B8C', IG_COLOR = '#D4627F';
  var hasFb = fb.length > 0;
  var hasIg = ig.length > 0 || igFollowers.length > 0 || posts.length > 0;

  var fbBox = document.getElementById('social-plat-fb');
  var igBox = document.getElementById('social-plat-ig');
  fbBox.checked = hasFb; fbBox.disabled = !hasFb;
  igBox.checked = hasIg; igBox.disabled = !hasIg;

  var allDates = [];
  fb.forEach(function(r) { allDates.push(r.date); });
  ig.forEach(function(r) { allDates.push(r.date); });
  igFollowers.forEach(function(r) { allDates.push(r.date); });
  allDates.sort();
  var latest = allDates.length ? allDates[allDates.length - 1] : new Date().toISOString().slice(0, 10);
  var begin = document.getElementById('social-date-begin');
  var end = document.getElementById('social-date-end');
  end.value = latest;
  begin.value = new Date(new Date(latest + 'T00:00:00Z').getTime() - 27 * 86400000).toISOString().slice(0, 10);

  var metricMode = 'views';

  function inRange(d) { return d && (!begin.value || d >= begin.value) && (!end.value || d <= end.value); }
  function fmt(n) { return n === null || n === undefined ? '—' : Number(n).toLocaleString(undefined, {maximumFractionDigits: 0}); }
  function sumOf(rows, key) { return rows.reduce(function(s, r) { return s + (r[key] || 0); }, 0); }
  function signed(n) { return (n > 0 ? '+' : '') + Number(n).toLocaleString(); }
  function dayRange() {
    var days = [];
    if (!begin.value || !end.value) return days;
    var d = new Date(begin.value + 'T00:00:00Z'), stop = new Date(end.value + 'T00:00:00Z');
    while (d <= stop && days.length < 800) { days.push(d.toISOString().slice(0, 10)); d = new Date(d.getTime() + 86400000); }
    return days;
  }
  function byDate(rows) { var m = {}; rows.forEach(function(r) { m[r.date] = r; }); return m; }
  function seriesFor(map, days, key) { return days.map(function(d) { return map[d] && map[d][key] !== undefined ? map[d][key] : null; }); }

  function followersKpi(label, points, color) {
    if (!points.length) return '';
    var last = points[points.length - 1].v;
    var delta = points.length > 1 ? last - points[0].v : null;
    var sub = delta === null ? '' : ' <span style="font-size:13px;font-weight:600;color:' + (delta >= 0 ? '#2e8b57' : '#b23a48') + ';">' + signed(delta) + '</span>';
    return '<div class="kpi"><div class="kpi-value" style="color:' + color + ';">' + fmt(last) + sub + '</div><div class="kpi-label">' + label + '</div></div>';
  }

  function render() {
    var showFb = fbBox.checked && hasFb, showIg = igBox.checked && hasIg;
    var days = dayRange();
    var fbRows = fb.filter(function(r) { return inRange(r.date); });
    var igRows = ig.filter(function(r) { return inRange(r.date); });
    var fbMap = byDate(fbRows), igMap = byDate(igRows);

    // --- KPIs ---
    var kpis = '';
    if (showFb) {
      var pts = fbRows.filter(function(r) { return r.page_follows !== null; }).map(function(r) { return {v: r.page_follows}; });
      kpis += followersKpi('Facebook followers (change in range)', pts, FB_COLOR);
    }
    if (showIg) {
      var ipts = igFollowers.filter(function(r) { return inRange(r.date); }).map(function(r) { return {v: r.followers}; });
      kpis += followersKpi('Instagram followers (change in range)', ipts, IG_COLOR);
    }
    var views = (showFb ? sumOf(fbRows, 'views') : 0) + (showIg ? sumOf(igRows, 'views') : 0);
    var engage = (showFb ? sumOf(fbRows, 'engagements') : 0) + (showIg ? sumOf(igRows, 'total_interactions') : 0);
    kpis += '<div class="kpi"><div class="kpi-value">' + fmt(views) + '</div><div class="kpi-label">Views in range</div></div>';
    kpis += '<div class="kpi"><div class="kpi-value">' + fmt(engage) + '</div><div class="kpi-label">Engagements in range</div></div>';
    document.getElementById('social-kpi-row').innerHTML = '<div class="kpi-row">' + kpis + '</div>';

    // --- Followers chart (two axes: the two audiences are different sizes) ---
    var fTraces = [];
    if (showFb) {
      var fbPts = fbRows.filter(function(r) { return r.page_follows !== null; });
      fTraces.push({x: fbPts.map(function(r) { return r.date; }), y: fbPts.map(function(r) { return r.page_follows; }),
        type: 'scatter', mode: 'lines+markers', name: 'Facebook', line: {color: FB_COLOR}, marker: {size: 4}});
    }
    if (showIg) {
      var igPts = igFollowers.filter(function(r) { return inRange(r.date); });
      var est = igPts.filter(function(r) { return r.estimated; });
      var real = igPts.filter(function(r) { return !r.estimated; });
      if (est.length) {
        var bridge = est.concat(real.slice(0, 1));
        fTraces.push({x: bridge.map(function(r) { return r.date; }), y: bridge.map(function(r) { return r.followers; }),
          type: 'scatter', mode: 'lines', name: 'Instagram (estimated)', yaxis: 'y2', line: {color: IG_COLOR, dash: 'dot'}});
      }
      fTraces.push({x: real.map(function(r) { return r.date; }), y: real.map(function(r) { return r.followers; }),
        type: 'scatter', mode: 'lines+markers', name: 'Instagram', yaxis: 'y2', line: {color: IG_COLOR}, marker: {size: 4}});
    }
    var layout1 = {margin: {t: 20, r: 60, l: 60}, hovermode: 'x unified', legend: {orientation: 'h', y: -0.15},
      yaxis: {title: {text: showFb ? 'Facebook followers' : '', font: {color: FB_COLOR}}, tickfont: {color: FB_COLOR}},
      yaxis2: {title: {text: showIg ? 'Instagram followers' : '', font: {color: IG_COLOR}}, overlaying: 'y', side: 'right', tickfont: {color: IG_COLOR}}};
    Plotly.react('social-followers-chart', fTraces, layout1, {responsive: true});
    document.getElementById('social-followers-note').textContent = showIg
      ? 'Facebook reports a full follower history. Instagram only reports today’s count, so its line is built from a snapshot saved at every refresh; the dotted part (if shown) is estimated backwards from Instagram’s daily follower gains.'
      : '';

    // --- Views / reach chart ---
    var vTraces = [];
    if (showFb) vTraces.push({x: days, y: seriesFor(fbMap, days, metricMode === 'views' ? 'views' : 'unique_viewers'),
      type: 'bar', name: 'Facebook', marker: {color: FB_COLOR}});
    if (showIg) vTraces.push({x: days, y: seriesFor(igMap, days, metricMode === 'views' ? 'views' : 'reach'),
      type: 'bar', name: 'Instagram', marker: {color: IG_COLOR}});
    Plotly.react('social-views-chart', vTraces, {barmode: 'group', margin: {t: 20}, hovermode: 'x unified',
      legend: {orientation: 'h', y: -0.15}, yaxis: {title: metricMode === 'views' ? 'Views per day' : 'People reached per day'}}, {responsive: true});

    // --- Engagement chart ---
    var eTraces = [];
    if (showIg) {
      [['likes', 'Instagram likes', '#D4627F'], ['comments', 'Instagram comments', '#E8A3B5'],
       ['shares', 'Instagram shares', '#9B3D5A'], ['saves', 'Instagram saves', '#F2C6D1']].forEach(function(s) {
        eTraces.push({x: days, y: seriesFor(igMap, days, s[0]), type: 'bar', name: s[1], marker: {color: s[2]}});
      });
    }
    if (showFb) eTraces.push({x: days, y: seriesFor(fbMap, days, 'engagements'), type: 'bar', name: 'Facebook post engagements', marker: {color: FB_COLOR}});
    Plotly.react('social-engagement-chart', eTraces, {barmode: 'stack', margin: {t: 20}, hovermode: 'x unified',
      legend: {orientation: 'h', y: -0.15}, yaxis: {title: 'Engagements per day'}}, {responsive: true});

    renderPosts(showIg);
  }

  // --- Posts table ---
  var POST_COLUMNS = [
    {key: 'date', label: 'Date', type: 'string'},
    {key: 'type', label: 'Type', type: 'string'},
    {key: 'caption', label: 'Post', type: 'string'},
    {key: 'reach', label: 'Reach', type: 'number'},
    {key: 'views', label: 'Views', type: 'number'},
    {key: 'likes', label: 'Likes', type: 'number'},
    {key: 'comments', label: 'Comments', type: 'number'},
    {key: 'shares', label: 'Shares', type: 'number'},
    {key: 'saves', label: 'Saves', type: 'number'},
    {key: 'interactions', label: 'Interactions', type: 'number'}
  ];
  var postSortColumn = 'views', postSortAscending = false;

  function renderPosts(showIg) {
    var table = document.getElementById('social-posts-table');
    var note = document.getElementById('social-posts-note');
    if (!showIg) { table.innerHTML = ''; note.textContent = 'Select Instagram above to see its posts.'; return; }
    note.textContent = 'Posts published in the selected date range. Numbers are lifetime totals so far for each post. Click any column header to sort; click a caption to open the post.';
    var rows = posts.filter(function(p) { return inRange(p.date); });
    var colDef = POST_COLUMNS.find(function(c) { return c.key === postSortColumn; }) || POST_COLUMNS[4];
    var sorted = sortGenericRows(rows, postSortColumn, postSortAscending, colDef.type);
    var body = sorted.map(function(p) {
      var cap = escapeHtml(p.caption || '(no caption)');
      var link = p.permalink ? '<a href="' + escapeHtml(p.permalink) + '" target="_blank" rel="noopener noreferrer">' + cap + '</a>' : cap;
      return '<tr><td>' + escapeHtml(p.date) + '</td><td>' + escapeHtml(p.type) + '</td><td style="max-width:360px;">' + link + '</td>' +
        '<td>' + fmt(p.reach) + '</td><td>' + fmt(p.views) + '</td><td>' + fmt(p.likes) + '</td><td>' + fmt(p.comments) + '</td>' +
        '<td>' + fmt(p.shares) + '</td><td>' + fmt(p.saves) + '</td><td>' + fmt(p.interactions) + '</td></tr>';
    }).join('');
    table.innerHTML = buildSortableHeaderRow(POST_COLUMNS, postSortColumn, postSortAscending) +
      '<tbody>' + (body || '<tr><td colspan="10" style="color:#a39a8c;font-style:italic;">No posts in this date range.</td></tr>') + '</tbody>';
  }

  document.getElementById('social-posts-table').addEventListener('click', function(e) {
    var btn = e.target.closest('[data-sort-key]');
    if (!btn) return;
    var key = btn.getAttribute('data-sort-key');
    if (postSortColumn === key) { postSortAscending = !postSortAscending; }
    else {
      postSortColumn = key;
      var def = POST_COLUMNS.find(function(c) { return c.key === key; });
      postSortAscending = def.type !== 'number';
    }
    render();
  });

  document.getElementById('social-metric-toggle').addEventListener('click', function(e) {
    var btn = e.target.closest('[data-metric]');
    if (!btn) return;
    metricMode = btn.getAttribute('data-metric');
    this.querySelectorAll('button').forEach(function(b) { b.classList.toggle('active', b === btn); });
    render();
  });
  [begin, end, fbBox, igBox].forEach(function(el) { el.addEventListener('change', render); });

  render();
})();
</script>
"""


def build_social_section(fb_df, ig_df, followers_df, posts_df):
    if all(d is None for d in (fb_df, ig_df, followers_df, posts_df)):
        return (
            "<h2>Social</h2>"
            "<p class='missing'>No cached Facebook or Instagram data yet - if you "
            "haven't set this up, create a Meta Page token (see the README's Social "
            "section) and set META_PAGE_TOKEN in your .env, then run fetch_data.py. "
            "If you already have, check that fetch_data.py ran successfully and had "
            "the token available when it ran.</p>"
        )

    fb = _daily_records(fb_df, ["page_follows", "follows", "unfollows", "views",
                                "unique_viewers", "page_visits", "engagements"])
    ig = _daily_records(ig_df, ["reach", "views", "profile_views", "accounts_engaged",
                                "total_interactions", "likes", "comments", "shares",
                                "saves", "replies", "website_clicks"])
    followers = build_follower_series(followers_df, ig_df)
    posts = _post_records(posts_df)

    dates = [r["date"] for r in fb + ig + followers]
    latest = max(dates) if dates else "n/a"

    html = SOCIAL_TEMPLATE
    html = html.replace("%%LATEST%%", latest)
    html = html.replace("%%FB_JSON%%", json.dumps(fb, allow_nan=False))
    html = html.replace("%%IG_JSON%%", json.dumps(ig, allow_nan=False))
    html = html.replace("%%FOLLOWERS_JSON%%", json.dumps(followers, allow_nan=False))
    html = html.replace("%%POSTS_JSON%%", json.dumps(posts, allow_nan=False).replace("</", "<\\/"))
    return html
