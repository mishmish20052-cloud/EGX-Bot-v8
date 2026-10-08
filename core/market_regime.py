"""
تحليل حالة السوق العامة (Market Regime).

يحدد حالة السوق بناءً على:
- EGX30 مباشرة (أو سلة أسهم كبديل)
- المتوسطات المتحركة (EMA50, EMA200)
- MACD
- RSI
- فحص اتساع السوق (breadth)

الحالات:
- CRASH       : انهيار — إيقاف كل شيء
- BEAR        : دب — مخاطرة عالية + أسهم دفاعية فقط
- SIDEWAYS    : عرضي — مخاطرة متوسطة
- BULL        : صعود — مخاطرة منخفضة
- STRONG_BULL : صعود قوي — مخاطرة منخفضة + عدد صفقات أعلى
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config.settings import CAIRO_TZ

logger = logging.getLogger("egx_bot.market_regime")


# ===========================================================
# نموذج البيانات لحالة السوق
# ===========================================================
@dataclass
class MarketRegime:
    """يمثل حالة السوق الحالية."""
    type: str = "SIDEWAYS"           # CRASH / BEAR / SIDEWAYS / BULL / STRONG_BULL
    risk: str = "MEDIUM"             # EXTREME / HIGH / MEDIUM / LOW
    risk_multiplier: float = 1.0     # معامل ضرب المخاطرة
    max_trades: int = 3              # أقصى عدد صفقات مفتوحة
    defensive_only: bool = False     # هل نتعامل مع الأسهم الدفاعية فقط؟
    change_pct: float = 0.0          # نسبة التغير اليومية
    source: str = "unknown"          # مصدر البيانات
    breadth_pct: Optional[float] = None  # نسبة الأسهم الحمراء
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "risk": self.risk,
            "risk_multiplier": self.risk_multiplier,
            "max_trades": self.max_trades,
            "defensive_only": self.defensive_only,
            "change_pct": self.change_pct,
            "source": self.source,
            "breadth_pct": self.breadth_pct,
            "timestamp": self.timestamp,
        }

    def banner(self) -> str:
        """يرجع إيموجي + اسم الحالة."""
        icons = {
            "CRASH": "⚫",
            "BEAR": "🔴",
            "SIDEWAYS": "🟠",
            "BULL": "🟢",
            "STRONG_BULL": "🟢🟢",
        }
        return f"{self.type} {icons.get(self.type, '')}"


# ===========================================================
# تصنيف الحالة من المؤشرات
# ===========================================================
def classify_regime(
    close: float,
    open_price: float,
    ema50: float,
    ema200: Optional[float],
    rsi_val: float,
    macd_val: float,
    macd_signal: float,
) -> MarketRegime:
    """
    يصنف حالة السوق بناءً على المؤشرات.
    """
    chg = ((close - open_price) / open_price * 100) if open_price else 0.0

    # --- CRASH ---
    if chg <= -3.0:
        return MarketRegime(
            type="CRASH", risk="EXTREME", risk_multiplier=0.0,
            max_trades=0, defensive_only=True, change_pct=chg,
        )
    if ema200 and close < ema200 and rsi_val < 30:
        return MarketRegime(
            type="CRASH", risk="EXTREME", risk_multiplier=0.0,
            max_trades=0, defensive_only=True, change_pct=chg,
        )

    # --- STRONG_BULL ---
    if ema50 and ema200 and close > ema50 > ema200 and macd_val > macd_signal and rsi_val < 75:
        return MarketRegime(
            type="STRONG_BULL", risk="LOW", risk_multiplier=1.4,
            max_trades=5, change_pct=chg,
        )

    # --- BULL ---
    if ema50 and close > ema50 and macd_val > macd_signal:
        return MarketRegime(
            type="BULL", risk="LOW", risk_multiplier=1.1,
            max_trades=4, change_pct=chg,
        )

    # --- BEAR ---
    if ema50 and close < ema50 and macd_val < macd_signal:
        return MarketRegime(
            type="BEAR", risk="HIGH", risk_multiplier=0.5,
            max_trades=2, defensive_only=True, change_pct=chg,
        )

    # --- SIDEWAYS ---
    return MarketRegime(
        type="SIDEWAYS", risk="MEDIUM", risk_multiplier=0.8,
        max_trades=3, change_pct=chg,
    )


# ===========================================================
# تطبيق تعديل الاتساع (Breadth)
# ===========================================================
def apply_breadth_adjustment(
    regime: MarketRegime,
    all_data: dict,
    red_threshold: float = -0.5,
    red_ratio_trigger: float = 0.70,
    min_samples: int = 8,
) -> MarketRegime:
    """
    يعدّل حالة السوق بناءً على اتساع السوق.
    لو 70%+ من الأسهم حمراء، نخفض المخاطرة حتى لو المؤشر لسه مستقر.
    """
    if not all_data or len(all_data) < min_samples:
        return regime

    changes = [
        d.get("daily_change_pct", d.get("chg", 0))
        for d in all_data.values()
    ]
    red_count = sum(1 for c in changes if c < red_threshold)
    red_ratio = red_count / len(changes)
    regime.breadth_pct = round(red_ratio * 100, 1)

    if red_ratio >= red_ratio_trigger and regime.risk not in ("EXTREME", "HIGH"):
        logger.warning(
            f"⚠️ اتساع سلبي: {red_ratio*100:.0f}% من الأسهم حمراء — تخفيض المخاطرة"
        )
        regime.risk = "HIGH"
        regime.risk_multiplier = min(regime.risk_multiplier, 0.6)
        regime.max_trades = min(regime.max_trades, 2)
        regime.defensive_only = True

    return regime


# ===========================================================
# دوال مساعدة للفلترة
# ===========================================================
def should_skip_new_trades(regime: MarketRegime) -> bool:
    """هل نتوقف عن فتح صفقات جديدة؟"""
    return regime.type == "CRASH" or regime.risk_multiplier == 0.0


def should_use_defensive_only(regime: MarketRegime) -> bool:
    """هل نتعامل مع الأسهم الدفاعية فقط؟"""
    return regime.defensive_only or regime.type in ("BEAR", "CRASH")


def get_max_trades(regime: MarketRegime, measurement_mode: bool = False) -> int:
    """يرجع أقصى عدد صفقات — في وضع القياس نسمح بعدد كبير للتجريب."""
    if measurement_mode:
        return 999
    return regime.max_trades


# ===========================================================
# طباعة ملخص
# ===========================================================
def log_regime(regime: MarketRegime) -> None:
    """يطبع ملخص حالة السوق في اللوج."""
    logger.info(
        f"🌍 حالة السوق: {regime.banner()} | "
        f"مخاطرة: {regime.risk} | "
        f"معامل: {regime.risk_multiplier}x | "
        f"أقصى صفقات: {regime.max_trades} | "
        f"مصدر: {regime.source}"
    )
    if regime.breadth_pct is not None:
        logger.info(f"📉 اتساع السوق: {regime.breadth_pct}% أسهم حمراء")


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    # اختبار التصنيف
    cases = [
        ("CRASH", 100, 105, 95, 90, 25, -2, -1),
        ("STRONG_BULL", 110, 105, 100, 95, 65, 2, 1),
        ("BULL", 105, 100, 100, 90, 60, 1, 0.5),
        ("BEAR", 90, 95, 100, 105, 40, -1, -0.5),
        ("SIDEWAYS", 100, 100, 100, 100, 50, 0, 0),
    ]

    print("=" * 60)
    print("اختبار تصنيف حالة السوق:")
    print("=" * 60)
    for expected, c, o, e50, e200, rsi_v, macd_v, macd_s in cases:
        regime = classify_regime(c, o, e50, e200, rsi_v, macd_v, macd_s)
        status = "✅" if regime.type == expected else "❌"
        print(f"  {status} Expected: {expected:12s} | Got: {regime.type:12s}")
    print("=" * 60)
    print("✅ اختبار حالة السوق اكتمل")
