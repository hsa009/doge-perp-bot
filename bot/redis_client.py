import json
import logging
import os
import time
import redis

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("CRITICAL: REDIS_URL secret is missing from Hugging Face Space settings!")
        self.client = redis.Redis.from_url(
            redis_url,
            ssl_cert_reqs="none",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        try:
            self.client.ping()
            logger.info("Connected to Valkey/Redis")
        except Exception as e:
            logger.error(f"Valkey/Redis ping failed: {e}")

    def _ok(self):
        return self.client is not None

    def set_bot_running(self, running: bool):
        if not self._ok():
            return
        self.client.set("bot:running", "1" if running else "0")

    def is_bot_running(self) -> bool:
        if not self._ok():
            return False
        try:
            return self.client.get("bot:running") == "1"
        except Exception:
            return False

    def set_current_signal(self, signal: dict, *, preserve_timestamp: bool = False):
        if not self._ok():
            return
        if not preserve_timestamp:
            signal["timestamp"] = time.time()
        self.client.set("signal:current", json.dumps(signal))
        self.client.expire("signal:current", 7200)

    def get_current_signal(self) -> dict | None:
        if not self._ok():
            return None
        try:
            result = self.client.get("signal:current")
            return json.loads(result) if result else None
        except Exception:
            return None

    def clear_current_signal(self):
        if not self._ok():
            return
        self.client.delete("signal:current")

    def set_position(self, position: dict):
        if not self._ok():
            return
        self.client.set("position:current", json.dumps(position))

    def get_position(self) -> dict | None:
        if not self._ok():
            return None
        try:
            result = self.client.get("position:current")
            return json.loads(result) if result else None
        except Exception:
            return None

    def clear_position(self):
        if not self._ok():
            return
        self.client.delete("position:current")

    def set_emergency_stop(self, active: bool):
        if not self._ok():
            return
        self.client.set("bot:emergency_stop", "1" if active else "0")

    def is_emergency_stop(self) -> bool:
        if not self._ok():
            return False
        try:
            return self.client.get("bot:emergency_stop") == "1"
        except Exception:
            return False

    def set_close_position_signal(self):
        if not self._ok():
            return
        self.client.set("bot:close_position", "1")

    def get_close_position_signal(self) -> bool:
        if not self._ok():
            return False
        try:
            return self.client.get("bot:close_position") == "1"
        except Exception:
            return False

    def clear_close_position_signal(self):
        if not self._ok():
            return
        self.client.delete("bot:close_position")

    def get_config(self, key: str, default: str) -> str:
        if not self._ok():
            return default
        try:
            result = self.client.get(f"config:{key}")
            return result if result else default
        except Exception:
            return default

    def set_config(self, key: str, value: str):
        if not self._ok():
            return
        self.client.set(f"config:{key}", value)

    def set_model_details(self, details: list):
        if not self._ok():
            return
        self.client.set("signal:details", json.dumps(details))

    def get_model_details(self) -> list:
        if not self._ok():
            return []
        try:
            result = self.client.get("signal:details")
            return json.loads(result) if result else []
        except Exception:
            return []

    def set_enabled_models(self, keys: list[str]):
        if not self._ok():
            return
        self.client.set("config:enabled_models", ",".join(keys))

    def get_enabled_models(self) -> list[str]:
        if not self._ok():
            return []
        try:
            result = self.client.get("config:enabled_models")
            return [k for k in result.split(",") if k] if result else []
        except Exception:
            return []

    def set_model_defs(self, defs: list[dict]):
        if not self._ok():
            return
        self.client.set("config:model_defs", json.dumps(defs))

    def get_model_defs(self) -> list:
        if not self._ok():
            return []
        try:
            result = self.client.get("config:model_defs")
            return json.loads(result) if result else []
        except Exception:
            return []

    def set_consecutive_waits(self, n: int):
        if not self._ok():
            return
        self.client.set("signal:consecutive_waits", str(n))

    def get_consecutive_waits(self) -> int:
        if not self._ok():
            return 0
        try:
            result = self.client.get("signal:consecutive_waits")
            return int(result) if result else 0
        except Exception:
            return 0

    def set_config_with_ttl(self, key: str, value: str, ttl: int):
        if not self._ok():
            return
        self.client.setex(f"config:{key}", ttl, value)

    def set_cooldown(self, coin: str, ttl: int = 10):
        self.set_config_with_ttl(f"cooldown:{coin}", "1", ttl)

    def get_cooldown(self, coin: str) -> bool:
        if not self._ok():
            return False
        try:
            return self.client.get(f"config:cooldown:{coin}") == "1"
        except Exception:
            return False

    def set_sniper_error(self, msg: str):
        if not self._ok():
            return
        self.client.set("sniper:last_error", msg)

    def get_sniper_error(self) -> str | None:
        if not self._ok():
            return None
        try:
            return self.client.get("sniper:last_error")
        except Exception:
            return None

    def set_enabled_coins(self, coins: list[str]):
        if not self._ok():
            return
        self.client.set("config:enabled_coins", ",".join(coins))

    def get_enabled_coins(self) -> list[str]:
        if not self._ok():
            from bot.config import COIN_LIST
            return list(COIN_LIST)
        try:
            from bot.config import COIN_LIST
            result = self.client.get("config:enabled_coins")
            if result:
                return [c.strip() for c in result.split(",") if c.strip()]
            return list(COIN_LIST)
        except Exception:
            from bot.config import COIN_LIST
            return list(COIN_LIST)

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
