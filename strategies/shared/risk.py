"""
إدارة المخاطر المشتركة بين الاستراتيجيتين.

المسؤوليات:
- حساب حجم المركز (position sizing)
- حساب المخاطرة الفعلية
- التحقق من الحدود القصوى
- حساب نسبة R:R
- تعديل المخاطرة حسب حالة السوق
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

from config.settings import (
    TOTAL_CAPITAL,
    RISK_PER_TRADE,
    MIN_POSITION_VALUE,
    TOTAL_FEE_RATE,
)

logger = logging.getLogger("egx_bot.risk")


# ===========================================================
# نموذج النتيجة
# ===========================================================
@dataclass
class RiskPlan:
    """خطة المخاطرة لصفقة واحدة."""
    shares: int                    # عدد الأسهم
    entry_price: float             # سعر الدخول
    stop_loss: float               # سعر الستوب
    position_value: float          # قيمة المركز
    risk_amount: float             # المبلغ المعرض للخطر
    risk_pct: float                # نسبة المخاطرة من رأس المال
    weight_pct: float              # وزن المركز من رأس المال
    sl_distance: float             # المسافة بين الدخول والستوب
    valid: bool = True             # هل الخطة صالحة؟
    reason: str = ""               # سبب الرفض (لو مش صالحة)

    def to_dict(self) -> dict:
        return {
            "shares": self.shares,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "position_value": round(self.position_value, 2),
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct": round(self.risk_pct, 2),
            "weight_pct": round(self.weight_pct, 2),
            "sl_distance": round(self.sl_distance, 3),
            "valid": self.valid,
            "reason": self.reason,
        }


# ===========================================================
# الحساب الرئيسي
# ===========================================================
def calculate_position(
    entry_price: float,
    stop_loss: float,
    capital: float = None,
    risk_pct: float = None,
    max_weight_pct: float = 30.0,
    deployed: float = 0.0,
    max_exposure_pct: float = 90.0,
) -> RiskPlan:
    """
    يحسب حجم المركز بناءً على:
    1. المخاطرة لكل صفقة (RISK_PER_TRADE)
    2. الوزن الأقصى للمركز (max_weight_pct)
    3. التعرض الكلي للمحفظة (max_exposure_pct)

    المعاملات:
    - entry_price: سعر الدخول
    - stop_loss: سعر الستوب
    - capital: رأس المال (افتراضي: TOTAL_CAPITAL)
    - risk_pct: نسبة المخاطرة (افتراضي: RISK_PER_TRADE)
    - max_weight_pct: الحد الأقصى لوزن المركز الواحد
    - deployed: المبلغ المستثمر حاليًا
    - max_exposure_pct: الحد الأقصى للتعرض الكلي

    ترجع: RiskPlan
    """
    capital = capital or TOTAL_CAPITAL
    risk_pct = risk_pct or RISK_PER_TRADE

    # التحقق من صحة المدخلات
    if entry_price <= 0 or stop_loss <= 0:
        return RiskPlan(
            shares=0, entry_price=entry_price, stop_loss=stop_loss,
            position_value=0, risk_amount=0, risk_pct=0, weight_pct=0,
            sl_distance=0, valid=False, reason="سعر غير صالح",
        )

    sl_distance = entry_price - stop_loss
    if sl_distance <= 0:
        return RiskPlan(
            shares=0, entry_price=entry_price, stop_loss=stop_loss,
            position_value=0, risk_amount=0, risk_pct=0, weight_pct=0,
            sl_distance=0, valid=False, reason="الستوب أعلى من الدخول",
        )

    # المبلغ المعرض للخطر
    risk_amount = capital * risk_pct

    # حجم المركز بناءً على المخاطرة
    shares_by_risk = int(risk_amount // sl_distance)

    # حجم المركز بناءً على الوزن الأقصى
    max_position_value = capital * (max_weight_pct / 100)
    shares_by_weight = int(max_position_value // entry_price)

    # حجم المركز بناءً على التعرض المتبقي
    max_exposure = capital * (max_exposure_pct / 100)
    remaining_exposure = max_exposure - deployed
    shares_by_exposure = int(remaining_exposure // entry_price) if remaining_exposure > 0 else 0

    # نأخذ الأصغر
    shares = min(shares_by_risk, shares_by_weight, shares_by_exposure)

    if shares < 1:
        return RiskPlan(
            shares=0, entry_price=entry_price, stop_loss=stop_loss,
            position_value=0, risk_amount=0, risk_pct=0, weight_pct=0,
            sl_distance=sl_distance, valid=False,
            reason=f"عدد الأسهم أقل من 1 (by_risk={shares_by_risk}, by_weight={shares_by_weight}, by_exposure={shares_by_exposure})",
        )

    position_value = shares * entry_price

    # التحقق من الحد الأدنى للمركز
    if position_value < MIN_POSITION_VALUE:
        return RiskPlan(
            shares=shares, entry_price=entry_price, stop_loss=stop_loss,
            position_value=position_value, risk_amount=0, risk_pct=0,
            weight_pct=0, sl_distance=sl_distance, valid=False,
            reason=f"قيمة المركز {position_value:.0f} أقل من الحد الأدنى {MIN_POSITION_VALUE}",
        )

    # المخاطرة الفعلية (مع العمولات)
    actual_risk = shares * sl_distance * (1 + TOTAL_FEE_RATE)
    actual_risk_pct = actual_risk / capital * 100

    # وزن المركز
    weight_pct = position_value / capital * 100

    return RiskPlan(
        shares=shares,
        entry_price=entry_price,
        stop_loss=stop_loss,
        position_value=position_value,
        risk_amount=actual_risk,
        risk_pct=actual_risk_pct,
        weight_pct=weight_pct,
        sl_distance=sl_distance,
        valid=True,
    )


# ===========================================================
# حساب نسبة R:R
# ===========================================================
def calculate_rr_ratio(
    entry: float,
    stop: float,
    target: float,
) -> float:
    """حساب نسبة المخاطرة/المكافأة."""
    risk = entry - stop
    reward = target - entry
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def check_rr_ratio(
    entry: float,
    stop: float,
    target: float,
    min_rr: float = 2.0,
) -> tuple[bool, float]:
    """
    يتحقق من أن R:R فوق الحد الأدنى.
    ترجع: (نجح؟، النسبة الفعلية)
    """
    rr = calculate_rr_ratio(entry, stop, target)
    return (rr >= min_rr, rr)


# ===========================================================
# تعديل المخاطرة حسب حالة السوق
# ===========================================================
def adjust_risk_by_regime(
    base_risk_pct: float,
    regime_risk_multiplier: float,
    min_risk_pct: float = 0.003,
    max_risk_pct: float = 0.020,
) -> float:
    """
    يعدّل نسبة المخاطرة حسب معامل حالة السوق.
    - regime_risk_multiplier: 0.0 = توقف، 1.0 = طبيعي، 1.4 = مضاعف
    """
    adjusted = base_risk_pct * regime_risk_multiplier
    return max(min_risk_pct, min(max_risk_pct, adjusted))


# ===========================================================
# حساب الخسارة/الربح الصافي
# ===========================================================
def calculate_net_pnl(
    entry: float,
    exit_price: float,
    shares: int,
) -> float:
    """
    حساب الربح/الخسارة الصافي بعد كل العمولات.
    """
    if shares <= 0:
        return 0.0

    entry_with_fees = entry * (1 + TOTAL_FEE_RATE)
    exit_with_fees = exit_price * (1 - TOTAL_FEE_RATE)

    return (exit_with_fees - entry_with_fees) * shares


def calculate_gross_pnl(
    entry: float,
    exit_price: float,
    shares: int,
) -> float:
    """حساب الربح/الخسارة الإجمالي (بدون عمولات)."""
    return (exit_price - entry) * shares


# ===========================================================
# حساب العوائد المتوقعة
# ===========================================================
def calculate_targets_pnl(
    entry: float,
    targets: list[dict],
    shares: int,
) -> list[dict]:
    """
    يحسب العائد المتوقع لكل هدف.

    targets: list of {"pct": 0.10, "sell_portion": 0.25, "label": "T1"}

    ترجع: list of dict مع قيمة كل هدف.
    """
    results = []
    for target in targets:
        target_price = entry * (1 + target["pct"])
        target_shares = int(shares * target["sell_portion"])
        gross = (target_price - entry) * target_shares
        net = calculate_net_pnl(entry, target_price, target_shares)

        results.append({
            "label": target["label"],
            "price": round(target_price, 2),
            "shares": target_shares,
            "gross_pnl": round(gross, 2),
            "net_pnl": round(net, 2),
            "pct_gain": round(target["pct"] * 100, 2),
        })
    return results


# ===========================================================
# التحقق من المخاطرة الكلية
# ===========================================================
def check_total_risk(
    open_positions: dict,
    capital: float = None,
    max_total_risk_pct: float = 6.0,
) -> tuple[bool, float]:
    """
    يتحقق من أن المخاطرة الكلية للمحفظة ضمن الحدود.

    المعاملات:
    - open_positions: {symbol: {"entry_price": ..., "shares": ..., "sl": ...}}
    - max_total_risk_pct: الحد الأقصى للمخاطرة الكلية

    ترجع: (مسموح؟، المخاطرة الحالية %)
    """
    capital = capital or TOTAL_CAPITAL
    total_risk = 0.0

    for pos in open_positions.values():
        entry = pos.get("entry_price", 0)
        shares = pos.get("shares", 0)
        sl = pos.get("sl", 0)
        if entry > 0 and sl > 0 and shares > 0:
            total_risk += shares * (entry - sl)

    risk_pct = (total_risk / capital) * 100
    return (risk_pct < max_total_risk_pct, round(risk_pct, 2))


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار إدارة المخاطر")
    print("=" * 60)

    # 1. حساب position لصفقة
    print("\n1️⃣ حساب حجم مركز (رأس مال 10000، 25.50 → 24.50):")
    plan = calculate_position(
        entry_price=25.50,
        stop_loss=24.50,
        capital=10000,
    )
    for k, v in plan.to_dict().items():
        print(f"   {k}: {v}")

    # 2. R:R
    print("\n2️⃣ نسبة R:R:")
    rr = calculate_rr_ratio(entry=25.5, stop=24.5, target=28.0)
    print(f"   R:R = 1:{rr}")

    # 3. Ajust by regime
    print("\n3️⃣ تعديل المخاطرة حسب حالة السوق:")
    for mult in [0.5, 1.0, 1.4]:
        adj = adjust_risk_by_regime(0.01, mult)
        print(f"   multiplier={mult} → risk={adj*100:.2f}%")

    # 4. Net PnL
    print("\n4️⃣ صافي ربح (دخول 25.5 → خروج 27.0، 100 سهم):")
    net = calculate_net_pnl(25.5, 27.0, 100)
    print(f"   صافي = {net:.2f} ج.م")

    # 5. Targets PnL
    print("\n5️⃣ أهداف الصفقة:")
    targets = [
        {"pct": 0.10, "sell_portion": 0.25, "label": "T1"},
        {"pct": 0.25, "sell_portion": 0.25, "label": "T2"},
        {"pct": 0.45, "sell_portion": 0.25, "label": "T3"},
        {"pct": 0.70, "sell_portion": 1.00, "label": "T4"},
    ]
    for t in calculate_targets_pnl(25.50, targets, 100):
        print(f"   {t['label']}: {t['price']} | "
              f"{t['shares']} سهم | صافي +{t['net_pnl']:.0f} ج.م")

    # 6. حالة invalid
    print("\n6️⃣ حالة فشل — مركز صغير جدًا (سهم 500 ج):")
    plan = calculate_position(entry_price=500, stop_loss=490, capital=10000)
    print(f"   صالح؟ {plan.valid}")
    print(f"   السبب: {plan.reason}")

    print("\n" + "=" * 60)
    print("✅ اختبار إدارة المخاطر اكتمل")
