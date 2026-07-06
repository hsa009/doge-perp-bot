import numpy as np


def calculate_wilders_rsi(
    prices: list[float] | np.ndarray, period: int = 14
) -> np.ndarray:
    """Calculates Wilder's RSI using standard RMA smoothing."""
    prices = np.array(prices, dtype=float)
    rsi_array = np.full_like(prices, np.nan)

    if len(prices) <= period:
        return rsi_array

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gains = np.zeros_like(prices)
    avg_losses = np.zeros_like(prices)

    avg_gains[period] = np.mean(gains[:period])
    avg_losses[period] = np.mean(losses[:period])

    if avg_losses[period] == 0:
        rsi_array[period] = 100.0 if avg_gains[period] > 0 else 50.0
    else:
        rs = avg_gains[period] / avg_losses[period]
        rsi_array[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(prices)):
        avg_gains[i] = (
            avg_gains[i - 1] * (period - 1) + gains[i - 1]
        ) / period
        avg_losses[i] = (
            avg_losses[i - 1] * (period - 1) + losses[i - 1]
        ) / period

        if avg_losses[i] == 0:
            rsi_array[i] = 100.0 if avg_gains[i] > 0 else 50.0
        else:
            rs = avg_gains[i] / avg_losses[i]
            rsi_array[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi_array


# ============================================================
# DOUBLE RSI TREND STRATEGY (DISABLED — preserved for reference)
# ============================================================
# def _supertrend_direction(
#     high: list[float] | np.ndarray,
#     low: list[float] | np.ndarray,
#     close: list[float] | np.ndarray,
#     factor: float = 1.85,
#     atr_period: int = 1,
# ) -> np.ndarray:
#     """Pine-exact ta.supertrend direction.
#
#     +1 = uptrend (supertrend line below price), -1 = downtrend.
#     Uses propagating bands (can only widen) and checks close against
#     the prior bar's supertrend line to detect flips.
#     """
#     close = np.array(close, dtype=float)
#     high = np.array(high, dtype=float)
#     low = np.array(low, dtype=float)
#     n = len(close)
#
#     prev_close = np.roll(close, 1)
#     prev_close[0] = close[0]
#     tr = np.maximum(
#         high - low,
#         np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
#     )
#     atr = tr
#
#     hl_avg = (high + low) / 2
#     raw_upper = hl_avg + factor * atr
#     raw_lower = hl_avg - factor * atr
#
#     direction = np.ones(n)
#     supertrend = np.empty(n)
#
#     upper_band = np.empty(n)
#     lower_band = np.empty(n)
#
#     for i in range(n):
#         if i == 0:
#             upper_band[i] = raw_upper[i]
#             lower_band[i] = raw_lower[i]
#             direction[i] = 1
#         else:
#             upper_band[i] = raw_upper[i] if raw_upper[i] < upper_band[i - 1] else upper_band[i - 1]
#             lower_band[i] = raw_lower[i] if raw_lower[i] > lower_band[i - 1] else lower_band[i - 1]
#
#         if direction[i - 1] == -1 if i > 0 else False:
#             supertrend[i] = upper_band[i]
#             if close[i] > supertrend[i]:
#                 direction[i] = 1
#                 supertrend[i] = lower_band[i]
#             else:
#                 direction[i] = -1
#         else:
#             supertrend[i] = lower_band[i]
#             if close[i] < supertrend[i]:
#                 direction[i] = -1
#                 supertrend[i] = upper_band[i]
#             else:
#                 direction[i] = 1
#
#     return direction
# ============================================================
# def evaluate_coin_momentum(close, high, low, tp_pct):
#     """Double RSI Trend strategy: Supertrend flip + RSI25/100 crossover."""
#     min_bars = 150
#     if len(close) < min_bars:
#         return {
#             "suggestion": "wait",
#             "rsi_value": 50.0,
#             "score": 0.0,
#             "logic": f"Insufficient data: need >= {min_bars} candles.",
#             "confidence_score": 0.0,
#         }
#
#     rsi_25 = calculate_wilders_rsi(close, 25)
#     rsi_100 = calculate_wilders_rsi(close, 100)
#     current_rsi_25 = rsi_25[-1]
#     current_rsi_100 = rsi_100[-1]
#     prev_rsi_25 = rsi_25[-2]
#     prev_rsi_100 = rsi_100[-2]
#
#     if np.isnan(current_rsi_25) or np.isnan(current_rsi_100):
#         return {
#             "suggestion": "wait",
#             "rsi_value": 50.0,
#             "score": 0.0,
#             "logic": "RSI returned NaN.",
#             "confidence_score": 0.0,
#         }
#
#     st_dir = _supertrend_direction(high, low, close, factor=1.85, atr_period=1)
#     current_dir = st_dir[-1]
#     prev_dir = st_dir[-2]
#     crossover = prev_rsi_25 <= prev_rsi_100 and current_rsi_25 > current_rsi_100
#     crossunder = prev_rsi_25 >= prev_rsi_100 and current_rsi_25 < current_rsi_100
#     is_long = current_dir == -1 and prev_dir == 1 and crossover
#     is_short = current_dir == 1 and prev_dir == -1 and crossunder
#
#     if is_long:
#         suggestion = "long"
#         score = round(float(current_rsi_25 - current_rsi_100), 2)
#     elif is_short:
#         suggestion = "short"
#         score = round(float(current_rsi_100 - current_rsi_25), 2)
#     else:
#         suggestion = "wait"
#         score = 0.0
#
#     regime = "uptrend" if current_dir == 1 else "downtrend"
#     logic = (
#         f"Double RSI Trend: regime={regime}, "
#         f"RSI25={current_rsi_25:.1f}, RSI100={current_rsi_100:.1f}, "
#         f"crossover={crossover}, crossunder={crossunder}"
#     )
#     return {
#         "suggestion": suggestion,
#         "score": score,
#         "rsi_value": round(float(current_rsi_25), 2),
#         "logic": logic,
#         "confidence_score": score,
#     }
# ============================================================


def evaluate_coin_momentum(prices: list[float], tp_pct: float) -> dict:
    """Selects dynamic period, monitors velocity, and formats trading decisions."""
    if len(prices) < 50:
        return {
            "suggestion": "wait",
            "rsi_value": 50.0,
            "logic": "Insufficient initialization data buffer.",
            "confidence_score": 0.0,
        }

    if tp_pct <= 0.005:
        period = 5
    elif tp_pct <= 0.01:
        period = 8
    else:
        period = 14

    rsi_values = calculate_wilders_rsi(prices, period)
    current_rsi = rsi_values[-1]
    previous_rsi = rsi_values[-2]

    if np.isnan(current_rsi) or np.isnan(previous_rsi):
        return {
            "suggestion": "wait",
            "rsi_value": 50.0,
            "logic": "RSI returned as NaN value.",
            "confidence_score": 0.0,
        }

    rsi_slope = current_rsi - previous_rsi

    if current_rsi > 53 and rsi_slope > 0:
        suggestion = "long"
        confidence_score = round((current_rsi - 50) + (rsi_slope * 2), 2)
        logic = (
            f"RSI({period}) is bullish at {current_rsi:.1f} with positive"
            f" momentum slope ({rsi_slope:+.2f}). Supports a {tp_pct * 100:.2f}%"
            " long extension."
        )
    elif current_rsi < 47 and rsi_slope < 0:
        suggestion = "short"
        confidence_score = round((50 - current_rsi) + (abs(rsi_slope) * 2), 2)
        logic = (
            f"RSI({period}) is bearish at {current_rsi:.1f} with negative"
            f" momentum slope ({rsi_slope:+.2f}). Supports a {tp_pct * 100:.2f}%"
            " short breakdown."
        )
    else:
        suggestion = "wait"
        confidence_score = 0.0
        logic = (
            f"RSI({period}) is stalling at {current_rsi:.1f} (slope:"
            f" {rsi_slope:+.2f}). No velocity setup detected."
        )

    return {
        "suggestion": suggestion,
        "rsi_value": round(float(current_rsi), 2),
        "logic": logic,
        "confidence_score": confidence_score,
    }
