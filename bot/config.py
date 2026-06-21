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

AI_MODELS = os.environ.get(
    "AI_MODELS",
    "groq:llama-3.3-70b-versatile,groq:llama-3.1-8b-instant",
)
AI_LOOP_INTERVAL = int(os.environ.get("AI_LOOP_INTERVAL", "600"))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_GEMINI_KEYS = [k.strip() for k in os.environ.get("FALLBACK_GEMINI_KEYS", "").split(",") if k.strip()]

ACTIVE_ASSET = os.environ.get("ACTIVE_ASSET", "DOGE")

COIN_LIST = os.environ.get("COIN_LIST", "PEPE,BONK,FLOKI,BOME,WIF,POPCAT,DOGE,SUI,JUP,PYTH,SOL").split(",")


def get_coin_gemini_keys(coin: str) -> list[str]:
    keys = []
    for i in (1, 2, 3):
        val = os.environ.get(f"{coin}_GEMINI_KEY{i}", "")
        if val:
            keys.append(val)
    if not keys:
        keys = list(FALLBACK_GEMINI_KEYS)
    if not keys:
        global_keys = GEMINI_API_KEYS or ([GEMINI_API_KEY] if GEMINI_API_KEY else [])
        keys = [k for k in global_keys if k]
    return keys

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"
