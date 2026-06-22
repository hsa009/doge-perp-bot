import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


def get_market_context(hl, coin: str = "DOGE",
                       l2_data: dict | None = None,
                       asset_ctx: dict | None = None) -> dict:
    if l2_data is None:
        try:
            l2_data = hl.info.l2_snapshot(coin)
        except Exception as e:
            logger.warning(f"Failed to fetch L2 snapshot for {coin}: {e}")
            l2_data = None

    bids = []
    asks = []
    if l2_data and "levels" in l2_data:
        for level in l2_data["levels"][0][:5]:
            bids.append([float(level["px"]), float(level["sz"])])
        for level in l2_data["levels"][1][:5]:
            asks.append([float(level["px"]), float(level["sz"])])

    bid_volume = sum(sz for _, sz in bids)
    ask_volume = sum(sz for _, sz in asks)
    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    spread = best_ask - best_bid if best_bid and best_ask else 0.0
    spread_pct = (spread / best_bid * 100) if best_bid else 0.0

    try:
        result = hl.info.meta_and_asset_ctxs() if asset_ctx is None else ([], [asset_ctx])
        meta, ctxs = result[0], result[1]
        doge_ctx = None
        if asset_ctx is not None:
            doge_ctx = asset_ctx
        else:
            for i, asset in enumerate(meta["universe"]):
                if asset["name"] == coin:
                    doge_ctx = ctxs[i]
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch meta/ctxs: {e}")
        doge_ctx = None

    funding_rate = 0.0
    open_interest = 0.0
    if doge_ctx:
        funding_rate = float(doge_ctx.get("funding", "0.0"))
        open_interest = float(doge_ctx.get("openInterest", "0.0"))

    annualized_funding = funding_rate * 24 * 365 * 100

    if funding_rate > 0.0001:
        funding_signal = "bullish (shorts paying)"
    elif funding_rate < -0.0001:
        funding_signal = "bearish (longs paying)"
    else:
        funding_signal = "neutral"

    if not bids and not asks and funding_rate == 0.0 and open_interest == 0.0:
        logger.warning("All market context data unavailable")

    return {
        "current_price": best_bid,
        "funding_rate": funding_rate,
        "funding_annualized_pct": round(annualized_funding, 2),
        "funding_signal": funding_signal,
        "open_interest": open_interest,
        "order_book": {
            "bids": bids,
            "asks": asks,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "spread": spread,
            "spread_pct": round(spread_pct, 4),
        },
        "recent_closes": [],
    }


async def _fetch_l2(client: httpx.AsyncClient, coin: str) -> dict | None:
    try:
        resp = await client.post(HYPERLIQUID_INFO_URL, json={"type": "l2Book", "coin": coin})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch L2 for {coin}: {e}")
        return None


async def _fetch_all_market_data(coins: list[str]) -> dict[str, dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        meta_ctxs_resp, mids_resp = await asyncio.gather(
            client.post(HYPERLIQUID_INFO_URL, json={"type": "metaAndAssetCtxs"}),
            client.post(HYPERLIQUID_INFO_URL, json={"type": "allMids"}),
        )
        meta_ctxs = meta_ctxs_resp.json()
        mids = mids_resp.json()

        meta, ctxs = meta_ctxs[0], meta_ctxs[1]

        coin_ctx_map: dict[str, dict] = {}
        exchange_names: dict[str, str] = {}
        for i, asset in enumerate(meta["universe"]):
            name = asset["name"]
            coin_ctx_map[name] = ctxs[i] if i < len(ctxs) else {}
            exchange_names[name] = name
            if name.startswith("k") and len(name) > 1:
                exchange_names[name[1:]] = name

        l2_tasks: dict[str, asyncio.Task] = {}
        for coin in coins:
            ex_name = exchange_names.get(coin, coin)
            l2_tasks[coin] = asyncio.ensure_future(_fetch_l2(client, ex_name))

        l2_results = await asyncio.gather(*l2_tasks.values())

        results: dict[str, dict] = {}
        for coin in coins:
            ex_name = exchange_names.get(coin, coin)
            l2_data = l2_results[coins.index(coin)]
            ctx = coin_ctx_map.get(ex_name, {})

            bids, asks = [], []
            if l2_data and "levels" in l2_data:
                for level in l2_data["levels"][0][:5]:
                    bids.append([float(level["px"]), float(level["sz"])])
                for level in l2_data["levels"][1][:5]:
                    asks.append([float(level["px"]), float(level["sz"])])

            bid_volume = sum(sz for _, sz in bids)
            ask_volume = sum(sz for _, sz in asks)
            best_bid = bids[0][0] if bids else 0.0
            best_ask = asks[0][0] if asks else 0.0
            spread = best_ask - best_bid if best_bid and best_ask else 0.0
            spread_pct = (spread / best_bid * 100) if best_bid else 0.0

            funding_rate = float(ctx.get("funding", "0.0"))
            open_interest = float(ctx.get("openInterest", "0.0"))
            annualized_funding = funding_rate * 24 * 365 * 100

            if funding_rate > 0.0001:
                funding_signal = "bullish (shorts paying)"
            elif funding_rate < -0.0001:
                funding_signal = "bearish (longs paying)"
            else:
                funding_signal = "neutral"

            current_price = float(mids.get(ex_name, best_bid or 0.0))

            results[coin] = {
                "current_price": current_price,
                "funding_rate": funding_rate,
                "funding_annualized_pct": round(annualized_funding, 2),
                "funding_signal": funding_signal,
                "open_interest": open_interest,
                "order_book": {
                    "bids": bids,
                    "asks": asks,
                    "bid_volume": bid_volume,
                    "ask_volume": ask_volume,
                    "spread": spread,
                    "spread_pct": round(spread_pct, 4),
                },
                "recent_closes": [],
            }
        return results


def fetch_all_market_data(coins: list[str]) -> dict[str, dict]:
    return asyncio.run(_fetch_all_market_data(coins))
