"""
جلب الأساسيات المالية من Yahoo Finance.

المصادر:
- yfinance (Ticker.info) — الأساسي
- fallback: قيم محايدة لو البيانات مش متوفرة

يستخدم cache داخلي لتقليل عدد الطلبات.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from config.settings import CAIRO_TZ

logger = logging.getLogger("egx_bot.fundamentals")


# ===========================================================
# إعدادات الكاش
# ===========================================================
CACHE_FILE = "fundamentals_cache.json"
CACHE_TTL_HOURS = 24  # صلاحية البيانات: يوم واحد


# ===========================================================
# نموذج البيانات
# ===========================================================
class FundamentalData:
    """يمثل الأساسيات المالية لسهم."""

    def __init__(
        self,
        symbol: str,
        pe_ratio: Optional[float] = None,
        earnings_growth: Optional[float] = None,
        roe: Optional[float] = None,
        roa: Optional[float] = None,
        profit_margin: Optional[float] = None,
        market_cap: Optional[float] = None,
        dividend_yield: Optional[float] = None,
        source: str = "unknown",
    ):
        self.symbol = symbol
        self.pe_ratio = pe_ratio
        self.earnings_growth = earnings_growth  # نسبة مئوية
        self.roe = roe                          # نسبة مئوية
        self.roa = roa                          # نسبة مئوية
        self.profit_margin = profit_margin      # نسبة مئوية
        self.market_cap = market_cap            # بالمليار جنيه
        self.dividend_yield = dividend_yield    # نسبة مئوية
        self.source = source
        self.fetched_at = datetime.now(CAIRO_TZ).isoformat()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "pe_ratio": self.pe_ratio,
            "earnings_growth": self.earnings_growth,
            "roe": self.roe,
            "roa": self.roa,
            "profit_margin": self.profit_margin,
            "market_cap": self.market_cap,
            "dividend_yield": self.dividend_yield,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }

    def is_empty(self) -> bool:
        """هل كل القيم فاضية؟"""
        return all([
            self.pe_ratio is None,
            self.earnings_growth is None,
            self.roe is None,
            self.roa is None,
        ])


# ===========================================================
# إدارة الكاش
# ===========================================================
def _load_cache() -> dict:
    """يحمل الكاش من الملف المحلي."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"تعذر تحميل الكاش: {e}")
        return {}


def _save_cache(cache: dict) -> None:
    """يحفظ الكاش في الملف المحلي."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"تعذر حفظ الكاش: {e}")


def _is_cache_valid(entry: dict) -> bool:
    """يتحقق من صلاحية الكاش."""
    if not entry.get("fetched_at"):
        return False
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
        age = datetime.now(CAIRO_TZ) - fetched
        return age < timedelta(hours=CACHE_TTL_HOURS)
    except Exception:
        return False


# ===========================================================
# جلب الأساسيات من Yahoo Finance
# ===========================================================
def _fetch_from_yahoo(symbol: str) -> Optional[FundamentalData]:
    """
    يجلب الأساسيات من Yahoo Finance.
    يرجع None لو فشل.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance غير متوفرة")
        return None

    try:
        # جرب الرموز المحتملة
        yahoo_symbols = [f"{symbol}.CA", f"{symbol}.EGX"]

        for yf_symbol in yahoo_symbols:
            try:
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info

                if not info or info.get("regularMarketPrice") is None:
                    continue

                # استخراج القيم مع تنظيف
                pe = _safe_float(info.get("trailingPE"))
                growth = _safe_float(info.get("earningsGrowth"))
                roe = _safe_float(info.get("returnOnEquity"))
                roa = _safe_float(info.get("returnOnAssets"))
                margin = _safe_float(info.get("profitMargins"))
                mcap = _safe_float(info.get("marketCap"))
                div_yield = _safe_float(info.get("dividendYield"))

                # تحويل النسب المئوية
                if growth is not None:
                    growth = growth * 100
                if roe is not None:
                    roe = roe * 100
                if roa is not None:
                    roa = roa * 100
                if margin is not None:
                    margin = margin * 100
                if div_yield is not None:
                    div_yield = div_yield * 100
                if mcap is not None:
                    mcap = mcap / 1_000_000_000  # مليار

                return FundamentalData(
                    symbol=symbol,
                    pe_ratio=pe,
                    earnings_growth=growth,
                    roe=roe,
                    roa=roa,
                    profit_margin=margin,
                    market_cap=mcap,
                    dividend_yield=div_yield,
                    source="yahoo",
                )
            except Exception:
                continue

        return None

    except Exception as e:
        logger.warning(f"فشل جلب أساسيات {symbol}: {e}")
        return None


def _safe_float(value) -> Optional[float]:
    """يحول القيمة لـ float بأمان."""
    if value is None:
        return None
    try:
        f = float(value)
        # رفض القيم غير المنطقية
        if f != f or abs(f) == float("inf"):  # NaN أو inf
            return None
        return round(f, 2)
    except (ValueError, TypeError):
        return None


# ===========================================================
# الدالة الرئيسية: جلب دفعة أساسيات
# ===========================================================
def fetch_fundamentals(symbols: list[str], use_cache: bool = True) -> dict[str, FundamentalData]:
    """
    يجلب الأساسيات لدفعة أسهم.
    يستخدم الكاش لو متاح وصالح.

    ترجع: {symbol: FundamentalData}
    """
    cache = _load_cache() if use_cache else {}
    results: dict[str, FundamentalData] = {}
    cache_hits = 0
    fresh_fetches = 0

    for symbol in symbols:
        # جرب الكاش أولًا
        if use_cache and symbol in cache and _is_cache_valid(cache[symbol]):
            entry = cache[symbol]
            results[symbol] = FundamentalData(
                symbol=symbol,
                pe_ratio=entry.get("pe_ratio"),
                earnings_growth=entry.get("earnings_growth"),
                roe=entry.get("roe"),
                roa=entry.get("roa"),
                profit_margin=entry.get("profit_margin"),
                market_cap=entry.get("market_cap"),
                dividend_yield=entry.get("dividend_yield"),
                source="cache",
            )
            cache_hits += 1
            continue

        # جلب جديد
        data = _fetch_from_yahoo(symbol)
        if data is None:
            data = FundamentalData(symbol=symbol, source="empty")
        results[symbol] = data
        cache[symbol] = data.to_dict()
        fresh_fetches += 1

    # احفظ الكاش المحدث
    if fresh_fetches > 0:
        _save_cache(cache)

    logger.info(f"📊 أساسيات: {cache_hits} من الكاش، {fresh_fetches} طلب جديد")

    return results


# ===========================================================
# دالة ملائمة للاستخدام في scoring.py
# ===========================================================
def fetch_fundamentals_dict(symbols: list[str]) -> dict[str, dict]:
    """
    نفس fetch_fundamentals لكن ترجع dict جاهز للاستخدام في score_stock.
    """
    data = fetch_fundamentals(symbols)
    return {
        sym: {
            "pe_ratio": d.pe_ratio,
            "earnings_growth": d.earnings_growth,
            "roe": d.roe,
            "roa": d.roa,
            "profit_margin": d.profit_margin,
            "market_cap": d.market_cap,
            "dividend_yield": d.dividend_yield,
        }
        for sym, d in data.items()
    }


# ===========================================================
# حساب قوة القطاع (Sector Strength)
# ===========================================================
def compute_sector_strength(
    stocks_data: dict,
    sectors_map: dict,
) -> dict[str, float]:
    """
    يحسب قوة كل قطاع بناءً على متوسط أداء أسهمه.

    stocks_data: {symbol: technical_data}
    sectors_map: {symbol: sector_name}
    ترجع: {sector_name: strength (0-100)}
    """
    sector_changes: dict[str, list[float]] = {}

    for symbol, data in stocks_data.items():
        sector = sectors_map.get(symbol, "OTHER")
        change = data.get("momentum_60d", data.get("daily_change_pct", 0))
        sector_changes.setdefault(sector, []).append(change)

    sector_strength = {}
    for sector, changes in sector_changes.items():
        if not changes:
            sector_strength[sector] = 50.0
            continue

        avg_change = sum(changes) / len(changes)

        # تحويل التغير لمقياس 0-100
        # +20% متوسط → 100
        # -20% متوسط → 0
        # 0% → 50
        strength = 50 + (avg_change * 2.5)
        strength = max(0.0, min(100.0, strength))
        sector_strength[sector] = round(strength, 1)

    return sector_strength


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    from config.stocks import ALL_SYMBOLS

    # اختبار على أول 3 أسهم
    test_symbols = ALL_SYMBOLS[:3]
    print("=" * 60)
    print(f"اختبار جلب الأساسيات لـ: {test_symbols}")
    print("=" * 60)

    data = fetch_fundamentals(test_symbols)
    for sym, d in data.items():
        print(f"\n📊 {sym}")
        print(f"   P/E: {d.pe_ratio}")
        print(f"   نمو الأرباح: {d.earnings_growth}%")
        print(f"   ROE: {d.roe}%")
        print(f"   ROA: {d.roa}%")
        print(f"   القيمة السوقية: {d.market_cap} مليار")
        print(f"   المصدر: {d.source}")

    # اختبار sector strength
    print("\n" + "=" * 60)
    print("اختبار قوة القطاعات:")
    print("=" * 60)
    mock_data = {
        "COMI": {"momentum_60d": 15.0},
        "TMGH": {"momentum_60d": 22.0},
        "PHDC": {"momentum_60d": 18.0},
        "EFIH": {"momentum_60d": -5.0},
    }
    mock_sectors = {
        "COMI": "FINANCIAL",
        "TMGH": "REALESTATE",
        "PHDC": "REALESTATE",
        "EFIH": "TECH",
    }
    strengths = compute_sector_strength(mock_data, mock_sectors)
    for sector, strength in strengths.items():
        print(f"  {sector:15s}: {strength:.1f}")

    print("\n" + "=" * 60)
    print("✅ اختبار الأساسيات اكتمل")
