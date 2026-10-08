"""
نظام التقييم المركّب للأسهم.
يجمع بين المؤشرات الفنية (70%) والأساسيات (30%)
لإنتاج درجة من 100 لكل سهم.

الاستخدام:
    from core.scoring import score_stock, ScoreResult
    result = score_stock(symbol, technical_data, fundamental_data, sector_strength=...)
    if result.total >= 60:
        # السهم مرشح للدخول
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("egx_bot.scoring")


# ===========================================================
# نموذج النتيجة
# ===========================================================
@dataclass
class ScoreResult:
    """نتيجة تقييم سهم واحد."""
    symbol: str
    total: float = 0.0
    technical_score: float = 0.0        # من 70
    fundamental_score: float = 0.0      # من 30
    breakdown: dict = field(default_factory=dict)  # تفاصيل كل معيار
    reasons: list = field(default_factory=list)    # أسباب الرفض / القبول
    passed_hard_filters: bool = True    # اجتاز الفلاتر الإجبارية؟
    sector_strength: float = 0.0        # قوة القطاع (0-100)

    @property
    def grade(self) -> str:
        """تصنيف مبدئي للدرجة."""
        if self.total >= 85: return "A+"
        if self.total >= 75: return "A"
        if self.total >= 65: return "B"
        if self.total >= 55: return "C"
        if self.total >= 45: return "D"
        return "F"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "total": round(self.total, 2),
            "technical_score": round(self.technical_score, 2),
            "fundamental_score": round(self.fundamental_score, 2),
            "grade": self.grade,
            "passed_hard_filters": self.passed_hard_filters,
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "reasons": self.reasons,
        }


# ===========================================================
# الفلاتر الإجبارية (Hard Filters)
# ===========================================================
def check_hard_filters(
    technical: dict,
    min_price: float = 5.0,
    max_price: float = 500.0,
    min_liquidity_egp: float = 200_000,
    require_uptrend: bool = True,
) -> tuple[bool, list[str]]:
    """
    فلترة إجبارية — لو فشل أي منها، السهم يُرفض فورًا.
    ترجع: (نجح؟، قائمة الأسباب)
    """
    reasons = []

    # 1. السعر
    close = technical.get("close", 0)
    if close < min_price:
        reasons.append(f"السعر {close:.2f} أقل من الحد الأدنى {min_price}")
    if close > max_price:
        reasons.append(f"السعر {close:.2f} أعلى من الحد الأقصى {max_price}")

    # 2. السيولة
    volume = technical.get("volume", 0)
    liquidity_egp = volume * close
    if liquidity_egp < min_liquidity_egp:
        reasons.append(
            f"السيولة {liquidity_egp:,.0f} ج.م أقل من الحد الأدنى {min_liquidity_egp:,.0f}"
        )

    # 3. الاتجاه (EMA50 > EMA200)
    if require_uptrend:
        ema50 = technical.get("ema50")
        ema200 = technical.get("ema200")
        if ema50 and ema200:
            if ema50 <= ema200:
                reasons.append("EMA50 أقل من EMA200 (لا يوجد اتجاه صاعد)")
        else:
            reasons.append("لا يمكن التحقق من الاتجاه (بيانات ناقصة)")

    return (len(reasons) == 0, reasons)


# ===========================================================
# حساب الدرجة الفنية (70 نقطة)
# ===========================================================
def compute_technical_score(
    technical: dict,
    sector_strength: float = 50.0,
) -> tuple[float, dict]:
    """
    الدرجة الفنية = 70 نقطة كحد أقصى.
    التوزيع:
    - الاتجاه (25):    EMA50 > EMA200 + السعر أعلى من EMA50
    - الزخم (15):      momentum_60d موجب
    - القوة النسبية (15): relative_strength موجب
    - قوة القطاع (10): sector_strength (0-100)
    - السيولة (5):     rvol مرتفع
    """
    breakdown = {}

    # --- 1. الاتجاه (25 نقطة) ---
    trend_score = 0.0
    ema50 = technical.get("ema50", 0)
    ema200 = technical.get("ema200", 0) or ema50
    close = technical.get("close", 0)

    if ema50 > 0 and ema200 > 0:
        # كلما زادت المسافة بين EMA50 و EMA200، كان الاتجاه أقوى
        gap_pct = ((ema50 - ema200) / ema200) * 100 if ema200 > 0 else 0
        if gap_pct > 0:
            trend_score += min(15.0, gap_pct * 1.5)  # حتى 15 نقطة
        if close > ema50:
            trend_score += 10.0  # 10 نقاط إضافية
    breakdown["trend"] = trend_score

    # --- 2. الزخم (15 نقطة) ---
    momentum_60d = technical.get("momentum_60d", 0)
    if momentum_60d > 0:
        # حتى 15 نقطة
        momentum_score = min(15.0, momentum_60d * 0.5)
    else:
        momentum_score = max(0.0, 15 + momentum_60d * 0.5)  # عقوبة طفيفة
    breakdown["momentum"] = momentum_score

    # --- 3. القوة النسبية (15 نقطة) ---
    rs = technical.get("relative_strength", 0)
    if rs > 0:
        rs_score = min(15.0, rs * 0.5)
    else:
        rs_score = max(0.0, 7.5 + rs * 0.5)  # حتى لو ضعيف، ندي نص الدرجة
    breakdown["relative_strength"] = rs_score

    # --- 4. قوة القطاع (10 نقاط) ---
    sector_score = max(0.0, min(10.0, sector_strength / 10))
    breakdown["sector_strength"] = sector_score

    # --- 5. السيولة (5 نقطة) ---
    rvol = technical.get("rvol", 1.0)
    if rvol >= 1.5:
        liquidity_score = 5.0
    elif rvol >= 1.2:
        liquidity_score = 3.5
    elif rvol >= 1.0:
        liquidity_score = 2.0
    else:
        liquidity_score = max(0.0, rvol * 2.0)
    breakdown["liquidity"] = liquidity_score

    total = sum(breakdown.values())
    return (round(min(total, 70.0), 2), breakdown)


# ===========================================================
# حساب درجة الأساسيات (30 نقطة)
# ===========================================================
def compute_fundamental_score(fundamental: dict) -> tuple[float, dict]:
    """
    الدرجة الأساسية = 30 نقطة كحد أقصى.
    التوزيع:
    - التقييم (10): P/E معقول
    - نمو الأرباح (10): earnings_growth موجب
    - الربحية (10): ROE / ROA
    """
    breakdown = {}

    # --- 1. التقييم (10 نقطة) ---
    pe = fundamental.get("pe_ratio")
    if pe is None or pe <= 0:
        # مفيش بيانات → ندي درجة محايدة
        valuation_score = 5.0
    elif pe < 8:
        valuation_score = 10.0
    elif pe < 12:
        valuation_score = 8.0
    elif pe < 18:
        valuation_score = 6.0
    elif pe < 25:
        valuation_score = 4.0
    else:
        valuation_score = 2.0
    breakdown["valuation"] = valuation_score

    # --- 2. نمو الأرباح (10 نقطة) ---
    growth = fundamental.get("earnings_growth")
    if growth is None:
        earnings_score = 5.0  # محايد
    elif growth >= 30:
        earnings_score = 10.0
    elif growth >= 15:
        earnings_score = 8.0
    elif growth >= 5:
        earnings_score = 6.0
    elif growth >= 0:
        earnings_score = 4.0
    else:
        earnings_score = max(0.0, 4.0 + growth * 0.2)
    breakdown["earnings_growth"] = earnings_score

    # --- 3. الربحية (10 نقطة) ---
    roe = fundamental.get("roe")
    roa = fundamental.get("roa")

    if roe is not None and roe > 0:
        roe_score = min(10.0, roe * 0.4)
    elif roa is not None and roa > 0:
        roe_score = min(10.0, roa * 0.8)
    else:
        roe_score = 5.0  # محايد
    breakdown["profitability"] = roe_score

    total = sum(breakdown.values())
    return (round(min(total, 30.0), 2), breakdown)


# ===========================================================
# الدالة الرئيسية: تقييم سهم واحد
# ===========================================================
def score_stock(
    symbol: str,
    technical: dict,
    fundamental: Optional[dict] = None,
    sector_strength: float = 50.0,
    min_price: float = 5.0,
    max_price: float = 500.0,
    min_liquidity_egp: float = 200_000,
    require_uptrend: bool = True,
) -> ScoreResult:
    """
    تقييم سهم واحد وإرجاع النتيجة.

    المعاملات:
    - symbol: رمز السهم
    - technical: dict من core.indicators.compute_all
    - fundamental: dict فيه pe_ratio, earnings_growth, roe, roa (اختياري)
    - sector_strength: قوة القطاع (0-100)
    """
    result = ScoreResult(symbol=symbol, sector_strength=sector_strength)

    # --- الفلاتر الإجبارية ---
    passed, reasons = check_hard_filters(
        technical=technical,
        min_price=min_price,
        max_price=max_price,
        min_liquidity_egp=min_liquidity_egp,
        require_uptrend=require_uptrend,
    )
    result.passed_hard_filters = passed
    result.reasons.extend(reasons)

    if not passed:
        result.total = 0.0
        return result

    # --- الدرجة الفنية ---
    tech_score, tech_breakdown = compute_technical_score(technical, sector_strength)
    result.technical_score = tech_score
    result.breakdown.update({f"tech_{k}": v for k, v in tech_breakdown.items()})

    # --- درجة الأساسيات ---
    if fundamental:
        fund_score, fund_breakdown = compute_fundamental_score(fundamental)
    else:
        # مفيش أساسيات → ندي 15 من 30 (محايد)
        fund_score = 15.0
        fund_breakdown = {"no_data": 15.0}
    result.fundamental_score = fund_score
    result.breakdown.update({f"fund_{k}": v for k, v in fund_breakdown.items()})

    # --- الإجمالي ---
    result.total = round(tech_score + fund_score, 2)

    return result


# ===========================================================
# تقييم دفعة أسهم
# ===========================================================
def score_batch(
    stocks_data: dict,
    fundamentals_data: Optional[dict] = None,
    sector_strengths: Optional[dict] = None,
    **kwargs,
) -> list[ScoreResult]:
    """
    تقييم دفعة أسهم.
    ترجع قائمة مرتبة تنازليًا حسب الدرجة.
    """
    results = []
    for symbol, technical in stocks_data.items():
        fundamental = (fundamentals_data or {}).get(symbol)
        sector = technical.get("sector", "OTHER")
        sector_strength = (sector_strengths or {}).get(sector, 50.0)

        result = score_stock(
            symbol=symbol,
            technical=technical,
            fundamental=fundamental,
            sector_strength=sector_strength,
            **kwargs,
        )
        results.append(result)

    results.sort(key=lambda r: r.total, reverse=True)
    return results


# ===========================================================
# دوال مساعدة
# ===========================================================
def filter_by_min_score(results: list[ScoreResult], min_score: float = 60.0) -> list[ScoreResult]:
    """يرجع الأسهم اللي فوق الحد الأدنى فقط."""
    return [r for r in results if r.passed_hard_filters and r.total >= min_score]


def get_weights_by_score(results: list[ScoreResult]) -> dict:
    """
    يحدد وزن كل سهم بناءً على درجته.
    الأسهم الأعلى درجة تحصل على وزن أكبر.
    """
    valid = [r for r in results if r.passed_hard_filters and r.total >= 55]
    if not valid:
        return {}

    total_score = sum(r.total for r in valid)
    weights = {r.symbol: r.total / total_score for r in valid}
    return weights


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    # سهم قوي
    strong_tech = {
        "close": 50.0,
        "volume": 500_000,
        "ema50": 48.0,
        "ema200": 42.0,
        "rvol": 1.6,
        "momentum_60d": 25.0,
        "relative_strength": 12.0,
    }
    strong_fund = {"pe_ratio": 9.5, "earnings_growth": 22.0, "roe": 18.0}

    # سهم ضعيف
    weak_tech = {
        "close": 3.0,
        "volume": 10_000,
        "ema50": 40.0,
        "ema200": 45.0,
        "rvol": 0.7,
        "momentum_60d": -15.0,
        "relative_strength": -8.0,
    }

    print("=" * 60)
    print("اختبار نظام التقييم:")
    print("=" * 60)

    r1 = score_stock("STRONG", strong_tech, strong_fund, sector_strength=75)
    print(f"\n📈 سهم قوي — {r1.symbol}")
    print(f"   الإجمالي: {r1.total}/100 (Grade: {r1.grade})")
    print(f"   فني: {r1.technical_score}/70 | أساسي: {r1.fundamental_score}/30")
    print(f"   الأسباب: {r1.reasons or 'لا يوجد'}")

    r2 = score_stock("WEAK", weak_tech, sector_strength=40)
    print(f"\n📉 سهم ضعيف — {r2.symbol}")
    print(f"   الإجمالي: {r2.total}/100 (Grade: {r2.grade})")
    print(f"   اجتاز الفلاتر؟ {r2.passed_hard_filters}")
    print(f"   الأسباب: {r2.reasons}")

    print("\n" + "=" * 60)
    print("✅ اختبار نظام التقييم اكتمل")
