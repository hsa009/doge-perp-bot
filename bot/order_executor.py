from decimal import Decimal, ROUND_HALF_UP

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from bot.config import POSITION_SIZE_USD


class OrderExecutor:
    def __init__(self, exchange: Exchange, info: Info, address: str):
        self.exchange = exchange
        self.info = info
        self.address = address

    def _get_sz(self, size_usd: float) -> int:
        price = float(self.info.all_mids()["DOGE"])
        return max(int(size_usd / price) + 1, 1)

    def _fmt_px(self, px: float, is_spot: bool = False) -> float:
        meta = self.info.meta()
        sz_dec = 5
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == "DOGE":
                sz_dec = self.info.asset_to_sz_decimals.get(i, asset.get("szDecimals", 5))
                break
        decimals = (6 if not is_spot else 8) - (sz_dec if isinstance(sz_dec, int) else 5)
        return round(float(f"{px:.5g}"), max(decimals, 0))

    def open_market(self, is_buy: bool, size_usd: float = POSITION_SIZE_USD, slippage: float = 0.005) -> dict:
        sz = self._get_sz(size_usd)
        return self.exchange.market_open(
            name="DOGE",
            is_buy=is_buy,
            sz=sz,
            slippage=slippage,
        )

    def close_position(self, coin: str = "DOGE"):
        return self.exchange.market_close(coin=coin)

    def _slippage_price(self, is_buy: bool, slippage: float) -> float:
        mid = float(self.info.all_mids()["DOGE"])
        px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
        return self._fmt_px(px)

    def set_take_profit(self, is_buy: bool, size_usd: float, trigger_price: float):
        sz = self._get_sz(size_usd)
        px = self._slippage_price(not is_buy, 0)
        return self.exchange.order(
            name="DOGE",
            is_buy=not is_buy,
            sz=float(sz),
            limit_px=px,
            order_type={"trigger": {"triggerPx": self._fmt_px(trigger_price), "isMarket": True, "tpsl": "tp"}},
            reduce_only=True,
        )

    def set_stop_loss(self, is_buy: bool, size_usd: float, trigger_price: float):
        sz = self._get_sz(size_usd)
        px = self._slippage_price(not is_buy, 0)
        return self.exchange.order(
            name="DOGE",
            is_buy=not is_buy,
            sz=float(sz),
            limit_px=px,
            order_type={"trigger": {"triggerPx": self._fmt_px(trigger_price), "isMarket": True, "tpsl": "sl"}},
            reduce_only=True,
        )

    def cancel_all_orders(self, open_orders: list):
        for order in open_orders:
            self.exchange.cancel(name=order["coin"], oid=order["oid"])
