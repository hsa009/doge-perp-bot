import numpy as np
import pandas as pd


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
