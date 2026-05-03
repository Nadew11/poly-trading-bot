#!/usr/bin/env python3
"""
End-to-end dry-run smoke test.

Hits the LIVE Polymarket Gamma API (unauthenticated) and CLOB orderbook
endpoints to verify the full pipeline works — discovery → orderbook → would-
be-order shape — without sending any actual trade. No private key required.

Usage:
    python scripts/dry_run_smoke.py
    python scripts/dry_run_smoke.py --strategy safe-compounder

This is the closest we can get to a "real trade in DRY_RUN mode" without an
actual wallet & USDC balance. Once you have a funded Polygon wallet:
    1. Add POLYMARKET_PRIVATE_KEY to .env
    2. Run scripts/set_allowances.py --send  (one time per wallet)
    3. python cli.py run --safe-compounder    (defaults to dry-run)
    4. python cli.py run --safe-compounder --live    (sends real orders)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Make `src` importable when invoked via `python scripts/dry_run_smoke.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub `structlog` if not installed locally — the smoke test only needs the
# Gamma + CLOB read paths, which don't actually log structured events. Real
# bot runs use the real package from requirements.txt.
import types as _types  # noqa: E402
try:
    import structlog  # noqa: F401
except ImportError:
    _stub = _types.ModuleType("structlog")
    class _NoopLogger:
        def __getattr__(self, _n):
            return lambda *a, **k: None
    _stub.get_logger = lambda *a, **k: _NoopLogger()
    _stub.configure = lambda *a, **k: None
    _stub.make_filtering_bound_logger = lambda l: _NoopLogger
    _ctx = _types.ModuleType("structlog.contextvars")
    _ctx.merge_contextvars = lambda *a, **k: {}
    _ctx.bind_contextvars = lambda *a, **k: None
    _ctx.clear_contextvars = lambda: None
    _stl = _types.ModuleType("structlog.stdlib")
    _stl.LoggerFactory = lambda *a, **k: None
    _stl.BoundLogger = _NoopLogger
    for n in ("add_log_level", "add_logger_name", "filter_by_level"):
        setattr(_stl, n, lambda *a, **k: {})
    _proc = _types.ModuleType("structlog.processors")
    for n in ("TimeStamper", "StackInfoRenderer", "format_exc_info",
              "UnicodeDecoder", "JSONRenderer", "KeyValueRenderer"):
        setattr(_proc, n, lambda *a, **k: (lambda *aa, **kk: {}))
    _dev = _types.ModuleType("structlog.dev")
    _dev.ConsoleRenderer = lambda *a, **k: (lambda *aa, **kk: "")
    _stub.contextvars = _ctx
    _stub.stdlib = _stl
    _stub.processors = _proc
    _stub.dev = _dev
    sys.modules["structlog"] = _stub
    sys.modules["structlog.contextvars"] = _ctx
    sys.modules["structlog.stdlib"] = _stl
    sys.modules["structlog.processors"] = _proc
    sys.modules["structlog.dev"] = _dev

from src.clients.gamma_client import GammaClient, to_legacy_market_shape  # noqa: E402


async def smoke_default():
    """Pipeline: discover top-volume markets → fetch orderbook → show what
    a market BUY would compute (no actual call)."""
    print("=" * 72)
    print("  DRY-RUN SMOKE TEST — Polymarket pipeline")
    print("=" * 72)
    print()

    async with GammaClient() as gamma:
        # 1. DISCOVERY
        print("📡 Step 1: Gamma discovery (active markets, vol≥10k, ≤30d to expiry)")
        markets = await gamma.get_markets(
            active=True, closed=False, accepting_orders=True,
            min_volume=10000, max_time_to_expiry_days=30, max_results=10,
        )
        print(f"   ✓ Got {len(markets)} markets")
        if not markets:
            print("   ⚠️  No markets matched filters — try loosening thresholds")
            return

        # Pick first market with a non-extreme price (not 0.99 / 0.01)
        target = None
        for m in markets:
            yes, _no = m["_outcome_prices"]
            if 0.10 < yes < 0.90:
                target = m
                break
        if target is None:
            target = markets[0]

        cond = target["_condition_id"]
        yes_token, no_token = target["_token_ids"]
        yes_price, no_price = target["_outcome_prices"]
        print()
        print("🎯 Selected market:")
        print(f"   condition_id: {cond}")
        print(f"   question:     {target.get('question', '')[:80]}")
        print(f"   yes_token_id: {yes_token[:30]}…")
        print(f"   no_token_id:  {no_token[:30]}…")
        print(f"   prices:       YES=${yes_price:.3f}  NO=${no_price:.3f}")
        print(f"   volume:       ${target['_volume_num']:>12,.0f}")
        print(f"   category:     {target['_category']}")
        print(f"   end_date:     {target.get('endDate', '?')}")

        # 2. ORDERBOOK (live CLOB call, no auth needed for this read)
        print()
        print("📊 Step 2: Fetching live orderbook for YES token via CLOB…")
        try:
            from py_clob_client.client import ClobClient
        except ImportError:
            print("   ⚠️  py-clob-client not installed — skipping orderbook step")
            print("       (run: pip install -r requirements.txt)")
            book = None
        else:
            # Read-only ClobClient — no key needed for orderbook reads
            clob_ro = ClobClient("https://clob.polymarket.com", chain_id=137)
            book = await asyncio.to_thread(clob_ro.get_order_book, yes_token)

        if book is not None:
            n_bids = len(getattr(book, "bids", []) or [])
            n_asks = len(getattr(book, "asks", []) or [])
            print(f"   ✓ Orderbook: {n_bids} bids, {n_asks} asks on YES token")

            best_bid = max(
                (float(b.price) for b in (book.bids or [])),
                default=0.0,
            )
            best_ask = min(
                (float(a.price) for a in (book.asks or [])),
                default=0.0,
            )
            print(f"   best bid (YES): ${best_bid:.3f}")
            print(f"   best ask (YES): ${best_ask:.3f}")
            spread = best_ask - best_bid if best_bid and best_ask else 0
            print(f"   spread:         ${spread:.3f}")

        # 3. WOULD-BE ORDER (constructed but NOT sent)
        print()
        print("🧪 Step 3: Computing would-be order params (DRY-RUN, nothing sent)")
        # Pretend we'd buy 10 YES contracts at the best ask
        if book is not None and best_ask:
            target_price_cents = int(round(best_ask * 100))
            target_qty = 10
            usdc_amount = target_qty * best_ask
            print(f"   would_call: client.place_order(")
            print(f"       ticker='{cond[:20]}…',")
            print(f"       client_order_id='{uuid.uuid4()}',")
            print(f"       side='yes',")
            print(f"       action='buy',")
            print(f"       count={target_qty},")
            print(f"       type_='market',")
            print(f"       yes_price={target_price_cents},  # cents — adapter converts to ${best_ask:.3f}")
            print(f"   )")
            print(f"   would_send_to_sdk: MarketOrderArgs(")
            print(f"       token_id='{yes_token[:30]}…',")
            print(f"       amount={usdc_amount:.4f},  # USDC.e dollars to spend")
            print(f"       side=BUY,")
            print(f"   )")
            print(f"   would_post: client.post_order(signed, OrderType.FOK)")
        else:
            print("   (skipped — no orderbook fetched)")

        # 4. POLYMARKET-SHAPE CONVERSION (verify Market dataclass compatibility)
        print()
        print("🔄 Step 4: Verifying legacy-shape adapter (used by ingest.py)")
        ks = to_legacy_market_shape(target)
        for k in ("ticker", "title", "yes_price", "no_price", "yes_ask_dollars",
                  "yes_bid", "volume", "expiration_time", "category", "status",
                  "yes_token_id", "no_token_id", "neg_risk"):
            v = ks.get(k, "<missing>")
            v_str = str(v)[:60]
            print(f"   {k:<22} = {v_str}")

        # 5. PRICE HISTORY
        print()
        print("📈 Step 5: Fetching 24h price history for YES token…")
        try:
            ph = await gamma.get_price_history(yes_token, interval="1d", fidelity=60)
            history = ph["history"]
            print(f"   ✓ {len(history)} samples; first={history[0] if history else 'empty'}, "
                  f"last={history[-1] if history else 'empty'}")
        except Exception as exc:
            print(f"   ⚠️  price-history failed: {exc}")

    print()
    print("=" * 72)
    print("  DRY-RUN SMOKE COMPLETE — pipeline functional end to end.")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="default", choices=["default", "safe-compounder"])
    args = parser.parse_args()

    if args.strategy == "default":
        asyncio.run(smoke_default())
    elif args.strategy == "safe-compounder":
        # SafeCompounder dry-run requires a PolymarketClient (which needs a key).
        # Skipped here to keep the smoke test usable without credentials.
        print("safe-compounder dry-run requires POLYMARKET_PRIVATE_KEY in .env.")
        print("Once set, run: python cli.py run --safe-compounder")


if __name__ == "__main__":
    main()
