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

    def _fmt_px(self, px: float) -> float:
        coin = "DOGE"
        asset = self.info.coin_to_asset[coin]
        sz_dec = self.info.asset_to_sz_decimals[asset]
        decimals = 6 - sz_dec
        return round(float(f"{px:.5g}"), decimals)

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

    def _trigger_order(self, is_buy: bool, sz: float, trigger_px: float, tpsl: str):
        limit_px = self.exchange._slippage_price("DOGE", is_buy, 0)
        return self.exchange.order(
            name="DOGE",
            is_buy=is_buy,
            sz=float(sz),
            limit_px=limit_px,
            order_type={"trigger": {"triggerPx": self.exchange._slippage_price("DOGE", is_buy, 0, trigger_px), "isMarket": True, "tpsl": tpsl}},
            reduce_only=True,
        )

    def set_take_profit(self, is_buy: bool, size_usd: float, trigger_price: float):
        sz = self._get_sz(size_usd)
        return self._trigger_order(not is_buy, sz, trigger_price, "tp")

    def set_stop_loss(self, is_buy: bool, size_usd: float, trigger_price: float):
        sz = self._get_sz(size_usd)
        return self._trigger_order(not is_buy, sz, trigger_price, "sl")

    def cancel_all_orders(self, open_orders: list):
        for order in open_orders:
            self.exchange.cancel(name=order["coin"], oid=order["oid"])
