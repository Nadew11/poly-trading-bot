#!/usr/bin/env python3
"""
Interactive Beast Mode monitoring (Streamlit).

Shows open positions (with market titles), paper/live mode, AI spend, and
aggregate metrics from the same paths as beast_mode_dashboard.py.

Run (localhost only — recommended):

    cd /path/to/poly-trading-bot
    streamlit run streamlit_dashboard.py --server.address 127.0.0.1

Optional port:

    streamlit run streamlit_dashboard.py --server.address 127.0.0.1 --server.port 8501

Requires Python 3.11+ and dependencies from requirements.txt. Loads .env via
src.config.settings (same as the trading bot).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import timedelta
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

# Import settings first so python-dotenv loads .env before other src imports.
from src.config.settings import settings  # noqa: F401

from beast_mode_dashboard import BeastModeDashboard


def _position_rows_for_df(positions: List[Any]) -> List[Dict[str, Any]]:
    rows = []
    for p in positions:
        d = asdict(p)
        ts = d.get("timestamp")
        if hasattr(ts, "isoformat"):
            d["timestamp"] = ts.isoformat(sep=" ", timespec="seconds")
        rationale = d.get("rationale") or ""
        if len(rationale) > 120:
            d["rationale"] = rationale[:117] + "..."
        rows.append(d)
    return rows


async def _fetch_snapshot(dashboard: BeastModeDashboard) -> Tuple[Dict[str, Any], List[Any]]:
    await dashboard.db_manager.initialize()
    await dashboard.unified_system.async_initialize()
    performance = await dashboard.get_comprehensive_performance()
    enriched = await dashboard.db_manager.get_open_positions_with_market_titles()
    return performance, enriched


@st.cache_resource(show_spinner=False)
def _get_dashboard() -> BeastModeDashboard:
    return BeastModeDashboard()


def _run_fetch() -> Tuple[Dict[str, Any], List[Any]]:
    dashboard = _get_dashboard()
    return asyncio.run(_fetch_snapshot(dashboard))


def main() -> None:
    st.set_page_config(
        page_title="Beast Mode Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("Beast Mode — live monitor")
    st.caption("Read-only view of SQLite state used by the bot.")

    with st.sidebar:
        st.header("Controls")
        refresh_sec = st.slider("Auto-refresh (seconds)", min_value=5, max_value=60, value=15, step=1)
        if st.button("Refresh now", use_container_width=True):
            st.rerun()

    paper = getattr(settings.trading, "paper_trading_mode", True)
    live_on = getattr(settings.trading, "live_trading_enabled", False)
    mode = "Paper (simulated)" if paper else "LIVE (real funds)"
    st.subheader(f"Trading mode: {mode}")
    if not paper or live_on:
        st.warning("Live trading may be enabled — this UI does not place orders.")

    @st.fragment(run_every=timedelta(seconds=refresh_sec))
    def render_live() -> None:
        try:
            performance, enriched = _run_fetch()
        except Exception as exc:
            st.error(f"Failed to load data: {exc}")
            return

        sys_perf = performance.get("system_performance") or {}
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Open positions", len(enriched))
        col2.metric("Daily AI cost (USD)", f"{float(performance.get('daily_ai_cost') or 0):.2f}")
        col3.metric("Eligible markets (DB)", int(performance.get("available_markets") or 0))
        col4.metric("Total capital (model)", f"{float(sys_perf.get('total_capital') or 0):,.0f}")

        st.divider()
        st.subheader("Open positions (with market title)")
        if enriched:
            df = pd.DataFrame(_position_rows_for_df(enriched))
            preferred = [
                "market_title",
                "market_id",
                "side",
                "entry_price",
                "quantity",
                "confidence",
                "live",
                "strategy",
                "timestamp",
                "market_category",
                "yes_price",
                "no_price",
                "rationale",
                "id",
            ]
            cols = [c for c in preferred if c in df.columns]
            extra = [c for c in df.columns if c not in cols]
            df = df[cols + extra]
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "entry_price": st.column_config.NumberColumn(format="%.4f"),
                    "yes_price": st.column_config.NumberColumn(format="%.4f"),
                    "no_price": st.column_config.NumberColumn(format="%.4f"),
                    "confidence": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        else:
            st.info("No open positions in the database.")

        st.divider()
        st.subheader("Recent activity (from snapshot)")
        rt = performance.get("recent_trades") or {}
        c1, c2, c3 = st.columns(3)
        c1.metric("Trades today", int(rt.get("trades_today", 0)))
        c2.metric("P&L today (USD)", f"{float(rt.get('pnl_today', 0)):+.2f}")
        c3.metric("Win rate (7d)", f"{float(rt.get('win_rate_7d', 0)):.1%}")

        cost = performance.get("cost_analysis") or {}
        with st.expander("Cost analysis"):
            st.json(cost if isinstance(cost, dict) else {"detail": str(cost)})

        mm = sys_perf.get("market_making_performance") or {}
        with st.expander("Market making (unified system)"):
            st.json(mm if isinstance(mm, dict) else {"detail": str(mm)})

    render_live()


if __name__ == "__main__":
    main()
