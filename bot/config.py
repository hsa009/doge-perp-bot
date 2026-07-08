import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

PHANTOM_EVM_PRIVATE_KEY = os.environ.get("PHANTOM_EVM_PRIVATE_KEY", "")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# REDIS_URL is read directly from environment by redis_client.py via os.getenv("REDIS_URL")

TRADE_AMOUNT_USD = float(os.environ.get("TRADE_AMOUNT_USD", "10.0"))
POSITION_SIZE_USD = TRADE_AMOUNT_USD
TAKE_PROFIT_USD = float(os.environ.get("TAKE_PROFIT_USD", "3.0"))
STOP_LOSS_USD = float(os.environ.get("STOP_LOSS_USD", "3.0"))
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "0.65"))
LEVERAGE = int(os.environ.get("LEVERAGE", "10"))
MAX_DAILY_LOSS_USD = float(os.environ.get("MAX_DAILY_LOSS_USD", "2.0"))

AI_LOOP_INTERVAL = int(os.environ.get("AI_LOOP_INTERVAL", "600"))
AI_MODELS = ""

ACTIVE_ASSET = os.environ.get("ACTIVE_ASSET", "DOGE")

REMOVED_COINS = ("PEPE", "BONK", "FLOKI", "BOME")

COIN_LIST = os.environ.get("COIN_LIST", "WIF,POPCAT,DOGE,SUI,JUP,PYTH,SOL").split(",")


def get_coin_api_keys(coin: str) -> list[tuple[str, str]]:
    keys = []
    g1 = os.environ.get(f"{coin}_GEMINI_KEY", "")
    if g1:
        keys.append(("gemini", g1))
    g2 = os.environ.get(f"{coin}_GEMINI_BACKUP", "")
    if g2:
        keys.append(("gemini", g2))
    o3 = os.environ.get(f"{coin}_OPENROUTER_BACKUP", "")
    if o3:
        keys.append(("openrouter", o3))
    return keys

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"
