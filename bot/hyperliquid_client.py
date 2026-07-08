import time
import logging

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils.error import ClientError

from bot.config import PHANTOM_EVM_PRIVATE_KEY, LEVERAGE, ACTIVE_ASSET, COIN_LIST

logger = logging.getLogger(__name__)


def _retry(fn, max_retries=5, base_delay=2):
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except ClientError as e:
            last_exc = e
            if e.status_code == 429:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Rate limited (attempt {attempt+1}/{max_retries}), retrying in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise
    raise last_exc


class HyperliquidClient:
    def __init__(self):
        if not PHANTOM_EVM_PRIVATE_KEY or PHANTOM_EVM_PRIVATE_KEY == "your_64_char_hex_key":
            logger.warning("No valid PHANTOM_EVM_PRIVATE_KEY — bot will start without Hyperliquid")
            self.wallet = None
            self.info = None
            self.exchange = None
            self.address = "0x0000000000000000000000000000000000000000"
            return
        self.wallet = Account.from_key(PHANTOM_EVM_PRIVATE_KEY)
        self.info = _retry(lambda: Info("https://api.hyperliquid.xyz", skip_ws=True, timeout=20))
        self.exchange = _retry(lambda: Exchange(self.wallet, "https://api.hyperliquid.xyz", timeout=20))
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

    def get_position(self, coin: str = "DOGE") -> dict | None:
        state = self.info.user_state(self.address)
        for pos in state.get("assetPositions", []):
            if pos["position"]["coin"] == coin:
                return pos["position"]
        return None

    def get_doge_position(self) -> dict | None:
        return self.get_position("DOGE")

    def get_all_positions(self) -> dict[str, dict]:
        state = self.info.user_state(self.address)
        result: dict[str, dict] = {}
        for pos in state.get("assetPositions", []):
            p = pos["position"]
            result[p["coin"]] = p
        return result

    def set_leverage(self, coin: str = "DOGE", leverage: int = 3, is_cross: bool = True):
        return self.exchange.update_leverage(leverage=leverage, name=coin, is_cross=is_cross)

    def get_open_orders(self) -> list:
        return self.info.open_orders(self.address)

    def initialize(self, leverage: int | None = None):
        if not self.info or not self.exchange:
            logger.warning("Hyperliquid not connected — skipping initialize")
            return

        def _do_init():
            for c in COIN_LIST:
                try:
                    pos = self.get_position(c)
                    if pos and float(pos["szi"]) != 0:
                        logger.info(f"Existing {c} position detected — skipping leverage change")
                    else:
                        self.set_leverage(c, leverage or LEVERAGE, is_cross=True)
                except Exception:
                    logger.warning(f"Failed to set leverage for {c}")

        _retry(_do_init)
