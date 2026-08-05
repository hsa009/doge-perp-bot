import math

import numpy as np
import pandas as pd


def _f(value, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def compute_market_structure_summary(df: pd.DataFrame) -> dict:
    """Translate the last 32 15m candles into categorical price-action facts.

    Designed to replace raw floating-point candle arrays in the AI prompt with
    a compact, human-readable structural summary the model can reason over
    directly. All divisions are NaN/zero-guarded; short frames degrade to the
    largest safe window instead of raising.
    """
    n = min(32, 0 if df is None else len(df))
    if n == 0:
        return {"valid": False, "price_action_summary": "", "reason": "no_data"}

    closes = df["close"]
    highs = df["high"]
    lows = df["low"]
    opens = df["open"]

    win_high = highs.tail(n)
    win_low = lows.tail(n)

    high_32 = _f(win_high.max())
    low_32 = _f(win_low.min())
    close = _f(closes.iloc[-1])
    open_c = _f(opens.iloc[-1])

    # --- 1. Range position & structure state ---
    rng = high_32 - low_32
    if rng <= 0:
        range_pos_pct = 50.0
    else:
        range_pos_pct = min(100.0, max(0.0, (close - low_32) / rng * 100.0))

    near_high = high_32 > 0 and close >= high_32 * (1 - 0.003)
    near_low = low_32 > 0 and close <= low_32 * (1 + 0.003)

    if near_high:
        structure_state = "Near Local Resistance"
    elif near_low:
        structure_state = "Near Local Support"
    elif 30 <= range_pos_pct <= 70:
        structure_state = "Mid-Range Consolidation"
    elif range_pos_pct > 85:
        structure_state = "Upper Range / Pullback Risk"
    elif range_pos_pct < 15:
        structure_state = "Lower Range / Bounce Zone"
    else:
        structure_state = "Mid-Range Consolidation"

    # --- 2. Candle anatomy & exhaustion (last 3 candles) ---
    last3 = slice(len(closes) - 3, len(closes))
    bodies: list[float] = []
    upper_ratios: list[float] = []
    lower_ratios: list[float] = []
    heights: list[float] = []
    wicks_upper: list[float] = []
    for i in range(last3.start, last3.stop):
        o = _f(opens.iloc[i])
        h = _f(highs.iloc[i])
        lo = _f(lows.iloc[i])
        c = _f(closes.iloc[i])
        height = max(h - lo, 0.0)
        body = abs(c - o)
        upper_wick = max(h - max(o, c), 0.0) if h >= 0 else 0.0
        lower_wick = max(min(o, c) - lo, 0.0) if lo >= 0 else 0.0
        heights.append(height)
        bodies.append(body)
        wicks_upper.append(upper_wick)
        upper_ratios.append(upper_wick / height if height > 0 else 0.0)
        lower_ratios.append(lower_wick / height if height > 0 else 0.0)

    avg_upper_wick_ratio = sum(upper_ratios) / len(upper_ratios) if upper_ratios else 0.0
    avg_lower_wick_ratio = sum(lower_ratios) / len(lower_ratios) if lower_ratios else 0.0
    body_shrinking = len(bodies) >= 2 and bodies[-1] <= bodies[-2]

    last_body = bodies[-1] if bodies else 0.0
    last_height = heights[-1] if heights else 0.0
    last_upper_wick = wicks_upper[-1] if wicks_upper else 0.0
    lower_wick_last = (min(open_c, close) - _f(lows.iloc[-1])) if _f(lows.iloc[-1]) >= 0 else 0.0
    last_green = close >= open_c

    if last_height > 0 and last_body >= 0.65 * last_height and avg_upper_wick_ratio < 0.20:
        exhaustion_state = "Strong Trend Continuation"
    elif last_height > 0 and last_body > 0 and last_upper_wick > 2 * last_body and (near_high or range_pos_pct > 85):
        exhaustion_state = "Bearish Rejection"
    elif last_height > 0 and last_body > 0 and lower_wick_last > 2 * last_body and (near_low or range_pos_pct < 15):
        exhaustion_state = "Bullish Rejection"
    elif avg_upper_wick_ratio > 0.50 and (last_green or near_high):
        exhaustion_state = "Buying Exhaustion"
    elif avg_lower_wick_ratio > 0.50 and near_low:
        exhaustion_state = "Selling Exhaustion"
    else:
        exhaustion_state = "Neutral / Indecision"

    # --- 3. ROC / velocity ---
    def _roc(back: int) -> float:
        if len(closes) <= back:
            return 0.0
        prev = _f(closes.iloc[-1 - back])
        if prev == 0:
            return 0.0
        return (_f(closes.iloc[-1]) / prev - 1.0) * 100.0

    roc_1 = _roc(1)
    roc_3 = _roc(3)
    roc_12 = _roc(12)

    if abs(roc_12) > 1.5 and abs(roc_3) < 0.1:
        velocity_state = "Decelerating"
    elif abs(roc_3) / 3.0 > abs(roc_12) / 12.0:
        velocity_state = "Accelerating"
    elif abs(roc_1) < 0.1 and abs(roc_3) < 0.1 and abs(roc_12) < 0.5:
        velocity_state = "Neutral / Stagnant"
    else:
        velocity_state = "Steady / In Progress"

    # --- 4. Extension risk vs EMAs ---
    ema9 = _f(ema(closes, 9).iloc[-1])
    ema21 = _f(ema(closes, 21).iloc[-1])
    dist_ema9_pct = ((close - ema9) / ema9 * 100.0) if ema9 else 0.0
    dist_ema21_pct = ((close - ema21) / ema21 * 100.0) if ema21 else 0.0

    if dist_ema21_pct > 1.8:
        extension_state = "Overextended Bullish"
    elif dist_ema21_pct < -1.8:
        extension_state = "Overextended Bearish"
    elif abs(dist_ema21_pct) <= 0.5:
        extension_state = "Anchored"
    else:
        extension_state = "Mildly Extended"

    # --- 5. Format ---
    price_action_summary = (
        f"Location: Price is at {range_pos_pct:.1f}% of 32-candle range "
        f"(Resistance: ${high_32:.5f} / Support: ${low_32:.5f})\n"
        f"Structure State: {structure_state}\n"
        f"Velocity: 15m: {roc_1:+.2f}%, 45m: {roc_3:+.2f}%, 3h: {roc_12:+.2f}% ({velocity_state})\n"
        f"Candle Anatomy: {exhaustion_state}\n"
        f"Extension Risk: {extension_state} (Distance to EMA21: {dist_ema21_pct:+.2f}%)"
    )

    return {
        "valid": True,
        "range_pos_pct": range_pos_pct,
        "high_32": high_32,
        "low_32": low_32,
        "structure_state": structure_state,
        "exhaustion_state": exhaustion_state,
        "body_shrinking": body_shrinking,
        "roc_1": roc_1,
        "roc_3": roc_3,
        "roc_12": roc_12,
        "velocity_state": velocity_state,
        "dist_ema9_pct": dist_ema9_pct,
        "dist_ema21_pct": dist_ema21_pct,
        "extension_state": extension_state,
        "price_action_summary": price_action_summary,
    }


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=length).mean()
    avg_loss = loss.rolling(window=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series) -> dict:
    ema_12 = ema(series, 12)
    ema_26 = ema(series, 26)
    macd_line = ema_12 - ema_26
    signal_line = ema(macd_line, 9)
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def bollinger_bands(series: pd.Series, length: int = 20, std: float = 2.0) -> dict:
    mid = sma(series, length)
    sd = series.rolling(window=length).std(ddof=0)
    return {"upper": mid + std * sd, "mid": mid, "lower": mid - std * sd}


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr_val = tr.rolling(window=length).mean()
    plus_di = 100 * (plus_dm.rolling(window=length).mean() / atr_val.replace(0, np.nan))
    minus_di = 100 * (-minus_dm.rolling(window=length).mean() / atr_val.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.rolling(window=length).mean()


def generate_signal(ohlcv: pd.DataFrame) -> dict:
    closes = ohlcv["close"]
    highs = ohlcv["high"]
    lows = ohlcv["low"]
    volumes = ohlcv["volume"]

    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)
    ema_50 = ema(closes, 50)
    rsi_v = rsi(closes, 14)
    macd_v = macd(closes)
    atr_v = atr(highs, lows, closes, 14)
    bb = bollinger_bands(closes, 20)
    vol_ma_20 = sma(volumes, 20)
    adx_v = adx(highs, lows, closes, 14)

    last = lambda s: float(s.iloc[-1]) if s is not None and not s.empty else 0.0

    ema_9_v = last(ema_9)
    ema_21_v = last(ema_21)
    ema_50_v = last(ema_50)
    rsi_last = last(rsi_v)
    atr_last = last(atr_v)
    close_v = last(closes)
    vol_last = last(volumes)
    vol_ma = last(vol_ma_20)
    vol_ratio = vol_last / vol_ma if vol_ma > 0 else 1.0
    adx_last = last(adx_v)
    macd_hist = last(macd_v["histogram"])

    bullish_trend = ema_9_v > ema_21_v > ema_50_v
    bearish_trend = ema_9_v < ema_21_v < ema_50_v
    ranging = adx_last < 20
    high_vol = (atr_last / close_v) > 0.03 if close_v > 0 else False

    if high_vol or ranging:
        return {
            "direction": "wait",
            "confidence": 0.40,
            "regime": "HIGH_VOL" if high_vol else "RANGING",
            "reasoning": "High volatility or ranging market — skipping",
        }

    if bullish_trend and rsi_last < 70 and rsi_last > 50 and vol_ratio > 1.1:
        return {
            "direction": "long",
            "confidence": 0.70,
            "regime": "TRENDING_UP",
            "reasoning": f"EMA bullish cross, RSI {rsi_last:.1f}, volume {vol_ratio:.2f}x",
        }

    if bearish_trend and rsi_last > 30 and rsi_last < 50 and vol_ratio > 1.1:
        return {
            "direction": "short",
            "confidence": 0.70,
            "regime": "TRENDING_DOWN",
            "reasoning": f"EMA bearish cross, RSI {rsi_last:.1f}, volume {vol_ratio:.2f}x",
        }

    return {
        "direction": "wait",
        "confidence": 0.45,
        "regime": "NEUTRAL",
        "reasoning": "No clear signal from EMA + RSI + volume",
    }
