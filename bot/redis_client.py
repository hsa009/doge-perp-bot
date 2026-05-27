import json
import time
import httpx
from bot.config import UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN


class RedisClient:
    def __init__(self):
        url = UPSTASH_REDIS_URL
        if url.startswith("rediss://") or url.startswith("redis://"):
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or 6379
            pw = parsed.password or ""
            rest_url = f"https://{host}"
            token = pw
        else:
            rest_url = url
            token = UPSTASH_REDIS_TOKEN

        self.rest_url = rest_url.rstrip("/")
        self.token = token or UPSTASH_REDIS_TOKEN
        self.http = httpx.Client(timeout=10.0)

    def _request(self, method: str, *args):
        payload = json.dumps([method, *args])
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = self.http.post(f"{self.rest_url}", content=payload, headers=headers)
        data = resp.json()
        if data.get("error"):
            raise Exception(f"Upstash error: {data['error']}")
        return data.get("result")

    def set_bot_running(self, running: bool):
        self._request("SET", "bot:running", "1" if running else "0")

    def is_bot_running(self) -> bool:
        result = self._request("GET", "bot:running")
        return result == "1"

    def set_current_signal(self, signal: dict, *, preserve_timestamp: bool = False):
        if not preserve_timestamp:
            signal["timestamp"] = time.time()
        self._request("SET", "signal:current", json.dumps(signal))
        self._request("EXPIRE", "signal:current", 7200)

    def get_current_signal(self) -> dict | None:
        result = self._request("GET", "signal:current")
        if result:
            return json.loads(result)
        return None

    def set_position(self, position: dict):
        self._request("SET", "position:current", json.dumps(position))

    def get_position(self) -> dict | None:
        result = self._request("GET", "position:current")
        if result:
            return json.loads(result)
        return None

    def clear_position(self):
        self._request("DEL", "position:current")

    def set_emergency_stop(self, active: bool):
        self._request("SET", "bot:emergency_stop", "1" if active else "0")

    def is_emergency_stop(self) -> bool:
        result = self._request("GET", "bot:emergency_stop")
        return result == "1"

    def set_close_position_signal(self):
        self._request("SET", "bot:close_position", "1")

    def get_close_position_signal(self) -> bool:
        return self._request("GET", "bot:close_position") == "1"

    def clear_close_position_signal(self):
        self._request("DEL", "bot:close_position")

    def get_config(self, key: str, default: str) -> str:
        result = self._request("GET", f"config:{key}")
        if result is not None:
            return result
        return default

    def set_config(self, key: str, value: str):
        self._request("SET", f"config:{key}", value)

    def set_model_details(self, details: list):
        self._request("SET", "signal:details", json.dumps(details))

    def get_model_details(self) -> list:
        result = self._request("GET", "signal:details")
        if result:
            return json.loads(result)
        return []

    def set_enabled_models(self, keys: list[str]):
        self._request("SET", "config:enabled_models", ",".join(keys))

    def get_enabled_models(self) -> list[str]:
        result = self._request("GET", "config:enabled_models")
        if result:
            return [k for k in result.split(",") if k]
        return []

    def set_model_defs(self, defs: list[dict]):
        self._request("SET", "config:model_defs", json.dumps(defs))

    def get_model_defs(self) -> list:
        result = self._request("GET", "config:model_defs")
        if result:
            return json.loads(result)
        return []

    def set_consecutive_waits(self, n: int):
        self._request("SET", "signal:consecutive_waits", str(n))

    def get_consecutive_waits(self) -> int:
        result = self._request("GET", "signal:consecutive_waits")
        return int(result) if result else 0

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
