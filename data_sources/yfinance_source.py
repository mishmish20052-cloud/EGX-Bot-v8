"""
جلب البيانات من Yahoo Finance كمصدر احتياطي.

يُستخدم لو TradingView فشلت أو رجعت بيانات غير مكتملة.

يُصلح كل مشاكل النسخة القديمة (v7):
- multi-index columns
- فترة زمنية كافية (1mo بدل 5d)
- حساب RSI/Stoch حقيقي بدل القيم الوهمية
- التحقق من وجود الأعمدة المطلوبة
"""

import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import (
    CAIRO_TZ,
    REQUEST_DELAY,
    MAX_RETRIES,
)
from config.stocks import get_sector

logger = logging.getLogger("egx_bot.yfinance_source")


# ===========================================================
# إعدادات
# ===========================================================
# فترة التحميل — 1mo كافية لحساب EMA50 بثقة
DOWNLOAD_PERIOD = "1mo"
DOWNLOAD_INTERVAL_DAILY = "1d"
DOWNLOAD_INTERVAL_15M = "15m"

# الأعمدة المطلوبة
REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


# ===========================================================
# دوال مساعدة للحساب
# ===========================================================
def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """حساب RSI (Wilder) بمعادلة صحيحة."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _calc_stoch_k(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """حساب Stochastic %K."""
    low_n = df["Low"].rolling(period).min()
    high_n = df["High"].rolling(period).max()
    denom = (high_n - low_n).replace(0, np.nan)
    stoch = ((df["Close"] - low_n) / denom) * 100
    return stoch.fillna(50)


def _calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """حساب ATR (Wilder)."""
    high = df["High"]
    low = df["Low"]
    close_prev = df["Close"].shift(1)
    tr = pd.concat(
        [high - low, (high - close_prev).abs(), (low - close_prev).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return atr


def _calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """حساب ADX مبسط."""
    try:
        high = df["High"]
        low = df["Low"]
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
            index=df.index,
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
            index=df.index,
        )

        tr = pd.concat(
            [
                high - low,
                (high - df["Close"].shift()).abs(),
                (low - df["Close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_val = tr.ewm(alpha=1 / period, adjust=False).mean()

        plus_di = 100 * (
            plus_dm.ewm(alpha=1 / period, adjust=False).mean()
            / atr_val.replace(0, np.nan)
        )
        minus_di = 100 * (
            minus_dm.ewm(alpha=1 / period, adjust=False).mean()
            / atr_val.replace(0, np.nan)
        )

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1 / period, adjust=False).mean()
        return adx.fillna(20)
    except Exception:
        return pd.Series(20, index=df.index)


# ===========================================================
# تنظيف DataFrame
# ===========================================================
def _clean_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    ينظف DataFrame من yfinance:
    - معالجة multi-index columns
    - التحقق من الأعمدة المطلوبة
    """
    if df is None or df.empty:
        return None

    # معالجة multi-index
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # التحقق من الأعمدة المطلوبة
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        logger.debug(f"أعمدة ناقصة: {missing}")
        return None

    return df


# ===========================================================
# جلب البيانات من Yahoo
# ===========================================================
def _try_download(
    yf_symbol: str, period: str, interval: str
) -> Optional[pd.DataFrame]:
    """محاولة تحميل واحدة مع retry."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance غير مثبتة")
        return None

    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(
                yf_symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.debug(f"yfinance محاولة {attempt + 1} فشلت لـ {yf_symbol}: {e}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(2 ** attempt)

    return None


# ===========================================================
# الدالة الرئيسية
# ===========================================================
def fetch_stock(symbol: str, use_cache: bool = True) -> Optional[dict]:
    """
    جلب بيانات سهم واحد من Yahoo Finance.

    يرجّع dict بنفس بنية TradingView.
    """
    time.sleep(REQUEST_DELAY * 0.5)

    # جرب الرموز المحتملة
    candidates = [f"{symbol}.CA", f"{symbol}.EGX"]

    daily_df = None
    intraday_df = None
    used_symbol = None

    for yf_symbol in candidates:
        daily_df = _try_download(yf_symbol, DOWNLOAD_PERIOD, DOWNLOAD_INTERVAL_DAILY)
        if daily_df is not None:
            daily_df = _clean_df(daily_df)
            if daily_df is not None and len(daily_df) >= 20:
                used_symbol = yf_symbol
                # جرب البيانات اللحظية (اختيارية)
                intraday_df = _try_download(yf_symbol, "5d", DOWNLOAD_INTERVAL_15M)
                if intraday_df is not None:
                    intraday_df = _clean_df(intraday_df)
                break

    if daily_df is None or len(daily_df) < 20:
        logger.debug(f"yfinance: بيانات غير كافية لـ {symbol}")
        return None

    # --- البيانات اليومية ---
    close_daily = daily_df["Close"]
    last_daily = daily_df.iloc[-1]
    prev_daily = daily_df.iloc[-2] if len(daily_df) >= 2 else last_daily

    # المتوسطات
    ema50_daily = close_daily.ewm(span=50, adjust=False).mean().iloc[-1]
    ema25_daily = close_daily.ewm(span=25, adjust=False).mean().iloc[-1]

    # المؤشرات
    rsi_series = _calc_rsi(close_daily)
    stoch_series = _calc_stoch_k(daily_df)
    atr_series = _calc_atr(daily_df)
    adx_series = _calc_adx(daily_df)

    # --- البيانات اللحظية أو اليومية كبديل ---
    if intraday_df is not None and len(intraday_df) >= 5:
        price_df = intraday_df
    else:
        price_df = daily_df

    last_price = price_df.iloc[-1]
    close = float(last_price["Close"])
    open_price = float(last_price["Open"])
    high = float(last_price["High"])
    low = float(last_price["Low"])
    volume = float(last_price["Volume"])

    # RVOL
    vol_sma20 = price_df["Volume"].rolling(20).mean().iloc[-1]
    if pd.isna(vol_sma20) or vol_sma20 <= 0:
        rvol = 1.0
    else:
        rvol = round(float(volume) / float(vol_sma20), 2)

    # التغير اليومي
    daily_change_pct = 0.0
    if len(daily_df) >= 2:
        prev_close = float(prev_daily["Close"])
        curr_close = float(last_daily["Close"])
        if prev_close > 0:
            daily_change_pct = ((curr_close - prev_close) / prev_close) * 100

    # RSI للـ 15 دقيقة (لو متاح)
    if intraday_df is not None and len(intraday_df) >= 20:
        rsi_15m = float(_calc_rsi(intraday_df["Close"]).iloc[-1])
        ema25_15m = float(
            intraday_df["Close"].ewm(span=25, adjust=False).mean().iloc[-1]
        )
        ema50_15m = float(
            intraday_df["Close"].ewm(span=50, adjust=False).mean().iloc[-1]
        )
    else:
        rsi_15m = float(rsi_series.iloc[-1])
        ema25_15m = float(ema25_daily)
        ema50_15m = float(ema50_daily)

    # بناء البيانات الموحدة
    data = {
        "symbol": symbol,
        "sector": get_sector(symbol),
        "close": close,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "rvol": rvol,
        "daily_change_pct": round(daily_change_pct, 2),
        # مؤشرات 15 دقيقة
        "rsi": round(rsi_15m, 1),
        "ema25": ema25_15m,
        "ema50": ema50_15m,
        "macd": 0.0,  # غير متاح بثقة من yfinance في هذه النسخة
        "macd_signal": 0.0,
        "stoch_k": round(float(stoch_series.iloc[-1]), 1),
        # مؤشرات يومية
        "close_daily": float(last_daily["Close"]),
        "ema50_daily": float(ema50_daily),
        "atr": float(atr_series.iloc[-1])
        if not pd.isna(atr_series.iloc[-1])
        else close * 0.02,
        "adx": round(float(adx_series.iloc[-1]), 1)
        if not pd.isna(adx_series.iloc[-1])
        else 20.0,
        "stoch_daily": round(float(stoch_series.iloc[-1]), 1),
        # إشارات محسوبة
        "green_15m": close > open_price,
        "bull_daily": float(last_daily["Close"]) >= float(ema50_daily),
        # مصدر البيانات
        "source": "yfinance",
        "reliable": True,
        "yf_symbol": used_symbol,
    }

    return data


# ===========================================================
# جلب عدة أسهم
# ===========================================================
def fetch_stocks(symbols: list[str]) -> dict[str, dict]:
    """جلب عدة أسهم بالتتابع."""
    results = {}
    for symbol in symbols:
        data = fetch_stock(symbol)
        if data:
            results[symbol] = data
    return results


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    from config.stocks import ALL_SYMBOLS

    print("=" * 60)
    print("اختبار yfinance — أول 3 أسهم")
    print("=" * 60)

    for sym in ALL_SYMBOLS[:3]:
        print(f"\n📊 جاري جلب {sym}...")
        data = fetch_stock(sym)
        if data:
            print(
                f"   ✅ {sym}: سعر={data['close']:.2f}, "
                f"تغير={data['daily_change_pct']:+.2f}%, "
                f"RSI={data['rsi']:.0f}, "
                f"ADX={data['adx']:.0f}, "
                f"RVOL={data['rvol']:.2f}x"
            )
        else:
            print(f"   ❌ فشل جلب {sym}")

    print("\n" + "=" * 60)
    print("✅ اختبار yfinance اكتمل")
