"""Production batches tab."""
import pandas as pd
import plotly.express as px

import config
from shared import PLOTLY_TEMPLATE, kpi_row, fig_to_html, table_html

def build_batches_section(df):
    if df is None:
        return "<h2>Production batches</h2><p class='missing'>No cached data yet - run fetch_data.py first.</p>"

    parts = ["<h2>Production batches</h2>"]
    d = df.copy()
    if "datetime_started" in d.columns:
        d["datetime_started"] = pd.to_datetime(d["datetime_started"], errors="coerce", utc=True)
    vol_col = "total_volume.litre" if "total_volume.litre" in d.columns else None
    if vol_col:
        d[vol_col] = pd.to_numeric(d[vol_col], errors="coerce")
    if "status" in d.columns:
        d["status_label"] = d["status"].map(config.BATCH_STATUS_LABELS).fillna("Unknown")
    if "brew_type" in d.columns:
        d["brew_type_label"] = d["brew_type"].map(config.BREW_TYPE_LABELS).fillna("Unknown")

    kpis = [(f"{len(d):,}", "Batches (all-time)")]
    if vol_col:
        kpis.append((f"{d[vol_col].sum():,.0f} L", "Total volume brewed (all-time)"))
    if "abv" in d.columns:
        avg_abv = pd.to_numeric(d["abv"], errors="coerce").mean()
        if pd.notna(avg_abv):
            kpis.append((f"{avg_abv:.1f}%", "Average ABV"))
    parts.append(kpi_row(kpis))

    if "datetime_started" in d.columns and vol_col:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=config.TREND_DAYS)
        trend = d.dropna(subset=["datetime_started"])
        trend = trend[trend["datetime_started"] >= cutoff]
        if not trend.empty:
            parts.append("<h3>Batch Volume</h3>")
            parts.append(f"<p class='section-note'>Total litres brewed per batch, over the last {config.TREND_DAYS} days.</p>")
            fig = px.bar(trend.sort_values("datetime_started"), x="datetime_started", y=vol_col,
                         template=PLOTLY_TEMPLATE, title=f"Batch volume, last {config.TREND_DAYS} days",
                         hover_data=["drink.name"] if "drink.name" in trend.columns else None)
            fig.update_layout(yaxis_title="Volume (litres)", xaxis_title="")
            parts.append(fig_to_html(fig))

    if "status_label" in d.columns:
        parts.append("<h3>Batches by Status</h3>")
        parts.append("<p class='section-note'>How your all-time batch count breaks down across Planned, In-progress, and Complete.</p>")
        counts = d["status_label"].value_counts().reset_index()
        counts.columns = ["status", "count"]
        fig = px.pie(counts, names="status", values="count", template=PLOTLY_TEMPLATE,
                     title="Batches by status")
        parts.append(fig_to_html(fig))

    if "drink.name" in d.columns:
        parts.append("<h3>Most-Brewed Beers</h3>")
        parts.append("<p class='section-note'>Your top 10 beers by all-time batch count.</p>")
        counts = d["drink.name"].value_counts().head(10).reset_index()
        counts.columns = ["beer", "count"]
        fig = px.bar(counts, x="count", y="beer", orientation="h", template=PLOTLY_TEMPLATE,
                     title="Most-brewed beers (top 10 by batch count)")
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, xaxis_title="Batches", yaxis_title="")
        parts.append(fig_to_html(fig))

    parts.append("<h3>Recent Batches</h3>")
    parts.append("<p class='section-note'>Your most recent batches, all-time.</p>")
    display_cols = [c for c in ["batch_code", "drink.name", "status_label", "datetime_started",
                                 vol_col, "abv", "brew_type_label"] if c and c in d.columns]
    parts.append(table_html(
        d.sort_values("datetime_started", ascending=False) if "datetime_started" in d.columns else d,
        cols=display_cols or None))
    return "\n".join(parts)


# ---------------------------------------------------------------------
# Stock received (StockReceived schema: stock_item.name, current_quantity,
# price_per_quantity, location.name, batch_code, expiry_date)
# This endpoint has no received-date field, so it's shown as a current
# on-hand snapshot rather than a trend.
# ---------------------------------------------------------------------
