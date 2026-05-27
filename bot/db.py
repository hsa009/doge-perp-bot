import json
import logging
from datetime import datetime, timedelta, timezone
from supabase import create_client
from bot.config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.enabled = bool(SUPABASE_URL and SUPABASE_KEY)
        if self.enabled:
            self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
        else:
            logger.warning("Supabase not configured — DB calls disabled")

    def save_trade(self, trade_data: dict):
        if not self.enabled:
            return
        return self.client.table("trades").insert(trade_data).execute()

    def close_trade(self, trade_id: str, exit_data: dict):
        if not self.enabled:
            return
        exit_data["status"] = "closed"
        exit_data["closed_at"] = datetime.now(timezone.utc).isoformat()
        return (
            self.client.table("trades")
            .update(exit_data)
            .eq("id", trade_id)
            .execute()
        )

    def get_open_trades(self) -> list:
        if not self.enabled:
            return []
        result = (
            self.client.table("trades")
            .select("*")
            .eq("status", "open")
            .execute()
        )
        return result.data

    def save_signal(self, signal_data: dict):
        if not self.enabled:
            return
        return self.client.table("ai_signals").insert(signal_data).execute()

    def log(self, level: str, message: str):
        if not self.enabled:
            return
        return (
            self.client.table("bot_log")
            .insert({"level": level, "message": message})
            .execute()
        )

    def get_todays_pnl(self) -> float:
        if not self.enabled:
            return 0.0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        result = (
            self.client.table("trades")
            .select("net_pnl_usd")
            .eq("status", "closed")
            .gte("closed_at", cutoff)
            .execute()
        )
        total = 0.0
        for row in result.data:
            pnl = row.get("net_pnl_usd")
            if pnl is not None:
                total += float(pnl)
        return total

    def get_trade_stats(self) -> dict:
        if not self.enabled:
            return {"total_pnl": 0.0, "win_rate": 0.0, "total_trades": 0}
        result = (
            self.client.table("trades")
            .select("net_pnl_usd")
            .eq("status", "closed")
            .execute()
        )
        total_pnl = 0.0
        wins = 0
        total = len(result.data)
        for row in result.data:
            pnl = row.get("net_pnl_usd")
            if pnl is not None:
                total_pnl += float(pnl)
                if float(pnl) > 0:
                    wins += 1
        win_rate = wins / total if total > 0 else 0
        return {"total_pnl": total_pnl, "win_rate": win_rate, "total_trades": total}
