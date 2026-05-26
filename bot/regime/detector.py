import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


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


def detect_regime(ohlcv: pd.DataFrame) -> str:
    closes = ohlcv["close"]
    highs = ohlcv["high"]
    lows = ohlcv["low"]

    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)
    ema_50 = ema(closes, 50)
    atr_v = atr(highs, lows, closes, 14)
    adx_v = adx(highs, lows, closes, 14)

    last = lambda s: float(s.iloc[-1]) if s is not None and not s.empty else 0.0

    atr_pct = last(atr_v) / last(closes) if last(closes) > 0 else 0
    adx_last = last(adx_v)
    e9 = last(ema_9)
    e21 = last(ema_21)
    e50 = last(ema_50)

    if adx_last > 25 and e9 > e21 > e50:
        return "TRENDING_UP"
    if adx_last > 25 and e9 < e21 < e50:
        return "TRENDING_DOWN"
    if adx_last < 20:
        return "RANGING"
    if atr_pct > 0.03:
        return "HIGH_VOL"
    return "NEUTRAL"
