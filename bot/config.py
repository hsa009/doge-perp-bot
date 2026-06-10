import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

PHANTOM_EVM_PRIVATE_KEY = os.environ.get("PHANTOM_EVM_PRIVATE_KEY", "")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

VALKEY_HOST = os.environ.get("VALKEY_HOST", "")
VALKEY_PORT = int(os.environ.get("VALKEY_PORT", "16955"))
VALKEY_PASSWORD = os.environ.get("VALKEY_PASSWORD", "")

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

ACTIVE_ASSET = os.environ.get("ACTIVE_ASSET", "DOGE")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"
