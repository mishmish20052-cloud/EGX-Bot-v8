"""
بناء خطة صفقة السوينج.

يستقبل EvaluationResult + بيانات السهم + رأس المال،
ويرجع خطة كاملة جاهزة للتنفيذ.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from config.strategies import SHORT_TERM
from config.settings import (
    TOTAL_CAPITAL,
    TOTAL_FEE_RATE,
)
from strategies.shared.risk import (
    calculate_position,
    calculate_rr_ratio,
    calculate_net_pnl,
)

logger = logging.getLogger("egx_bot.short_term.planner")


# ===========================================================
# نموذج الخطة
# ===========================================================
@dataclass
class TradePlan:
    """خطة صفقة سوينج كاملة."""
    symbol: str
    signal_type: str

    # الأسعار
    entry_price: float
    stop_loss: float
    t1: float
    t2: float
    t3: float

    # الكميات
    shares: int
    position_value: float
    weight_pct: float

    # المخاطرة
    risk_amount: float
    risk_pct: float
    rr_ratio: float

    # العوائد المتوقعة لكل هدف
    targets: list = field(default_factory=list)

    # الميتا
    atr: float = 0.0
    sl_distance_pct: float = 0.0
    valid: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "t1": round(self.t1, 2),
            "t2": round(self.t2, 2),
            "t3": round(self.t3, 2),
            "shares": self.shares,
            "position_value": round(self.position_value, 2),
            "weight_pct": round(self.weight_pct, 2),
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct": round(self.risk_pct, 2),
            "rr_ratio": self.rr_ratio,
            "sl_distance_pct": round(self.sl_distance_pct, 2),
            "atr": round(self.atr, 3),
            "targets": self.targets,
            "valid": self.valid,
            "reason": self.reason,
        }


# ===========================================================
# حساب Stop Loss
# ===========================================================
def calculate_stop_loss(
    entry: float,
    atr: float,
    strategy: str = "Trend",
) -> float:
    """
    حساب Stop Loss بناءً على ATR ونوع الإشارة.

    - Trend: ATR × 1.5
    - Super Breakout: ATR × 1.2 (أضيق لأن الزخم أقوى)
    - حد أدنى: 2% من السعر
    """
    if atr <= 0:
        atr = entry * 0.02  # fallback

    if strategy == "Super Breakout":
        sl_distance = max(atr * 1.2, entry * 0.02)
    else:
        sl_distance = max(atr * 1.5, entry * 0.025)

    return round(entry - sl_distance, 2)


# ===========================================================
# حساب الأهداف
# ===========================================================
def calculate_targets(
    entry: float,
    stop_loss: float,
    targets_config: Optional[list] = None,
) -> tuple[float, float, float, float]:
    """
    حساب T1/T2/T3 بناءً على المسافة من الدخول للستوب.

    المنطق:
    - R = entry - stop_loss (المسافة الأساسية)
    - T1 = entry + 1.5R
    - T2 = entry + 2.5R
    - T3 = entry + 4.0R
    """
    if targets_config is None:
        targets_config = SHORT_TERM.targets

    risk = entry - stop_loss
    if risk <= 0:
        return (entry, entry, entry, 0.0)

    # نستخدم R:R ratios من الاستراتيجية
    # بدل النسب المئوية، عشان تكون متماشية مع المخاطرة
    t1 = round(entry + risk * 1.5, 2)
    t2 = round(entry + risk * 2.5, 2)
    t3 = round(entry + risk * 4.0, 2)

    # ضمان ترتيب منطقي
    if t2 <= t1:
        t2 = round(t1 + risk * 0.5, 2)
    if t3 <= t2:
        t3 = round(t2 + risk * 0.5, 2)

    # النسبة الفعلية لـ T1
    actual_rr = round((t1 - entry) / risk, 2)

    return (t1, t2, t3, actual_rr)


# ===========================================================
# حساب عوائد الأهداف
# ===========================================================
def compute_targets_pnl(
    entry: float,
    targets: tuple,
    shares: int,
    targets_config: Optional[list] = None,
) -> list[dict]:
    """
    حساب العائد المتوقع لكل هدف بناءً على نسبة البيع.
    """
    if targets_config is None:
        targets_config = SHORT_TERM.targets

    t1, t2, t3 = targets[:3]
    results = []

    # نوزع shares على الأهداف حسب sell_portion
    # T1: 40%, T2: 30%, T3: 30% (نسبة افتراضية)
    portions = [0.40, 0.30, 0.30]
    if len(targets_config) >= 3:
        # نأخذ النسب من الاستراتيجية (مع تطبيعها)
        config_portions = [t.get("sell_portion", 0) for t in targets_config[:3]]
        total = sum(config_portions)
        if total > 0:
            portions = [p / total for p in config_portions]

    for i, (label, price) in enumerate(zip(["T1", "T2", "T3"], [t1, t2, t3])):
        portion = portions[i] if i < len(portions) else 0
        target_shares = max(1, int(shares * portion))
        gross_pnl = (price - entry) * target_shares
        net_pnl = calculate_net_pnl(entry, price, target_shares)

        results.append({
            "label": label,
            "price": round(price, 2),
            "shares": target_shares,
            "portion_pct": round(portion * 100, 1),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
        })

    return results


# ===========================================================
# الدالة الرئيسية
# ===========================================================
def build_plan(
    symbol: str,
    data: dict,
    signal_type: str,
    capital: float = None,
    deployed: float = 0.0,
    max_weight_pct: float = 30.0,
) -> TradePlan:
    """
    بناء خطة صفقة سوينج كاملة.

    المعاملات:
    - symbol: رمز السهم
    - data: dict من dispatcher
    - signal_type: "Trend 📈" أو "Super Breakout 🚀"
    - capital: رأس المال المتاح للسوينج
    - deployed: المبلغ المستثمر حاليًا
    - max_weight_pct: الحد الأقصى لوزن المركز

    ترجع: TradePlan
    """
    capital = capital or TOTAL_CAPITAL

    entry = data.get("close", 0)
    atr = data.get("atr", entry * 0.02)

    if entry <= 0:
        return TradePlan(
            symbol=symbol, signal_type=signal_type,
            entry_price=0, stop_loss=0, t1=0, t2=0, t3=0,
            shares=0, position_value=0, weight_pct=0,
            risk_amount=0, risk_pct=0, rr_ratio=0,
            valid=False, reason="سعر غير صالح",
        )

    # 1. حساب Stop Loss
    sl = calculate_stop_loss(entry, atr, strategy=signal_type.split()[0])

    # 2. حساب الأهداف
    t1, t2, t3, rr = calculate_targets(entry, sl)

    # 3. التحقق من R:R
    if rr < SHORT_TERM.min_rr_ratio:
        return TradePlan(
            symbol=symbol, signal_type=signal_type,
            entry_price=entry, stop_loss=sl, t1=t1, t2=t2, t3=t3,
            shares=0, position_value=0, weight_pct=0,
            risk_amount=0, risk_pct=0, rr_ratio=rr,
            valid=False,
            reason=f"R:R {rr} أقل من الحد {SHORT_TERM.min_rr_ratio}",
        )

    # 4. حساب حجم المركز
    risk_plan = calculate_position(
        entry_price=entry,
        stop_loss=sl,
        capital=capital,
        max_weight_pct=max_weight_pct,
        deployed=deployed,
    )

    if not risk_plan.valid:
        return TradePlan(
            symbol=symbol, signal_type=signal_type,
            entry_price=entry, stop_loss=sl, t1=t1, t2=t2, t3=t3,
            shares=0, position_value=0, weight_pct=0,
            risk_amount=0, risk_pct=0, rr_ratio=rr,
            valid=False, reason=risk_plan.reason,
        )

    # 5. حساب عوائد الأهداف
    targets_pnl = compute_targets_pnl(entry, (t1, t2, t3), risk_plan.shares)

    sl_distance_pct = ((entry - sl) / entry) * 100

    return TradePlan(
        symbol=symbol,
        signal_type=signal_type,
        entry_price=entry,
        stop_loss=sl,
        t1=t1, t2=t2, t3=t3,
        shares=risk_plan.shares,
        position_value=risk_plan.position_value,
        weight_pct=risk_plan.weight_pct,
        risk_amount=risk_plan.risk_amount,
        risk_pct=risk_plan.risk_pct,
        rr_ratio=rr,
        targets=targets_pnl,
        atr=atr,
        sl_distance_pct=sl_distance_pct,
        valid=True,
    )


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار خطة السوينج")
    print("=" * 60)

    # سهم قوي
    data = {
        "close": 50.0,
        "atr": 1.5,
        "rsi": 55.0,
        "rvol": 2.0,
    }

    # 1. خطة Trend
    print("\n1️⃣ خطة Trend (رأس مال 10000):")
    plan = build_plan("TMGH", data, "Trend 📈", capital=10000)
    for k, v in plan.to_dict().items():
        if k == "targets":
            print(f"   targets:")
            for t in v:
                print(f"     {t}")
        else:
            print(f"   {k}: {v}")

    # 2. خطة Super Breakout
    print("\n2️⃣ خطة Super Breakout:")
    plan = build_plan("TMGH", data, "Super Breakout 🚀", capital=10000)
    print(f"   SL: {plan.stop_loss} | T1: {plan.t1} | T2: {plan.t2} | T3: {plan.t3}")
    print(f"   Shares: {plan.shares} | Weight: {plan.weight_pct:.1f}%")
    print(f"   Risk: {plan.risk_pct:.2f}% | R:R = 1:{plan.rr_ratio}")

    # 3. سهم بسيولة ضعيفة
    print("\n3️⃣ خطة على سهم صغير (رأس مال 5000):")
    plan = build_plan("TEST", data, "Trend 📈", capital=5000)
    print(f"   Valid: {plan.valid}")
    print(f"   Reason: {plan.reason}")

    print("\n" + "=" * 60)
    print("✅ اختبار خطة السوينج اكتمل")
