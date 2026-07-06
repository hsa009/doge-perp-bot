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


def evaluate_coin_momentum(prices: list[float], tp_pct: float) -> dict:
    """Selects dynamic period, monitors velocity, and formats trading decisions."""
    if len(prices) < 50:
        return {
            "suggestion": "wait",
            "rsi_value": 50.0,
            "logic": "Insufficient initialization data buffer.",
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
        }

    rsi_slope = current_rsi - previous_rsi

    if current_rsi > 53 and rsi_slope > 0:
        suggestion = "long"
        logic = (
            f"RSI({period}) is bullish at {current_rsi:.1f} with positive"
            f" momentum slope ({rsi_slope:+.2f}). Supports a {tp_pct * 100:.2f}%"
            " long extension."
        )
    elif current_rsi < 47 and rsi_slope < 0:
        suggestion = "short"
        logic = (
            f"RSI({period}) is bearish at {current_rsi:.1f} with negative"
            f" momentum slope ({rsi_slope:+.2f}). Supports a {tp_pct * 100:.2f}%"
            " short breakdown."
        )
    else:
        suggestion = "wait"
        logic = (
            f"RSI({period}) is stalling at {current_rsi:.1f} (slope:"
            f" {rsi_slope:+.2f}). No velocity setup detected."
        )

    return {
        "suggestion": suggestion,
        "rsi_value": round(float(current_rsi), 2),
        "logic": logic,
    }
