"""
موزّع مصادر البيانات (Data Source Dispatcher).

يجرب المصادر بالترتيب:
1. TradingView (الأساسي، الأسرع)
2. Yahoo Finance (الاحتياطي)

يضمن الحصول على بيانات موحدة الشكل مهما كان المصدر.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from config.settings import REQUEST_DELAY
from config.stocks import ALL_SYMBOLS

from data_sources import tradingview, yfinance_source

logger = logging.getLogger("egx_bot.dispatcher")


# ===========================================================
# إعدادات
# ===========================================================
# عدد الـ workers المتوازية
# TradingView مش thread-safe بقوة، فبنحدد عدد معتدل
MAX_WORKERS = 4


# ===========================================================
# جلب سهم واحد
# ===========================================================
def fetch_stock(
    symbol: str,
    prefer_tv: bool = True,
) -> Optional[dict]:
    """
    جلب سهم واحد من المصدر الأنسب.

    المعاملات:
    - symbol: رمز السهم
    - prefer_tv: يفضل TradingView (افتراضيًا)

    ترجع: dict بنفس البنية الموحدة أو None
    """
    # ترتيب المحاولات
    sources = (
        [("tradingview", tradingview.fetch_stock),
         ("yfinance", yfinance_source.fetch_stock)]
        if prefer_tv
        else [("yfinance", yfinance_source.fetch_stock),
              ("tradingview", tradingview.fetch_stock)]
    )

    for source_name, fetcher in sources:
        try:
            data = fetcher(symbol)
            if data and data.get("close", 0) > 0:
                data["fetched_from"] = source_name
                return data
            logger.debug(f"{source_name}: بيانات فاضية لـ {symbol}")
        except Exception as e:
            logger.warning(f"{source_name} فشل لـ {symbol}: {e}")

    logger.warning(f"❌ كل المصادر فشلت لـ {symbol}")
    return None


# ===========================================================
# جلب عدة أسهم بالتوازي
# ===========================================================
def fetch_stocks(
    symbols: Optional[list[str]] = None,
    max_workers: int = MAX_WORKERS,
) -> dict[str, dict]:
    """
    جلب عدة أسهم بالتوازي.

    ترجع: {symbol: data} للسهام اللي اتحققت بنجاح فقط.
    """
    if symbols is None:
        symbols = ALL_SYMBOLS

    results: dict[str, dict] = {}
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_stock, sym): sym for sym in symbols}

        for future in as_completed(futures):
            sym = futures[future]
            try:
                data = future.result(timeout=30)
                if data:
                    results[sym] = data
                else:
                    failed.append(sym)
            except Exception as e:
                logger.warning(f"خطأ في {sym}: {e}")
                failed.append(sym)

    # ملخص النتائج
    total = len(symbols)
    success = len(results)
    logger.info(
        f"📊 نتائج الجلب: {success}/{total} نجحت "
        f"({success/total*100:.0f}%)"
    )

    if failed:
        logger.debug(f"أسهم فشلت: {failed}")

    return results


# ===========================================================
# جلب EGX30 (أو سلة بديلة)
# ===========================================================
def fetch_market_index() -> Optional[dict]:
    """
    جلب مؤشر السوق (EGX30 أو بديل).
    """
    # جرب TradingView أولًا
    try:
        data = tradingview.fetch_index()
        if data:
            data["fetched_from"] = "tradingview"
            return data
    except Exception as e:
        logger.warning(f"فشل جلب EGX30 من TradingView: {e}")

    # جرب yfinance
    try:
        import yfinance as yf
        for idx_symbol in ["EGX30.CA", "^CASE30", "EGX30"]:
            try:
                ticker = yf.Ticker(idx_symbol)
                hist = ticker.history(period="1mo", interval="1d")
                if hist is not None and not hist.empty and len(hist) >= 20:
                    close = float(hist["Close"].iloc[-1])
                    open_price = float(hist["Open"].iloc[-1])
                    ema50 = float(hist["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
                    return {
                        "symbol": idx_symbol,
                        "close": close,
                        "open": open_price,
                        "ema50": ema50,
                        "ema200": 0.0,
                        "rsi": 50.0,
                        "macd": 0.0,
                        "macd_signal": 0.0,
                        "source": "yfinance",
                        "fetched_from": "yfinance",
                    }
            except Exception:
                continue
    except ImportError:
        pass

    logger.warning("⚠️ تعذر جلب EGX30 من كل المصادر")
    return None


# ===========================================================
# جلب سلة أسهم تقديرية للسوق
# ===========================================================
def fetch_market_basket(basket: list[str]) -> dict[str, dict]:
    """
    جلب سلة أسهم كبيرة لاستخدامها كبديل للسوق.
    """
    return fetch_stocks(basket)


# ===========================================================
# إحصائيات المصادر
# ===========================================================
def get_source_stats(stocks_data: dict) -> dict:
    """
    يحسب إحصائيات المصادر المستخدمة.
    """
    stats: dict[str, int] = {}
    for data in stocks_data.values():
        source = data.get("fetched_from", data.get("source", "unknown"))
        stats[source] = stats.get(source, 0) + 1
    return stats


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار Dispatcher — أول 5 أسهم")
    print("=" * 60)

    test_symbols = ALL_SYMBOLS[:5]
    data = fetch_stocks(test_symbols)

    print(f"\n✅ نجح جلب: {len(data)}/{len(test_symbols)} سهم")
    print()
    for sym, d in data.items():
        print(f"  📊 {sym:8s} | "
              f"سعر={d['close']:.2f} | "
              f"تغير={d['daily_change_pct']:+.2f}% | "
              f"مصدر={d.get('fetched_from', '?')}")

    print("\n" + "=" * 60)
    print("📊 إحصائيات المصادر:")
    for source, count in get_source_stats(data).items():
        print(f"  {source:15s}: {count}")

    print("\n✅ اختبار Dispatcher اكتمل")
