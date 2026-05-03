"""
Clients package — exchange + LLM connectors.

Public helpers:
    PolymarketClient, GammaClient — async clients (see modules)
    build_polymarket_clients()    — context-managed factory that wires
                                    PolymarketClient and GammaClient together
                                    so that token-id resolution works without
                                    extra plumbing in every call site.

Usage:
    from src.clients import build_polymarket_clients
    async with build_polymarket_clients() as (client, gamma):
        bal = await client.get_balance()
        markets = await gamma.get_markets(min_volume=500)
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Tuple

from .polymarket_client import (  # noqa: F401
    PolymarketClient,
    PolymarketAPIError,
    PolymarketAuthError,
    InsufficientFundsError,
    RateLimitError,
    UnknownMarketError,
    AllowanceError,
)
from .gamma_client import (  # noqa: F401
    GammaClient,
    GammaAPIError,
    to_legacy_market_shape,
)


@asynccontextmanager
async def build_polymarket_clients(
    *,
    private_key: Optional[str] = None,
    funder: Optional[str] = None,
    host: Optional[str] = None,
    chain_id: Optional[int] = None,
    signature_type: Optional[int] = None,
    polygon_rpc_url: Optional[str] = None,
    gamma_host: Optional[str] = None,
) -> AsyncIterator[Tuple[PolymarketClient, GammaClient]]:
    """Yield a `(PolymarketClient, GammaClient)` pair, wired together so that
    `client._resolve_token_id` falls back to gamma lookups when a market has
    not been pre-registered. Closes both on exit.

    All keyword args are optional — defaults read from environment.
    """
    gamma = GammaClient(host=gamma_host)
    client = PolymarketClient(
        private_key=private_key,
        funder=funder,
        host=host,
        chain_id=chain_id,
        signature_type=signature_type,
        polygon_rpc_url=polygon_rpc_url,
        gamma_client=gamma,
    )
    try:
        yield client, gamma
    finally:
        await client.close()
        await gamma.close()
