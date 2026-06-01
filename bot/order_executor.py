import logging
from decimal import Decimal, ROUND_HALF_UP

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from bot.config import POSITION_SIZE_USD

logger = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, exchange: Exchange, info: Info, address: str):
        self.exchange = exchange
        self.info = info
        self.address = address
        self._sz_decimals_cache: dict[str, int] = {}

    def _get_sz_decimals(self, coin: str) -> int:
        cached = self._sz_decimals_cache.get(coin)
        if cached is not None:
            return cached
        meta = self.info.meta()
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == coin:
                sz_dec = asset.get("szDecimals")
                if sz_dec is None:
                    raise Exception(f"szDecimals not found for {coin}")
                self._sz_decimals_cache[coin] = sz_dec
                return sz_dec
        raise Exception(f"Coin {coin} not found in universe")

    def _get_sz(self, coin: str, notional: float) -> int | float:
        price = float(self.info.all_mids()[coin])
        sz = notional / price
        decimals = self._get_sz_decimals(coin)
        if decimals == 0:
            result = max(int(sz), 1)
        else:
            result = round(sz, decimals)
        logger.info(f"_get_sz: coin={coin}, target_notional=${notional:.2f}, price=${price:.5f}, sz_decimals={decimals}, sz={result}")
        return result

    def _fmt_px(self, px: float, coin: str = "DOGE", is_spot: bool = False) -> float:
        sz_dec = self._get_sz_decimals(coin)
        decimals = (6 if not is_spot else 8) - sz_dec
        return round(float(f"{px:.5g}"), max(decimals, 0))

    def open_market(self, coin: str, is_buy: bool, notional: float, slippage: float = 0.005) -> dict:
        mid_price = float(self.info.all_mids()[coin])
        sz = self._get_sz(coin, notional)
        actual_notional = sz * mid_price
        logger.info(f"open_market: coin={coin}, dir={'BUY' if is_buy else 'SELL'}, sz={sz}, mid_price=${mid_price:.5f}, estimated_notional=${actual_notional:.2f}, slippage={slippage}")
        if actual_notional < 1.0:
            raise Exception(f"Notional ${actual_notional:.2f} below $1 minimum")
        return self.exchange.market_open(
            name=coin,
            is_buy=is_buy,
            sz=sz,
            slippage=slippage,
        )

    def close_position(self, coin: str = "DOGE"):
        return self.exchange.market_close(coin=coin)

    def _slippage_price(self, coin: str, is_buy: bool, slippage: float) -> float:
        mid = float(self.info.all_mids()[coin])
        px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
        return self._fmt_px(px, coin)

    def set_take_profit(self, coin: str, is_buy: bool, notional: float, trigger_price: float):
        sz = self._get_sz(coin, notional)
        px = self._slippage_price(coin, not is_buy, 0)
        return self.exchange.order(
            name=coin,
            is_buy=not is_buy,
            sz=float(sz),
            limit_px=px,
            order_type={"trigger": {"triggerPx": self._fmt_px(trigger_price, coin), "isMarket": True, "tpsl": "tp"}},
            reduce_only=True,
        )

    def set_stop_loss(self, coin: str, is_buy: bool, notional: float, trigger_price: float):
        sz = self._get_sz(coin, notional)
        px = self._slippage_price(coin, not is_buy, 0)
        return self.exchange.order(
            name=coin,
            is_buy=not is_buy,
            sz=float(sz),
            limit_px=px,
            order_type={"trigger": {"triggerPx": self._fmt_px(trigger_price, coin), "isMarket": True, "tpsl": "sl"}},
            reduce_only=True,
        )

    def cancel_all_orders(self, open_orders: list):
        for order in open_orders:
            self.exchange.cancel(name=order["coin"], oid=order["oid"])
