from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange

from bot.config import PHANTOM_EVM_PRIVATE_KEY, LEVERAGE


class HyperliquidClient:
    def __init__(self):
        if not PHANTOM_EVM_PRIVATE_KEY or PHANTOM_EVM_PRIVATE_KEY == "your_64_char_hex_key":
            logger = __import__("logging").getLogger(__name__)
            logger.warning("No valid PHANTOM_EVM_PRIVATE_KEY — bot will start without Hyperliquid")
            self.wallet = None
            self.info = None
            self.exchange = None
            self.address = "0x0000000000000000000000000000000000000000"
            return
        self.wallet = Account.from_key(PHANTOM_EVM_PRIVATE_KEY)
        self.info = Info("https://api.hyperliquid.xyz", skip_ws=True)
        self.exchange = Exchange(self.wallet, "https://api.hyperliquid.xyz")
        self.address = self.wallet.address

    def get_balance(self) -> dict:
        spot = self.get_spot_balance()
        state = self.info.user_state(self.address)
        summary = state["marginSummary"]
        return {
            "account_value": float(summary["accountValue"]) + spot,
            "perp_value": float(summary["accountValue"]),
            "spot_usdc": spot,
            "total_ntl_pos": float(summary["totalNtlPos"]),
            "withdrawable": float(state["withdrawable"]),
        }

    def get_spot_balance(self) -> float:
        import httpx
        resp = httpx.post("https://api.hyperliquid.xyz/info", json={
            "type": "spotClearinghouseState",
            "user": self.address,
        }, timeout=10)
        data = resp.json()
        for b in data.get("balances", []):
            if b["coin"] == "USDC":
                return float(b["total"])
        return 0.0

    def get_current_price(self, coin: str = "DOGE") -> float:
        mids = self.info.all_mids()
        return float(mids[coin])

    def get_doge_position(self) -> dict | None:
        state = self.info.user_state(self.address)
        for pos in state.get("assetPositions", []):
            if pos["position"]["coin"] == "DOGE":
                return pos["position"]
        return None

    def set_leverage(self, coin: str = "DOGE", leverage: int = 3, is_cross: bool = True):
        return self.exchange.update_leverage(leverage=leverage, name=coin, is_cross=is_cross)

    def get_open_orders(self) -> list:
        return self.info.open_orders(self.address)

    def initialize(self, leverage: int | None = None):
        if not self.info or not self.exchange:
            logger = __import__("logging").getLogger(__name__)
            logger.warning("Hyperliquid not connected — skipping initialize")
            return
        pos = self.get_doge_position()
        if pos and float(pos["szi"]) != 0:
            logger = __import__("logging").getLogger(__name__)
            logger.info(f"Existing position detected — skipping leverage change")
        else:
            self.set_leverage("DOGE", leverage or LEVERAGE, is_cross=True)
