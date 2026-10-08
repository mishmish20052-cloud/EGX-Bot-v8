"""
حساب المؤشرات الفنية الأساسية والمتقدمة.
يعمل مع pandas Series و numpy arrays.

المؤشرات المدعومة:
- RSI (Relative Strength Index)
- EMA / SMA (Moving Averages)
- ATR (Average True Range)
- ADX (Average Directional Index)
- MACD
- Stochastic
- Bollinger Bands
- Relative Strength vs Market
- Volume Z-Score
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("egx_bot.indicators")


# ===========================================================
# المتوسطات المتحركة
# ===========================================================
def sma(series: pd.Series, period: int) -> pd.Series:
    """المتوسط المتحرك البسيط."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """المتوسط المتحرك الأسي."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wilder_ema(series: pd.Series, period: int) -> pd.Series:
    """
    المتوسط الأسي بطريقة Wilder (يُستخدم في RSI و ATR و ADX).
    alpha = 1 / period
    """
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ===========================================================
# RSI
# ===========================================================
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    مؤشر القوة النسبية (Wilder's RSI).
    يرجع Series بقيم من 0 إلى 100.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = wilder_ema(gain, period)
    avg_loss = wilder_ema(loss, period)

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.fillna(50)


# ===========================================================
# ATR (Average True Range)
# ===========================================================
def true_range(df: pd.DataFrame) -> pd.Series:
    """يحسب True Range لكل شمعة."""
    high = df["High"]
    low = df["Low"]
    close_prev = df["Close"].shift(1)

    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()

    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """المدى الحقيقي المتوسط (Wilder)."""
    tr = true_range(df)
    return wilder_ema(tr, period)


def atr_percent(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR كنسبة مئوية من السعر الحالي."""
    atr_val = atr(df, period)
    return (atr_val / df["Close"]) * 100


# ===========================================================
# ADX (Average Directional Index)
# ===========================================================
def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    مؤشر قوة الاتجاه (Average Directional Index).
    قيم > 25 تعني اتجاه قوي.
    """
    high = df["High"]
    low = df["Low"]

    # +DM و -DM
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # ATR للـ smoothing
    tr = true_range(df)
    atr_val = wilder_ema(tr, period)

    plus_di = 100 * (wilder_ema(plus_dm, period) / atr_val.replace(0, np.nan))
    minus_di = 100 * (wilder_ema(minus_dm, period) / atr_val.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    result = wilder_ema(dx, period)
    return result.fillna(20)


# ===========================================================
# MACD
# ===========================================================
def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    MACD Line + Signal Line + Histogram.
    """
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


# ===========================================================
# Stochastic
# ===========================================================
def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    """
    Stochastic Oscillator.
    يرجع %K و %D.
    """
    low_n = df["Low"].rolling(window=k_period).min()
    high_n = df["High"].rolling(window=k_period).max()

    denom = (high_n - low_n).replace(0, np.nan)
    k = 100 * (df["Close"] - low_n) / denom
    k = k.fillna(50)
    d = k.rolling(window=d_period).mean().fillna(50)

    return {"k": k, "d": d}


# ===========================================================
# Bollinger Bands
# ===========================================================
def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> dict:
    """نطاقات بولينجر."""
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width = (upper - lower) / middle
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "width": width,
    }


# ===========================================================
# Volume Z-Score
# ===========================================================
def volume_zscore(volume: pd.Series, period: int = 20) -> pd.Series:
    """Z-Score لحجم التداول."""
    mean = volume.rolling(window=period).mean()
    std = volume.rolling(window=period).std()
    return (volume - mean) / std.replace(0, np.nan)


# ===========================================================
# Relative Strength (RS) - القوة النسبية
# ===========================================================
def relative_strength(
    stock_close: pd.Series,
    market_close: pd.Series,
    period: int = 60,
) -> float:
    """
    القوة النسبية للسهم مقابل السوق خلال فترة.
    القيمة > 0 تعني أن السهم أقوى من السوق.
    """
    if len(stock_close) < period + 1 or len(market_close) < period + 1:
        return 0.0

    stock_return = (stock_close.iloc[-1] / stock_close.iloc[-period - 1] - 1) * 100
    market_return = (market_close.iloc[-1] / market_close.iloc[-period - 1] - 1) * 100

    return float(stock_return - market_return)


# ===========================================================
# Momentum
# ===========================================================
def momentum(series: pd.Series, period: int = 60) -> pd.Series:
    """الزخم — نسبة التغير خلال فترة."""
    return series.pct_change(periods=period) * 100


# ===========================================================
# دالة شاملة: حساب كل المؤشرات على DataFrame
# ===========================================================
def compute_all(
    df: pd.DataFrame,
    market_close: Optional[pd.Series] = None,
) -> dict:
    """
    يحسب كل المؤشرات على DataFrame دفعة واحدة.

    المتوقع في df: Open, High, Low, Close, Volume
    المتوقع في market_close: سلسلة تاريخية لسعر السوق (اختياري)

    يرجع dictionary بكل القيم الأخيرة (scalars) + القيم التاريخية المهمة.
    """
    if df.empty or len(df) < 30:
        logger.warning("البيانات غير كافية لحساب المؤشرات")
        return {}

    result: dict = {}

    # --- المتوسطات ---
    result["ema25"] = float(ema(df["Close"], 25).iloc[-1])
    result["ema50"] = float(ema(df["Close"], 50).iloc[-1])
    result["ema200"] = float(ema(df["Close"], 200).iloc[-1]) if len(df) >= 200 else None
    result["sma20"] = float(sma(df["Close"], 20).iloc[-1])

    # --- RSI ---
    rsi_series = rsi(df["Close"], 14)
    result["rsi"] = float(rsi_series.iloc[-1])

    # --- ATR ---
    atr_series = atr(df, 14)
    result["atr"] = float(atr_series.iloc[-1])
    result["atr_pct"] = float(atr_percent(df, 14).iloc[-1])

    # --- ADX ---
    result["adx"] = float(adx(df, 14).iloc[-1])

    # --- MACD ---
    macd_data = macd(df["Close"])
    result["macd"] = float(macd_data["macd"].iloc[-1])
    result["macd_signal"] = float(macd_data["signal"].iloc[-1])
    result["macd_histogram"] = float(macd_data["histogram"].iloc[-1])

    # --- Stochastic ---
    stoch_data = stochastic(df)
    result["stoch_k"] = float(stoch_data["k"].iloc[-1])
    result["stoch_d"] = float(stoch_data["d"].iloc[-1])

    # --- Bollinger ---
    bb = bollinger_bands(df["Close"])
    result["bb_upper"] = float(bb["upper"].iloc[-1])
    result["bb_lower"] = float(bb["lower"].iloc[-1])
    result["bb_width"] = float(bb["width"].iloc[-1]) if not pd.isna(bb["width"].iloc[-1]) else 0.0

    # --- Volume ---
    vol = df["Volume"]
    result["volume"] = float(vol.iloc[-1])
    result["volume_sma20"] = float(sma(vol, 20).iloc[-1])
    vol_sma = result["volume_sma20"]
    result["rvol"] = float(vol.iloc[-1] / vol_sma) if vol_sma > 0 else 1.0

    # --- Momentum ---
    if len(df) >= 61:
        result["momentum_60d"] = float(momentum(df["Close"], 60).iloc[-1])
    else:
        result["momentum_60d"] = 0.0

    # --- Relative Strength vs Market ---
    if market_close is not None and len(market_close) >= 60:
        try:
            result["relative_strength"] = relative_strength(
                df["Close"], market_close, period=60
            )
        except Exception:
            result["relative_strength"] = 0.0
    else:
        result["relative_strength"] = 0.0

    # --- التغير اليومي ---
    if len(df) >= 2:
        prev_close = float(df["Close"].iloc[-2])
        current_close = float(df["Close"].iloc[-1])
        result["daily_change_pct"] = (
            (current_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        )
    else:
        result["daily_change_pct"] = 0.0

    # --- السعر الحالي ---
    result["close"] = float(df["Close"].iloc[-1])

    return result


# ===========================================================
# اختبار سريع عند التشغيل المباشر
# ===========================================================
if __name__ == "__main__":
    # بيانات وهمية للاختبار
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(100 + np.cumsum(np.random.randn(n) * 2), index=dates)
    high = close + np.random.rand(n) * 2
    low = close - np.random.rand(n) * 2
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.randint(50000, 200000, n), index=dates)

    df = pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })

    result = compute_all(df)
    print("=" * 60)
    print("اختبار المؤشرات:")
    print("=" * 60)
    for key, value in result.items():
        if value is None:
            print(f"  {key:25s}: None")
        else:
            print(f"  {key:25s}: {value:.4f}")
    print("=" * 60)
    print("✅ كل المؤشرات اتحسبت بنجاح")
