import logging

logger = logging.getLogger(__name__)


def get_market_context(hl, coin: str = "DOGE") -> dict:
    try:
        l2_data = hl.info.l2_snapshot(coin)
    except Exception as e:
        logger.warning(f"Failed to fetch L2 snapshot: {e}")
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
        result = hl.info.meta_and_asset_ctxs()
        meta, ctxs = result[0], result[1]
        doge_ctx = None
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
