"""
تقييم إشارات السوينج (Short-Term Strategy).

الفلاتر:
1. فلاتر إجبارية (Hard):
   - السيولة اليومية
   - السعر في النطاق
   - ADX فوق الحد

2. آلية الدخول المركبة (Entry Conditions):
   - RSI في النطاق
   - EMA25 > EMA50
   - MACD إيجابي
   - RVOL مرتفع
   - السعر فوق EMA25

3. نظام تقييم نقاط (Score 0-100):
   - كل شرط له وزن
   - نرفض إذا الـ score أقل من الحد

4. تحقق من R:R
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from config.strategies import SHORT_TERM

logger = logging.getLogger("egx_bot.short_term.evaluator")


# ===========================================================
# نموذج النتيجة
# ===========================================================
@dataclass
class EvaluationResult:
    """نتيجة تقييم إشارة سوينج."""
    symbol: str
    passed: bool = False
    score: float = 0.0
    signal_type: str = ""       # "Trend" / "Super Breakout" / "Rejected"
    reasons: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "passed": self.passed,
            "score": round(self.score, 1),
            "signal_type": self.signal_type,
            "reasons": self.reasons,
            "details": self.details,
        }


# ===========================================================
# الفلاتر الإجبارية
# ===========================================================
def check_hard_filters(
    data: dict,
    min_price: float = 5.0,
    max_price: float = 500.0,
    min_daily_liquidity: float = 200_000,
    min_adx: float = 25.0,
) -> tuple[bool, list[str]]:
    """
    فلاتر إجبارية — أي فشل = رفض فوري.
    ترجع: (نجح؟، أسباب الرفض)
    """
    reasons = []

    close = data.get("close", 0)
    volume = data.get("volume", 0)
    adx = data.get("adx", 0)

    # 1. السعر
    if close < min_price:
        reasons.append(f"السعر {close:.2f} أقل من {min_price}")
    elif close > max_price:
        reasons.append(f"السعر {close:.2f} أعلى من {max_price}")

    # 2. السيولة
    liquidity = close * volume
    if liquidity < min_daily_liquidity:
        reasons.append(
            f"السيولة {liquidity:,.0f} ج.م أقل من {min_daily_liquidity:,.0f}"
        )

    # 3. ADX
    if adx < min_adx:
        reasons.append(f"ADX {adx:.1f} أقل من {min_adx}")

    # 4. تغير مفرط (احتمال فخ)
    daily_change = data.get("daily_change_pct", 0)
    if daily_change >= 8.5:
        reasons.append(f"التغير اليومي {daily_change:.1f}% مرتفع جدًا (احتمال فخ)")

    return (len(reasons) == 0, reasons)


# ===========================================================
# نقاط الدخول
# ===========================================================
def compute_entry_score(data: dict) -> tuple[float, dict]:
    """
    حساب نقاط الدخول من 0 إلى 100.

    التوزيع:
    - RSI في النطاق (25)
    - EMA25 > EMA50 (20)
    - MACD إيجابي (20)
    - RVOL مرتفع (20)
    - السعر فوق EMA25 (15)
    """
    breakdown = {}
    st = SHORT_TERM

    # 1. RSI (25 نقطة)
    rsi = data.get("rsi", 50)
    if st.rsi_min <= rsi <= st.rsi_max:
        # كلما كان قريب من المنتصف، نقاط أكثر
        mid = (st.rsi_min + st.rsi_max) / 2
        distance = abs(rsi - mid)
        max_distance = (st.rsi_max - st.rsi_min) / 2
        rsi_score = 25 * (1 - distance / max_distance)
    else:
        rsi_score = 0
    breakdown["rsi"] = rsi_score

    # 2. EMA cross (20 نقطة)
    ema25 = data.get("ema25", 0)
    ema50 = data.get("ema50", 0)
    if ema25 > 0 and ema50 > 0 and ema25 > ema50:
        gap_pct = ((ema25 - ema50) / ema50) * 100
        ema_score = min(20.0, gap_pct * 4)
    else:
        ema_score = 0
    breakdown["ema_cross"] = ema_score

    # 3. MACD (20 نقطة)
    macd = data.get("macd", 0)
    macd_signal = data.get("macd_signal", 0)
    if macd > macd_signal and macd > 0:
        macd_score = 20.0
    elif macd > macd_signal:
        macd_score = 12.0
    elif macd > 0:
        macd_score = 8.0
    else:
        macd_score = 0.0
    breakdown["macd"] = macd_score

    # 4. RVOL (20 نقطة)
    rvol = data.get("rvol", 1.0)
    if rvol >= 2.0:
        rvol_score = 20.0
    elif rvol >= 1.5:
        rvol_score = 16.0
    elif rvol >= 1.2:
        rvol_score = 12.0
    elif rvol >= 1.0:
        rvol_score = 6.0
    else:
        rvol_score = 0.0
    breakdown["rvol"] = rvol_score

    # 5. السعر فوق EMA25 (15 نقطة)
    close = data.get("close", 0)
    if ema25 > 0 and close > ema25:
        gap_pct = ((close - ema25) / ema25) * 100
        price_score = min(15.0, gap_pct * 5)
    else:
        price_score = 0.0
    breakdown["price_above_ema"] = price_score

    total = sum(breakdown.values())
    return (round(min(total, 100.0), 1), breakdown)


# ===========================================================
# التحقق من شروط الدخول المركبة
# ===========================================================
def check_entry_conditions(data: dict) -> tuple[bool, list[str]]:
    """
    آلية الدخول المركبة — كل الشروط لازم تتحقق.
    ترجع: (نجح؟، الأسباب الفاشلة)
    """
    failed = []
    st = SHORT_TERM
    cond = st.entry_conditions

    # 1. RSI
    if cond.get("rsi_in_range", True):
        rsi = data.get("rsi", 50)
        if not (st.rsi_min <= rsi <= st.rsi_max):
            failed.append(f"RSI {rsi:.0f} خارج النطاق [{st.rsi_min}-{st.rsi_max}]")

    # 2. EMA cross
    if cond.get("ema_cross_bullish", True):
        ema25 = data.get("ema25", 0)
        ema50 = data.get("ema50", 0)
        if not (ema25 > 0 and ema50 > 0 and ema25 > ema50):
            failed.append("EMA25 ليس أعلى من EMA50")

    # 3. MACD
    if cond.get("macd_positive", True):
        macd = data.get("macd", 0)
        macd_signal = data.get("macd_signal", 0)
        if not (macd > macd_signal):
            failed.append("MACD أقل من Signal")

    # 4. Volume confirmation
    if cond.get("volume_confirmation", True):
        rvol = data.get("rvol", 0)
        if rvol < st.min_rvol:
            failed.append(f"RVOL {rvol:.2f} أقل من {st.min_rvol}")

    # 5. Price above EMA25
    if cond.get("price_above_ema25", True):
        close = data.get("close", 0)
        ema25 = data.get("ema25", 0)
        if not (ema25 > 0 and close > ema25):
            failed.append("السعر ليس أعلى من EMA25")

    return (len(failed) == 0, failed)


# ===========================================================
# الدالة الرئيسية
# ===========================================================
def evaluate_signal(
    symbol: str,
    data: dict,
    regime_risk_multiplier: float = 1.0,
    min_score: float = 60.0,
) -> EvaluationResult:
    """
    تقييم سهم كإشارة سوينج.

    المعاملات:
    - symbol: رمز السهم
    - data: dict من dispatcher
    - regime_risk_multiplier: معامل حالة السوق (0.0 = توقف)
    - min_score: الحد الأدنى للـ score

    ترجع: EvaluationResult
    """
    result = EvaluationResult(symbol=symbol)

    # 1. حالة السوق
    if regime_risk_multiplier == 0.0:
        result.reasons.append("حالة السوق تمنع فتح صفقات")
        return result

    # 2. فلاتر إجبارية
    passed, reasons = check_hard_filters(data)
    if not passed:
        result.reasons.extend(reasons)
        return result

    # 3. شروط الدخول المركبة
    cond_passed, cond_failed = check_entry_conditions(data)
    if not cond_passed:
        result.reasons.extend(cond_failed)
        return result

    # 4. حساب الـ score
    score, breakdown = compute_entry_score(data)
    result.score = score
    result.details["score_breakdown"] = breakdown

    # تعديل الـ score حسب حالة السوق
    adjusted_score = score * regime_risk_multiplier
    result.details["adjusted_score"] = round(adjusted_score, 1)

    # 5. التحقق من الحد الأدنى
    if adjusted_score < min_score:
        result.reasons.append(
            f"Score {adjusted_score:.0f} أقل من الحد {min_score}"
        )
        return result

    # 6. تحديد نوع الإشارة
    daily_change = data.get("daily_change_pct", 0)
    rvol = data.get("rvol", 0)

    if daily_change >= 2.0 and rvol >= 2.0:
        result.signal_type = "Super Breakout 🚀"
    else:
        result.signal_type = "Trend 📈"

    result.passed = True
    return result


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار تقييم السوينج")
    print("=" * 60)

    # حالة 1: سهم قوي
    strong = {
        "close": 50.0,
        "volume": 500_000,
        "adx": 32.0,
        "rsi": 55.0,
        "ema25": 49.0,
        "ema50": 47.0,
        "macd": 1.5,
        "macd_signal": 1.0,
        "rvol": 2.2,
        "daily_change_pct": 3.5,
    }
    print("\n1️⃣ سهم قوي:")
    r = evaluate_signal("STRONG", strong, regime_risk_multiplier=1.2)
    for k, v in r.to_dict().items():
        print(f"   {k}: {v}")

    # حالة 2: سهم متوسط
    medium = dict(strong)
    medium.update({"rsi": 68, "rvol": 1.3, "adx": 27, "daily_change_pct": 1.0})
    print("\n2️⃣ سهم متوسط:")
    r = evaluate_signal("MEDIUM", medium, regime_risk_multiplier=1.0)
    for k, v in r.to_dict().items():
        print(f"   {k}: {v}")

    # حالة 3: سهم فاشل
    weak = dict(strong)
    weak.update({"adx": 15, "rsi": 78, "rvol": 0.8})
    print("\n3️⃣ سهم ضعيف (ADX منخفض):")
    r = evaluate_signal("WEAK", weak, regime_risk_multiplier=1.0)
    for k, v in r.to_dict().items():
        print(f"   {k}: {v}")

    print("\n" + "=" * 60)
    print("✅ اختبار تقييم السوينج اكتمل")
