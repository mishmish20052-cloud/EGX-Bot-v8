"""
جلب البيانات من TradingView عبر مكتبة tradingview_ta.

المزايا:
- Retry تلقائي مع تأخير متزايد
- Cache داخلي لجلسة واحدة
- دعم فترات: 15 دقيقة + يومي
- معالجة أخطاء شاملة
"""

import logging
import time
from datetime import datetime
from typing import Optional

from tradingview_ta import TA_Handler, Interval

from config.settings import (
    CAIRO_TZ,
    REQUEST_DELAY,
    MAX_RETRIES,
)
from config.stocks import get_sector

logger = logging.getLogger("egx_bot.tradingview")


# ===========================================================
# إعدادات
# ===========================================================
SCREENER = "egypt"
EXCHANGE = "EGX"

# Cache داخلي (يُصفّر بين التشغيلات)
_CACHE: dict = {}
_CACHE_TTL_SECONDS = 60  # صلاحية الكاش: دقيقة واحدة


# ===========================================================
# دالة جلب بيانات الإطار الزمني
# ===========================================================
def _fetch_interval(symbol: str, interval: str, retries: int = MAX_RETRIES) -> Optional[dict]:
    """
    جلب بيانات إطار زمني واحد من TradingView.

    المعاملات:
    - symbol: رمز السهم (مثل ADIB)
    - interval: Interval.INTERVAL_15_MINUTES أو INTERVAL_1_DAY
    - retries: عدد المحاولات

    ترجع: indicators dict أو None
    """
    for attempt in range(retries):
        try:
            handler = TA_Handler(
                symbol=symbol,
                screener=SCREENER,
                exchange=EXCHANGE,
                interval=interval,
            )
            analysis = handler.get_analysis()
            indicators = analysis.indicators

            if indicators and indicators.get("close", 0) > 0:
                return indicators

            # لو البيانات فاضية، اعتبرها فشل
            logger.debug(f"TradingView: بيانات فاضية لـ {symbol} @ {interval}")

        except Exception as e:
            logger.debug(
                f"TradingView محاولة {attempt + 1}/{retries} فشلت "
                f"لـ {symbol}: {e}"
            )

        # exponential backoff: 2, 4, 8, 16 ثانية
        if attempt < retries - 1:
            sleep_time = 2 ** attempt
            time.sleep(sleep_time)

    return None


# ===========================================================
# الدالة الرئيسية: جلب سهم واحد
# ===========================================================
def fetch_stock(symbol: str, use_cache: bool = True) -> Optional[dict]:
    """
    جلب كل بيانات سهم واحد (15 دقيقة + يومي).

    ترجع dict موحد أو None لو فشل.
    """
    # فحص الكاش
    if use_cache:
        cached = _CACHE.get(symbol)
        if cached:
            age = (datetime.now(CAIRO_TZ) - cached["_cached_at"]).total_seconds()
            if age < _CACHE_TTL_SECONDS:
                return cached["data"]

    # تأخير بسيط لتجنب rate limit
    time.sleep(REQUEST_DELAY)

    # جلب الإطارين
    i15 = _fetch_interval(symbol, Interval.INTERVAL_15_MINUTES)
    if i15 is None:
        logger.warning(f"❌ فشل جلب {symbol} (15 دقيقة)")
        return None

    i1d = _fetch_interval(symbol, Interval.INTERVAL_1_DAY)

    # استخراج القيم مع حماية
    close = _safe(i15.get("close"), 0)
    open_price = _safe(i15.get("open"), close)

    if close <= 0:
        logger.warning(f"❌ سعر غير صالح لـ {symbol}")
        return None

    # السعر اليومي
    close_daily = _safe(i1d.get("close"), close) if i1d else close
    ema50_daily = _safe(i1d.get("EMA50"), close_daily) if i1d else close_daily

    # حساب RVOL
    volume = _safe(i15.get("volume"), 0)
    vol_sma20 = _safe(i15.get("volume.SMA20"), 0)
    rvol = round(volume / vol_sma20, 2) if vol_sma20 > 0 else 1.0

    # التغير اليومي
    if open_price > 0:
        daily_change_pct = ((close - open_price) / open_price) * 100
    else:
        daily_change_pct = 0.0

    # بناء البيانات الموحدة
    data = {
        "symbol": symbol,
        "sector": get_sector(symbol),
        "close": close,
        "open": open_price,
        "high": _safe(i15.get("high"), close),
        "low": _safe(i15.get("low"), close),
        "volume": volume,
        "rvol": rvol,
        "daily_change_pct": round(daily_change_pct, 2),

        # مؤشرات 15 دقيقة
        "rsi": _safe(i15.get("RSI"), 50),
        "ema25": _safe(i15.get("EMA25"), close),
        "ema50": _safe(i15.get("EMA50"), close),
        "macd": _safe(i15.get("MACD.macd"), 0),
        "macd_signal": _safe(i15.get("MACD.signal"), 0),
        "stoch_k": _safe(i15.get("Stoch.K"), 50),

        # مؤشرات يومية
        "close_daily": close_daily,
        "ema50_daily": ema50_daily,
        "atr": _safe(i1d.get("ATR"), close * 0.02) if i1d else close * 0.02,
        "adx": _safe(i1d.get("ADX"), 20) if i1d else 20,
        "stoch_daily": _safe(i1d.get("Stoch.K"), 50) if i1d else 50,

        # إشارات محسوبة
        "green_15m": close > open_price,
        "bull_daily": close_daily >= ema50_daily,

        # مصدر البيانات
        "source": "tradingview",
        "reliable": True,
    }

    # إضافة للأساسيات لو متاحة
    if i1d:
        data["pe_ratio"] = _safe(i1d.get("P/E"), None)

    # تخزين في الكاش
    if use_cache:
        _CACHE[symbol] = {
            "data": data,
            "_cached_at": datetime.now(CAIRO_TZ),
        }

    return data


# ===========================================================
# جلب عدة أسهم
# ===========================================================
def fetch_stocks(symbols: list[str], use_cache: bool = True) -> dict[str, dict]:
    """
    جلب عدة أسهم بالتتابع (TradingView مش بيدعم thread-safe بشكل مثالي).
    """
    results = {}
    for symbol in symbols:
        data = fetch_stock(symbol, use_cache=use_cache)
        if data:
            results[symbol] = data
    return results


# ===========================================================
# جلب EGX30 (أو سلة بديلة)
# ===========================================================
def fetch_index(index_candidates: list[str] = None) -> Optional[dict]:
    """
    محاولة جلب EGX30 من TradingView.
    ترجع None لو فشلت كل الرموز.
    """
    if index_candidates is None:
        index_candidates = ["EGX30", "EGX30.CA", "^EGX30"]

    for sym in index_candidates:
        try:
            i1d = _fetch_interval(sym, Interval.INTERVAL_1_DAY, retries=2)
            if i1d and i1d.get("close", 0) > 0:
                return {
                    "symbol": sym,
                    "close": _safe(i1d.get("close"), 0),
                    "open": _safe(i1d.get("open"), 0),
                    "ema50": _safe(i1d.get("EMA50"), 0),
                    "ema200": _safe(i1d.get("EMA200"), 0),
                    "rsi": _safe(i1d.get("RSI"), 50),
                    "macd": _safe(i1d.get("MACD.macd"), 0),
                    "macd_signal": _safe(i1d.get("MACD.signal"), 0),
                    "source": "tradingview",
                }
        except Exception:
            continue
    return None


# ===========================================================
# دوال مساعدة
# ===========================================================
def _safe(value, default):
    """يحول القيمة لرقم بأمان."""
    if value is None:
        return default
    try:
        f = float(value)
        if f != f or abs(f) == float("inf"):
            return default
        return f
    except (ValueError, TypeError):
        return default


def clear_cache() -> None:
    """يمسح الكاش الداخلي (يُستخدم بين الدورات)."""
    global _CACHE
    _CACHE = {}
    logger.debug("🧹 تم مسح cache TradingView")


def get_cache_size() -> int:
    """يرجع حجم الكاش الحالي."""
    return len(_CACHE)


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    from config.stocks import ALL_SYMBOLS

    print("=" * 60)
    print("اختبار TradingView — أول 3 أسهم")
    print("=" * 60)

    for sym in ALL_SYMBOLS[:3]:
        print(f"\n📊 جاري جلب {sym}...")
        data = fetch_stock(sym)
        if data:
            print(f"   ✅ {sym}: سعر={data['close']:.2f}, "
                  f"تغير={data['daily_change_pct']:+.2f}%, "
                  f"RSI={data['rsi']:.0f}, "
                  f"RVOL={data['rvol']:.2f}x")
        else:
            print(f"   ❌ فشل جلب {sym}")

    print("\n" + "=" * 60)
    print(f"حجم الكاش: {get_cache_size()} سهم")
    print("✅ اختبار TradingView اكتمل")
