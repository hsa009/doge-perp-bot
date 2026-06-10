import json
import logging
import time
import redis
from bot.config import VALKEY_HOST, VALKEY_PORT, VALKEY_PASSWORD

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self):
        self.client = redis.Redis(
            host=VALKEY_HOST,
            port=VALKEY_PORT,
            password=VALKEY_PASSWORD,
            ssl=True,
            decode_responses=True,
        )

    def set_bot_running(self, running: bool):
        self.client.set("bot:running", "1" if running else "0")

    def is_bot_running(self) -> bool:
        try:
            return self.client.get("bot:running") == "1"
        except Exception:
            return False

    def set_current_signal(self, signal: dict, *, preserve_timestamp: bool = False):
        if not preserve_timestamp:
            signal["timestamp"] = time.time()
        self.client.set("signal:current", json.dumps(signal))
        self.client.expire("signal:current", 7200)

    def get_current_signal(self) -> dict | None:
        try:
            result = self.client.get("signal:current")
            return json.loads(result) if result else None
        except Exception:
            return None

    def clear_current_signal(self):
        self.client.delete("signal:current")

    def set_position(self, position: dict):
        self.client.set("position:current", json.dumps(position))

    def get_position(self) -> dict | None:
        try:
            result = self.client.get("position:current")
            return json.loads(result) if result else None
        except Exception:
            return None

    def clear_position(self):
        self.client.delete("position:current")

    def set_emergency_stop(self, active: bool):
        self.client.set("bot:emergency_stop", "1" if active else "0")

    def is_emergency_stop(self) -> bool:
        try:
            return self.client.get("bot:emergency_stop") == "1"
        except Exception:
            return False

    def set_close_position_signal(self):
        self.client.set("bot:close_position", "1")

    def get_close_position_signal(self) -> bool:
        try:
            return self.client.get("bot:close_position") == "1"
        except Exception:
            return False

    def clear_close_position_signal(self):
        self.client.delete("bot:close_position")

    def get_config(self, key: str, default: str) -> str:
        try:
            result = self.client.get(f"config:{key}")
            return result if result else default
        except Exception:
            return default

    def set_config(self, key: str, value: str):
        self.client.set(f"config:{key}", value)

    def set_model_details(self, details: list):
        self.client.set("signal:details", json.dumps(details))

    def get_model_details(self) -> list:
        try:
            result = self.client.get("signal:details")
            return json.loads(result) if result else []
        except Exception:
            return []

    def set_enabled_models(self, keys: list[str]):
        self.client.set("config:enabled_models", ",".join(keys))

    def get_enabled_models(self) -> list[str]:
        try:
            result = self.client.get("config:enabled_models")
            return [k for k in result.split(",") if k] if result else []
        except Exception:
            return []

    def set_model_defs(self, defs: list[dict]):
        self.client.set("config:model_defs", json.dumps(defs))

    def get_model_defs(self) -> list:
        try:
            result = self.client.get("config:model_defs")
            return json.loads(result) if result else []
        except Exception:
            return []

    def set_consecutive_waits(self, n: int):
        self.client.set("signal:consecutive_waits", str(n))

    def get_consecutive_waits(self) -> int:
        try:
            result = self.client.get("signal:consecutive_waits")
            return int(result) if result else 0
        except Exception:
            return 0

    def set_config_with_ttl(self, key: str, value: str, ttl: int):
        self.client.setex(f"config:{key}", ttl, value)

    def set_cooldown(self, coin: str, ttl: int = 10):
        self.set_config_with_ttl(f"cooldown:{coin}", "1", ttl)

    def get_cooldown(self, coin: str) -> bool:
        try:
            return self.client.get(f"config:cooldown:{coin}") == "1"
        except Exception:
            return False

    def set_sniper_error(self, msg: str):
        self.client.set("sniper:last_error", msg)

    def get_sniper_error(self) -> str | None:
        try:
            return self.client.get("sniper:last_error")
        except Exception:
            return None

    def get_all_config(self) -> dict:
        keys = ["tp_usd", "sl_usd", "trade_amount", "leverage", "min_confidence", "max_daily_loss", "max_daily_loss_enabled"]
        config = {}
        for k in keys:
            config[k] = self.get_config(k, "")
        try:
            config["enabled_models"] = self.get_enabled_models()
        except Exception:
            config["enabled_models"] = []
        return config
