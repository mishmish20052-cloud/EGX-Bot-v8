"""
فلترة أولية للأسهم المرشحة للاستثمار متوسط المدى.

يقوم بفحص سريع وواسع لكل الأسهم، ويرجع فقط:
- الأسهم ذات السيولة الكافية
- الأسهم في اتجاه صاعد (EMA50 > EMA200)
- الأسهم بسعر في النطاق

بعدها، يجتاز السهم مرحلة التقييم المركب (scorer).
"""

import logging
from dataclasses import dataclass, field

from config.settings import (
    MIN_STOCK_PRICE,
    MIN_DAILY_LIQUIDITY,
)

logger = logging.getLogger("egx_bot.long_term.screener")


# ===========================================================
# نموذج النتيجة
# ===========================================================
@dataclass
class ScreenedStock:
    """سهم اجتاز الفلترة الأولية."""
    symbol: str
    close: float
    daily_liquidity: float
    ema50: float
    ema200: float
    uptrend: bool
    momentum_60d: float
    data: dict = field(default_factory=dict)   # البيانات الكاملة

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "close": round(self.close, 2),
            "daily_liquidity": round(self.daily_liquidity, 0),
            "uptrend": self.uptrend,
            "momentum_60d": round(self.momentum_60d, 2),
        }


# ===========================================================
# فلاتر فردية
# ===========================================================
def check_price(data: dict) -> tuple[bool, str]:
    """السعر في النطاق المسموح."""
    close = data.get("close", 0)
    if close < MIN_STOCK_PRICE:
        return (False, f"السعر {close:.2f} أقل من {MIN_STOCK_PRICE}")
    if close > 500:
        return (False, f"السعر {close:.2f} مرتفع جدًا")
    return (True, "")


def check_liquidity(data: dict) -> tuple[bool, str]:
    """السيولة اليومية كافية."""
    close = data.get("close", 0)
    volume = data.get("volume", 0)
    liquidity = close * volume
    if liquidity < MIN_DAILY_LIQUIDITY:
        return (False, f"السيولة {liquidity:,.0f} أقل من {MIN_DAILY_LIQUIDITY:,.0f}")
    return (True, "")


def check_uptrend(data: dict) -> tuple[bool, str]:
    """
    الاتجاه صاعد — إجباري للاستثمار متوسط المدى.

    الشرط:
    - EMA50 > EMA200 (دعم أساسي)
    - السعر > EMA50 (تأكيد)
    """
    close = data.get("close", 0)
    ema50_daily = data.get("ema50_daily", 0)
    ema200 = data.get("ema200", 0)

    # لو عندنا EMA200 مباشر
    if ema200 > 0:
        if ema50_daily <= ema200:
            return (False, f"EMA50 ({ema50_daily:.2f}) ≤ EMA200 ({ema200:.2f})")
    else:
        # بديل: نتحقق فقط أن السعر فوق EMA50
        if ema50_daily > 0 and close < ema50_daily:
            return (False, f"السعر ({close:.2f}) أقل من EMA50 ({ema50_daily:.2f})")

    return (True, "")


def check_not_overbought(data: dict) -> tuple[bool, str]:
    """ليس في حالة تشبع شراء مفرط."""
    rsi = data.get("rsi", 50)
    if rsi > 80:
        return (False, f"RSI {rsi:.1f} > 80 (تشبع شراء)")
    return (True, "")


# ===========================================================
# الدالة الرئيسية: فحص سهم
# ===========================================================
def screen_stock(symbol: str, data: dict) -> tuple[bool, str]:
    """
    فحص سريع لسهم واحد.
    ترجع: (نجح؟، السبب)
    """
    checks = [
        check_price(data),
        check_liquidity(data),
        check_uptrend(data),
        check_not_overbought(data),
    ]

    for passed, reason in checks:
        if not passed:
            return (False, reason)

    return (True, "")


# ===========================================================
# فلترة دفعة كاملة
# ===========================================================
def screen_batch(stocks_data: dict) -> list[ScreenedStock]:
    """
    فلترة كل الأسهم مرة واحدة.

    المعاملات:
    - stocks_data: {symbol: data} من dispatcher

    ترجع: قائمة بـ ScreenedStock مرتبة تنازليًا حسب الزخم.
    """
    candidates: list[ScreenedStock] = []
    rejected_count = 0
    reject_reasons: dict[str, int] = {}

    for symbol, data in stocks_data.items():
        passed, reason = screen_stock(symbol, data)

        if not passed:
            rejected_count += 1
            # نجمع الأسباب للإحصاءات
            short_reason = reason.split("(")[0].strip()
            reject_reasons[short_reason] = reject_reasons.get(short_reason, 0) + 1
            continue

        # السهم اجتاز الفحص — أضفه للقائمة
        close = data.get("close", 0)
        volume = data.get("volume", 0)
        liquidity = close * volume

        candidates.append(ScreenedStock(
            symbol=symbol,
            close=close,
            daily_liquidity=liquidity,
            ema50=data.get("ema50", 0),
            ema200=data.get("ema200", 0),
            uptrend=True,
            momentum_60d=data.get("momentum_60d", 0),
            data=data,
        ))

    # ترتيب حسب الزخم تنازليًا
    candidates.sort(key=lambda c: c.momentum_60d, reverse=True)

    logger.info(
        f"📋 الفلترة الأولية: {len(candidates)} مرشح من "
        f"{len(stocks_data)} ({rejected_count} مرفوض)"
    )

    if reject_reasons:
        top_reasons = sorted(reject_reasons.items(), key=lambda x: -x[1])[:3]
        for reason, count in top_reasons:
            logger.debug(f"   ❌ {reason}: {count} سهم")

    return candidates


# ===========================================================
# دوال مساعدة
# ===========================================================
def get_top_candidates(
    stocks_data: dict,
    max_count: int = 10,
) -> list[ScreenedStock]:
    """
    يرجع أفضل N مرشح بعد الفلترة.
    """
    candidates = screen_batch(stocks_data)
    return candidates[:max_count]


def screening_stats(stocks_data: dict) -> dict:
    """إحصاءات الفلترة (للتقارير)."""
    candidates = screen_batch(stocks_data)
    total = len(stocks_data)
    passed = len(candidates)

    return {
        "total": total,
        "passed": passed,
        "rejected": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "symbols": [c.symbol for c in candidates],
    }


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار فلترة الأسهم")
    print("=" * 60)

    # بيانات وهمية
    mock_data = {
        "STRONG": {
            "close": 50.0,
            "volume": 500_000,
            "ema50": 48.0,
            "ema50_daily": 48.0,
            "ema200": 42.0,
            "rsi": 55.0,
            "momentum_60d": 15.0,
        },
        "MEDIUM": {
            "close": 30.0,
            "volume": 300_000,
            "ema50_daily": 29.0,
            "ema200": 25.0,
            "rsi": 62.0,
            "momentum_60d": 8.0,
        },
        "WEAK_PRICE": {
            "close": 3.0,
            "volume": 500_000,
            "ema50_daily": 3.0,
            "ema200": 3.5,
            "rsi": 55.0,
            "momentum_60d": 5.0,
        },
        "WEAK_LIQUIDITY": {
            "close": 25.0,
            "volume": 1000,  # قليل جدًا
            "ema50_daily": 24.0,
            "ema200": 22.0,
            "rsi": 60.0,
            "momentum_60d": 10.0,
        },
        "DOWNTREND": {
            "close": 20.0,
            "volume": 300_000,
            "ema50_daily": 22.0,
            "ema200": 25.0,  # EMA50 < EMA200
            "rsi": 45.0,
            "momentum_60d": -5.0,
        },
    }

    print("\n📊 فحص فردي:")
    for symbol, data in mock_data.items():
        passed, reason = screen_stock(symbol, data)
        status = "✅" if passed else "❌"
        print(f"  {status} {symbol:20s} | {reason or 'OK'}")

    print("\n📊 الفلترة الكاملة:")
    candidates = screen_batch(mock_data)
    for c in candidates:
        print(f"  ✅ {c.symbol} | "
              f"سعر={c.close:.2f} | "
              f"سيولة={c.daily_liquidity:,.0f} | "
              f"زخم={c.momentum_60d:+.1f}%")

    print("\n📊 إحصاءات:")
    stats = screening_stats(mock_data)
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("✅ اختبار الفلترة اكتمل")
