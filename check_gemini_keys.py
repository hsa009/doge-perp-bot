"""Test all Gemini API keys by sending 'hi' and checking for a response."""
import os, json, httpx, time, sys
sys.path.insert(0, os.path.dirname(__file__))

from bot.config import get_coin_gemini_keys, COIN_LIST, REMOVED_COINS

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "models/gemini-2.0-flash-exp"

def test_key(key: str, label: str) -> bool:
    url = f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={key}"
    payload = {"contents": [{"parts": [{"text": "hi"}]}]}
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                print(f"  ✅ {label}: works")
                return True
            else:
                body = resp.json()
                err = body.get("error", {}).get("message", resp.text[:100])
                print(f"  ❌ {label}: HTTP {resp.status_code} — {err}")
                return False
    except Exception as e:
        print(f"  ❌ {label}: exception — {e}")
        return False

def main():
    seen = set()
    all_keys: list[tuple[str, str]] = []

    # 1. Collect from all coins
    for coin in COIN_LIST:
        keys = get_coin_gemini_keys(coin)
        for i, k in enumerate(keys):
            if k and k not in seen:
                seen.add(k)
                all_keys.append((k, f"{coin}#{i}"))
    # 2. Also from removed coins
    for coin in REMOVED_COINS:
        keys = get_coin_gemini_keys(coin)
        for i, k in enumerate(keys):
            if k and k not in seen:
                seen.add(k)
                all_keys.append((k, f"{coin}#{i}"))
    # 3. Global keys
    for i, k in enumerate(os.environ.get("GEMINI_API_KEYS", "").split(",")):
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            all_keys.append((k, f"global#{i}"))
    gk = os.environ.get("GEMINI_API_KEY", "")
    if gk and gk not in seen:
        all_keys.append((gk, "GEMINI_API_KEY"))

    print(f"Found {len(all_keys)} unique Gemini keys. Testing each...\n")
    good = 0
    bad = 0
    for key, label in all_keys:
        time.sleep(2)
        if test_key(key, label):
            good += 1
        else:
            bad += 1
    print(f"\nDone: {good} working, {bad} failed out of {len(all_keys)} keys")

if __name__ == "__main__":
    main()
